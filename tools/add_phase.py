#!/usr/bin/env python3
# Expected JSON: {"phase_id": 1, "parent_project_id": 1, "phase_name": "Foundation", "phase_summary": "...", "status": "new", "deliverables": "...", "architecture_contract": "...", "acceptance_checklist": "...", "fail_reason": null, "phase_order": 1}
"""Insert a project phase into the SQLite database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "database" / "grindr.db"
STATUSES = {"new", "in_progress", "complete", "fail"}
REQUIRED_TEXT_FIELDS = (
    "phase_name",
    "phase_summary",
    "deliverables",
    "architecture_contract",
    "acceptance_checklist",
)


def _read_payload(value: str | None) -> dict[str, Any]:
    raw = value if value is not None else sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("phase JSON must be an object")
    for field in REQUIRED_TEXT_FIELDS:
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    if "status" in payload and payload["status"] not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")
    for field in ("phase_id", "parent_project_id", "phase_order"):
        if field in payload and not isinstance(payload[field], int):
            raise ValueError(f"{field} must be an integer")
    if "fail_reason" in payload and payload["fail_reason"] is not None and not isinstance(payload["fail_reason"], str):
        raise ValueError("fail_reason must be a string or null")
    return payload


def add_phase(database: Path, payload: dict[str, Any]) -> int:
    """Insert a phase and return its database identifier."""
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        cursor = connection.execute(
            """
            INSERT INTO phases (
                phase_id, parent_project_id, phase_name, status, deliverables,
                phase_summary, architecture_contract, acceptance_checklist, fail_reason, phase_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("phase_id"),
                payload.get("parent_project_id", 1),
                payload["phase_name"].strip(),
                payload.get("status", "new"),
                payload["deliverables"],
                payload["phase_summary"].strip(),
                payload["architecture_contract"],
                payload["acceptance_checklist"],
                payload.get("fail_reason"),
                payload.get("phase_order", payload.get("phase_id")),
            ),
        )
        return int(cursor.lastrowid)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", help="phase JSON object; read stdin when omitted")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        payload = _read_payload(args.json)
        if "phase_order" not in payload and "phase_id" not in payload:
            raise ValueError("phase_order or phase_id is required")
        phase_id = add_phase(args.database, payload)
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps({"phase_id": phase_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
