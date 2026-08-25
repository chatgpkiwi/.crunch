#!/usr/bin/env python3
# Expected JSON: {"project_id": 1, "task_id": 1, "task_instructions": "Replacement instructions."}
"""Reset a failed task for a deterministic retry."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "database" / "crunch.db"


def _read_payload(value: str | None) -> dict[str, Any]:
    raw = value if value is not None else sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("fix input must be a JSON object")
    for field in ("project_id", "task_id"):
        if isinstance(payload.get(field), bool) or not isinstance(payload.get(field), int):
            raise ValueError(f"{field} must be an integer")
    instructions = payload.get("task_instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError("task_instructions must be a non-empty string")
    unknown = set(payload) - {"project_id", "task_id", "task_instructions"}
    if unknown:
        raise ValueError(f"unknown fix fields: {', '.join(sorted(unknown))}")
    return payload


def fix_task(database: Path, payload: dict[str, Any]) -> dict[str, object]:
    """Reset execution state and replace instructions for one task."""
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(
            """
            UPDATE tasks
            SET task_status = 'new',
                task_instructions = ?,
                task_start_date = NULL,
                task_end_date = NULL,
                fail_reason = NULL,
                completion_summary = NULL,
                test_results = NULL,
                retry_count = retry_count + 1
            WHERE task_id = ? AND EXISTS (SELECT 1 FROM phases WHERE phases.phase_id = tasks.parent_phase_id AND phases.parent_project_id = ?)
            """, (payload["task_instructions"].strip(), payload["task_id"], payload["project_id"]),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"task {payload['task_id']} does not exist")
        row = connection.execute(
            """
            SELECT tasks.task_id, tasks.parent_phase_id, tasks.task_name, tasks.task_status, tasks.task_instructions,
                   tasks.task_start_date, tasks.task_end_date, tasks.fail_reason, tasks.completion_summary, tasks.retry_count, tasks.task_order, tasks.test_results
            FROM tasks JOIN phases ON phases.phase_id = tasks.parent_phase_id
            WHERE tasks.task_id = ? AND phases.parent_project_id = ?
            """, (payload["task_id"], payload["project_id"]),
        ).fetchone()
    assert row is not None
    return dict(row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", help="fix JSON; read stdin when omitted")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        task = fix_task(args.database, _read_payload(args.json))
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(task, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
