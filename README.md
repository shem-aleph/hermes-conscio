# Conscio — Cognitive Overlay for Hermes Agent

An operational architecture for auditable machine consciousness,
implemented as a persistent cognitive service that Hermes Agent
consults and updates during its session loop.

## Architecture

```
Hermes Agent Session
  │
  ├── /cognitive preflight       ← consult SelfState, workspace, memory
  ├── /cognitive intention "..." ← log what I intend + expected outcome
  ├── /cognitive outcome "..."   ← log what happened, compute prediction error
  ├── /cognitive reflect         ← check for conflicts, update self-model
  └── /cognitive status          ← view current state
```

## Tables (SQLite)

- `self_state` — current uncertainty, conflict, load, focus, intention, goals, prediction error
- `workspace_entries` — scored candidates competing for attention
- `episodes` — cognitive episodes with intention, expectation, outcome, prediction error
- `intentions` — logged intentions before action
- `goals` — seed drives + user influence + active projects
- `projects` — durable projects linked to goals
- `tasks` — tasks linked to projects
- `semantic_memory` — durable facts learned
- `procedural_memory` — procedural summaries of episodes
- `attention_schema` — focus, ignored candidates, interruptors

## Quick Start

```bash
python3 /home/jon/.hermes/conscio/service.py [command]
```

Commands:
- `preflight` — consult self-state, recent episodes, workspace before acting
- `intention <kind> "<content>" [expected]` — log a cognitive intention
- `outcome <episode_id> "<observation>"` — log outcome, compute prediction error
- `reflect` — check for conflicts, update self-model, consolidate memory
- `influence "<content>"` — submit user influence (goal/constraint)
- `status` — print full cognitive state
- `reset` — reset episodic state (keep durable memory/goals)
- `goal "<description>"` — add a durable goal
- `project "<name>" "<description>"` — create a project
- `task "<project_id>" "<description>"` — create a task
- `heartbeat` — autonomous tick: select goal → select/create task → run episode
