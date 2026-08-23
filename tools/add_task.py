#!/usr/bin/env python3
# Expected JSON: {"parent_phase_id": 1, "tasks": [{"task_name": "...", "task_instructions": "...", "task_status": "new", "task_order": 1, "task_start_date": null, "task_end_date": null, "fail_reason": null, "test_results": null}]}
"""Insert one or more tasks (parts) into a phase."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "database" / "crunch.db"
STATUSES = {"new", "in_progress", "complete", "fail"}


def _read_payload(value: str | None) -> dict[str, Any]:
    raw = value if value is not None else sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("task input must be a JSON object")
    if isinstance(payload.get("parent_phase_id"), bool) or not isinstance(payload.get("parent_phase_id"), int):
        raise ValueError("parent_phase_id must be an integer")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks must be a non-empty array")
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("each task must be a JSON object")
        for field in ("task_name", "task_instructions"):
            if not isinstance(task.get(field), str) or not task[field].strip():
                raise ValueError(f"{field} must be a non-empty string")
        if task.get("task_status", "new") not in STATUSES:
            raise ValueError(f"task_status must be one of: {', '.join(sorted(STATUSES))}")
        if "task_order" in task and (isinstance(task["task_order"], bool) or not isinstance(task["task_order"], int)):
            raise ValueError("task_order must be an integer")
    return payload


def add_tasks(database: Path, payload: dict[str, Any]) -> list[int]:
    """Insert all tasks in one transaction and return their IDs."""
    database.parent.mkdir(parents=True, exist_ok=True)
    inserted_ids: list[int] = []
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for index, task in enumerate(payload["tasks"], start=1):
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    parent_phase_id, task_name, task_status, task_instructions,
                    task_start_date, task_end_date, fail_reason, task_order, test_results
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["parent_phase_id"],
                    task["task_name"].strip(),
                    task.get("task_status", "new"),
                    task["task_instructions"],
                    task.get("task_start_date"),
                    task.get("task_end_date"),
                    task.get("fail_reason"),
                    task.get("task_order", index),
                    task.get("test_results"),
                ),
            )
            inserted_ids.append(int(cursor.lastrowid))
    return inserted_ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", help="task batch JSON; read stdin when omitted")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        ids = add_tasks(args.database, _read_payload(args.json))
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps({"task_ids": ids}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
