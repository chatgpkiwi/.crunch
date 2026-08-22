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


GRINDR_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = GRINDR_ROOT.parent
DEFAULT_CONFIG = GRINDR_ROOT / "config" / "config.yaml"
LOG_DIRECTORY = GRINDR_ROOT / "logs"
AIDER_COMMAND = "aider"


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


def build_command(settings: AiderSettings, prompt_path: Path) -> list[str]:
    """Build a one-shot Aider command that edits the project without commits."""
    return [
        AIDER_COMMAND,
        "--model",
        settings.model,
        "--openai-api-base",
        settings.openai_api_base,
        "--openai-api-key",
        settings.openai_api_key,
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


def extract_completion_response(output: str) -> str:
    """Return the final Grinder completion object from Aider's transcript.

    Aider writes startup/status lines around the assistant's one-shot reply, so
    forwarding stdout verbatim would violate Grinder's JSON-only contract.
    """
    decoder = json.JSONDecoder()
    completions: list[dict[str, object]] = []
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(candidate, dict):
            continue
        if candidate == {"task_status": "complete"}:
            completions.append(candidate)
        elif (
            set(candidate) == {"task_status", "fail_reason"}
            and candidate.get("task_status") == "failed"
            and isinstance(candidate.get("fail_reason"), str)
            and candidate["fail_reason"].strip()
        ):
            completions.append(candidate)
    if not completions:
        raise RuntimeError("Aider completed without the required task-status JSON response")
    return json.dumps(completions[-1], ensure_ascii=False)


def run_aider(prompt: str, settings: AiderSettings) -> str:
    """Run Aider and return its textual one-shot response."""
    if not shutil.which(AIDER_COMMAND):
        log_event("aider_not_found")
        raise RuntimeError("Aider CLI was not found on PATH")
    with tempfile.TemporaryDirectory(prefix="grindr-aider-") as temporary_directory:
        prompt_path = Path(temporary_directory) / "prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        command = build_command(settings, prompt_path)
        log_event("invocation_started", model=settings.model, project_root=str(PROJECT_ROOT))
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
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "no error output"
            raise RuntimeError(f"Aider exited with {result.returncode}: {detail[:1000]}")
        return extract_completion_response(result.stdout)


def main(arguments: list[str] | None = None) -> int:
    """Read a prompt, execute Aider, and write its final response to stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", help="prompt text; read stdin when omitted")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(arguments)
    try:
        prompt = read_prompt(args.prompt)
        if not prompt.strip():
            raise ValueError("prompt cannot be empty")
        print(run_aider(prompt, read_settings(args.config)))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        log_event("invocation_failed", reason=str(error))
        print(f"aider.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
