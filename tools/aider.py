#!/usr/bin/env python3
"""Send one prompt to the installed Aider CLI and print its final response.

This adapter deliberately launches Aider as a separate process.  It does not
create an OpenAI/LiteLLM client or otherwise call the configured model endpoint
itself; Aider owns that interaction.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


crunch_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = crunch_ROOT.parent
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
    "Aider did not produce the required task-status JSON after the initial response and two format reminders."
)
FORMAT_REMINDER = """This is an unattended development cycle. Your previous reply was invalid.

Reply now with exactly one JSON object and no other text, Markdown, code fence, question, explanation, or request for files. No other replies will be accepted. You must not ask for more information. Inspect the workspace and complete the assigned task using the existing context.

Reply with exactly one of:
{"task_status":"complete"}
{"task_status":"failed","fail_reason":"specific reason"}
"""


@dataclass(frozen=True)
class AiderSettings:
    """The Aider CLI settings read from ``coding_agents.default``."""

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


def read_default_agent_fields(config_path: Path) -> dict[str, str]:
    """Read scalar fields from the project's small coding-agent YAML section."""
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read configuration: {error}") from error

    fields: dict[str, str] = {}
    in_default = False
    for line in lines:
        content = line.split("#", 1)[0].rstrip()
        if not content:
            continue
        if content == "  default:":
            in_default = True
            continue
        if in_default and not line.startswith("    "):
            in_default = False
        if in_default and line.startswith("    ") and ":" in content:
            key, value = content.strip().split(":", 1)
            fields[key.strip()] = value.strip().strip("\"'")
    return fields


def read_settings(config_path: Path = DEFAULT_CONFIG) -> AiderSettings:
    """Read and validate the Aider settings needed for an Aider CLI run."""
    fields = read_default_agent_fields(config_path)
    if fields.get("provider") != "aider":
        raise ValueError("config.yaml must define coding_agents.default.provider as aider")
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


def project_files() -> list[Path]:
    """Find editable text files in the project that contains ``.crunch``.

    Aider's repository map only includes Git-tracked files.  A project may not
    yet have a Git repository, or may have untracked files, so explicitly add
    the parent project's text files.  Keep crunch's own state and generated
    caches out of the coding session.
    """
    files: list[Path] = []
    for path in PROJECT_ROOT.rglob("*"):
        relative_path = path.relative_to(PROJECT_ROOT)
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


def extract_completion_response_from_history(history_path: Path) -> str:
    """Read the latest Aider reply and require exactly one unfenced JSON object.

    Aider's terminal transcript may wrap long JSON strings. Its chat history
    preserves the model's raw reply, while marking command output with ``>``
    and the prompt with ``####``. Inspecting that latest section lets crunch
    reject prose and Markdown fences without mistaking Aider's own status
    output for the model's response.
    """
    try:
        latest_session = history_path.read_text(encoding="utf-8").rsplit("# aider chat started", 1)[-1]
    except OSError as error:
        raise RuntimeError(f"cannot read Aider chat history: {error}") from error
    _, separator, latest_session = latest_session.partition("\n")
    if not separator:
        raise RuntimeError("Aider chat history does not contain a completed session")

    reply_lines = [
        line.strip()
        for line in latest_session.splitlines()
        if line.strip()
        and not line.lstrip().startswith(("#", ">", "####"))
    ]
    if len(reply_lines) != 1:
        raise RuntimeError("Aider completed without exactly one JSON task-status reply")

    try:
        response = json.loads(reply_lines[0])
    except json.JSONDecodeError as error:
        raise RuntimeError("Aider completed without exactly one JSON task-status reply") from error
    if response == {"task_status": "complete"}:
        return json.dumps(response, ensure_ascii=False)
    if (
        isinstance(response, dict)
        and set(response) == {"task_status", "fail_reason"}
        and response.get("task_status") == "failed"
        and isinstance(response.get("fail_reason"), str)
        and response["fail_reason"].strip()
    ):
        return json.dumps(response, ensure_ascii=False)
    raise RuntimeError("Aider completed without exactly one JSON task-status reply")


def run_aider(prompt: str, settings: AiderSettings, task_id: int) -> str:
    """Run Aider and return its textual one-shot response."""
    if task_id < 1:
        raise ValueError("task_id must be a positive integer")
    if not shutil.which(AIDER_COMMAND):
        log_event("aider_not_found")
        raise RuntimeError("Aider CLI was not found on PATH")
    with tempfile.TemporaryDirectory(prefix="crunch-aider-") as temporary_directory:
        prompt_path = Path(temporary_directory) / "prompt.md"
        history_path = LOG_DIRECTORY / f"task-{task_id}-aider-chat-history.md"
        editable_files = project_files()
        prompts = [prompt, *([FORMAT_REMINDER] * MAX_INVALID_RESPONSE_RETRIES)]
        for attempt, current_prompt in enumerate(prompts):
            prompt_path.write_text(current_prompt, encoding="utf-8")
            command = build_command(settings, prompt_path, task_id, editable_files)
            log_event(
                "invocation_started",
                model=settings.model,
                project_root=str(PROJECT_ROOT),
                task_id=task_id,
                editable_file_count=len(editable_files),
                chat_history_file=str(history_path),
                attempt=attempt + 1,
                format_retry=attempt > 0,
            )
            result = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
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
                return extract_completion_response_from_history(history_path)
            except RuntimeError:
                log_event("invalid_completion_response", task_id=task_id, attempt=attempt + 1)

        return json.dumps(
            {"task_status": "failed", "fail_reason": INVALID_RESPONSE_FAILURE_REASON},
            ensure_ascii=False,
        )


def main(arguments: list[str] | None = None) -> int:
    """Read a prompt, execute Aider, and write its final response to stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", help="prompt text; read stdin when omitted")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--task-id", type=int, required=True, help="crunch task ID for the isolated Aider chat history file")
    args = parser.parse_args(arguments)
    try:
        prompt = read_prompt(args.prompt)
        if not prompt.strip():
            raise ValueError("prompt cannot be empty")
        print(run_aider(prompt, read_settings(args.config), args.task_id))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        log_event("invocation_failed", reason=str(error))
        print(f"aider.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
