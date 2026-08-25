#!/usr/bin/env python3
# Input JSON: a project_id integer. Output: that project record or null.
"""Return one project record as JSON."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "database" / "crunch.db"


def get_project(database: Path, project_id: int) -> dict[str, object] | None:
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT project_id, project_name, description, toolchain, workspace_path, created_at, updated_at
            FROM project WHERE project_id = ?
            """
            , (project_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", help="JSON project ID; read stdin when omitted")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        project_id = json.loads(args.json if args.json is not None else sys.stdin.read())
        if isinstance(project_id, bool) or not isinstance(project_id, int):
            raise ValueError("project input must be a JSON integer")
        result = get_project(args.database, project_id)
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
