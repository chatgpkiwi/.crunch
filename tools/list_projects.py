#!/usr/bin/env python3
"""List every registered Crunch project."""
import argparse
import json
import sqlite3
from pathlib import Path

DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "database" / "crunch.db"

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT project_id, project_name, description, toolchain, workspace_path, created_at, updated_at FROM project ORDER BY project_id").fetchall()
    print(json.dumps({"projects": [dict(row) for row in rows]}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
