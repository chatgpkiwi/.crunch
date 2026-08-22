# .grindr

`.grindr` helps turn a conversation with ChatGPT into completed project work. Describe the project, its goals, and what success looks like; ChatGPT captures the plan, breaks it into concrete work, and lets Codex carry out the tasks while you go do something else with your time.

Forget running Codex one prompt at a time. Explain what you want. Let .grindr grind code while you go AFK. Check the project status later.

Currently, .grindr can grind code using Codex itself, or delegate the grinding to Aider, and save your ChatGPT quota if you have a local LLM available. 


Agents, see [AGENTS.md](AGENTS.md).

## Prerequisites

The host project must have these commands available on `PATH`:

- Python 3
- SQLite 3
- Codex
- Git
- Aider (optional - Local LLM use)

## Setup

1. Create a new project in Codex. This is not a ChatGPT project. It's a Codex project, pointing to a folder on your computer/server.
2. Setup your project with git or whaterver your project needs. 
3. Inside the project folder run:  git clone 

```bash
git clone git@github.com:chatgpkiwi/codex-grinder.git
```

4. Edit config/config.yaml with your coding agent and model preferences. 
5. Make a AGENTS.md file in your root directory that says:
      "Read .grindr/AGENTS.md" 
6. Finally, chat with Codex while it has your project open. 

## Advanced

Codex starts the worker automatically, but if you must manually start it or stop it, you can run:

```bash
./tools/start-grinder.sh
```

```bash
./tools/kill-grinder.sh
```
