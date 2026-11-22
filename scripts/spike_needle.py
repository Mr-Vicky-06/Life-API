"""Spike script for Needle (Cactus 3) tool routing evaluation.

Evaluates 20 test queries across 3 tools:
- sql_query(question: str)
- search_notes(query: str, top_k: int)
- get_metrics(from: str, to: str, metrics: list[str])
Plus no-tool / conversational queries.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# Enforce strict privacy guardrails prior to engine import
os.environ.setdefault("CACTUS_TELEMETRY", "0")
os.environ.setdefault("NEEDLE_TELEMETRY", "0")
os.environ.setdefault("DO_NOT_TRACK", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import cactus  # noqa: E402

TEST_CASES = [
    # --- sql_query (>= 6) ---
    {
        "query": "Run a SQL query: what was my average sleep duration last week?",
        "expected_tool": "sql_query",
    },
    {
        "query": "Execute SQL query to calculate total commits per repository",
        "expected_tool": "sql_query",
    },
    {
        "query": "Run SQL query to show my top 5 longest reading sessions",
        "expected_tool": "sql_query",
    },
    {
        "query": "Query database: which day had the highest screen time?",
        "expected_tool": "sql_query",
    },
    {
        "query": "Run SQL query to calculate correlation between sleep and commits",
        "expected_tool": "sql_query",
    },
    {
        "query": "Query the database for all records with zero commits",
        "expected_tool": "sql_query",
    },
    # --- search_notes (>= 6) ---
    {
        "query": "Search notes for machine learning ideas with top_k 5",
        "expected_tool": "search_notes",
    },
    {
        "query": "Search my notes for travel itinerary top 3",
        "expected_tool": "search_notes",
    },
    {
        "query": "Search journal notes for workout routines top 10",
        "expected_tool": "search_notes",
    },
    {
        "query": "Search notes for book summary notes top 5",
        "expected_tool": "search_notes",
    },
    {
        "query": "Search notes for career goals top 5",
        "expected_tool": "search_notes",
    },
    {
        "query": "Find in notes meeting notes with Sarah top 5",
        "expected_tool": "search_notes",
    },
    # --- get_metrics (>= 6) ---
    {
        "query": "Get metrics for sleep from 2026-10-01 to 2026-10-31",
        "expected_tool": "get_metrics",
    },
    {
        "query": "Retrieve metrics commits and steps from 2026-09-01 to 2026-09-30",
        "expected_tool": "get_metrics",
    },
    {
        "query": "Fetch metrics for screen_time from 2026-11-01 to 2026-11-15",
        "expected_tool": "get_metrics",
    },
    {
        "query": "Get metrics for reading_minutes and sleep from 2026-08-01 to 2026-08-15",
        "expected_tool": "get_metrics",
    },
    {
        "query": "Pull metrics steps from 2026-07-01 to 2026-07-31",
        "expected_tool": "get_metrics",
    },
    {
        "query": "Get daily metrics for commits from 2026-10-15 to 2026-10-25",
        "expected_tool": "get_metrics",
    },
    # --- no tool (>= 2) ---
    {
        "query": "Hello! What can you help me with today?",
        "expected_tool": None,
    },
    {
        "query": "What is the capital of France?",
        "expected_tool": None,
    },
]


def validate_args(expected_tool: str | None, actual_args: dict[str, Any]) -> bool:
    if expected_tool is None:
        return len(actual_args) == 0
    if expected_tool == "sql_query":
        q = actual_args.get("question")
        return isinstance(q, str) and len(q.strip()) > 0
    if expected_tool == "search_notes":
        query = actual_args.get("query")
        top_k = actual_args.get("top_k")
        return (
            isinstance(query, str)
            and len(query.strip()) > 0
            and isinstance(top_k, int)
            and top_k > 0
        )
    if expected_tool == "get_metrics":
        from_d = actual_args.get("from")
        to_d = actual_args.get("to")
        metrics = actual_args.get("metrics")
        date_pattern = r"^\d{4}-\d{2}-\d{2}$"
        has_dates = bool(
            from_d
            and to_d
            and re.match(date_pattern, str(from_d))
            and re.match(date_pattern, str(to_d))
        )
        has_metrics = (
            isinstance(metrics, list)
            and len(metrics) > 0
            and all(isinstance(m, str) for m in metrics)
        )
        return has_dates and has_metrics
    return False


def run_spike() -> int:
    tools_path = Path("tools.json")
    if not tools_path.is_file():
        print(f"Error: {tools_path} not found.")
        return 1

    tools_json_str = tools_path.read_text(encoding="utf-8")
    print(f"Loaded tools definition from {tools_path} ({len(json.loads(tools_json_str))} tools)")
    print(f"Initializing NeedleAgent (cactus v{getattr(cactus, '__version__', 'unknown')}) ...")

    agent = cactus.Cactus(tools=tools_json_str, stateless=True)

    print("\n" + "=" * 80)
    print("NEEDLE SPIKE EVALUATION (20 TEST QUERIES)")
    print("=" * 80)

    results = []
    total = len(TEST_CASES)
    tool_correct_count = 0
    arg_correct_count = 0
    latencies: list[float] = []

    for i, item in enumerate(TEST_CASES, start=1):
        query = item["query"]
        expected_tool = item["expected_tool"]

        t0 = time.perf_counter()
        out = agent.complete(query)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(latency_ms)

        calls = out.get("function_calls", [])
        actual_tool = calls[0]["name"] if calls and isinstance(calls[0], dict) else None
        actual_args = calls[0].get("arguments", {}) if calls and isinstance(calls[0], dict) else {}

        tool_match = (actual_tool == expected_tool)
        arg_match = validate_args(expected_tool, actual_args) if tool_match else False

        if tool_match:
            tool_correct_count += 1
        if arg_match:
            arg_correct_count += 1

        results.append({
            "idx": i,
            "query": query,
            "expected_tool": expected_tool,
            "actual_tool": actual_tool,
            "actual_args": actual_args,
            "tool_match": tool_match,
            "arg_match": arg_match,
            "latency_ms": latency_ms,
            "confidence": out.get("confidence"),
            "reasoning": out.get("reasoning", ""),
        })

        status_tool = "PASS" if tool_match else "FAIL"
        status_arg = "PASS" if arg_match else "FAIL"
        print(f"[{i:02d}/20] Query: '{query}'")
        print(f"       Expected: {expected_tool} | Actual: {actual_tool} -> Tool: [{status_tool}]")
        print(f"       Args: {actual_args} -> Args: [{status_arg}]")
        print(f"       Latency: {latency_ms:.1f}ms | Confidence: {out.get('confidence')}")
        print()

    agent.close()

    tool_accuracy = (tool_correct_count / total) * 100.0
    arg_accuracy = (arg_correct_count / total) * 100.0
    avg_latency = sum(latencies) / len(latencies)

    print("=" * 80)
    print("SPIKE SUMMARY")
    print("=" * 80)
    print(f"Total Queries:     {total}")
    print(f"Tool Matches:      {tool_correct_count}/{total} ({tool_accuracy:.1f}%)")
    print(f"Arg Correctness:   {arg_correct_count}/{total} ({arg_accuracy:.1f}%)")
    min_lat = min(latencies)
    max_lat = max(latencies)
    print(f"Average Latency:   {avg_latency:.1f} ms (min: {min_lat:.1f}ms, max: {max_lat:.1f}ms)")
    print()

    # Decision rule: tool accuracy >= 90% and arguments correct >= 80%
    passed = (tool_accuracy >= 90.0) and (arg_accuracy >= 80.0)
    thresh = ">=90%/80%"
    if passed:
        decision_str = (
            f"Needle accepted: tool={tool_accuracy:.1f}%, args={arg_accuracy:.1f}% "
            f"(threshold: {thresh})"
        )
        print(f"DECISION: {decision_str}")
    else:
        decision_str = (
            f"Needle rejected: tool={tool_accuracy:.1f}%, args={arg_accuracy:.1f}% "
            f"(threshold: {thresh})"
        )
        print(f"DECISION: {decision_str}")

    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(run_spike())
