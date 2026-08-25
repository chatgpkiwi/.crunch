#!/usr/bin/env python3
"""Send one prompt to the installed Qwen Code CLI and print its task result.

The adapter owns only the boundary between crunch and Qwen Code: non-interactive
invocation, compact logs, and validation of the final task status. Authentication,
provider, endpoint, and model selection remain the Qwen CLI's responsibility and
come from the user's Qwen configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


CRUNCH_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = CRUNCH_ROOT / "config" / "config.yaml"
LOG_DIRECTORY = CRUNCH_ROOT / "logs"
QWEN_COMMAND = "qwen"
DEFAULT_OUTPUT_FORMAT = "stream-json"
VALID_OUTPUT_FORMATS = {"text", "json", "stream-json"}
MAX_INVALID_RESPONSE_RETRIES = 2
INVALID_RESPONSE_FAILURE_REASON = (
    "Qwen Code did not produce a recognizable task-status JSON object after "
    "the initial response and two format reminders."
)
JSON_OBJECT_PATTERN = re.compile(r"\{[^{}]*\}")
QWEN_API_ERROR_PATTERN = re.compile(r"^\[API Error:\s*(.*?)\]$", re.IGNORECASE | re.DOTALL)
TASK_FORMAT_REMINDER = """This is an unattended development cycle. Your previous reply was invalid.

Reply now with exactly one JSON object and no other text, Markdown, code fence, question, explanation, or request for files. You must not ask for more information. Inspect the workspace and complete the assigned task using the existing context.

Reply with exactly one of:
{"task_status":"complete","completion_summary":"- feature, contract, or interface established"}
{"task_status":"failed","fail_reason":"specific reason"}
"""
PHASE_SUMMARY_FORMAT_REMINDER = """Your previous phase-consolidation reply was invalid.

Reply now with exactly one JSON object and no other text:
{"completion_summary":"- consolidated feature, contract, or interface"}
"""


@dataclass(frozen=True)
class QwenSettings:
    """The Qwen invocation controls read from one named coding agent."""

    max_wall_time: str | None
    max_tool_calls: str | None
    output_format: str


def log_event(event: str, **fields: object) -> None:
    """Append a non-sensitive event to the date-specific Qwen log."""
    now = datetime.now().astimezone()
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": now.isoformat(), "event": event, **fields}
    with (LOG_DIRECTORY / f"qwen-{now.date().isoformat()}.log").open(
        "a", encoding="utf-8"
    ) as log_file:
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


def read_settings(config_path: Path = DEFAULT_CONFIG, agent_name: str = "default_task_agent") -> QwenSettings:
    """Read Qwen run controls without overriding the user's Qwen settings."""
    fields = read_agent_fields(config_path, agent_name)
    if fields.get("provider") != "qwen":
        raise ValueError(f"config.yaml must define coding_agents.{agent_name}.provider as qwen")
    output_format = fields.get("output-format", DEFAULT_OUTPUT_FORMAT).lower()
    if output_format not in VALID_OUTPUT_FORMATS:
        allowed = ", ".join(sorted(VALID_OUTPUT_FORMATS))
        raise ValueError(f"unsupported Qwen output format: {output_format}; expected one of: {allowed}")
    return QwenSettings(
        max_wall_time=fields.get("max-wall-time") or None,
        max_tool_calls=fields.get("max-tool-calls") or None,
        output_format=output_format,
    )


def read_prompt(value: str | None) -> str:
    """Return the prompt argument or piped stdin content."""
    if value is not None:
        return value
    if sys.stdin.isatty():
        raise ValueError("provide a prompt argument or pipe a prompt through standard input")
    return sys.stdin.read()


def build_command(settings: QwenSettings) -> list[str]:
    """Build a headless command while leaving model access to Qwen settings."""
    command = [
        QWEN_COMMAND,
        "--approval-mode",
        "yolo",
        "--output-format",
        settings.output_format,
    ]
    if settings.max_wall_time:
        command.extend(("--max-wall-time", settings.max_wall_time))
    if settings.max_tool_calls:
        command.extend(("--max-tool-calls", settings.max_tool_calls))
    return command


def text_from_content(value: Any) -> str:
    """Extract text from common Qwen stream-json message shapes."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(text_from_content(item) for item in value)
    if isinstance(value, dict):
        for key in ("text", "content", "result", "response", "output", "message"):
            text = text_from_content(value.get(key))
            if text:
                return text
    return ""


def response_text(output: str, output_format: str) -> str:
    """Return Qwen's final assistant text, without retaining tool transcripts."""
    if output_format == "text":
        return output.strip()

    if output_format == "json":
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Qwen JSON output could not be parsed: {error.msg}") from error
        events = payload if isinstance(payload, list) else [payload]
    else:
        events = []
        for line in output.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    final_text = ""
    assistant_text = ""
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            result = event.get("result")
            text = (
                result
                if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False)
                if isinstance(result, (dict, list))
                else ""
            )
            if text:
                final_text = text
        elif event.get("type") == "assistant":
            message = event.get("message")
            text = text_from_content(message if message is not None else event.get("content"))
            if text:
                assistant_text = text
    return (final_text or assistant_text).strip()


def extract_completion_response(output: str, response_kind: str = "task") -> str:
    """Find and normalize a valid task-status JSON object in Qwen's reply."""
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
    raise RuntimeError("Qwen output did not contain a valid task-status JSON object")


def raise_for_qwen_api_error(output: str) -> None:
    """Treat Qwen's exit-zero API error result as an adapter failure."""
    match = QWEN_API_ERROR_PATTERN.fullmatch(output.strip())
    if match:
        raise RuntimeError(f"Qwen Code reported an API error: {match.group(1).strip()}")


def run_qwen(prompt: str, settings: QwenSettings, workspace: Path, response_kind: str = "task") -> str:
    """Run Qwen Code and return a normalized task-status response."""
    if not shutil.which(QWEN_COMMAND):
        log_event("qwen_not_found")
        raise RuntimeError("Qwen Code CLI was not found on PATH")

    environment = os.environ.copy()
    environment["QWEN_CODE_SUPPRESS_YOLO_WARNING"] = "1"
    reminder = TASK_FORMAT_REMINDER if response_kind == "task" else PHASE_SUMMARY_FORMAT_REMINDER
    prompts = [prompt, *([reminder] * MAX_INVALID_RESPONSE_RETRIES)]
    for attempt, current_prompt in enumerate(prompts, start=1):
        command = build_command(settings)
        log_event(
            "invocation_started",
            model_source="qwen_user_settings",
            project_root=str(workspace),
            attempt=attempt,
            format_retry=attempt > 1,
        )
        result = subprocess.run(
            command,
            cwd=workspace,
            env=environment,
            input=current_prompt,
            text=True,
            capture_output=True,
            check=False,
        )
        log_event(
            "process_finished",
            returncode=result.returncode,
            stdout_tail=result.stdout[-1000:],
            stderr_tail=result.stderr[-1000:],
            attempt=attempt,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "no error output"
            raise RuntimeError(f"Qwen Code exited with {result.returncode}: {detail[:1000]}")
        final_text = response_text(result.stdout, settings.output_format)
        raise_for_qwen_api_error(final_text)
        try:
            return extract_completion_response(final_text, response_kind)
        except RuntimeError:
            log_event("invalid_completion_response", attempt=attempt)

    if response_kind == "phase-summary":
        raise RuntimeError("Qwen Code did not produce a recognizable phase completion-summary JSON object")
    return json.dumps(
        {"task_status": "failed", "fail_reason": INVALID_RESPONSE_FAILURE_REASON},
        ensure_ascii=False,
    )


def main(arguments: list[str] | None = None) -> int:
    """Read a prompt, execute Qwen Code, and write the final response to stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", help="prompt text; read stdin when omitted")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--agent", default="default_task_agent")
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
        print(run_qwen(prompt, read_settings(args.config, args.agent), workspace, args.response_kind))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        log_event("invocation_failed", reason=str(error))
        print(f"qwen.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
