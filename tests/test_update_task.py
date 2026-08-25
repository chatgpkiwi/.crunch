"""Regression tests for safe task-state updates."""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import update_task  # noqa: E402


class UpdateTaskStateTests(unittest.TestCase):
    def test_rejects_reset_of_an_active_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "crunch.db"
            schema = Path(__file__).resolve().parents[1] / "database" / "schema.sql"
            with sqlite3.connect(database) as connection:
                connection.executescript(schema.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO project VALUES (1, 'project', 'description', 'Python 3.12; pytest.', '/tmp/project', 'now', 'now')"
                )
                connection.execute(
                    "INSERT INTO phases (phase_id, parent_project_id, phase_name, phase_summary, status, deliverables, architecture_contract, acceptance_checklist, fail_reason, phase_order) VALUES (1, 1, 'phase', 'summary', 'in_progress', 'deliverables', 'contract', 'checks', NULL, 1)"
                )
                connection.execute(
                    "INSERT INTO tasks (task_id, parent_phase_id, task_name, task_status, task_instructions, task_order) VALUES (1, 1, 'task', 'in_progress', 'instructions', 1)"
                )

            with self.assertRaisesRegex(ValueError, "cannot reset an in-progress task"):
                update_task.update_task(database, {"project_id": 1, "task_id": 1, "task_status": "new"})


if __name__ == "__main__":
    unittest.main()
