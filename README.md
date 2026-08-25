# .crunch

`.crunch` is a standalone workspace for dispatching unattended coding work.
Projects live below `projects/`, not beside Crunch's own tools, so each project
is an isolated Git repository with its own history and remote.

## Setup

Clone `.crunch` into the workspace where you want to manage projects, configure
`config/config.yaml`, then run `./setup.sh` once from a normal logged-in shell.
It creates the database and `projects/` directory. Child projects and their
contents are ignored by the Crunch repository.

Required commands: Python 3, SQLite 3, Git, and the coding-agent CLIs selected
in `config/config.yaml` (Codex, Aider, or Qwen Code). New tasks use
`default_task_agent`; tasks reset after failure use `retry_task_agent`.

## Projects

Create a local project repository and register it:

```bash
python3 tools/create_workspace_project.py \
  '{"project_name":"timersafe","description":"A safe timer application.","toolchain":"Python 3.12; project-local .venv; pytest."}'
```

Clone an existing repository and register it:

```bash
python3 tools/clone_project.py \
  '{"url":"git@github.com:example/timersafe.git","description":"TimerSafe application.","toolchain":"Node.js 22; pnpm; React 19; Vitest."}'
```

Both commands place the repository in `projects/<name>` and return its workspace
path. Use `python3 tools/list_projects.py` to see registered projects.

The worker may process work from any registered project, but each dispatch is
scoped to exactly one project workspace. It never gives a coding agent a mixed
multi-project prompt or runs it in the Crunch repository.

See [AGENTS.md](AGENTS.md) for the agent workflow and complete tool contracts.
