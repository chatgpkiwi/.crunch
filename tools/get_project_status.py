#!/usr/bin/env python3
# Output JSON: {"project": {"project_id": 1, "project_name": "...", "phases": [{"phase_id": 1, "phase_name": "...", "status": "new", "tasks": [{"task_id": 1, "task_name": "...", "task_status": "new"}]}]}}; only ID, name, and status fields are returned.
"""Return the project's IDs, names, and statuses as nested JSON."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "database" / "crunch.db"


def get_project_status(database: Path = DEFAULT_DATABASE) -> dict[str, object] | None:
    """Return the project status tree, or ``None`` when no project exists."""
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        project_row = connection.execute(
            "SELECT project_id, project_name FROM project ORDER BY project_id LIMIT 1"
        ).fetchone()
        if project_row is None:
            return None
        phases = []
        phase_rows = connection.execute(
            "SELECT phase_id, phase_name, status FROM phases ORDER BY phase_order, phase_id"
        ).fetchall()
        for phase_row in phase_rows:
            phase = dict(phase_row)
            tasks = [
                dict(task_row)
                for task_row in connection.execute(
                    """
                    SELECT task_id, task_name, task_status
                    FROM tasks
                    WHERE parent_phase_id = ?
                    ORDER BY task_order, task_id
                    """,
                    (phase["phase_id"],),
                ).fetchall()
            ]
            phase["tasks"] = tasks
            phases.append(phase)
    project = dict(project_row)
    project["phases"] = phases
    return {"project": project}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    print(json.dumps(get_project_status(args.database), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
