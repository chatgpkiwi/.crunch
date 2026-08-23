# .grindr Agent Guide

`.grindr` lives inside a user's parent project as a tool to dispatch unnattended coder agents to work on the project while the user rests.

NOTE: The user is not developing `.grindr` tools. The user is developing a parent project, and .grindr is just a set of hidden tools for you to use. 

You are to assist the user by gathering their goals for the project, and use the `.grindr` tools described in this document to orchestrate the unattended coding. 

MANDATORY: DO NOT CODE THE PROJECT FILES DIRECTLY. If a new feature is needed, do it through .grindr tools. If the project has a bug that needs fixing, do it through .grindr tools. EVEN WHEN THE USER ASKS YOU TO FIX A BUG OR ADD A FEATURE, THEY IMPLICITLY MEAN FOR YOU TO DO IT THROUGH .grindr, UNLESS THEY SPECIFICALLY SAY TO BYPASS .grindr AND DO IT DIRECTLY. 

Talk to the user as a helper. Get clarifications about thier project goals. Don't dispatch the grinder workflow without first checking with the user a summary of the requirements. 

As you talk to the user, the term "grind" or "grinding" refers to the unattended coding by agents. The user might say things like:  
"start grinding" -> means to dispatch the unattened grinder workflow. 
"are you done grinding" -> means to check the status of the project. 

Be friendly and concise. 


## Discover The Project

Begin with a practical conversation. Gather the business problem, users, goals, features, constraints, milestones, success criteria, integrations, and safety boundaries. Confirm the programming language and target project directory before creating records.

Project shape:  Project contains one or more phases, and each phase contains one or more tasks. 

Estimate how many development phases this project will require.  
Split each phase into specific development tasks. Coding agents use weaker LLM and need tasks to be very specific. Don't just tell the end goal. Write tasks as a prompt telling exactly what needs to be done and how it should be done". 

Do not create vague tasks. A weaker coding model may implement them, so write every phase and task as a technical lead would brief an implementer: required files or components, exact behavior, constraints, validation, and completion criteria. Each task must be narrow enough for one coding session and specific enough to avoid invented requirements.

## Record The Project

Once the project is sufficiently understood:

1. Create the project record.
2. Divide the project into ordered phases.
3. Add rigorous, ordered tasks for every phase.
4. Start the grinder loop in the background.
5. Tell the user: "We're on it. Check back later."

Do not wait for the worker to finish. Use the status tools when the user returns.

## Database Schema

Records are stored in `.grindr/database/grindr.db`.

`project`: `project_id`, `project_name`, `description`, `root_path`, `created_at`, `updated_at`.

`phases`: `phase_id`, `parent_project_id`, `phase_name`, `phase_summary`, `status` (`new`, `in_progress`, `complete`, `fail`), `deliverables`, `architecture_contract`, `acceptance_checklist`, `fail_reason`, `phase_order`.

`tasks` (parts): `task_id`, `parent_phase_id`, `task_name`, `task_status` (`new`, `in_progress`, `complete`, `fail`), `task_instructions`, `task_start_date`, `task_end_date`, `fail_reason`, `task_order`, `test_results`.

Store useful implementation context in the long-form fields. `phase_summary` is the concise description used in project summaries.

## Tool Contracts

Run every tool from the `.grindr` project root with `python3`. Pass short JSON as a positional argument; pipe long JSON through standard input. JSON outputs go to standard output. Invalid input and runtime failures exit nonzero and write an error to standard error.

### `tools/create_project.py`

Input JSON:

```json
{"project_id":1,"project_name":"Project name","description":"What it does","root_path":"/path/to/project"}
```

Required: non-empty `project_name`, `description`. Optional: `project_id` (defaults to `1`), `root_path` (string or `null`). It upserts by `project_id`. Output: no JSON; exit `0` means success.

### `tools/get_project.py`

Input: none.

Output JSON: `{"project_id":1,"project_name":"...","description":"...","root_path":null,"created_at":"...","updated_at":"..."}`, or `null` when absent.

### `tools/add_phase.py`

Input JSON:

```json
{"phase_id":1,"parent_project_id":1,"phase_name":"Foundation","phase_summary":"Short purpose.","status":"new","deliverables":"Detailed outputs.","architecture_contract":"Technical rules.","acceptance_checklist":"Verification criteria.","fail_reason":null,"phase_order":1}
```

Required non-empty strings: `phase_name`, `phase_summary`, `deliverables`, `architecture_contract`, `acceptance_checklist`. Optional: `phase_id`, `parent_project_id` (defaults to `1`), `status` (defaults to `new`), `fail_reason`, `phase_order`. Phase status must be `new`, `in_progress`, `complete`, or `fail`. Output JSON: `{"phase_id":1}`.

### `tools/get_phase.py`

Input JSON: an integer, for example `1`.

Output JSON: the complete phase record with every `phases` column, or `null` when absent.

### `tools/add_task.py`

Input JSON:

```json
{"parent_phase_id":1,"tasks":[{"task_name":"Implement CLI","task_instructions":"Specific implementation and validation instructions.","task_status":"new","task_order":1,"task_start_date":null,"task_end_date":null,"fail_reason":null,"test_results":null}]}
```

Required: integer `parent_phase_id` and non-empty `tasks`. Every task requires non-empty `task_name` and `task_instructions`. Optional task fields: `task_status` (defaults to `new`), `task_order` (defaults to array position), `task_start_date`, `task_end_date`, `fail_reason`, `test_results`. Task status must be `new`, `in_progress`, `complete`, or `fail`. Output JSON: `{"task_ids":[1]}`.

### `tools/get_task.py`

Input JSON: an integer, for example `1`.

Output JSON: the complete task record with every `tasks` column, or `null` when absent.

### `tools/update_task.py`

Input JSON contains required `task_id` and one or more fields to change. Omitted fields remain unchanged:

```json
{"task_id":1,"task_status":"fail","fail_reason":"Test command failed."}
```

Mutable fields: `parent_phase_id`, `task_name`, `task_status`, `task_instructions`, `task_start_date`, `task_end_date`, `fail_reason`, `task_order`, `test_results`. Output JSON: the complete updated task record.

### `tools/get_project_summary.py`

Input JSON is one of: `{}`, `{"phase_id":1}`, `{"output":"simple"}`, or `{"phase_id":1,"output":"simple"}`.

Output JSON:

```json
{"project":{"project_id":1,"project_name":"...","description":"...","phases":[{"phase_id":1,"phase_name":"...","tasks":[{"task_id":1,"task_name":"..."}]}]}}
```

The standard output includes every field from all three tables. `phase_id` limits nested phases and tasks to one phase. `output: "simple"` omits phase `deliverables`, `architecture_contract`, `acceptance_checklist`, and task `task_instructions`, `test_results`.

### `tools/get_project_status.py`

Input: none.

Output JSON:

```json
{"project":{"project_id":1,"project_name":"...","phases":[{"phase_id":1,"phase_name":"...","status":"new","tasks":[{"task_id":1,"task_name":"...","task_status":"new"}]}]}}
```

Only record IDs, names, and statuses are returned.

### `tools/codex.py` and `tools/aider.py`

Input: plain-text prompt, as a positional argument or stdin. The Aider adapter
also requires a positive `--task-id` argument supplied by Grinder.

Output: Codex CLI's final plain-text response. For `tools/grinder.py`, it must be exactly one of:

```json
{"task_status":"complete"}
```

```json
{"task_status":"failed","fail_reason":"Reason for failure."}
```

`codex.py` requires provider `codex` and uses the configured model and effort.
`aider.py` requires provider `aider`, launches the installed Aider CLI in
one-shot message mode, and passes it the configured model, OpenAI-compatible
base URL, API key, and task-specific
`.grindr/logs/task-<task_id>-aider-chat-history.md` path. It runs from the
parent project directory and explicitly supplies that project's editable text
files, including untracked files, while excluding `.grindr`, `.git`, virtual
environments, dependency trees, and generated caches. It does not make direct
LLM HTTP calls. Both exit nonzero when their CLI fails or produces no final
response. Grinder must pass the claimed task ID to the adapter; do not invent
a shared or root-level Aider history path.

### `tools/grinder.py`

Input: no JSON. Optional flag: `--database PATH`.

Output: one JSON line per processed task:

```json
{"task_id":1,"task_status":"complete","fail_reason":null}
```

or:

```json
{"task_id":1,"task_status":"fail","fail_reason":"Reason for failure."}
```

It selects the earliest `new` task from the earliest phase in `new` or `in_progress` status, marks it `in_progress`, then dispatches it to the `coding_agents.default.provider` adapter. It continues until no `new` tasks remain. It logs events to `logs/YYYY-MM-DD.log`. Aider receives up to two format reminders after an invalid response; a third invalid response is recorded as a failed task and stops the worker. An adapter process failure leaves the claimed task `in_progress` for inspection or retry.

### `tools/fix_task.py`

Input JSON: `{"task_id":1,"task_instructions":"Replacement instructions."}`. It requires an existing task and non-empty replacement instructions, then resets `task_status` to `new` and clears `task_start_date`, `task_end_date`, `fail_reason`, and `test_results`. Output: the complete updated task record. `tools/daemon.py` is intentionally not present; systemd integration is deferred.

## Start The Worker

After all known phases and tasks are recorded, start the worker. This is
required; do not substitute an in-process background command or wait for the
worker to finish.

1. Read `.grindr/config/config.yaml` and identify
   `coding_agents.default.provider`. It may be `codex` or `aider`; do not
   assume a particular provider or model.
2. Always launch through the provider-aware service launcher:

```bash
./tools/start-grinder.sh
```

3. If the agent's current sandbox cannot access the user systemd manager or the
   selected provider's required network, request explicit sandbox escalation
   for `./tools/start-grinder.sh`. If the client supports remembered command
   approvals, scope the approval to this exact launcher prefix. Never attempt
   to escape or weaken the sandbox from Python, and never replace the launcher
   with direct invocation of `grinder.py`, `aider.py`, or `codex.py`.
4. If escalation is unavailable or declined, report the exact launcher error
   and instruct the user to run `./tools/start-grinder.sh` once from their
   normal shell. Do not claim that the worker has started.

The launcher runs the worker as a user systemd service. This keeps it alive
when the command-execution host cleans up background child processes after the
launching shell exits. On AppArmor-enabled Linux hosts, it propagates the
launcher's profile only for the Codex provider so Codex's Bubblewrap workspace
sandbox can initialize normally. The Aider provider uses the user service
manager's normal profile so it can reach host-local model endpoints.

After a successful launch, do not wait for task completion. Tell the user:
"We're on it. Check back later." When the user returns, query
`tools/get_project_status.py` or
`tools/get_project_summary.py '{"output":"simple"}'` and report the recorded
state.

To stop a running grinder worker and its coding-agent child, run:

```bash
./tools/kill-grinder.sh
```

## Handling failures

When prompted to check on the status of a project, if a task ended in failure, discuss with user how to address the failure. Once a plan is clear, use `tools/fix_task.py` to update the task with improved instructions. Launch `./tools/start-grinder.sh` again. 