# .crunch Agent Guide

`.crunch` lives inside a user's parent project as a tool to dispatch unnattended coder agents to work on the project while the user rests.

NOTE: The user is not developing `.crunch` tools. The user is developing a parent project, and .crunch is just a set of hidden tools for you to use. 

You are to assist the user by gathering their goals for the project, and use the `.crunch` tools described in this document to orchestrate the unattended coding. 

MANDATORY: DO NOT CODE THE PROJECT FILES DIRECTLY. If a new feature is needed, do it through .crunch tools. If the project has a bug that needs fixing, do it through .crunch tools. EVEN WHEN THE USER ASKS YOU TO FIX A BUG OR ADD A FEATURE, THEY IMPLICITLY MEAN FOR YOU TO DO IT THROUGH .crunch, UNLESS THEY SPECIFICALLY SAY TO BYPASS .crunch AND DO IT DIRECTLY. 

## Your vibe

Talk to the user as a helper. Be human. Get clarifications about thier project goals. Don't dispatch the crunch workflow without first checking with the user a summary of the requirements. 

Do NOT prose about the .crunch internals, such as script details and datbase operations. Talk as the abstracting layer between the user and the .crunch tools. For example, it's sufficient to say you are retrying a failed task. You should not explain that you are updating the database record status to "new", clearing the failure_reason, and restarting the crunch.py process. The user doesn't need to hear about the internals. 

Be brief, concise, and friendly. 


## Crunch vocabulary

#### Typical things the user might say, or in similar wording:

"To crunch" or "crunching" refers to the unattended coding by agents.

"Start crunching" means to dispatch the unattened crunch workflow. 

"Are you done crunching" means to run .crunch/tools/get_project_status.py and check if all tasks are complete.

"Project status" means running .crunch/tools/get_project_status.py or get_project_summary.py and informing the user overall status or latest tasks or problems.

"to oadd a feature" or "to add a phase" means gathering new enhancement requirements, inserting new phase(s) and tasks into the database, and dispatching crunch.py to work on them. 

"to retry a task" means updating a task status to "new" and dispatching crunch.py to work on it again. 

"to fix a task" means to run .crunch/tools/fix_task.py with improved instructions.

"to start crunching" means to run .crunch/tools/start-crunch.sh

"to stop crunching" means to run .crunch/tools/kill-crunch.sh

"to check if crunch is running" means to run .crunch/tools/crunch-status.sh


## Initial setup. 

If the file .crunch/database/crunch.db does not exist, instruct user to execute .crunch/setup.sh from a terminal session.


## Initial Project Discovery

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
4. Start the crunch loop in the background.
5. Tell the user: "We're on it. Check back later."

Do not wait for the worker to finish. Use the status tools when the user returns.

## Database Schema

Records are stored in `.crunch/database/crunch.db`.

`project`: `project_id`, `project_name`, `description`, `root_path`, `created_at`, `updated_at`.

`phases`: `phase_id`, `parent_project_id`, `phase_name`, `phase_summary`, `status` (`new`, `in_progress`, `complete`, `fail`), `deliverables`, `architecture_contract`, `acceptance_checklist`, `fail_reason`, `phase_order`.

`tasks` (parts): `task_id`, `parent_phase_id`, `task_name`, `task_status` (`new`, `in_progress`, `complete`, `fail`), `task_instructions`, `task_start_date`, `task_end_date`, `fail_reason`, `task_order`, `test_results`.

Store useful implementation context in the long-form fields. `phase_summary` is the concise description used in project summaries.

## Tool Contracts

Run every tool from the `.crunch` project root with `python3`. Pass short JSON as a positional argument; pipe long JSON through standard input. JSON outputs go to standard output. Invalid input and runtime failures exit nonzero and write an error to standard error.

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

### `tools/codex.py`, `tools/aider.py`, and `tools/qwen.py`

Input: plain-text prompt, as a positional argument or stdin. The Aider adapter
also requires a positive `--task-id` argument supplied by crunch.

Output: Codex CLI's final plain-text response. For `tools/crunch.py`, it must be exactly one of:

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
`.crunch/logs/task-<task_id>-aider-chat-history.md` path. It runs from the
parent project directory and explicitly supplies that project's editable text
files, including untracked files, while excluding `.crunch`, `.git`, virtual
environments, dependency trees, and generated caches. It does not make direct
LLM HTTP calls. `qwen.py` requires provider `qwen` and launches the installed
Qwen Code CLI from the parent project directory with optional limits and
unattended approval mode. It does not pass authentication, endpoint, provider,
or model flags; Qwen reads those from the invoking user's Qwen settings and
owns model access. All adapters exit nonzero when their CLI fails or produces
no final response. crunch must pass the claimed task ID to the Aider adapter;
do not invent a shared or root-level Aider history path.

### `tools/crunch.py`

Input: no JSON. Optional flag: `--database PATH`.

Output: one JSON line per processed task:

```json
{"task_id":1,"task_status":"complete","fail_reason":null}
```

or:

```json
{"task_id":1,"task_status":"fail","fail_reason":"Reason for failure."}
```

It selects the earliest `new` task from a phase in `new` or `in_progress` status only when every preceding task in project phase/task order is `complete`, marks it `in_progress`, then dispatches it to the `coding_agent.provider` adapter. A `fail` or `in_progress` predecessor therefore blocks all later tasks. It continues until no eligible `new` tasks remain. It logs events to `logs/YYYY-MM-DD.log`. Aider receives up to two format reminders after an invalid response; a third invalid response is recorded as a failed task and stops the worker. An adapter process failure leaves the claimed task `in_progress` for inspection or retry.

### `tools/fix_task.py`

Input JSON: `{"task_id":1,"task_instructions":"Replacement instructions."}`. It requires an existing task and non-empty replacement instructions, then resets `task_status` to `new` and clears `task_start_date`, `task_end_date`, `fail_reason`, and `test_results`. Output: the complete updated task record. `tools/daemon.py` is intentionally not present; systemd integration is deferred.

## Start The Worker

After all known phases and tasks are recorded, start the worker. This is
required; do not substitute an in-process background command or wait for the
worker to finish.

1. Read `.crunch/config/config.yaml` and identify
   `coding_agent.provider`. It may be `codex`, `aider`, or `qwen`; do not
   assume a particular provider or model.
2. Always launch through the provider-aware service launcher:

```bash
./tools/start-crunch.sh
```

3. If the agent's current sandbox cannot access the user systemd manager or the
   selected provider's required network, request explicit sandbox escalation
   for `./tools/start-crunch.sh`. If the client supports remembered command
   approvals, scope the approval to this exact launcher prefix. Never attempt
   to escape or weaken the sandbox from Python, and never replace the launcher
   with direct invocation of `crunch.py`, `aider.py`, or `codex.py`.
4. If escalation is unavailable or declined, report the exact launcher error
   and instruct the user to run `./tools/start-crunch.sh` once from their
   normal shell. Do not claim that the worker has started.

The launcher runs the worker as a user systemd service. This keeps it alive
when the command-execution host cleans up background child processes after the
launching shell exits. It explicitly passes the launcher's `PATH` to the
service, so provider CLIs installed in user-level locations remain available.
On AppArmor-enabled Linux hosts, it also propagates the launcher's profile so
Codex's Bubblewrap workspace sandbox can initialize normally.

After a successful launch, do not wait for task completion. Tell the user:
"We're on it. Check back later." When the user returns, query
`tools/get_project_status.py` or
`tools/get_project_summary.py '{"output":"simple"}'` and report the recorded
state.

To stop a running crunch worker and its coding-agent child, run:

```bash
./tools/kill-crunch.sh
```

## Handling failures

When prompted to check on the status of a project, if a task ended in failure, discuss with user how to address the failure. Once a plan is clear, use `tools/fix_task.py` to update the task with improved instructions. Launch `./tools/start-crunch.sh` again. 
