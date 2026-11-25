"""Benchmark (NOT a pytest gate): evaluate real Ollama models on golden & held-out SQL sets."""
from __future__ import annotations

import argparse
import datetime
import re
import statistics
import subprocess
import sys
import time
from typing import Any

import httpx
import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import reset_engines, ro_engine
from app.gateway.guardrails import check_input
from app.sql_agent.executor import execute_readonly_sql
from app.sql_agent.generator import generate_sql, repair_sql
from app.sql_agent.validator import validate_sql
from scripts.seed import seed_database
from tests.golden.heldout import HELDOUT_CASES, compute_heldout_expected
from tests.golden.test_golden_sql import SEED_END, compute_golden_expected

BENCH_DB_NAME = "life_test"
ADMIN_CONN_STR = "postgresql://life:life@127.0.0.1:5432/life"
BENCH_RW_URL = f"postgresql+psycopg://life:life@127.0.0.1:5432/{BENCH_DB_NAME}"
BENCH_RO_URL = f"postgresql+psycopg://life_ro:life_ro@127.0.0.1:5432/{BENCH_DB_NAME}"

# Questions overlapping with prompt examples (for honest accuracy separation)
FEW_SHOT_OVERLAP_IDS = {1, 4, 6, 8}
# Held-out questions whose conventions were clarified in Step 1c prompt tuning
TUNED_HELDOUT_IDS = {1, 8, 9}
ORDER_SENSITIVE_GOLDEN = {3, 8}
ORDER_SENSITIVE_HELDOUT = {7, 10, 11}

_MIDNIGHT_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T00:00:00(?:[+-]\d{2}:\d{2}|Z)?$")

GOLDEN_QUESTIONS: list[tuple[int, str]] = [
    (1, "What was my average sleep on days with commits > 0?"),
    (2, "What were my total commits in the last 30 days?"),
    (3, "Which day had the most steps?"),
    (4, "What is the correlation between sleep_hours and commits?"),
    (5, "What is my average screen minutes on days sleep < 6?"),
    (6, "What are my weekly commit totals?"),
    (7, "How many total pages did I read in the last 14 days?"),
    (8, "What are my top 3 screen-time categories?"),
    (9, "What is my average HRV on days with >=1 commit compared to days with 0 commits?"),
    (10, "What is my longest streak of consecutive commit days?"),
]


def _verify_ollama_model_exists(api_base: str, llm_model: str) -> None:
    """Verify Ollama model exists before benchmarking; fail fast with exact error."""
    if not llm_model.startswith("ollama/"):
        return
    model_name = llm_model.removeprefix("ollama/")
    url = f"{api_base.rstrip('/')}/api/show"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(url, json={"name": model_name})
            if resp.status_code != 200:
                print(
                    f"ERROR: Ollama model '{model_name}' not available (HTTP {resp.status_code}): "
                    f"{resp.text.strip()}",
                    file=sys.stderr,
                )
                raise SystemExit(1)
    except httpx.HTTPError as exc:
        print(f"ERROR: Failed to verify Ollama model '{model_name}': {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _setup_bench_db() -> None:
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {BENCH_DB_NAME} WITH (FORCE);")
            cur.execute(f"CREATE DATABASE {BENCH_DB_NAME};")
            cur.execute(f"GRANT ALL PRIVILEGES ON DATABASE {BENCH_DB_NAME} TO life;")
            cur.execute(f"GRANT CONNECT ON DATABASE {BENCH_DB_NAME} TO life_ro;")

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", BENCH_RW_URL)
    command.upgrade(cfg, "head")

    settings = get_settings()
    settings.database_url = BENCH_RW_URL
    settings.database_url_ro = BENCH_RO_URL
    settings.seed_end_date = SEED_END
    settings.reference_date = SEED_END
    reset_engines()
    seed_database(end_date=SEED_END)


def _cleanup_bench_db() -> None:
    reset_engines()
    with psycopg.connect(ADMIN_CONN_STR, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {BENCH_DB_NAME} WITH (FORCE);")


def _normalize_scalar(v: Any) -> Any:
    if isinstance(v, (datetime.datetime,)):
        if v.time() == datetime.time(0, 0, 0):
            return v.date().isoformat()
        return v.isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 3)
    if isinstance(v, str):
        s = v.strip()
        m = _MIDNIGHT_TS_RE.match(s)
        if m:
            return m.group(1)
        try:
            return round(float(s), 3)
        except ValueError:
            return s
    return v


def _row_sort_key(row: list[Any]) -> list[str]:
    return [str(_normalize_scalar(x)) for x in row]


def _results_equal(
    actual_rows: list[list[Any]],
    expected_rows: list[list[Any]],
    *,
    order_sensitive: bool = False,
) -> bool:
    if len(actual_rows) != len(expected_rows):
        return False

    a_rows = actual_rows if order_sensitive else sorted(actual_rows, key=_row_sort_key)
    e_rows = expected_rows if order_sensitive else sorted(expected_rows, key=_row_sort_key)

    for a_row, e_row in zip(a_rows, e_rows, strict=True):
        if len(a_row) != len(e_row):
            return False
        for av, ev in zip(a_row, e_row, strict=True):
            an, en = _normalize_scalar(av), _normalize_scalar(ev)
            if isinstance(an, (int, float)) and isinstance(en, (int, float)):
                if abs(float(an) - float(en)) > 0.05:
                    return False
            elif str(an) != str(en):
                return False
    return True


def _build_question_suite(set_name: str) -> list[dict[str, Any]]:
    golden_expected = compute_golden_expected()
    heldout_expected = compute_heldout_expected()

    items: list[dict[str, Any]] = []
    if set_name in ("golden", "both"):
        for qid, qtext in GOLDEN_QUESTIONS:
            items.append({
                "set": "golden",
                "label": f"Q{qid:02d}",
                "overlap": qid in FEW_SHOT_OVERLAP_IDS,
                "tuned": False,
                "order_sensitive": qid in ORDER_SENSITIVE_GOLDEN,
                "question": qtext,
                "expected": golden_expected[qid],
            })
    if set_name in ("heldout", "both"):
        for hid, qtext, _ in HELDOUT_CASES:
            items.append({
                "set": "heldout",
                "label": f"H{hid:02d}",
                "overlap": False,
                "tuned": hid in TUNED_HELDOUT_IDS,
                "order_sensitive": hid in ORDER_SENSITIVE_HELDOUT,
                "question": qtext,
                "expected": heldout_expected[hid],
            })
    return items


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Text-to-SQL against real Ollama LLM.")
    parser.add_argument(
        "--set",
        choices=("golden", "heldout", "both"),
        default="both",
        help="Question suite to benchmark (default: both).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override LLM_MODEL (e.g. ollama/llama3.1:8b or ollama/qwen2.5-coder:7b).",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Optional comma-separated question labels to run (e.g. Q06 or Q06,H01).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    if args.model:
        settings.llm_model = args.model

    _verify_ollama_model_exists(settings.llm_api_base, settings.llm_model)

    print(
        f"Preparing isolated life_test DB (SEED_END_DATE={SEED_END.isoformat()}, "
        f"REFERENCE_DATE={SEED_END.isoformat()})..."
    )
    _setup_bench_db()
    questions = _build_question_suite(args.set)
    if args.only:
        wanted = {lbl.strip().upper() for lbl in args.only.split(",") if lbl.strip()}
        questions = [q for q in questions if q["label"].upper() in wanted]

    stats_by_set: dict[str, dict[str, Any]] = {}
    all_latencies: list[float] = []
    gen_latencies: list[float] = []
    total_exec_ok = 0
    total_matched = 0
    overlap_matched = 0
    overlap_total = 0
    heldout_untuned_matched = 0
    heldout_untuned_total = 0
    heldout_tuned_matched = 0
    heldout_tuned_total = 0

    print(
        f"\n=== REAL LLM TEXT-TO-SQL BENCHMARK (set={args.set}, count={len(questions)}) ==="
    )
    print(f"Model: {settings.llm_model} | Prompt Reference Date: {SEED_END.isoformat()}")
    if args.set in ("golden", "both"):
        print(
            "Note: Golden Q01, Q04, Q06, Q08 overlap with few-shot examples "
            "(overstate accuracy vs novel/held-out queries).\n"
        )

    try:
        for item in questions:
            sname = item["set"]
            sstats = stats_by_set.setdefault(sname, {"total": 0, "exec_ok": 0, "matched": 0})
            sstats["total"] += 1
            if item["overlap"]:
                overlap_total += 1
                tag = "[GOLDEN OVERLAP]"
            elif sname == "golden":
                tag = "[GOLDEN NOVEL]"
            elif item["tuned"]:
                heldout_tuned_total += 1
                tag = "[HELDOUT TUNED]"
            else:
                heldout_untuned_total += 1
                tag = "[HELDOUT UNTUNED]"

            t0 = time.perf_counter()
            t_gen = t_val = t_exec = 0.0
            gen_sql = ""
            repaired_sql = ""
            repair_err = ""
            exec_ok = False
            matched = False
            err_detail = ""
            actual_rows: list[list[Any]] = []

            try:
                check_input(item["question"])
                tg = time.perf_counter()
                generated = generate_sql(item["question"], settings=settings)
                t_gen += (time.perf_counter() - tg) * 1000.0
                gen_sql = generated.sql

                tv = time.perf_counter()
                validated_sql = validate_sql(generated.sql)
                t_val += (time.perf_counter() - tv) * 1000.0
                gen_sql = validated_sql

                with Session(bind=ro_engine()) as ro_sess:
                    te = time.perf_counter()
                    try:
                        res = execute_readonly_sql(validated_sql, session=ro_sess)
                        t_exec += (time.perf_counter() - te) * 1000.0
                    except Exception as first_err:
                        t_exec += (time.perf_counter() - te) * 1000.0
                        repair_err = str(first_err).splitlines()[0][:180]
                        tg2 = time.perf_counter()
                        repaired = repair_sql(
                            item["question"],
                            validated_sql,
                            str(first_err),
                            settings=settings,
                        )
                        t_gen += (time.perf_counter() - tg2) * 1000.0
                        repaired_sql = repaired.sql
                        tv2 = time.perf_counter()
                        validated_repaired = validate_sql(repaired.sql)
                        t_val += (time.perf_counter() - tv2) * 1000.0
                        repaired_sql = validated_repaired
                        te2 = time.perf_counter()
                        res = execute_readonly_sql(validated_repaired, session=ro_sess)
                        t_exec += (time.perf_counter() - te2) * 1000.0
                exec_ok = True
                actual_rows = res.rows
                matched = _results_equal(
                    actual_rows,
                    item["expected"],
                    order_sensitive=item["order_sensitive"],
                )
            except Exception as exc:
                err_detail = str(exc).splitlines()[0][:180]

            latency_ms = (time.perf_counter() - t0) * 1000.0
            all_latencies.append(latency_ms)
            gen_latencies.append(t_gen)
            if exec_ok:
                total_exec_ok += 1
                sstats["exec_ok"] += 1
            if matched:
                total_matched += 1
                sstats["matched"] += 1
                if item["overlap"]:
                    overlap_matched += 1
                elif sname == "heldout":
                    if item["tuned"]:
                        heldout_tuned_matched += 1
                    else:
                        heldout_untuned_matched += 1

            print(f"{item['label']} {tag}: {item['question']}")
            print(f"  Generated SQL : {gen_sql or '(none)'}")
            if repair_err:
                print(f"  Repair Trigger: {repair_err}")
                print(f"  Repaired SQL  : {repaired_sql or '(none)'}")
            print(f"  Executed OK   : {exec_ok}" + (f" ({err_detail})" if err_detail else ""))
            mismatch_info = (
                ""
                if matched
                else f" (actual={actual_rows[:3]} vs expected={item['expected'][:3]})"
            )
            print(f"  Result Match  : {matched}{mismatch_info}")
            print(
                f"  Latency       : {latency_ms:.0f} ms "
                f"(gen={t_gen:.0f}, val={t_val:.0f}, exec={t_exec:.0f})\n"
            )

        mean_ms = statistics.mean(all_latencies) if all_latencies else 0.0
        max_ms = max(all_latencies) if all_latencies else 0.0
        mean_gen_ms = statistics.mean(gen_latencies) if gen_latencies else 0.0
        print("=== BENCHMARK TOTALS ===")
        print(f"Model                        : {settings.llm_model}")
        print(f"Overall Executed OK          : {total_exec_ok}/{len(questions)}")
        print(f"Overall Result Match         : {total_matched}/{len(questions)}")
        for sname, sstats in stats_by_set.items():
            print(
                f"  Set '{sname}'               : "
                f"match={sstats['matched']}/{sstats['total']}, "
                f"exec_ok={sstats['exec_ok']}/{sstats['total']}"
            )
        if overlap_total:
            print(f"  Golden overlap (Q1,4,6,8)  : {overlap_matched}/{overlap_total}")
        if heldout_untuned_total:
            print(
                f"  Held-out untuned           : "
                f"{heldout_untuned_matched}/{heldout_untuned_total}"
            )
        if heldout_tuned_total:
            print(
                f"  Held-out tuned (H01,08,09) : "
                f"{heldout_tuned_matched}/{heldout_tuned_total}"
            )
        print(
            f"Latency (mean / max / total) : {mean_ms:.0f} ms / {max_ms:.0f} ms / "
            f"{sum(all_latencies) / 1000.0:.2f}s (mean_gen={mean_gen_ms:.0f} ms)"
        )
        print("\n=== ollama ps ===")
        subprocess.run(["ollama", "ps"], check=False)
    finally:
        _cleanup_bench_db()


if __name__ == "__main__":
    main()
