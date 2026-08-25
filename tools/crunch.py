#!/usr/bin/env python3
"""Run eligible tasks through the configured coding-agent adapter."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / "database" / "crunch.db"
CONFIG_PATH = ROOT / "config" / "config.yaml"
AGENT_PROGRAMS = {
    "codex": Path(__file__).resolve().parent / "codex.py",
    "aider": Path(__file__).resolve().parent / "aider.py",
    "qwen": Path(__file__).resolve().parent / "qwen.py",
}
UPDATE_TASK_PROGRAM = Path(__file__).resolve().parent / "update_task.py"
FIX_TASK_PROGRAM = Path(__file__).resolve().parent / "fix_task.py"
LOG_DIRECTORY = ROOT / "logs"
PROMPT_LOG_DIRECTORY = LOG_DIRECTORY / "prompts"
LOCK_PATH = LOG_DIRECTORY / "crunch.lock"
CODEX_TRANSPORT_ATTEMPTS = 2
ADAPTER_STOP_GRACE_SECONDS = 5
_stop_requested = False
_active_adapter: subprocess.Popen[str] | None = None


class StopRequested(RuntimeError):
    """Raised when the worker must stop without accepting more work."""


def _worker_state_exists(connection: sqlite3.Connection) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'worker_state'"
    ).fetchone() is not None


def stop_requested(database: Path) -> bool:
    """Return whether a durable stop request has been made."""
    if _stop_requested:
        return True
    with sqlite3.connect(database) as connection:
        if not _worker_state_exists(connection):
            return False
        row = connection.execute(
            "SELECT stop_requested FROM worker_state WHERE worker_id = 1"
        ).fetchone()
    return row is not None and bool(row[0])


def request_stop(database: Path) -> None:
    """Durably request shutdown; safe to call repeatedly during cleanup."""
    global _stop_requested
    _stop_requested = True
    try:
        with sqlite3.connect(database, timeout=1) as connection:
            if _worker_state_exists(connection):
                connection.execute(
                    "UPDATE worker_state SET stop_requested = 1, updated_at = CURRENT_TIMESTAMP WHERE worker_id = 1"
                )
    except sqlite3.Error:
        # SIGTERM cleanup must still terminate the adapter even if SQLite is
        # briefly locked by the stop-requesting process.
        pass


def _terminate_active_adapter() -> None:
    """TERM the adapter process group, then arrange a bounded forced cleanup."""
    adapter = _active_adapter
    if adapter is None or adapter.poll() is not None:
        return
    try:
        os.killpg(adapter.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    def force_kill(process_group: int) -> None:
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass

    timer = threading.Timer(ADAPTER_STOP_GRACE_SECONDS, force_kill, args=(adapter.pid,))
    timer.daemon = True
    timer.start()


def install_signal_handler(database: Path) -> None:
    """Make SIGTERM a cooperative worker stop rather than an abrupt exit."""
    def handle_sigterm(_signum: int, _frame: object) -> None:
        request_stop(database)
        _terminate_active_adapter()

    signal.signal(signal.SIGTERM, handle_sigterm)


class CodexTransportFailure(RuntimeError):
    """A transient Codex CLI transport failure after all retry attempts."""


def acquire_worker_lock() -> TextIO:
    """Acquire the process-wide worker lock without waiting for another worker."""
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    lock_file = LOCK_PATH.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        raise
    return lock_file


def release_worker_lock(lock_file: TextIO) -> None:
    """Release a lock acquired by :func:`acquire_worker_lock`."""
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    lock_file.close()


def get_next_task(database: Path) -> dict[str, object] | None:
    """Return the first new task whose earlier project tasks all completed."""
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT
                project.project_id, project.project_name, project.description, project.toolchain, project.workspace_path,
                phases.phase_id, phases.phase_name, phases.phase_summary, phases.phase_order,
                phases.deliverables, phases.architecture_contract,
                phases.acceptance_checklist,
                tasks.task_id, tasks.task_name, tasks.task_instructions, tasks.task_order, tasks.retry_count
            FROM tasks
            JOIN phases ON phases.phase_id = tasks.parent_phase_id
            JOIN project ON project.project_id = phases.parent_project_id
            WHERE tasks.task_status = 'new'
              AND phases.status IN ('new', 'in_progress')
              AND NOT EXISTS (
                  SELECT 1
                  FROM tasks AS earlier_tasks
                  JOIN phases AS earlier_phases
                    ON earlier_phases.phase_id = earlier_tasks.parent_phase_id
                  WHERE earlier_phases.parent_project_id = project.project_id
                    AND (
                        earlier_phases.phase_order < phases.phase_order
                        OR (
                            earlier_phases.phase_order = phases.phase_order
                            AND earlier_phases.phase_id < phases.phase_id
                        )
                        OR (
                            earlier_phases.phase_id = phases.phase_id
                            AND (
                                earlier_tasks.task_order < tasks.task_order
                                OR (
                                    earlier_tasks.task_order = tasks.task_order
                                    AND earlier_tasks.task_id < tasks.task_id
                                )
                            )
                        )
                    )
                    AND earlier_tasks.task_status != 'complete'
              )
            ORDER BY
                project.project_id ASC,
                phases.phase_order ASC,
                phases.phase_id ASC,
                tasks.task_order ASC,
                tasks.task_id ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        record = dict(row)
        previous_phases = connection.execute(
            """
            SELECT phase_name, completion_summary
            FROM phases
            WHERE parent_project_id = ?
              AND status = 'complete'
              AND phase_order < ?
              AND completion_summary IS NOT NULL
              AND trim(completion_summary) != ''
            ORDER BY phase_order, phase_id
            """,
            (record["project_id"], record["phase_order"]),
        ).fetchall()
        previous_tasks = connection.execute(
            """
            SELECT task_name, completion_summary
            FROM tasks
            WHERE parent_phase_id = ?
              AND task_status = 'complete'
              AND task_order < ?
              AND completion_summary IS NOT NULL
              AND trim(completion_summary) != ''
            ORDER BY task_order, task_id
            """,
            (record["phase_id"], record["task_order"]),
        ).fetchall()
    record["previous_phase_completion_summaries"] = [dict(item) for item in previous_phases]
    record["previous_task_completion_summaries"] = [dict(item) for item in previous_tasks]
    return record


def claim_task(database: Path, task_id: int) -> bool:
    """Claim a task only while no durable worker stop is requested."""
    started_at = datetime.now().astimezone().isoformat()
    with sqlite3.connect(database) as connection:
        if _worker_state_exists(connection):
            state = connection.execute(
                "SELECT stop_requested FROM worker_state WHERE worker_id = 1"
            ).fetchone()
            if state is not None and state[0]:
                return False
        cursor = connection.execute(
            """
            UPDATE tasks
            SET task_status = 'in_progress',
                task_start_date = COALESCE(task_start_date, ?)
            WHERE task_id = ? AND task_status = 'new'
            """,
            (started_at, task_id),
        )
        if cursor.rowcount == 1:
            connection.execute(
                """
                UPDATE phases
                SET status = 'in_progress'
                WHERE phase_id = (SELECT parent_phase_id FROM tasks WHERE task_id = ?)
                  AND status = 'new'
                """,
                (task_id,),
            )
            if _worker_state_exists(connection):
                connection.execute(
                    "UPDATE worker_state SET active_task_id = ?, run_status = 'running', updated_at = CURRENT_TIMESTAMP WHERE worker_id = 1",
                    (task_id,),
                )
    return cursor.rowcount == 1


def _completion_context(items: object) -> str:
    """Render named completion summaries as compact task context."""
    if not isinstance(items, list):
        return ""
    sections = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("phase_name") or item.get("task_name")
        summary = item.get("completion_summary")
        if isinstance(name, str) and isinstance(summary, str) and summary.strip():
            sections.append(f"### {name}\n\n{summary.strip()}")
    return "\n\n".join(sections)


def build_prompt(record: dict[str, object]) -> str:
    """Create a task prompt with only relevant completed-work handoffs."""
    previous_phases = _completion_context(record.get("previous_phase_completion_summaries"))
    previous_tasks = _completion_context(record.get("previous_task_completion_summaries"))
    context = ""
    if previous_phases:
        context += f"""
## Completed Phase Context

These are established handoffs from earlier completed phases. Preserve them unless the current task explicitly changes them.

{previous_phases}
"""
    if previous_tasks:
        context += f"""
## Earlier Task Context in This Phase

These are established handoffs from earlier completed tasks in the current phase. Preserve them unless the current task explicitly changes them.

{previous_tasks}
"""
    return f"""# Task Implementation Request

## Project

You are coding project **{record['project_name']}**.

{record['description']}

## Required Toolchain

{record['toolchain']}

{context}

## Scope

You will code only one task in the phase below. The phase information is context only. Do not code the entire phase; implement only the immediate task in the **Current Task** section.

## Current Phase

{record['phase_summary']}

### Phase Deliverables

{record['deliverables']}

### Architecture Contract

{record['architecture_contract']}

### Acceptance Checklist

{record['acceptance_checklist']}




## Current Task

### Task Name

{record['task_name']}

### Task Instructions

{record['task_instructions']}

## Required Work

Implement the current task and run the relevant tests before responding. Do not
report success unless the task is implemented and its relevant tests pass.
Inspect the current repository before implementation; it is the source of truth
if it differs from the completion context.

## Required Response

Do not reply with prose, explanations, questions, code fences, etc.   

Reply with exactly one JSON object and no surrounding text.

"task_status" field must be either "complete" or "failed". 

When setting "task_status" to "complete", generate a summary of new features, contracts, interface established, libraries added, and answer in this format:

```json
{{"task_status": "complete", "completion_summary": "insert the generated completion summary here"}}
```

or, when the setting the "task_status" to "failed", generate a reason for failure, and answer in this format:

```json
{{"task_status": "failed", "fail_reason": "reason for failure"}}
```

Only reply after all your development process is complete, as a final answer, with nothing left to do or test. 

"""




def read_coding_agents(config_path: Path = CONFIG_PATH) -> dict[str, dict[str, str]]:
    """Read and validate the named coding-agent blocks from config.yaml."""
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read configuration: {error}") from error

    agents: dict[str, dict[str, str]] = {}
    in_agents = False
    current_agent: str | None = None
    for line in lines:
        content = line.split("#", 1)[0].rstrip()
        if not content:
            continue
        if content == "coding_agents:":
            in_agents = True
            current_agent = None
            continue
        if in_agents and not line.startswith((" ", "\t")):
            in_agents = False
            current_agent = None
        if in_agents and line.startswith(("  ", "\t")) and not line.startswith(("    ", "\t\t")) and content.endswith(":"):
            current_agent = content[:-1].strip()
            if not current_agent or current_agent in agents:
                raise ValueError("config.yaml must define unique coding-agent names")
            agents[current_agent] = {}
            continue
        if current_agent and line.startswith(("    ", "\t\t")) and ":" in content:
            key, value = content.strip().split(":", 1)
            agents[current_agent][key.strip()] = value.strip().strip("\"'")

    for required_name in ("default_task_agent", "retry_task_agent"):
        if required_name not in agents:
            raise ValueError(f"config.yaml must define coding_agents.{required_name}")
    supported = ", ".join(sorted(AGENT_PROGRAMS))
    for name, fields in agents.items():
        if fields.get("provider") not in AGENT_PROGRAMS:
            raise ValueError(f"config.yaml must define coding_agents.{name}.provider as one of: {supported}")
    return agents


def parse_agent_response(stdout: str) -> dict[str, str | None]:
    """Validate an adapter's required completion response."""
    response = json.loads(stdout.strip())
    if not isinstance(response, dict):
        raise ValueError("coding-agent adapter must return a JSON object")
    status = response.get("task_status")
    if (
        status == "complete"
        and set(response) == {"task_status", "completion_summary"}
        and isinstance(response.get("completion_summary"), str)
        and response["completion_summary"].strip()
    ):
        return {
            "task_status": "complete",
            "fail_reason": None,
            "completion_summary": response["completion_summary"].strip(),
        }
    if (
        status == "failed"
        and set(response) == {"task_status", "fail_reason"}
        and isinstance(response.get("fail_reason"), str)
        and response["fail_reason"].strip()
    ):
        return {"task_status": "fail", "fail_reason": response["fail_reason"].strip(), "completion_summary": None}
    raise ValueError("coding-agent response must be complete with a non-empty completion_summary, or failed with a non-empty fail_reason")


def parse_phase_summary_response(stdout: str) -> dict[str, str]:
    """Validate a default coding-agent phase-consolidation response."""
    response = json.loads(stdout.strip())
    if (
        isinstance(response, dict)
        and set(response) == {"completion_summary"}
        and isinstance(response.get("completion_summary"), str)
        and response["completion_summary"].strip()
    ):
        return {"completion_summary": response["completion_summary"].strip()}
    raise ValueError("phase consolidation response must contain only a non-empty completion_summary")


def _task_prompt_log(task_id: int) -> Path:
    """Return the per-task prompt log path."""
    return PROMPT_LOG_DIRECTORY / f"{task_id}.log"


def log_prompt(task_id: int, prompt: str) -> None:
    """Write a prompt before launching the coding-agent subprocess."""
    timestamp = datetime.now().astimezone().isoformat()
    try:
        PROMPT_LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
        with _task_prompt_log(task_id).open("a", encoding="utf-8") as log_file:
            log_file.write(f"[{timestamp}] PROMPT\n{prompt.rstrip()}\n")
    except OSError as error:
        log_event("prompt_log_failed", task_id=task_id, reason=str(error))


def log_response(task_id: int, response: str) -> None:
    """Append an adapter response after the coding-agent subprocess exits."""
    timestamp = datetime.now().astimezone().isoformat()
    try:
        PROMPT_LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
        with _task_prompt_log(task_id).open("a", encoding="utf-8") as log_file:
            log_file.write(f"\n[{timestamp}] RESPONSE\n{response.rstrip()}\n\n")
    except OSError as error:
        log_event("response_log_failed", task_id=task_id, reason=str(error))


def log_codex_exchange(task_id: int, prompt: str, response: str) -> None:
    """Append a complete Codex exchange (kept for adapter compatibility)."""
    log_prompt(task_id, prompt)
    log_response(task_id, response)


def codex_transport_failure_reason(stdout: str) -> str | None:
    """Return a terminal Codex transport-failure reason, if present in JSONL."""
    markers = ("stream disconnected", "connection failed", "connection reset", "network error", "timed out")
    for line in reversed(stdout.splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "turn.failed":
            continue
        error = event.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        if isinstance(message, str) and any(marker in message.lower() for marker in markers):
            return message.strip()
    return None


def run_agent(
    agent_name: str,
    provider: str,
    prompt: str,
    task_id: int,
    workspace: Path,
    response_kind: str = "task",
) -> dict[str, str | None]:
    """Invoke one named agent adapter and parse its JSON response."""
    program = AGENT_PROGRAMS[provider]
    command = [sys.executable, str(program)]
    command.extend(("--agent", agent_name))
    command.extend(("--response-kind", response_kind))
    if provider in {"aider", "codex"}:
        command.extend(("--task-id", str(task_id)))
    command.extend(("--project-workspace", str(workspace)))
    attempts = CODEX_TRANSPORT_ATTEMPTS if provider == "codex" else 1
    for attempt in range(1, attempts + 1):
        log_event(
            "agent_invocation_started",
            agent=agent_name,
            provider=provider,
            prompt_length=len(prompt),
            task_id=task_id,
            attempt=attempt,
            attempts=attempts,
        )
        # Make the work visible before subprocess.run blocks on the model.
        log_prompt(task_id, prompt)
        global _active_adapter
        adapter = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        _active_adapter = adapter
        try:
            stdout, stderr = adapter.communicate(input=prompt)
        finally:
            _active_adapter = None
        if _stop_requested:
            # The signal handler has already TERM'd the adapter group. Give it
            # a short chance to exit normally before escalating any survivors.
            if adapter.poll() is None:
                deadline = time.monotonic() + ADAPTER_STOP_GRACE_SECONDS
                while adapter.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                if adapter.poll() is None:
                    try:
                        os.killpg(adapter.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    adapter.wait()
            raise StopRequested("worker stop requested while adapter was running")
        result = subprocess.CompletedProcess(command, adapter.returncode, stdout, stderr)
        log_event(
            "agent_process_finished",
            agent=agent_name,
            provider=provider,
            returncode=result.returncode,
            stdout_tail=result.stdout[-1000:],
            stderr_tail=result.stderr[-1000:],
            attempt=attempt,
            attempts=attempts,
        )
        if provider == "codex":
            response = result.stdout
            if result.stderr:
                response = f"{response}\n[stderr]\n{result.stderr}" if response else result.stderr
            log_response(task_id, response)
        else:
            response = result.stdout
            if result.stderr:
                response = f"{response}\n[stderr]\n{result.stderr}" if response else result.stderr
            log_response(task_id, response)
        if result.returncode == 0:
            if response_kind == "task":
                return parse_agent_response(result.stdout)
            if response_kind == "phase-summary":
                return parse_phase_summary_response(result.stdout)
            raise ValueError(f"unsupported agent response kind: {response_kind}")

        transport_reason = codex_transport_failure_reason(result.stdout) if provider == "codex" else None
        if transport_reason is not None:
            log_event(
                "codex_transport_failure",
                task_id=task_id,
                attempt=attempt,
                attempts=attempts,
                reason=transport_reason,
            )
            if attempt < attempts:
                continue
            raise CodexTransportFailure(transport_reason)

        detail = result.stderr.strip() or result.stdout.strip() or "no error output"
        raise RuntimeError(f"{program.name} exited with {result.returncode}: {detail[:1000]}")

    raise AssertionError("agent invocation attempts exhausted unexpectedly")


def update_task(database: Path, project_id: int, task_id: int, outcome: dict[str, str | None]) -> None:
    """Persist a coding-agent outcome through the project's task-update tool."""
    payload = {"project_id": project_id, "task_id": task_id, **outcome}
    if outcome["task_status"] == "complete":
        payload["task_end_date"] = datetime.now().astimezone().isoformat()
    result = subprocess.run(
        [sys.executable, str(UPDATE_TASK_PROGRAM), "--database", str(database)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no error output"
        raise RuntimeError(f"update_task.py exited with {result.returncode}: {detail[:1000]}")


def requeue_task_after_transport_failure(database: Path, project_id: int, task_id: int, instructions: str) -> None:
    """Return a claimed task to the queue after a non-semantic Codex failure."""
    payload = {
        "project_id": project_id,
        "task_id": task_id,
        "task_instructions": instructions,
    }
    result = subprocess.run(
        [sys.executable, str(FIX_TASK_PROGRAM), "--database", str(database)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no error output"
        raise RuntimeError(f"fix_task.py exited with {result.returncode}: {detail[:1000]}")


def interrupt_task(database: Path, task_id: int) -> bool:
    """Atomically record an interrupted run and return its task to the queue."""
    with sqlite3.connect(database) as connection:
        if _worker_state_exists(connection):
            connection.execute(
                "UPDATE worker_state SET stop_requested = 1, active_task_id = ?, run_status = 'interrupted', updated_at = CURRENT_TIMESTAMP WHERE worker_id = 1",
                (task_id,),
            )
        cursor = connection.execute(
            """
            UPDATE tasks
            SET task_status = 'new', task_start_date = NULL, task_end_date = NULL,
                fail_reason = NULL, completion_summary = NULL, test_results = NULL
            WHERE task_id = ? AND task_status = 'in_progress'
            """,
            (task_id,),
        )
        if _worker_state_exists(connection):
            connection.execute(
                "UPDATE worker_state SET active_task_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE worker_id = 1"
            )
    return cursor.rowcount == 1


def get_ready_phase(database: Path, phase_id: int | None = None) -> dict[str, object] | None:
    """Return a fully completed in-progress phase that needs consolidation."""
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        where_phase = "AND phases.phase_id = ?" if phase_id is not None else ""
        parameters: tuple[object, ...] = (phase_id,) if phase_id is not None else ()
        phase = connection.execute(
            """
            SELECT phases.phase_id, phases.phase_name, phases.phase_summary,
                   project.project_name, project.description, project.workspace_path
            FROM phases
            JOIN project ON project.project_id = phases.parent_project_id
            WHERE phases.status = 'in_progress'
            """ + where_phase + """
              AND NOT EXISTS (
                  SELECT 1
                  FROM tasks
                  WHERE parent_phase_id = phases.phase_id
                    AND task_status != 'complete'
              )
            ORDER BY phases.phase_order, phases.phase_id
            LIMIT 1
            """,
            parameters,
        ).fetchone()
        if phase is None:
            return None
        task_summaries = connection.execute(
            """
            SELECT task_id, task_name, completion_summary
            FROM tasks
            WHERE parent_phase_id = ?
              AND completion_summary IS NOT NULL
              AND trim(completion_summary) != ''
            ORDER BY task_order, task_id
            """,
            (phase["phase_id"],),
        ).fetchall()
    record = dict(phase)
    record["task_completion_summaries"] = [dict(item) for item in task_summaries]
    return record


def build_phase_consolidation_prompt(record: dict[str, object]) -> str:
    """Ask the default coding agent to consolidate one phase's task handoffs."""
    summaries = _completion_context(record.get("task_completion_summaries"))
    return f"""# Phase Completion Consolidation Request

Project: **{record['project_name']}**

{record['description']}

The phase **{record['phase_name']}** has completed. Consolidate the task completion summaries below into one concise handoff for later phases. Capture durable features, contracts, and interface changes; omit transient implementation detail and secrets. Do not edit the workspace.

## Task Completion Summaries

{summaries or 'No task completion summaries were recorded.'}

## Required Response

Reply with exactly one JSON object and no surrounding text:

```json
{{"completion_summary": "- Consolidated feature, contract, or interface"}}
```
"""


def complete_phase_if_finished(
    database: Path, phase_id: int, agents: dict[str, dict[str, str]]
) -> bool:
    """Consolidate and complete a phase after every task is complete."""
    record = get_ready_phase(database, phase_id)
    if record is None:
        return False
    workspace = Path(str(record["workspace_path"])).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"project workspace does not exist: {workspace}")
    agent_name = "default_task_agent"
    summary = run_agent(
        agent_name,
        agents[agent_name]["provider"],
        build_phase_consolidation_prompt(record),
        int(record["task_completion_summaries"][-1]["task_id"]) if record["task_completion_summaries"] else int(phase_id),
        workspace,
        response_kind="phase-summary",
    )["completion_summary"]
    with sqlite3.connect(database) as connection:
        cursor = connection.execute(
            """
            UPDATE phases
            SET status = 'complete', completion_summary = ?
            WHERE phase_id = ?
              AND status = 'in_progress'
              AND NOT EXISTS (
                  SELECT 1 FROM tasks
                  WHERE parent_phase_id = phases.phase_id
                    AND task_status != 'complete'
              )
            """,
            (summary, phase_id),
        )
    return cursor.rowcount == 1


def log_event(event: str, **fields: object) -> None:
    """Append an event to the daily local log file."""
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    payload = {"timestamp": now.isoformat(), "event": event, **fields}
    log_path = LOG_DIRECTORY / f"crunch-{now.date().isoformat()}.log"
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()

    try:
        agents = read_coding_agents()
        log_event(
            "worker_started",
            database=str(args.database),
            pid=__import__("os").getpid(),
            agents={name: fields["provider"] for name, fields in agents.items()},
        )
        lock_file = acquire_worker_lock()
        install_signal_handler(args.database)
    except BlockingIOError:
        print("Another crunch worker is already running.", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Unable to acquire crunch worker lock: {error}", file=sys.stderr)
        return 1

    try:
        while True:
            if stop_requested(args.database):
                log_event("worker_stop_observed", stage="before_phase_consolidation")
                return 0
            try:
                ready_phase = get_ready_phase(args.database)
                if ready_phase is None:
                    break
                completed = complete_phase_if_finished(
                    args.database, int(ready_phase["phase_id"]), agents
                )
                if completed:
                    log_event("phase_completed", phase_id=ready_phase["phase_id"])
            except StopRequested:
                log_event("worker_stop_observed", stage="phase_consolidation")
                return 0
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError, sqlite3.Error) as error:
                log_event("phase_consolidation_failed", reason=str(error))
                print(f"A completed phase could not be consolidated: {error}", file=sys.stderr)
                return 1

        while True:
            if stop_requested(args.database):
                log_event("worker_stop_observed", stage="before_task_lookup")
                return 0
            try:
                record = get_next_task(args.database)
            except sqlite3.Error as error:
                log_event("task_lookup_failed", reason=str(error))
                print(f"Unable to find a task: {error}", file=sys.stderr)
                return 1

            if record is None:
                log_event("no_new_tasks_found")
                print("No new tasks found.")
                return 0

            task_id = int(record["task_id"])
            agent_name = "retry_task_agent" if int(record["retry_count"]) > 0 else "default_task_agent"
            provider = agents[agent_name]["provider"]
            log_event("task_found", task_id=task_id, phase_id=record["phase_id"])
            if stop_requested(args.database):
                log_event("worker_stop_observed", task_id=task_id, stage="before_task_claim")
                return 0
            try:
                claimed = claim_task(args.database, task_id)
            except sqlite3.Error as error:
                log_event("task_claim_failed", task_id=task_id, reason=str(error))
                print(f"Task {task_id} could not be claimed: {error}", file=sys.stderr)
                return 1
            if not claimed:
                if stop_requested(args.database):
                    log_event("worker_stop_observed", task_id=task_id, stage="task_claim")
                    return 0
                log_event("task_claim_skipped", task_id=task_id)
                continue
            log_event("task_claimed", task_id=task_id, phase_id=record["phase_id"])

            try:
                workspace_value = record["workspace_path"]
                workspace = Path(str(workspace_value)).expanduser().resolve()
                if not workspace.is_dir():
                    raise ValueError(f"project workspace does not exist: {workspace}")
                outcome = run_agent(agent_name, provider, build_prompt(record), task_id, workspace)
            except StopRequested:
                try:
                    interrupted = interrupt_task(args.database, task_id)
                except sqlite3.Error as error:
                    log_event("task_interrupt_record_failed", task_id=task_id, reason=str(error))
                    print(f"Task {task_id} could not be recorded as interrupted: {error}", file=sys.stderr)
                    return 1
                log_event("task_interrupted", task_id=task_id, phase_id=record["phase_id"], requeued=interrupted)
                return 0
            except CodexTransportFailure as error:
                try:
                    requeue_task_after_transport_failure(
                        args.database,
                        int(record["project_id"]),
                        task_id,
                        str(record["task_instructions"]),
                    )
                except RuntimeError as reset_error:
                    log_event(
                        "task_requeue_failed",
                        task_id=task_id,
                        phase_id=record["phase_id"],
                        reason=str(reset_error),
                    )
                    print(f"Task {task_id} could not be requeued: {reset_error}", file=sys.stderr)
                    return 1
                log_event(
                    "task_requeued_after_transport_failure",
                    task_id=task_id,
                    phase_id=record["phase_id"],
                    reason=str(error),
                )
                print(f"Task {task_id} was requeued after a Codex transport failure: {error}", file=sys.stderr)
                return 0
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
                log_event(
                    "agent_invocation_failed",
                    agent=agent_name, provider=provider,
                    task_id=task_id,
                    phase_id=record["phase_id"],
                    reason=str(error),
                )
                print(f"Task {task_id} was not processed: {error}", file=sys.stderr)
                return 1

            log_event(
                "task_result_received",
                task_id=task_id,
                phase_id=record["phase_id"],
                task_status=outcome["task_status"],
                fail_reason=outcome["fail_reason"],
            )

            # An adapter may finish at the exact moment a stop is requested.
            # Do not accept its completion (or failure) into task state then.
            if stop_requested(args.database):
                try:
                    interrupted = interrupt_task(args.database, task_id)
                except sqlite3.Error as error:
                    log_event("task_interrupt_record_failed", task_id=task_id, reason=str(error))
                    print(f"Task {task_id} could not be recorded as interrupted: {error}", file=sys.stderr)
                    return 1
                log_event("task_interrupted", task_id=task_id, phase_id=record["phase_id"], requeued=interrupted)
                return 0

            try:
                update_task(args.database, int(record["project_id"]), task_id, outcome)
                phase_completed = (
                    complete_phase_if_finished(args.database, int(record["phase_id"]), agents)
                    if outcome["task_status"] == "complete"
                    else False
                )
            except (RuntimeError, ValueError, json.JSONDecodeError, sqlite3.Error) as error:
                log_event("task_update_failed", task_id=task_id, reason=str(error))
                print(f"Task {task_id} could not be updated: {error}", file=sys.stderr)
                return 1

            if phase_completed:
                log_event("phase_completed", phase_id=record["phase_id"])
            print(json.dumps({"task_id": task_id, **outcome}))
            if stop_requested(args.database):
                log_event("worker_stop_observed", task_id=task_id, stage="after_task_update")
                return 0
    finally:
        release_worker_lock(lock_file)


if __name__ == "__main__":
    raise SystemExit(main())
