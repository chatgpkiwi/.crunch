#!/usr/bin/env python3
"""Run eligible tasks through the configured coding-agent adapter."""

from __future__ import annotations

import argparse
import fcntl
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / "database" / "grindr.db"
ADAPTER_PROGRAMS = {
    "codex": Path(__file__).resolve().parent / "codex.py",
    "aider": Path(__file__).resolve().parent / "aider.py",
}
CONFIG_PATH = ROOT / "config" / "config.yaml"
UPDATE_TASK_PROGRAM = Path(__file__).resolve().parent / "update_task.py"
LOG_DIRECTORY = ROOT / "logs"
LOCK_PATH = LOG_DIRECTORY / "grinder.lock"


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
    """Return the next new task from the oldest eligible phase."""
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT
                project.project_id, project.project_name, project.description,
                phases.phase_id, phases.phase_name, phases.phase_summary,
                phases.deliverables, phases.architecture_contract,
                phases.acceptance_checklist,
                tasks.task_id, tasks.task_name, tasks.task_instructions
            FROM tasks
            JOIN phases ON phases.phase_id = tasks.parent_phase_id
            JOIN project ON project.project_id = phases.parent_project_id
            WHERE tasks.task_status = 'new'
              AND phases.status IN ('new', 'in_progress')
            ORDER BY phases.phase_order ASC, tasks.task_order ASC, tasks.task_id ASC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row is not None else None


def claim_task(database: Path, task_id: int) -> bool:
    """Mark a new task and its new parent phase in progress before dispatch."""
    started_at = datetime.now().astimezone().isoformat()
    with sqlite3.connect(database) as connection:
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
    return cursor.rowcount == 1


def build_prompt(record: dict[str, object]) -> str:
    """Create the Markdown prompt for one task without exposing other tasks."""
    return f"""# Task Implementation Request

## Project

You are coding project **{record['project_name']}**.

{record['description']}

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

## Required Response

Reply with exactly one JSON object and no surrounding text:

```json
{{"task_status": "complete"}}
```

or:

```json
{{"task_status": "failed", "fail_reason": "reason for failure"}}
```
"""


def _parse_agent_response(stdout: str, provider: str) -> dict[str, str | None]:
    """Validate the coding agent's required completion response."""
    response = json.loads(stdout.strip())
    if not isinstance(response, dict):
        raise ValueError(f"{provider}.py must return a JSON object")
    status = response.get("task_status")
    if status == "complete" and set(response) == {"task_status"}:
        return {"task_status": "complete", "fail_reason": None}
    if (
        status == "failed"
        and set(response) == {"task_status", "fail_reason"}
        and isinstance(response.get("fail_reason"), str)
        and response["fail_reason"].strip()
    ):
        return {"task_status": "fail", "fail_reason": response["fail_reason"].strip()}
    raise ValueError(f"{provider}.py response must be complete or failed with a non-empty fail_reason")


def get_provider(config_path: Path = CONFIG_PATH) -> str:
    """Read the active provider from the small coding-agent YAML section."""
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read configuration: {error}") from error
    in_default = False
    for line in lines:
        content = line.split("#", 1)[0].strip()
        if content == "default:":
            in_default = True
            continue
        if in_default and line and not line.startswith("    "):
            in_default = False
        if in_default and content.startswith("provider:"):
            provider = content.split(":", 1)[1].strip().strip("\"'")
            if provider in ADAPTER_PROGRAMS:
                return provider
            raise ValueError(f"unsupported coding-agent provider: {provider or '(missing)'}")
    raise ValueError("config.yaml must define coding_agents.default.provider")


def run_agent(prompt: str, provider: str) -> dict[str, str | None]:
    """Invoke the selected adapter and parse its required JSON response."""
    program = ADAPTER_PROGRAMS[provider]
    log_event("agent_invocation_started", provider=provider, prompt_length=len(prompt))
    result = subprocess.run(
        [sys.executable, str(program)],
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
    )
    log_event(
        "agent_process_finished",
        provider=provider,
        returncode=result.returncode,
        stdout_tail=result.stdout[-1000:],
        stderr_tail=result.stderr[-1000:],
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no error output"
        raise RuntimeError(f"{provider}.py exited with {result.returncode}: {detail[:1000]}")
    return _parse_agent_response(result.stdout, provider)


def update_task(database: Path, task_id: int, outcome: dict[str, str | None]) -> None:
    """Persist the coding-agent outcome through the project's task-update tool."""
    payload = {"task_id": task_id, **outcome}
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


def complete_phase_if_finished(database: Path, phase_id: int) -> bool:
    """Complete an in-progress phase only after every one of its tasks completes."""
    with sqlite3.connect(database) as connection:
        cursor = connection.execute(
            """
            UPDATE phases
            SET status = 'complete'
            WHERE phase_id = ?
              AND status = 'in_progress'
              AND NOT EXISTS (
                  SELECT 1
                  FROM tasks
                  WHERE parent_phase_id = phases.phase_id
                    AND task_status != 'complete'
              )
            """,
            (phase_id,),
        )
    return cursor.rowcount == 1


def log_event(event: str, **fields: object) -> None:
    """Append an event to the daily local log file."""
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    payload = {"timestamp": now.isoformat(), "event": event, **fields}
    log_path = LOG_DIRECTORY / f"grinder-{now.date().isoformat()}.log"
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()

    try:
        log_event("worker_started", database=str(args.database), pid=__import__("os").getpid())
        lock_file = acquire_worker_lock()
    except BlockingIOError:
        print("Another grinder worker is already running.", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Unable to acquire grinder worker lock: {error}", file=sys.stderr)
        return 1

    try:
        while True:
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
            log_event("task_found", task_id=task_id, phase_id=record["phase_id"])
            try:
                claimed = claim_task(args.database, task_id)
            except sqlite3.Error as error:
                log_event("task_claim_failed", task_id=task_id, reason=str(error))
                print(f"Task {task_id} could not be claimed: {error}", file=sys.stderr)
                return 1
            if not claimed:
                log_event("task_claim_skipped", task_id=task_id)
                continue
            log_event("task_claimed", task_id=task_id, phase_id=record["phase_id"])

            try:
                provider = get_provider()
                outcome = run_agent(build_prompt(record), provider)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
                log_event("agent_invocation_failed", task_id=task_id, phase_id=record["phase_id"], reason=str(error))
                print(f"Task {task_id} was not processed: {error}", file=sys.stderr)
                return 1

            log_event(
                "task_result_received",
                task_id=task_id,
                phase_id=record["phase_id"],
                task_status=outcome["task_status"],
                fail_reason=outcome["fail_reason"],
            )

            try:
                update_task(args.database, task_id, outcome)
                phase_completed = (
                    complete_phase_if_finished(args.database, int(record["phase_id"]))
                    if outcome["task_status"] == "complete"
                    else False
                )
            except (RuntimeError, sqlite3.Error) as error:
                log_event("task_update_failed", task_id=task_id, reason=str(error))
                print(f"Task {task_id} could not be updated: {error}", file=sys.stderr)
                return 1

            if phase_completed:
                log_event("phase_completed", phase_id=record["phase_id"])
            print(json.dumps({"task_id": task_id, **outcome}))
    finally:
        release_worker_lock(lock_file)


if __name__ == "__main__":
    raise SystemExit(main())
