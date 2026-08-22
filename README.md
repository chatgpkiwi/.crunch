# .grindr

`.grindr` helps turn a conversation with ChatGPT into completed project work. Describe the project, its goals, and what success looks like; ChatGPT captures the plan, breaks it into concrete work, and lets Codex carry out the tasks while you go do something else with your time.

It is especially useful when you are away from your keyboard, such as while driving and using ChatGPT voice mode. When the ChatGPT phone app is linked to a remote Codex environment, you can explain what you need, let ChatGPT gather the details, then leave it to grind through the work. Check the project status when you are back.

For the agent workflow and tool reference, see [AGENTS.md](AGENTS.md).

## Prerequisites

The host project must have these commands available on `PATH`:

- Python 3
- SQLite 3
- Codex CLI
- Git

To stop a running worker and its Codex child, run:

```bash
./tools/kill-grinder.sh
```
