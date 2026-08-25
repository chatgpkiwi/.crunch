#!/usr/bin/env python3
# Expected JSON: {"project_id": 1, "task_id": 1, "task_status": "complete", "completion_summary": "- Established contract"}.
"""Partially update an existing task record."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "database" / "crunch.db"
STATUSES = {"new", "in_progress", "complete", "fail"}
MUTABLE_FIELDS = {
    "parent_phase_id",
    "task_name",
    "task_status",
    "task_instructions",
    "task_start_date",
    "task_end_date",
    "fail_reason",
    "completion_summary",
    "task_order",
    "test_results",
}
REQUIRED_TEXT_FIELDS = {"task_name", "task_instructions"}
NULLABLE_FIELDS = {"task_start_date", "task_end_date", "fail_reason", "completion_summary", "test_results"}


def _read_payload(value: str | None) -> dict[str, Any]:
    raw = value if value is not None else sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("task update must be a JSON object")
    for field in ("project_id", "task_id"):
        if isinstance(payload.get(field), bool) or not isinstance(payload.get(field), int):
            raise ValueError(f"{field} must be an integer")
    fields = set(payload) - {"project_id", "task_id"}
    unknown = fields - MUTABLE_FIELDS
    if unknown:
        raise ValueError(f"unknown task fields: {', '.join(sorted(unknown))}")
    if not fields:
        raise ValueError("at least one task field must be supplied for update")
    for field in REQUIRED_TEXT_FIELDS & fields:
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    if "task_status" in fields and payload["task_status"] not in STATUSES:
        raise ValueError(f"task_status must be one of: {', '.join(sorted(STATUSES))}")
    for field in {"parent_phase_id", "task_order"} & fields:
        if isinstance(payload[field], bool) or not isinstance(payload[field], int):
            raise ValueError(f"{field} must be an integer")
    for field in NULLABLE_FIELDS & fields:
        if payload[field] is not None and not isinstance(payload[field], str):
            raise ValueError(f"{field} must be a string or null")
    return payload


def update_task(database: Path, payload: dict[str, Any]) -> dict[str, object]:
    """Apply supplied fields to a task and return the updated record."""
    fields = sorted(set(payload) - {"project_id", "task_id"})
    assignments = ", ".join(f"{field} = ?" for field in fields)
    values = [payload[field].strip() if field in REQUIRED_TEXT_FIELDS else payload[field] for field in fields]
    values.append(payload["task_id"])
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        current = connection.execute(
            """
            SELECT tasks.task_status
            FROM tasks JOIN phases ON phases.phase_id = tasks.parent_phase_id
            WHERE tasks.task_id = ? AND phases.parent_project_id = ?
            """,
            (payload["task_id"], payload["project_id"]),
        ).fetchone()
        if current is None:
            raise ValueError(f"task {payload['task_id']} does not exist")
        if current["task_status"] == "in_progress" and payload.get("task_status") == "new":
            raise ValueError(
                "cannot reset an in-progress task through update_task; stop the worker "
                "and use fix_task to requeue it"
            )
        cursor = connection.execute(
            f"UPDATE tasks SET {assignments} WHERE task_id = ? AND EXISTS (SELECT 1 FROM phases WHERE phases.phase_id = tasks.parent_phase_id AND phases.parent_project_id = ?)",
            [*values, payload["project_id"]],
        )
        if cursor.rowcount != 1:
            raise ValueError(f"task {payload['task_id']} does not exist")
        row = connection.execute(
            """
            SELECT tasks.task_id, tasks.parent_phase_id, tasks.task_name, tasks.task_status, tasks.task_instructions,
                   tasks.task_start_date, tasks.task_end_date, tasks.fail_reason, tasks.completion_summary, tasks.task_order, tasks.test_results
            FROM tasks JOIN phases ON phases.phase_id = tasks.parent_phase_id
            WHERE tasks.task_id = ? AND phases.parent_project_id = ?
            """, (payload["task_id"], payload["project_id"]),
        ).fetchone()
    assert row is not None
    return dict(row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", help="task update JSON; read stdin when omitted")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        task = update_task(args.database, _read_payload(args.json))
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(task, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
