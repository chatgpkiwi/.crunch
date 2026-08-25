"""Focused regression tests for Codex adapter response handling."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import codex  # noqa: E402


class NormalizeFinalResponseTests(unittest.TestCase):
    def test_extracts_status_json_from_markdown_and_internal_tag(self) -> None:
        response = '```json\n{"task_status": "complete"}\n</parameter>'

        self.assertEqual(codex.normalize_final_response(response), '{"task_status": "complete"}')

    def test_keeps_unrecognized_response_for_the_worker_to_reject(self) -> None:
        self.assertEqual(codex.normalize_final_response("done"), "done")

    def test_uses_explicit_local_provider_overrides(self) -> None:
        observed_command = []

        class FakeProcess:
            def __init__(self, command):
                self.command = command
                self.stdin = SimpleNamespace(write=lambda value: None, close=lambda: None)
                class Output:
                    def __iter__(self):
                        return iter(['{"type":"turn.started","turn_id":"turn-1"}\n'])

                    def close(self):
                        pass

                self.stdout = Output()

            def wait(self):
                output_path = Path(self.command[self.command.index("--output-last-message") + 1])
                output_path.write_text('{"task_status":"complete"}', encoding="utf-8")
                return 0

        def fake_popen(command, **kwargs):
            observed_command.extend(command)
            return FakeProcess(command)

        settings = codex.CodexSettings(
            model="Qwen3-Coder-Next-Q6_K_L",
            effort=None,
            local_provider=codex.LocalProviderSettings(
                provider="lemonade",
                provider_name="Local Lemonade",
                base_url="http://127.0.0.1:13305/v1",
                wire_api="responses",
                context_window=262144,
                requires_openai_auth=False,
                supports_websockets=False,
            ),
        )
        with patch.object(codex.shutil, "which", return_value="codex"), patch.object(codex.subprocess, "Popen", side_effect=fake_popen):
            response = codex.run_codex("test prompt", settings, Path("."))

        self.assertEqual(response, '{"task_status": "complete"}')
        self.assertIn("--ignore-user-config", observed_command)
        self.assertNotIn("--profile", observed_command)
        self.assertIn('model_provider="lemonade"', observed_command)
        self.assertIn('model_providers.lemonade.base_url="http://127.0.0.1:13305/v1"', observed_command)


if __name__ == "__main__":
    unittest.main()
