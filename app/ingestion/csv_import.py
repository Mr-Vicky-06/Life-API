"""CSV parsing and validation utilities."""
from __future__ import annotations

import csv
import io
from typing import Any

from pydantic import ValidationError

from app.ingestion.cleaning import clean_text
from app.schemas.ingest import HealthCSVRow, ReadingCSVRow, ScreenTimeCSVRow


def parse_health_csv(csv_content: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse and validate health daily metrics CSV rows."""
    valid_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    reader = csv.DictReader(io.StringIO(csv_content))
    if not reader.fieldnames:
        return valid_rows, ["Empty CSV file."]

    for idx, raw_row in enumerate(reader, start=2):  # line 2 is first data row
        row = {k.strip().lower(): (v.strip() if v else "") for k, v in raw_row.items() if k}
        if not any(row.values()):
            continue  # skip completely blank row

        data_dict: dict[str, Any] = {
            "date": row.get("date") or None,
            "sleep_hours": row.get("sleep_hours") or None,
            "sleep_score": row.get("sleep_score") or None,
            "deep_sleep_min": row.get("deep_sleep_min") or None,
            "hrv_ms": row.get("hrv_ms") or None,
            "resting_hr": row.get("resting_hr") or None,
            "steps": row.get("steps") or None,
            "source": clean_text(row.get("source", "csv")) if row.get("source") else "csv",
        }

        try:
            validated = HealthCSVRow.model_validate(data_dict)
            valid_rows.append(validated.model_dump())
        except ValidationError as e:
            errors.append(f"Row {idx}: {e.errors()[0]['msg']}")
        except Exception as e:
            errors.append(f"Row {idx}: {e}")

    return valid_rows, errors


def parse_reading_csv(csv_content: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse and validate reading log CSV rows."""
    valid_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    reader = csv.DictReader(io.StringIO(csv_content))
    if not reader.fieldnames:
        return valid_rows, ["Empty CSV file."]

    for idx, raw_row in enumerate(reader, start=2):
        row = {k.strip().lower(): (v.strip() if v else "") for k, v in raw_row.items() if k}
        if not any(row.values()):
            continue

        title = clean_text(row.get("title", ""))
        data_dict = {
            "date": row.get("date") or None,
            "title": title,
            "pages_read": row.get("pages_read") or 0,
            "minutes": row.get("minutes") or 0,
        }

        try:
            validated = ReadingCSVRow.model_validate(data_dict)
            valid_rows.append(validated.model_dump())
        except ValidationError as e:
            errors.append(f"Row {idx}: {e.errors()[0]['msg']}")
        except Exception as e:
            errors.append(f"Row {idx}: {e}")

    return valid_rows, errors


def parse_screen_time_csv(csv_content: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse and validate screen time CSV rows."""
    valid_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    reader = csv.DictReader(io.StringIO(csv_content))
    if not reader.fieldnames:
        return valid_rows, ["Empty CSV file."]

    for idx, raw_row in enumerate(reader, start=2):
        row = {k.strip().lower(): (v.strip() if v else "") for k, v in raw_row.items() if k}
        if not any(row.values()):
            continue

        category = clean_text(row.get("category", ""))
        data_dict = {
            "date": row.get("date") or None,
            "category": category,
            "minutes": row.get("minutes") or 0,
        }

        try:
            validated = ScreenTimeCSVRow.model_validate(data_dict)
            valid_rows.append(validated.model_dump())
        except ValidationError as e:
            errors.append(f"Row {idx}: {e.errors()[0]['msg']}")
        except Exception as e:
            errors.append(f"Row {idx}: {e}")

    return valid_rows, errors
