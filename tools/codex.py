#!/usr/bin/env python3
"""Send one prompt to Codex CLI and print only its final response."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import json
from dataclasses import dataclass
from pathlib import Path


# This script is installed at <project>/.crunch/tools/codex.py.  Keep its
# configuration in .crunch, but run Codex from the project that contains it.
crunch_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = crunch_ROOT.parent
DEFAULT_CONFIG = crunch_ROOT / "config" / "config.yaml"
LOG_DIRECTORY = crunch_ROOT / "logs"
CODEX_COMMAND = "codex"
MODEL_ALIASES = {"5.6 luna": "gpt-5.6-luna", "gpt-5.6-luna": "gpt-5.6-luna"}
VALID_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}


@dataclass(frozen=True)
class CodexSettings:
    """The default Codex CLI settings read from config.yaml."""

    model: str
    effort: str


def log_event(event: str, **fields: object) -> None:
    """Append a non-sensitive event to the date-specific Codex log."""
    now = __import__("datetime").datetime.now().astimezone()
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIRECTORY / f"codex-{now.date().isoformat()}.log"
    payload = {"timestamp": now.isoformat(), "event": event, **fields}
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_settings(config_path: Path = DEFAULT_CONFIG) -> CodexSettings:
    """Read the limited coding-agent YAML configuration used by this project."""
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

    if fields.get("provider") != "codex":
        raise ValueError("config.yaml must define coding_agents.default.provider as codex")
    model = MODEL_ALIASES.get(fields.get("model", "").lower())
    if model is None:
        raise ValueError("config.yaml must define coding_agents.default.model as 5.6 Luna")
    effort = fields.get("effort", "").lower()
    if effort not in VALID_EFFORTS:
        raise ValueError(f"unsupported Codex reasoning effort: {effort or '(missing)'}")
    return CodexSettings(model=model, effort=effort)


def read_prompt(value: str | None) -> str:
    """Return the prompt argument or piped stdin content."""
    if value is not None:
        return value
    if sys.stdin.isatty():
        raise ValueError("provide a prompt argument or pipe a prompt through standard input")
    return sys.stdin.read()


def build_command(settings: CodexSettings, output_path: Path) -> list[str]:
    """Build the isolated non-interactive Codex CLI command."""
    return [
        CODEX_COMMAND,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--json",
        "--sandbox",
        "workspace-write",
        "--model",
        settings.model,
        "-c",
        f'model_reasoning_effort="{settings.effort}"',
        "--cd",
        str(PROJECT_ROOT),
        "--output-last-message",
        str(output_path),
        "-",
    ]


def run_codex(prompt: str, settings: CodexSettings) -> str:
    """Run Codex CLI and return its final response, raising on any failure."""
    if not shutil.which(CODEX_COMMAND):
        log_event("codex_not_found")
        raise RuntimeError("Codex CLI was not found on PATH")
    with tempfile.TemporaryDirectory(prefix="crunch-codex-") as temporary_directory:
        output_path = Path(temporary_directory) / "last-message.txt"
        command = build_command(settings, output_path)
        log_event(
            "invocation_started",
            model=settings.model,
            effort=settings.effort,
            project_root=str(PROJECT_ROOT),
        )
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
        )
        log_event(
            "process_finished",
            returncode=result.returncode,
            stdout_tail=result.stdout[-1000:],
            stderr_tail=result.stderr[-1000:],
            output_file_created=output_path.exists(),
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "no error output"
            raise RuntimeError(f"Codex CLI exited with {result.returncode}: {detail[:1000]}")
        if not output_path.exists():
            raise RuntimeError("Codex CLI completed without a final response")
        response = output_path.read_text(encoding="utf-8").strip()
        if not response:
            raise RuntimeError("Codex CLI completed with an empty final response")
        return response


def main(arguments: list[str] | None = None) -> int:
    """Read a prompt, execute Codex CLI, and write the final response to stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", help="prompt text; read stdin when omitted")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(arguments)
    try:
        prompt = read_prompt(args.prompt)
        if not prompt.strip():
            raise ValueError("prompt cannot be empty")
        print(run_codex(prompt, read_settings(args.config)))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        log_event("invocation_failed", reason=str(error))
        print(f"codex.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
