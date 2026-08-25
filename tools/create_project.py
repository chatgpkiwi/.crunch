#!/usr/bin/env python3
# Expected JSON: {"project_id": 1, "project_name": "...", "description": "...", "toolchain": "...", "workspace_path": "/path/to/project"}
"""Create or replace the project's SQLite metadata record."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "database" / "crunch.db"


def _read_payload(value: str | None) -> dict[str, Any]:
    raw = value if value is not None else sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("project JSON must be an object")
    for field in ("project_name", "description", "toolchain"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    if "project_id" in payload and not isinstance(payload["project_id"], int):
        raise ValueError("project_id must be an integer")
    workspace_path = payload.get("workspace_path", payload.get("root_path"))
    if not isinstance(workspace_path, str) or not workspace_path.strip():
        raise ValueError("workspace_path must be a non-empty string")
    payload["workspace_path"] = workspace_path
    return payload


def upsert_project(database: Path, payload: dict[str, Any]) -> None:
    """Insert the project, replacing the existing record with the same ID."""
    project_id = payload.get("project_id")
    now = datetime.now(timezone.utc).isoformat()
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO project (
                project_id, project_name, description, toolchain, workspace_path, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                project_name = excluded.project_name,
                description = excluded.description,
                toolchain = excluded.toolchain,
                workspace_path = excluded.workspace_path,
                updated_at = excluded.updated_at
            """,
            (
                project_id,
                payload["project_name"].strip(),
                payload["description"].strip(),
                payload["toolchain"].strip(),
                str(Path(payload["workspace_path"]).expanduser().resolve()),
                now,
                now,
            ),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", help="project JSON object; read stdin when omitted")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        upsert_project(args.database, _read_payload(args.json))
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
