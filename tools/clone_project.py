#!/usr/bin/env python3
"""Clone a Git repository into projects/ and register it as a Crunch project."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / "database" / "crunch.db"
PROJECTS_DIRECTORY = ROOT / "projects"


def read_payload(value: str | None) -> dict[str, Any]:
    raw = value if value is not None else sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("clone JSON must be an object")
    for key in ("url", "description", "toolchain"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    if "project_name" in payload:
        name = payload["project_name"]
        if not isinstance(name, str) or not name.strip() or Path(name).name != name.strip():
            raise ValueError("project_name must be a single directory name")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", help="clone JSON; read stdin when omitted")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        payload = read_payload(args.json)
        PROJECTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        name = payload.get("project_name") or Path(payload["url"].rstrip("/")).name.removesuffix(".git")
        if not name or name in {".", ".."}:
            raise ValueError("could not derive a project name from url; provide project_name")
        workspace = PROJECTS_DIRECTORY / name
        if workspace.exists():
            raise ValueError(f"workspace already exists: {workspace}")
        command = ["git", "clone", payload["url"].strip(), str(workspace)]
        subprocess.run(command, check=True, capture_output=True, text=True)
        from create_project import upsert_project
        upsert_project(args.database, {"project_name": name, "description": payload["description"], "toolchain": payload["toolchain"], "workspace_path": str(workspace)})
    except (ValueError, json.JSONDecodeError, sqlite3.Error, subprocess.SubprocessError) as error:
        parser.error(str(error))
    print(json.dumps({"project_name": name, "workspace_path": str(workspace.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
