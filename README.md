# .crunch

`.crunch` helps turn a conversation with ChatGPT into completed project work. Describe the project, its goals, and what success looks like; ChatGPT captures the plan, breaks it into concrete work, and lets Codex carry out the tasks while you go do something else with your time.

Forget running Codex one prompt at a time. Explain what you want. Let .crunch grind code while you go AFK. Check the project status later.

Currently, .crunch can grind code using Codex itself, or delegate the grinding to Aider or Qwen Code and save your ChatGPT quota if you have a local LLM available.


Agents, see [AGENTS.md](AGENTS.md).

## Prerequisites

The host project must have these commands available on `PATH`:

- Python 3
- SQLite 3
- Codex
- Git
- Aider (optional - Local LLM use)
- Qwen Code (optional - Qwen provider)

When you start a worker with `.crunch/tools/start-crunch.sh`, its current
`PATH` is passed to the background user service. This is important for CLIs
installed into user-level locations such as `~/.npm-global/bin`; no separate
systemd PATH configuration is required.

## Setup

1. Create a new project in Codex. This is not a ChatGPT project. It's a Codex project, pointing to a folder on your computer/server.
2. Setup your project with git or whaterver your project needs. 
3. Inside the project folder run:  git clone 

```bash
git clone git@github.com:chatgpkiwi/codex-crunch.git
```

4. Edit config/config.yaml with your coding-agent preferences. Codex and Aider
   accept model settings there; Qwen uses the invoking user's existing Qwen
   configuration (normally `~/.qwen/settings.json`).
5. Make a AGENTS.md file in your root directory that says:
      "Read .crunch/AGENTS.md" 
6. Finally, chat with Codex while it has your project open. 

Once it is installed, describe the work you want done in a project conversation.
crunch turns that conversation into a concrete plan and carries out the work in
the background while preserving a clear record of progress.
