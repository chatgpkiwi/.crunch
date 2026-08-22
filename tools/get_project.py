#!/usr/bin/env python3
# Output JSON: {"project_id": 1, "project_name": "...", "description": "...", "root_path": null, "created_at": "...", "updated_at": "..."} or null when no project exists.
"""Return the only project record as JSON, or null when the table is empty."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "database" / "grindr.db"


def get_project(database: Path = DEFAULT_DATABASE) -> dict[str, object] | None:
    """Return the first project record, or ``None`` when no record exists."""
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT project_id, project_name, description, root_path, created_at, updated_at
            FROM project
            ORDER BY project_id
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row is not None else None


def main() -> int:
    print(json.dumps(get_project(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
