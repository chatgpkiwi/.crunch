#!/usr/bin/env python3
# Input JSON: 1 (the task_id integer). Output JSON: the matching task record object, or null when no task has that ID.
"""Return one task record from the SQLite database as JSON."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "database" / "crunch.db"


def _read_task_id(value: str | None) -> tuple[int, int]:
    raw = value if value is not None else sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("task input must be a JSON object")
    task_id, project_id = payload.get("task_id"), payload.get("project_id")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in (task_id, project_id)):
        raise ValueError("task_id and project_id must be integers")
    return task_id, project_id


def get_task(database: Path, task_id: int, project_id: int) -> dict[str, object] | None:
    """Return the task identified by ``task_id``, or ``None`` if absent."""
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT tasks.task_id, tasks.parent_phase_id, tasks.task_name, tasks.task_status, tasks.task_instructions,
                   tasks.task_start_date, tasks.task_end_date, tasks.fail_reason, tasks.completion_summary, tasks.task_order, tasks.test_results
            FROM tasks JOIN phases ON phases.phase_id = tasks.parent_phase_id
            WHERE tasks.task_id = ? AND phases.parent_project_id = ?
            """, (task_id, project_id),
        ).fetchone()
    return dict(row) if row is not None else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", help="task ID JSON payload; read stdin when omitted")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        task = get_task(args.database, *_read_task_id(args.json))
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(task, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
