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


# Keep configuration and logs in Crunch, but run Codex only in the selected
# child project's workspace.
crunch_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = crunch_ROOT / "config" / "config.yaml"
LOG_DIRECTORY = crunch_ROOT / "logs"
CODEX_COMMAND = "codex"
MODEL_ALIASES = {
    "5.6 luna": "gpt-5.6-luna",
    "gpt-5.6-luna": "gpt-5.6-luna",
    "5.6 terra": "gpt-5.6-terra",
    "gpt-5.6-terra": "gpt-5.6-terra",
}
VALID_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}
LOCAL_PROFILE_MODEL = "local"


@dataclass(frozen=True)
class CodexSettings:
    """The default Codex CLI settings read from config.yaml."""

    model: str
    effort: str | None
    local_provider: "LocalProviderSettings | None" = None


@dataclass(frozen=True)
class LocalProviderSettings:
    """Explicit local provider settings for isolated Codex CLI runs."""

    provider: str
    provider_name: str
    base_url: str
    wire_api: str
    context_window: int
    requires_openai_auth: bool
    supports_websockets: bool


def log_event(event: str, **fields: object) -> None:
    """Append a non-sensitive event to the date-specific Codex log."""
    now = __import__("datetime").datetime.now().astimezone()
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIRECTORY / f"codex-{now.date().isoformat()}.log"
    payload = {"timestamp": now.isoformat(), "event": event, **fields}
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_settings(config_path: Path = DEFAULT_CONFIG, agent_name: str = "default_task_agent") -> CodexSettings:
    """Read the limited coding-agent YAML configuration used by this project."""
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

    if fields.get("provider") != "codex":
        raise ValueError(f"config.yaml must define coding_agents.{agent_name}.provider as codex")
    configured_model = fields.get("model", "").lower()
    if configured_model == LOCAL_PROFILE_MODEL:
        effort = fields.get("effort", "").lower() or None
        if effort is not None and effort not in VALID_EFFORTS:
            raise ValueError(f"unsupported Codex reasoning effort: {effort}")
        required = (
            "local-model",
            "local-provider",
            "local-provider-name",
            "local-base-url",
            "local-wire-api",
            "local-context-window",
            "local-requires-openai-auth",
            "local-supports-websockets",
        )
        missing = [name for name in required if not fields.get(name)]
        if missing:
            raise ValueError(f"config.yaml is missing Codex local setting(s): {', '.join(missing)}")
        try:
            context_window = int(fields["local-context-window"])
        except ValueError as error:
            raise ValueError("local-context-window must be an integer") from error
        if context_window <= 0:
            raise ValueError("local-context-window must be positive")
        boolean_fields = ("local-requires-openai-auth", "local-supports-websockets")
        invalid_booleans = [name for name in boolean_fields if fields[name].lower() not in {"true", "false"}]
        if invalid_booleans:
            raise ValueError(f"config.yaml local setting(s) must be true or false: {', '.join(invalid_booleans)}")
        return CodexSettings(
            model=fields["local-model"],
            effort=effort,
            local_provider=LocalProviderSettings(
                provider=fields["local-provider"],
                provider_name=fields["local-provider-name"],
                base_url=fields["local-base-url"],
                wire_api=fields["local-wire-api"],
                context_window=context_window,
                requires_openai_auth=fields["local-requires-openai-auth"].lower() == "true",
                supports_websockets=fields["local-supports-websockets"].lower() == "true",
            ),
        )

    model = MODEL_ALIASES.get(configured_model)
    if model is None:
        raise ValueError("config.yaml must define the Codex model as 5.6 Luna, 5.6 Terra, or local")
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


def build_command(settings: CodexSettings, output_path: Path, workspace: Path) -> list[str]:
    """Build the isolated non-interactive Codex CLI command."""
    command = [CODEX_COMMAND, "exec", "--ignore-user-config", "--model", settings.model]
    if settings.local_provider is not None:
        local = settings.local_provider
        command.extend(
            [
                "-c", f'model_provider="{local.provider}"',
                "-c", f'model_providers.{local.provider}.name="{local.provider_name}"',
                "-c", f'model_providers.{local.provider}.base_url="{local.base_url}"',
                "-c", f'model_providers.{local.provider}.wire_api="{local.wire_api}"',
                "-c", f"model_providers.{local.provider}.requires_openai_auth={str(local.requires_openai_auth).lower()}",
                "-c", f"model_providers.{local.provider}.supports_websockets={str(local.supports_websockets).lower()}",
                "-c", f"model_context_window={local.context_window}",
            ]
        )
    if settings.effort is not None:
        command.extend(["-c", f'model_reasoning_effort="{settings.effort}"'])
    command.extend(
        [
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            "--sandbox",
            "workspace-write",
            "--cd",
            str(workspace),
            "--output-last-message",
            str(output_path),
            "-",
        ]
    )
    return command


def normalize_final_response(response: str, response_kind: str = "task") -> str:
    """Return the requested JSON object from Codex's final message.

    Codex normally follows the worker's bare-JSON response contract, but some
    profiles wrap that response in a Markdown fence or an internal tag.  Keep
    the worker contract strict while accepting that harmless presentation
    wrapper from the CLI.
    """
    required_key = "task_status" if response_kind == "task" else "completion_summary"
    decoder = json.JSONDecoder()
    for index, character in enumerate(response):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(response[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and required_key in value:
            return json.dumps(value, ensure_ascii=False)
    return response.strip()


def log_codex_stream_event(event: dict[str, object], task_id: int | None = None) -> None:
    """Record useful, non-content progress from one Codex JSONL event."""
    event_type = event.get("type")
    fields: dict[str, object] = {
        "codex_event": event_type,
        "task_id": task_id,
    }
    for key in ("thread_id", "turn_id", "item_id", "status"):
        if key in event:
            fields[key] = event[key]
    item = event.get("item")
    if isinstance(item, dict):
        fields["item_type"] = item.get("type")
        for key in ("id", "status", "command", "name"):
            if key in item:
                value = item[key]
                fields[key if key != "id" else "item_id"] = value if key != "command" else str(value)[:300]
    log_event("stream_event", **fields)


def run_codex(
    prompt: str,
    settings: CodexSettings,
    workspace: Path,
    task_id: int | None = None,
    response_kind: str = "task",
) -> str:
    """Run Codex CLI and return its final response, raising on any failure."""
    if not shutil.which(CODEX_COMMAND):
        log_event("codex_not_found")
        raise RuntimeError("Codex CLI was not found on PATH")
    with tempfile.TemporaryDirectory(prefix="crunch-codex-") as temporary_directory:
        output_path = Path(temporary_directory) / "last-message.txt"
        command = build_command(settings, output_path, workspace)
        log_event(
            "invocation_started",
            model=settings.model,
            effort=settings.effort,
            local_provider=settings.local_provider.provider if settings.local_provider else None,
            project_root=str(workspace),
            task_id=task_id,
        )
        stderr_path = Path(temporary_directory) / "stderr.txt"
        stderr_file = stderr_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=workspace,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            bufsize=1,
        )
        assert process.stdin is not None
        process.stdin.write(prompt)
        process.stdin.close()
        stdout_tail = ""
        assert process.stdout is not None
        for line in process.stdout:
            stdout_tail = (stdout_tail + line)[-1000:]
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                log_codex_stream_event(event, task_id)
        process.stdout.close()
        returncode = process.wait()
        stderr_file.close()
        stderr = stderr_path.read_text(encoding="utf-8")
        log_event(
            "process_finished",
            returncode=returncode,
            stdout_tail=stdout_tail,
            stderr_tail=stderr[-1000:],
            output_file_created=output_path.exists(),
            task_id=task_id,
        )
        if returncode != 0:
            detail = stderr.strip() or stdout_tail.strip() or "no error output"
            raise RuntimeError(f"Codex CLI exited with {returncode}: {detail[:1000]}")
        if not output_path.exists():
            raise RuntimeError("Codex CLI completed without a final response")
        response = output_path.read_text(encoding="utf-8").strip()
        if not response:
            raise RuntimeError("Codex CLI completed with an empty final response")
        return normalize_final_response(response, response_kind)


def main(arguments: list[str] | None = None) -> int:
    """Read a prompt, execute Codex CLI, and write the final response to stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", help="prompt text; read stdin when omitted")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--agent", default="default_task_agent")
    parser.add_argument("--task-id", type=int)
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
        print(run_codex(prompt, read_settings(args.config, args.agent), workspace, args.task_id, args.response_kind))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        log_event("invocation_failed", reason=str(error))
        print(f"codex.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
