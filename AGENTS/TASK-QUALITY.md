# Task Quality Standard

Use this standard whenever creating or revising an implementation task.

Each task must be a small, independently executable unit of work that one
coding-agent session can complete and verify. Write it as a technical lead's
brief, not as a vague reminder.

Include, when relevant:

- The user-visible outcome and exact behavior.
- The affected files, modules, interfaces, or components.
- Important constraints, compatibility expectations, and non-goals.
- Data, error, loading, security, or edge-case behavior.
- The tests or validation commands to run and clear completion criteria.

Write task instructions so a coding agent can accurately report the durable
features, contracts, and interface changes it established in a concise
completion summary. This handoff is used as focused context by later tasks;
avoid asking for broad or speculative work that would make that summary vague.

Avoid broad tasks such as “build the dashboard,” “improve authentication,” or
“fix the API.” Split them into ordered tasks with concrete boundaries. Do not
invent product requirements; mark unresolved choices and ask the user before
recording the task.

The task instructions must be self-contained enough that an implementation
agent does not need to infer the intended result from a prior conversation.
