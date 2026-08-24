#!/usr/bin/env python3
# Input JSON: 1 (a phase_id integer). Output JSON: the matching phase record object, or null when no phase has that ID.
"""Return one phase record from the SQLite database as JSON."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "database" / "crunch.db"


def _read_phase_id(value: str | None) -> int:
    raw = value if value is not None else sys.stdin.read()
    phase_id = json.loads(raw)
    if isinstance(phase_id, bool) or not isinstance(phase_id, int):
        raise ValueError("phase input must be a JSON integer")
    return phase_id


def get_phase(database: Path, phase_id: int) -> dict[str, object] | None:
    """Return the phase identified by ``phase_id``, or ``None`` if absent."""
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT phase_id, parent_project_id, phase_name, phase_summary, status, deliverables,
                   architecture_contract, acceptance_checklist, fail_reason, phase_order
            FROM phases
            WHERE phase_id = ?
            """,
            (phase_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", help="JSON phase ID; read stdin when omitted")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        phase = get_phase(args.database, _read_phase_id(args.json))
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(phase, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
