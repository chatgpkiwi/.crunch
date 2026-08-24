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


def _read_task_id(value: str | None) -> int:
    raw = value if value is not None else sys.stdin.read()
    payload = json.loads(raw)
    # Accept the raw ID as the documented format and the object form for compatibility.
    task_id = payload.get("task_id") if isinstance(payload, dict) else payload
    if isinstance(task_id, bool) or not isinstance(task_id, int):
        raise ValueError("task_id must be an integer")
    return task_id


def get_task(database: Path, task_id: int) -> dict[str, object] | None:
    """Return the task identified by ``task_id``, or ``None`` if absent."""
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT task_id, parent_phase_id, task_name, task_status, task_instructions,
                   task_start_date, task_end_date, fail_reason, task_order, test_results
            FROM tasks
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", help="task ID JSON payload; read stdin when omitted")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        task = get_task(args.database, _read_task_id(args.json))
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(task, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
