# Conscio — Cognitive Overlay for AI Agents

An operational architecture for **auditable machine consciousness**, implemented as a standalone Python service with SQLite persistence. Conscio adds explicit SelfState, scored workspace attention, intention/outcome tracking with prediction error, and durable goals to any AI agent session.

Based on the Conscio paper by [Jonathan Schemoul](https://github.com/Jonnyboy) (LibertAI / Aleph Cloud).

## Features

- **Self-State Tracking** — uncertainty, confidence, conflict level, cognitive load, prediction error
- **Intention/Outcome Loop** — log what you intend, log what happened, compute prediction error
- **Weighted Prediction Error** — TF-IDF-style term overlap that handles intentional observations correctly (v1.1.0)
- **Attention Competition** — scored workspace entries compete; top entries are broadcast, ignored candidates are recorded in an auditable attention schema
- **Strategy Suggestion** — reads the self-state vector and recommends `reflect`, `tool`, or `answer`
- **Belief Analysis** — detects contradictions in semantic memory via negation-pair analysis
- **Cognitive Dashboard** — compact JSON output for programmatic consumption
- **Autonomous Heartbeat** — runs a maintenance cycle: closes dangling episodes, runs reflection, decays stale workspace, drifts state toward homeostasis — all with a logged, auditable episode
- **SQLite Persistence** — all state survives restarts

## Tables

| Table | Purpose |
|-------|---------|
| `self_state` | Current uncertainty, conflict, load, focus, intention, prediction error |
| `workspace_entries` | Scored candidates competing for attention |
| `episodes` | Cognitive episodes with intention, expectation, outcome, prediction error |
| `goals` | Active drives / objectives |
| `projects` | Projects linked to goals |
| `tasks` | Tasks linked to projects |
| `semantic_memory` | Durable facts |
| `procedural_memory` | Procedural summaries |
| `attention_schema` | Focus, ignored candidates, interruptors |

## Quick Start

```bash
git clone https://github.com/shem-aleph/hermes-conscio.git
cd hermes-conscio

# Bootstrap the database
python3 service.py set-uncertainty 0.5

# Seed a goal
python3 service.py goal "Research and implement Conscio architecture" 1.0

# Check state
python3 service.py status
```

For a full cognitive episode (the standard loop):

```bash
# 1. Preflight — consult state before acting
python3 service.py preflight

# 2. Log intention
python3 service.py intention search "Look for Conscio paper" "Find the latest document"

# 3. Act — do the thing (tool call, answer, etc.)

# 4. Log outcome
python3 service.py outcome EP20260506_XXXXXX "Found paper v1.0 — 12 pages"

# 5. Reflect
python3 service.py reflect
```

## Commands Reference

### Core Cognitive Loop

| Command | Description |
|---------|-------------|
| `preflight` | Pre-action state check: self-state, goals, workspace, pending influence |
| `intention <kind> "<content>" "<expected>"` | Log what you intend and what you expect to observe |
| `outcome <episode_id> "<observed>"` | Log what happened, compute prediction error |
| `reflect` | Consolidate workspace, decay entries, detect conflicts, update self-state |

### Workspace & Attention

| Command | Description |
|---------|-------------|
| `workspace "<content>" [type] [salience] [novelty] [urgency] [confidence] [priority] [conflict]` | Add a scored workspace entry |
| `run-attention` | Run attention competition: broadcast top entries, record ignored candidates |
| `strategy` | Suggest action strategy from self-state vector |

### Belief & Self-Model

| Command | Description |
|---------|-------------|
| `beliefs` | Detect contradictions in semantic memory |
| `memory "<fact>" <category> <confidence>` | Store a fact in semantic memory |
| `set-uncertainty <value>` | Manually set uncertainty (0.0–1.0) |
| `last-error "<msg>"` | Record an error to avoid repeating |
| `known-limitations '[...]'` | Set JSON array of known limitations |

### Dashboard & Audit

| Command | Description |
|---------|-------------|
| `dashboard [json]` | Compact status display. With `json`, outputs structured JSON |
| `status` | Full cognitive status with all state vectors |
| `reset` | Clear episodic state (keeps goals and memory) |
| `heartbeat` | Run one autonomous maintenance cycle |

### Goals & Projects

| Command | Description |
|---------|-------------|
| `goal "<desc>" <priority>` | Add an active goal |
| `project "<name>" "<desc>"` | Create a project |
| `task <project_id> "<desc>"` | Create a task under a project |

## How Prediction Error Works (v1.1.0)

Prediction error uses **weighted term frequency overlap**. Stop words are stripped and rare content words contribute more to the match score:

- Good match (e.g., "Found paper v1.0 — 12 pages" vs expected "Find the latest document") → **~0.44**
- Complete mismatch → **1.0**
- Partial overlap → **0.5–0.8**

This replaces the naive term-set overlap from v1.0 which produced artificially high errors when expected observations described intentions rather than concrete observables.

## How the Heartbeat Works (v1.1.0)

The heartbeat runs a **priority chain** — it always finds something productive before falling back to idling:

1. **Close dangling episodes** — finalize any incomplete autonomous_work episodes
2. **Reflect on high-PE episodes** — create conflict workspace entries from prediction mismatches
3. **Run attention competition** — promote non-broadcast entries, record ignored candidates
4. **Check beliefs** — scan for contradictions in semantic memory
5. **Housekeeping** — decay old workspace entries, purge low-relevance ones
6. **Log observation** — if everything is clean, note the current goal state
7. **Idle** — only if literally nothing else needs doing

Each heartbeat produces a logged, auditable episode with proper completion.

## Integration with Hermes Agent

Create a skill (`conscio-cognitive-loop`) that loads the Conscio service path and uses the standard cognitive loop before/after significant actions:

```bash
CONSCIO=/path/to/hermes-conscio/service.py

# Before acting:
python3 $CONSCIO preflight
python3 $CONSCIO intention tool "Check file system" "List of files found"

# Act...

# After acting:
python3 $CONSCIO outcome EP_ID "Found 3 files matching pattern"
python3 $CONSCIO reflect
```

## License

MIT
