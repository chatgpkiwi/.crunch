#!/usr/bin/env python3
# Input JSON: {}, {"phase_id": 1}, {"output": "simple"}, or {"phase_id": 1, "output": "simple"}. Output JSON: {"project": {project fields..., "phases": [{phase fields..., "tasks": [task records...]}]}}; simple output omits long-form phase and task text fields.
"""Return the project record with nested phases and tasks as JSON."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "database" / "grindr.db"
SIMPLE_PHASE_FIELDS = {"deliverables", "architecture_contract", "acceptance_checklist"}
SIMPLE_TASK_FIELDS = {"task_instructions", "test_results"}


def _read_options(value: str | None) -> dict[str, Any]:
    # With no argument, an interactive terminal means default options rather
    # than an invitation to wait forever for optional stdin input.
    raw = value if value is not None else ("" if sys.stdin.isatty() else sys.stdin.read())
    if not raw.strip():
        return {}
    options = json.loads(raw)
    if not isinstance(options, dict):
        raise ValueError("summary input must be a JSON object")
    if "phase_id" in options and (isinstance(options["phase_id"], bool) or not isinstance(options["phase_id"], int)):
        raise ValueError("phase_id must be an integer")
    if "output" in options and options["output"] != "simple":
        raise ValueError("output must be \"simple\" when provided")
    unknown = set(options) - {"phase_id", "output"}
    if unknown:
        raise ValueError(f"unknown summary options: {', '.join(sorted(unknown))}")
    return options


def _without_fields(record: dict[str, object], fields: set[str]) -> dict[str, object]:
    return {key: value for key, value in record.items() if key not in fields}


def get_project_summary(database: Path, options: dict[str, Any] | None = None) -> dict[str, object] | None:
    """Return the project and nested records, optionally filtered/projected."""
    options = options or {}
    simple = options.get("output") == "simple"
    phase_id = options.get("phase_id")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        project_row = connection.execute(
            "SELECT project_id, project_name, description, root_path, created_at, updated_at FROM project ORDER BY project_id LIMIT 1"
        ).fetchone()
        if project_row is None:
            return None
        phase_sql = """
            SELECT phase_id, parent_project_id, phase_name, phase_summary, status,
                   deliverables, architecture_contract, acceptance_checklist,
                   fail_reason, phase_order
            FROM phases
        """
        phase_parameters: tuple[object, ...] = ()
        if phase_id is not None:
            phase_sql += " WHERE phase_id = ?"
            phase_parameters = (phase_id,)
        phase_sql += " ORDER BY phase_order, phase_id"
        phase_rows = connection.execute(phase_sql, phase_parameters).fetchall()
        phases: list[dict[str, object]] = []
        for phase_row in phase_rows:
            phase = dict(phase_row)
            task_rows = connection.execute(
                """
                SELECT task_id, parent_phase_id, task_name, task_status, task_instructions,
                       task_start_date, task_end_date, fail_reason, task_order, test_results
                FROM tasks WHERE parent_phase_id = ? ORDER BY task_order, task_id
                """,
                (phase["phase_id"],),
            ).fetchall()
            tasks = [dict(task_row) for task_row in task_rows]
            if simple:
                phase = _without_fields(phase, SIMPLE_PHASE_FIELDS)
                tasks = [_without_fields(task, SIMPLE_TASK_FIELDS) for task in tasks]
            phase["tasks"] = tasks
            phases.append(phase)
    project = dict(project_row)
    project["phases"] = phases
    return {"project": project}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", help="summary options JSON; read stdin when omitted")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        summary = get_project_summary(args.database, _read_options(args.json))
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
