# View Project Workflow

Use this workflow for requests to list projects, inspect a project, check
progress, find a task, or summarize planned work. This workflow is read-only.

## Choose the Smallest Useful View

- For all projects, use `tools/list_projects.py`.
- For basic metadata for one known project ID, use `tools/get_project.py`.
- For phase and task progress, use `tools/get_project_status.py`.
- For a planned-work overview, use `tools/get_project_summary.py` with
  `{"project_id": <id>, "output":"simple"}`.
- For full phase or task detail, use `tools/get_phase.py` or `tools/get_task.py`.
  Both require the record ID and the verified `project_id`.

When the user gives only a project name, resolve it with `tools/list_projects.py`
before using project-specific tools. If multiple projects match the request,
ask which one they mean.

Report the answer in plain language: what is complete, in progress, queued,
or failed; include names and IDs only when they help the user act next. Do not
create, update, retry, start, or stop work as part of a view request unless the
user separately asks for that action.
