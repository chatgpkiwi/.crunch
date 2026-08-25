"""Focused regression tests for worker prompt and response logs."""

import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import crunch  # noqa: E402


class FakeAdapterProcess:
    """Small Popen substitute that keeps adapter execution tests deterministic."""

    _next_pid = 1000

    def __init__(self, result):
        self.result = result
        self.pid = FakeAdapterProcess._next_pid
        FakeAdapterProcess._next_pid += 1
        self.returncode = None

    def communicate(self, input=None):
        self.returncode = self.result.returncode
        return self.result.stdout, self.result.stderr

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode


class CodexExchangeLogTests(unittest.TestCase):
    def test_appends_prompt_and_response_to_task_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_directory = crunch.PROMPT_LOG_DIRECTORY
            crunch.PROMPT_LOG_DIRECTORY = Path(directory)
            try:
                crunch.log_codex_exchange(42, "implement the task", '{"task_status":"complete"}')
            finally:
                crunch.PROMPT_LOG_DIRECTORY = original_directory

            content = (Path(directory) / "42.log").read_text(encoding="utf-8")
            self.assertIn("PROMPT\nimplement the task", content)
            self.assertIn('RESPONSE\n{"task_status":"complete"}', content)

    def test_prompt_includes_project_toolchain(self) -> None:
        record = {
            "project_name": "example",
            "description": "Example project.",
            "toolchain": "Python 3.12; pytest.",
            "phase_summary": "Phase summary.",
            "deliverables": "Deliverables.",
            "architecture_contract": "Contract.",
            "acceptance_checklist": "Checks.",
            "task_name": "Task.",
            "task_instructions": "Instructions.",
            "previous_phase_completion_summaries": [
                {"phase_name": "Foundation", "completion_summary": "- Added package layout."},
            ],
            "previous_task_completion_summaries": [
                {"task_name": "Earlier task", "completion_summary": "- Added a reusable API."},
            ],
        }

        prompt = crunch.build_prompt(record)
        self.assertIn("## Required Toolchain\n\nPython 3.12; pytest.", prompt)
        self.assertIn("## Completed Phase Context", prompt)
        self.assertIn("- Added package layout.", prompt)
        self.assertIn("## Earlier Task Context in This Phase", prompt)
        self.assertIn("- Added a reusable API.", prompt)

    def test_complete_response_requires_a_completion_summary(self) -> None:
        with self.assertRaises(ValueError):
            crunch.parse_agent_response('{"task_status":"complete"}')

        self.assertEqual(
            crunch.parse_agent_response(
                '{"task_status":"complete","completion_summary":"- Added an API."}'
            ),
            {
                "task_status": "complete",
                "fail_reason": None,
                "completion_summary": "- Added an API.",
            },
        )


class CodexTransportFailureTests(unittest.TestCase):
    def test_detects_terminal_stream_disconnect_event(self) -> None:
        output = '\n'.join(
            [
                '{"type":"turn.started"}',
                '{"type":"turn.failed","error":{"message":"stream disconnected before completion"}}',
            ]
        )

        self.assertEqual(crunch.codex_transport_failure_reason(output), "stream disconnected before completion")

    def test_retries_one_transport_failure_then_accepts_success(self) -> None:
        failed = SimpleNamespace(
            returncode=1,
            stdout='{"type":"turn.failed","error":{"message":"stream disconnected before completion"}}',
            stderr="",
        )
        succeeded = SimpleNamespace(returncode=0, stdout='{"task_status":"complete","completion_summary":"- Completed the task"}', stderr="")
        with patch.object(crunch.subprocess, "Popen", side_effect=[FakeAdapterProcess(failed), FakeAdapterProcess(succeeded)]) as popen, patch.object(crunch, "log_event"), patch.object(crunch, "log_prompt") as prompt_log, patch.object(crunch, "log_response") as response_log:
            outcome = crunch.run_agent("default_task_agent", "codex", "prompt", 7, Path("."))

        self.assertEqual(outcome, {"task_status": "complete", "fail_reason": None, "completion_summary": "- Completed the task"})
        self.assertEqual(popen.call_count, 2)
        self.assertEqual(prompt_log.call_count, 2)
        self.assertEqual(response_log.call_count, 2)

    def test_logs_prompt_before_non_codex_agent_starts(self) -> None:
        result = SimpleNamespace(returncode=0, stdout='{"task_status":"complete","completion_summary":"- Completed the task"}', stderr="")
        events = []
        with patch.object(crunch.subprocess, "Popen", return_value=FakeAdapterProcess(result)) as popen, patch.object(crunch, "log_event"), patch.object(crunch, "log_prompt", side_effect=lambda *args: events.append("prompt")), patch.object(crunch, "log_response", side_effect=lambda *args: events.append("response")):
            crunch.run_agent("default_task_agent", "qwen", "prompt", 8, Path("."))

        self.assertEqual(events, ["prompt", "response"])
        self.assertEqual(popen.call_count, 1)

    def test_requeues_with_the_existing_task_instructions(self) -> None:
        result = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(crunch.subprocess, "run", return_value=result) as run:
            crunch.requeue_task_after_transport_failure(Path("/tmp/crunch.db"), 3, 9, "keep this scope")

        self.assertEqual(run.call_args.kwargs["input"], '{"project_id": 3, "task_id": 9, "task_instructions": "keep this scope"}')


class WorkerStopStateTests(unittest.TestCase):
    def test_stop_request_prevents_claim_and_preserves_new_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "crunch.db"
            schema = (Path(__file__).resolve().parents[1] / "database" / "schema.sql").read_text(encoding="utf-8")
            import sqlite3
            with sqlite3.connect(database) as connection:
                connection.executescript(schema)
                connection.execute("INSERT INTO project (project_id, project_name, description, toolchain, workspace_path) VALUES (1, 'project', 'description', '', ?)", (directory,))
                connection.execute("INSERT INTO phases (phase_id, parent_project_id, phase_name, phase_summary, deliverables, architecture_contract, acceptance_checklist, phase_order) VALUES (1, 1, 'phase', 'summary', '', '', '', 1)")
                connection.execute("INSERT INTO tasks (task_id, parent_phase_id, task_name, task_instructions, task_order) VALUES (1, 1, 'task', 'instructions', 1)")
                connection.execute("UPDATE worker_state SET stop_requested = 1 WHERE worker_id = 1")

            self.assertFalse(crunch.claim_task(database, 1))
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT task_status FROM tasks WHERE task_id = 1").fetchone()[0], "new")

    def test_interrupt_requeues_active_task_and_records_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "crunch.db"
            schema = (Path(__file__).resolve().parents[1] / "database" / "schema.sql").read_text(encoding="utf-8")
            import sqlite3
            with sqlite3.connect(database) as connection:
                connection.executescript(schema)
                connection.execute("INSERT INTO project (project_id, project_name, description, toolchain, workspace_path) VALUES (1, 'project', 'description', '', ?)", (directory,))
                connection.execute("INSERT INTO phases (phase_id, parent_project_id, phase_name, phase_summary, deliverables, architecture_contract, acceptance_checklist, phase_order) VALUES (1, 1, 'phase', 'summary', '', '', '', 1)")
                connection.execute("INSERT INTO tasks (task_id, parent_phase_id, task_name, task_status, task_instructions, task_order) VALUES (1, 1, 'task', 'in_progress', 'instructions', 1)")

            self.assertTrue(crunch.interrupt_task(database, 1))
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT task_status FROM tasks WHERE task_id = 1").fetchone()[0], "new")
                self.assertEqual(connection.execute("SELECT stop_requested, active_task_id, run_status FROM worker_state WHERE worker_id = 1").fetchone(), (1, None, "interrupted"))


if __name__ == "__main__":
    unittest.main()
