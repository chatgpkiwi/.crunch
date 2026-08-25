# New Project Workflow

Use this workflow when the user wants to start a new project or bring an
existing remote repository under `.crunch` management.

## 1. Discover the Project

Learn enough to state a concise project brief: the goal, intended users,
technology or language, and whether it begins as a new workspace or a clone.
Decide early on the language, version, environment, framework, and key
libraries required for the project. Record these as concise free text in the
project's `toolchain` field so every coding-agent prompt has deterministic
runtime and dependency guidance.
For a clone, obtain the repository URL. Confirm the planned project name and
directory under `projects/`.

Do not create anything until the user confirms this brief.

## 2. Create and Identify the Project

For a new local project, use `tools/create_workspace_project.py` with:

```json
{"project_name":"example-app","description":"What the project will do.","toolchain":"Python 3.12; .venv; FastAPI; uv; pytest."}
```

For a remote repository, use `tools/clone_project.py` with:

```json
{"url":"git@github.com:owner/example-app.git","project_name":"example-app","description":"What the project will do.","toolchain":"Node.js 22; pnpm; React 19; Vitest."}
```

Both commands return the project name and workspace path, not the project ID.
Use `tools/list_projects.py` immediately afterward to identify and retain the
resulting `project_id`.

## 3. Propose the Delivery Plan

Break the confirmed project into small, ordered phases. For each phase, define
its deliverables, architectural contract, and acceptance checklist. Present
the proposed phase plan and obtain confirmation before recording it.

Create every phase with `tools/add_phase.py`. Supply the actual `project_id`
and an explicit `phase_order`; neither defaults to a safe project selection.
Leave `completion_summary` unset for planned phases and tasks. The worker
records task handoffs after successful implementation and consolidates them
when a phase completes.

```json
{
  "parent_project_id": 12,
  "phase_name":"Foundation",
  "phase_summary":"Set up the application skeleton.",
  "status":"new",
  "deliverables":"Runnable application shell and documented local setup.",
  "architecture_contract":"Keep application code in src/ with configuration isolated from domain code.",
  "acceptance_checklist":"The app starts locally and the setup instructions work.",
  "phase_order":1
}
```

## 4. Create Implementation Tasks

Read `AGENTS/TASK-QUALITY.md`. Split each phase into narrow implementation
tasks and obtain confirmation of the task plan if it differs materially from
the approved phase plan. Create tasks with `tools/add_task.py`, never
`tools/add_phase.py`.

```json
{
  "project_id":12,
  "parent_phase_id":34,
  "tasks":[
    {
      "task_name":"Create the application entry point",
      "task_instructions":"...specific implementation and validation instructions...",
      "task_status":"new",
      "task_order":1
    }
  ]
}
```

Record the returned phase and task IDs, confirm what is ready, and offer to
start the worker only if the user asks to execute the work.
