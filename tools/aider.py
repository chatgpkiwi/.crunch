#!/usr/bin/env python3
"""Send one prompt to the installed Aider CLI and print its final response.

This adapter deliberately launches Aider as a separate process.  It does not
create an OpenAI/LiteLLM client or otherwise call the configured model endpoint
itself; Aider owns that interaction.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


crunch_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = crunch_ROOT / "config" / "config.yaml"
LOG_DIRECTORY = crunch_ROOT / "logs"
AIDER_COMMAND = "aider"
MAX_INVALID_RESPONSE_RETRIES = 2
EXCLUDED_PROJECT_DIRECTORIES = {
    ".git",
    ".crunch",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "build",
    "dist",
}
EXCLUDED_PROJECT_FILE_NAMES = {
    ".aiderignore",
}
INVALID_RESPONSE_FAILURE_REASON = (
    "Aider did not produce a recognizable task-status JSON object after the initial response and two format reminders."
)
JSON_OBJECT_PATTERN = re.compile(r"\{[^{}]*\}")
TASK_FORMAT_REMINDER = """This is an unattended development cycle. Your previous reply was invalid.

Reply now with exactly one JSON object and no other text, Markdown, code fence, question, explanation, or request for files. No other replies will be accepted. You must not ask for more information. Inspect the workspace and complete the assigned task using the existing context.

Reply with exactly one of:
{"task_status":"complete","completion_summary":"- feature, contract, or interface established"}
{"task_status":"failed","fail_reason":"specific reason"}
"""
PHASE_SUMMARY_FORMAT_REMINDER = """Your previous phase-consolidation reply was invalid.

Reply now with exactly one JSON object and no other text:
{"completion_summary":"- consolidated feature, contract, or interface"}
"""


@dataclass(frozen=True)
class AiderSettings:
    """The Aider CLI settings read from one named coding agent."""

    model: str
    openai_api_base: str
    openai_api_key: str


def log_event(event: str, **fields: object) -> None:
    """Append a non-sensitive event to the date-specific Aider log."""
    now = datetime.now().astimezone()
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": now.isoformat(), "event": event, **fields}
    log_path = LOG_DIRECTORY / f"aider-{now.date().isoformat()}.log"
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_agent_fields(config_path: Path, agent_name: str) -> dict[str, str]:
    """Read scalar fields for one named coding agent."""
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read configuration: {error}") from error

    fields: dict[str, str] = {}
    in_agents = False
    in_agent = False
    for line in lines:
        content = line.split("#", 1)[0].rstrip()
        if not content:
            continue
        if content == "coding_agents:":
            in_agents = True
            continue
        if in_agents and not line.startswith((" ", "\t")):
            in_agents = False
            in_agent = False
        if in_agents and line.startswith(("  ", "\t")) and not line.startswith(("    ", "\t\t")) and content.strip() == f"{agent_name}:":
            in_agent = True
            continue
        if in_agent and line.startswith(("  ", "\t")) and not line.startswith(("    ", "\t\t")):
            in_agent = False
        if in_agent and line.startswith(("    ", "\t\t")) and ":" in content:
            key, value = content.strip().split(":", 1)
            fields[key.strip()] = value.strip().strip("\"'")
    return fields


def read_settings(config_path: Path = DEFAULT_CONFIG, agent_name: str = "default_task_agent") -> AiderSettings:
    """Read and validate the Aider settings needed for an Aider CLI run."""
    fields = read_agent_fields(config_path, agent_name)
    if fields.get("provider") != "aider":
        raise ValueError(f"config.yaml must define coding_agents.{agent_name}.provider as aider")
    required = ("model", "openai-api-base", "openai-api-key")
    missing = [field for field in required if not fields.get(field)]
    if missing:
        raise ValueError(f"config.yaml is missing Aider setting(s): {', '.join(missing)}")
    return AiderSettings(
        model=fields["model"],
        openai_api_base=fields["openai-api-base"],
        openai_api_key=fields["openai-api-key"],
    )


def read_prompt(value: str | None) -> str:
    """Return the prompt argument or piped stdin content."""
    if value is not None:
        return value
    if sys.stdin.isatty():
        raise ValueError("provide a prompt argument or pipe a prompt through standard input")
    return sys.stdin.read()


def is_text_file(path: Path) -> bool:
    """Return whether a project file is safe to hand to Aider as source text."""
    try:
        with path.open("rb") as file_handle:
            return b"\0" not in file_handle.read(8192)
    except OSError:
        return False


def project_files(workspace: Path) -> list[Path]:
    """Find editable text files in the project that contains ``.crunch``.

    Aider's repository map only includes Git-tracked files.  A project may not
    yet have a Git repository, or may have untracked files, so explicitly add
    the selected child project's text files. Keep Crunch's own state and generated
    caches out of the coding session.
    """
    files: list[Path] = []
    for path in workspace.rglob("*"):
        relative_path = path.relative_to(workspace)
        if any(part in EXCLUDED_PROJECT_DIRECTORIES for part in relative_path.parts):
            continue
        if (
            path.is_symlink()
            or not path.is_file()
            or path.name in EXCLUDED_PROJECT_FILE_NAMES
            or path.name.startswith(".aider.")
        ):
            continue
        if is_text_file(path):
            files.append(relative_path)
    return sorted(files)


def build_command(
    settings: AiderSettings, prompt_path: Path, task_id: int, editable_files: list[Path]
) -> list[str]:
    """Build a one-shot Aider command that edits the project without commits."""
    history_path = Path(".crunch") / "logs" / f"task-{task_id}-aider-chat-history.md"
    command = [
        AIDER_COMMAND,
        "--model",
        settings.model,
        "--openai-api-base",
        settings.openai_api_base,
        "--openai-api-key",
        settings.openai_api_key,
        "--chat-history-file",
        str(history_path),
        "--message-file",
        str(prompt_path),
        "--yes-always",
        "--no-pretty",
        "--no-stream",
        "--no-auto-commits",
        "--no-show-model-warnings",
        "--no-check-update",
        "--no-analytics",
    ]
    for file_path in editable_files:
        command.extend(("--file", str(file_path)))
    return command


def extract_completion_response(output: str, response_kind: str = "task") -> str:
    """Return a valid task-status JSON object found anywhere in Aider output.

    Aider commonly wraps its final JSON status in prose or a Markdown code
    fence. Scan each flat JSON object in reverse order so the final valid
    status wins, then normalize it before returning it to ``crunch.py``.
    """
    for match in reversed(list(JSON_OBJECT_PATTERN.finditer(output))):
        try:
            response = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if (
            response_kind == "phase-summary"
            and isinstance(response, dict)
            and set(response) == {"completion_summary"}
            and isinstance(response.get("completion_summary"), str)
            and response["completion_summary"].strip()
        ):
            return json.dumps(response, ensure_ascii=False)
        if (
            response_kind == "task"
            and isinstance(response, dict)
            and set(response) == {"task_status", "completion_summary"}
            and response.get("task_status") == "complete"
            and isinstance(response.get("completion_summary"), str)
            and response["completion_summary"].strip()
        ):
            return json.dumps(response, ensure_ascii=False)
        if (
            response_kind == "task"
            and
            isinstance(response, dict)
            and set(response) == {"task_status", "fail_reason"}
            and response.get("task_status") == "failed"
            and isinstance(response.get("fail_reason"), str)
            and response["fail_reason"].strip()
        ):
            return json.dumps(response, ensure_ascii=False)
    raise RuntimeError("Aider output did not contain a valid task-status JSON object")


def run_aider(prompt: str, settings: AiderSettings, task_id: int, workspace: Path, response_kind: str = "task") -> str:
    """Run Aider and return its textual one-shot response."""
    if task_id < 1:
        raise ValueError("task_id must be a positive integer")
    if not shutil.which(AIDER_COMMAND):
        log_event("aider_not_found")
        raise RuntimeError("Aider CLI was not found on PATH")
    with tempfile.TemporaryDirectory(prefix="crunch-aider-") as temporary_directory:
        prompt_path = Path(temporary_directory) / "prompt.md"
        history_path = LOG_DIRECTORY / f"task-{task_id}-aider-chat-history.md"
        editable_files = project_files(workspace)
        reminder = TASK_FORMAT_REMINDER if response_kind == "task" else PHASE_SUMMARY_FORMAT_REMINDER
        prompts = [prompt, *([reminder] * MAX_INVALID_RESPONSE_RETRIES)]
        for attempt, current_prompt in enumerate(prompts):
            prompt_path.write_text(current_prompt, encoding="utf-8")
            command = build_command(settings, prompt_path, task_id, editable_files)
            log_event(
                "invocation_started",
                model=settings.model,
                project_root=str(workspace),
                task_id=task_id,
                editable_file_count=len(editable_files),
                chat_history_file=str(history_path),
                attempt=attempt + 1,
                format_retry=attempt > 0,
            )
            result = subprocess.run(
                command,
                cwd=workspace,
                text=True,
                capture_output=True,
                check=False,
            )
            log_event(
                "process_finished",
                returncode=result.returncode,
                stdout_tail=result.stdout[-1000:],
                stderr_tail=result.stderr[-1000:],
                attempt=attempt + 1,
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "no error output"
                raise RuntimeError(f"Aider exited with {result.returncode}: {detail[:1000]}")
            try:
                return extract_completion_response(result.stdout, response_kind)
            except RuntimeError:
                log_event("invalid_completion_response", task_id=task_id, attempt=attempt + 1)

        if response_kind == "phase-summary":
            raise RuntimeError("Aider did not produce a recognizable phase completion-summary JSON object")
        return json.dumps(
            {"task_status": "failed", "fail_reason": INVALID_RESPONSE_FAILURE_REASON},
            ensure_ascii=False,
        )


def main(arguments: list[str] | None = None) -> int:
    """Read a prompt, execute Aider, and write its final response to stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", help="prompt text; read stdin when omitted")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--agent", default="default_task_agent")
    parser.add_argument("--task-id", type=int, required=True, help="crunch task ID for the isolated Aider chat history file")
    parser.add_argument("--response-kind", choices=("task", "phase-summary"), default="task")
    parser.add_argument("--project-workspace", type=Path, required=True)
    args = parser.parse_args(arguments)
    try:
        prompt = read_prompt(args.prompt)
        if not prompt.strip():
            raise ValueError("prompt cannot be empty")
        workspace = args.project_workspace.expanduser().resolve()
        if not workspace.is_dir():
            raise ValueError(f"project workspace does not exist: {workspace}")
        print(run_aider(prompt, read_settings(args.config, args.agent), args.task_id, workspace, args.response_kind))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        log_event("invocation_failed", reason=str(error))
        print(f"aider.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
