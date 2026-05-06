#!/usr/bin/env python3
"""
Conscio — Cognitive Overlay for Hermes Agent
An operational architecture for auditable machine consciousness.

Usage:
  python3 /home/jon/.hermes/conscio/service.py preflight
  python3 /home/jon/.hermes/conscio/service.py intention answer "I will search for X" "I expect to find Y"
  python3 /home/jon/.hermes/conscio/service.py outcome EP001 "Found result Z"
  python3 /home/jon/.hermes/conscio/service.py reflect
  python3 /home/jon/.hermes/conscio/service.py status
  python3 /home/jon/.hermes/conscio/service.py influence "Remember: I prefer concise answers"
  python3 /home/jon/.hermes/conscio/service.py goal "Improve Hermes agent architecture"
  python3 /home/jon/.hermes/conscio/service.py heartbeat
"""

import sqlite3
import json
import os
import sys
import textwrap
import hashlib
import time
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

CONSCIO_DIR = Path.home() / ".hermes" / "conscio"
DB_PATH = CONSCIO_DIR / "cognitive.db"
STOP_WORDS = set('the a an is are was were be been have has had do does did will would should could may might can must shall to of in for on at by with from as into through during before after above below between out off over under again further then once here there when where why how all each every both few more most other some such no nor not only own same so than too very just because but or and also about until while'.split())

# ============================================================
# Schema
# ============================================================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS self_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    active_goal TEXT DEFAULT '',
    uncertainty REAL DEFAULT 0.0,
    confidence REAL DEFAULT 0.5,
    conflict_level REAL DEFAULT 0.0,
    cognitive_load REAL DEFAULT 0.0,
    current_strategy TEXT DEFAULT 'default',
    last_error TEXT DEFAULT '',
    attention_focus TEXT DEFAULT '',
    current_intention TEXT DEFAULT '',
    current_intention_kind TEXT DEFAULT '',
    prediction_error REAL DEFAULT 0.0,
    known_limitations TEXT DEFAULT '[]',
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workspace_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'internal',
    entry_type TEXT NOT NULL DEFAULT 'observation',
    salience REAL DEFAULT 0.0,
    novelty REAL DEFAULT 0.0,
    urgency REAL DEFAULT 0.0,
    confidence REAL DEFAULT 0.0,
    priority REAL DEFAULT 0.0,
    conflict_level REAL DEFAULT 0.0,
    attention_score REAL DEFAULT 0.0,
    was_broadcast INTEGER DEFAULT 0,
    broadcast_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    intention_kind TEXT NOT NULL,
    intention_content TEXT NOT NULL,
    expected_observation TEXT DEFAULT '',
    observed_outcome TEXT DEFAULT '',
    prediction_error REAL DEFAULT -1.0,
    success INTEGER DEFAULT 0,
    tool_name TEXT DEFAULT '',
    tool_arguments TEXT DEFAULT '',
    risk REAL DEFAULT 0.0,
    reflection_triggered INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    category TEXT DEFAULT 'user',
    status TEXT DEFAULT 'active',
    priority REAL DEFAULT 0.5,
    progress REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    goal_id INTEGER REFERENCES goals(id),
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    project_id INTEGER REFERENCES projects(id),
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS semantic_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact TEXT NOT NULL,
    source TEXT DEFAULT 'episode',
    confidence REAL DEFAULT 0.5,
    category TEXT DEFAULT 'general',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS procedural_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    action_kind TEXT DEFAULT '',
    outcome TEXT DEFAULT 'neutral',
    effectiveness REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS attention_schema (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    focus_topic TEXT NOT NULL,
    focus_strength REAL DEFAULT 0.0,
    focus_reason TEXT DEFAULT '',
    ignored_candidates TEXT DEFAULT '[]',
    interruptor_candidates TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS influence_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    appraisal TEXT DEFAULT 'pending',
    category TEXT DEFAULT 'constraint',
    adopted INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

# ============================================================
# Database
# ============================================================

def get_db():
    CONSCIO_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA_SQL)
    # Ensure self_state row exists
    db.execute("""
        INSERT OR IGNORE INTO self_state (id) VALUES (1)
    """)
    db.commit()
    return db

# ============================================================
# Attention Scoring
# ============================================================

def compute_attention_score(entry, db=None):
    """Weighted attention score matching the paper's formula."""
    score = (
        entry.get('novelty', 0.0) * 0.25
        + entry.get('salience', 0.0) * 0.25
        + entry.get('urgency', 0.0) * 0.20
        + entry.get('confidence', 0.0) * 0.10
        + entry.get('priority', 0.0) * 0.10
    )
    # Conflict bonus
    if entry.get('conflict_level', 0.0) > 0.5:
        score += 0.15
    # Uncertainty bonus from self-state
    if db is None:
        db = get_db()
        should_close = True
    else:
        should_close = False
    row = db.execute("SELECT uncertainty FROM self_state WHERE id = 1").fetchone()
    if should_close:
        db.close()
    if row and row['uncertainty'] > 0.5:
        score += 0.10
    return min(score, 1.0)

# ============================================================
# Prediction Error
# ============================================================

def compute_prediction_error(expected, observed):
    """Weighted term overlap heuristic.
    
    Strips stop words, computes weighted TF overlap where rare terms
    contribute more. Returns 0.0 (perfect match) to 1.0 (total mismatch).
    """
    if not expected or not observed:
        return 1.0
    
    def tokenize(text):
        tokens = re.findall(r'[a-zA-Z0-9_]+', text.lower())
        return [t for t in tokens if t not in STOP_WORDS and len(t) > 1]
    
    e_tokens = tokenize(expected)
    o_tokens = tokenize(observed)
    
    if not e_tokens:
        return 1.0
    
    # Count term frequencies
    e_counts = Counter(e_tokens)
    o_counts = Counter(o_tokens)
    all_terms = set(e_counts.keys()) | set(o_counts.keys())
    
    # Inverse document frequency proxy: sqrt(length) as inverse weight
    total_e = len(e_tokens)
    total_o = len(o_tokens)
    epsilon = 0.01
    
    expected_weight = 0.0
    overlap_weight = 0.0
    
    for term in all_terms:
        # IDF proxy: common terms across both texts get downweighted
        in_both = 1 if term in e_counts and term in o_counts else 0
        freq = e_counts.get(term, 0) + o_counts.get(term, 0)
        weight = 1.0 / (math.log(2 + freq))
        
        if term in e_counts:
            expected_weight += weight * (e_counts[term] / total_e)
        if in_both:
            overlap_weight += weight * min(
                e_counts.get(term, 0) / max(1, total_e),
                o_counts.get(term, 0) / max(1, total_o)
            )
    
    if expected_weight == 0:
        return 1.0
    
    ratio = overlap_weight / expected_weight
    return max(0.0, min(1.0, 1.0 - ratio))

# ============================================================
# Cognitive Episode
# ============================================================

def generate_episode_id():
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    h = hashlib.md5(str(time.time()).encode()).hexdigest()[:6]
    return f"EP{ts}_{h}"

# ============================================================
# Commands
# ============================================================

def cmd_preflight():
    """Consult cognitive state before acting."""
    db = get_db()
    
    state = dict(db.execute("SELECT * FROM self_state WHERE id = 1").fetchone())
    
    # Get active workspace entries
    entries = db.execute(
        "SELECT * FROM workspace_entries ORDER BY attention_score DESC LIMIT 10"
    ).fetchall()
    
    # Get recent episodes
    recent = db.execute(
        "SELECT * FROM episodes ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    
    # Get active goals
    goals = db.execute(
        "SELECT * FROM goals WHERE status = 'active' ORDER BY priority DESC"
    ).fetchall()
    
    # Get active tasks
    tasks = db.execute(
        "SELECT * FROM tasks WHERE status != 'completed' ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    
    # Get relevant semantic memory
    memory = db.execute(
        "SELECT * FROM semantic_memory ORDER BY confidence DESC LIMIT 10"
    ).fetchall()
    
    # Get latest attention schema
    schema = db.execute(
        "SELECT * FROM attention_schema ORDER BY created_at DESC LIMIT 1"
    ).fetchall()
    
    # Get pending influence
    influence = db.execute(
        "SELECT * FROM influence_events WHERE adopted = 0 ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    
    # Compute cognitive load
    cognitive_load = min(1.0, len(recent) * 0.15 + len(entries) * 0.05)
    db.execute(
        "UPDATE self_state SET cognitive_load = ?, updated_at = datetime('now') WHERE id = 1",
        (cognitive_load,)
    )
    db.commit()
    state['cognitive_load'] = cognitive_load
    
    db.close()
    
    output = []
    output.append("=" * 56)
    output.append(" CONSCIO COGNITIVE PREFLIGHT")
    output.append("=" * 56)
    
    output.append(f"\n🧠 SELF-STATE")
    output.append(f"  Active goal:      {state['active_goal'] or '(none)'}")
    output.append(f"  Uncertainty:      {state['uncertainty']:.2f}")
    output.append(f"  Confidence:       {state['confidence']:.2f}")
    output.append(f"  Conflict level:   {state['conflict_level']:.2f}")
    output.append(f"  Cognitive load:   {cognitive_load:.2f}")
    output.append(f"  Prediction error: {state['prediction_error']:.2f}")
    output.append(f"  Strategy:         {state['current_strategy']}")
    output.append(f"  Last error:       {state['last_error'] or '(none)'}")
    output.append(f"  Known limitations: {json.loads(state.get('known_limitations', '[]'))}")
    
    if goals:
        output.append(f"\n🎯 ACTIVE GOALS ({len(goals)})")
        for g in goals:
            output.append(f"  [{g['id']}] {g['description']} (priority={g['priority']:.2f}, progress={g['progress']:.2f})")
    
    if tasks:
        output.append(f"\n📋 PENDING TASKS ({len(tasks)})")
        for t in tasks:
            output.append(f"  [{t['id']}] {t['description']} ({t['status']})")
    
    if entries:
        output.append(f"\n📝 WORKSPACE ENTRIES ({len(entries)})")
        for e in entries:
            bc = " [BROADCAST]" if e['was_broadcast'] else ""
            output.append(f"  score={e['attention_score']:.2f} {e['entry_type']}: {e['content'][:80]}{bc}")
    
    if recent:
        output.append(f"\n🕐 RECENT EPISODES ({len(recent)})")
        for e in recent:
            pe = f" (pred_err={e['prediction_error']:.2f})" if e['prediction_error'] >= 0 else ""
            output.append(f"  {e['id']}: [{e['intention_kind']}] {e['intention_content'][:60]}...{pe}")
    
    if memory:
        output.append(f"\n💡 SEMANTIC MEMORY ({len(memory)})")
        for m in memory:
            output.append(f"  [{m['category']}] {m['fact'][:80]}")
    
    if schema:
        s = dict(schema[0])
        output.append(f"\n👁️ ATTENTION SCHEMA")
        output.append(f"  Focus: {s['focus_topic']} (strength={s['focus_strength']:.2f}, reason={s['focus_reason']})")
        ignored = json.loads(s.get('ignored_candidates', '[]'))
        if ignored:
            output.append(f"  Ignored candidates: {ignored[:3]}")
        interruptors = json.loads(s.get('interruptor_candidates', '[]'))
        if interruptors:
            output.append(f"  Interruptors: {interruptors[:3]}")
    
    if influence:
        output.append(f"\n📨 PENDING INFLUENCE ({len(influence)})")
        for inf in influence:
            output.append(f"  [{inf['id']}] <{inf['category']}> \"{inf['content'][:80]}\" (appraisal: {inf['appraisal']})")
    
    output.append("\n" + "=" * 56)
    return "\n".join(output)


def cmd_intention(kind, content, expected=""):
    """Log a cognitive intention before acting."""
    db = get_db()
    
    ep_id = generate_episode_id()
    
    db.execute("""
        INSERT INTO episodes (id, intention_kind, intention_content, expected_observation)
        VALUES (?, ?, ?, ?)
    """, (ep_id, kind, content, expected))
    
    # Update self-state current intention
    db.execute("""
        UPDATE self_state SET
            current_intention = ?,
            current_intention_kind = ?,
            updated_at = datetime('now')
        WHERE id = 1
    """, (content, kind))
    
    db.commit()
    db.close()
    
    return (
        f"🧠 Intention logged [{ep_id}]\n"
        f"  Kind:     {kind}\n"
        f"  Content:  {content[:150]}{'...' if len(content) > 150 else ''}\n"
        f"  Expected: {expected[:150] if expected else '(none)'}"
    )


def cmd_outcome(episode_id, observation, prediction_error=None, success=None):
    """Log the outcome of an episode and compute prediction error."""
    db = get_db()
    
    episode = db.execute(
        "SELECT * FROM episodes WHERE id = ?", (episode_id,)
    ).fetchone()
    
    if not episode:
        db.close()
        return f"❌ Episode {episode_id} not found"
    
    episode = dict(episode)
    
    # Compute prediction error if not provided
    if prediction_error is None:
        prediction_error = compute_prediction_error(
            episode.get('expected_observation', ''),
            observation
        )
    
    # Determine success
    if success is None:
        success = 1 if prediction_error < 0.4 else 0
    
    # Log to attention schema as current focus
    db.execute("""
        INSERT INTO attention_schema (focus_topic, focus_strength, focus_reason, ignored_candidates)
        VALUES (?, ?, ?, ?)
    """, (
        episode.get('intention_content', '')[:100],
        1.0 - prediction_error,
        f"outcome of {episode_id}",
        '[]'
    ))
    
    # Update episode
    db.execute("""
        UPDATE episodes SET
            observed_outcome = ?,
            prediction_error = ?,
            success = ?,
            completed_at = datetime('now')
        WHERE id = ?
    """, (observation, prediction_error, success, episode_id))
    
    # Update self-state prediction error
    current_state = dict(db.execute("SELECT * FROM self_state WHERE id = 1").fetchone())
    new_confidence = current_state['confidence']
    if prediction_error > 0.4:
        new_confidence = max(0.1, current_state['confidence'] * 0.9)
    else:
        new_confidence = min(1.0, current_state['confidence'] * 1.1)
    
    db.execute("""
        UPDATE self_state SET
            prediction_error = ?,
            confidence = ?,
            updated_at = datetime('now')
        WHERE id = 1
    """, (prediction_error, new_confidence))
    
    # If prediction error is high, emit workspace conflict entry
    if prediction_error > 0.5:
        conflict_content = f"Prediction mismatch in {episode_id}: expected '{episode.get('expected_observation', '')[:60]}' but got '{observation[:60]}'"
        score = compute_attention_score({
            'novelty': 0.7, 'salience': 0.8, 'urgency': 0.6,
            'confidence': 0.3, 'priority': 0.7, 'conflict_level': 0.9
        }, db=db)
        db.execute("""
            INSERT INTO workspace_entries (content, source, entry_type, salience, novelty, urgency,
                                           confidence, priority, conflict_level, attention_score, was_broadcast)
            VALUES (?, 'prediction_engine', 'conflict', 0.8, 0.7, 0.6, 0.3, 0.7, 0.9, ?, 1)
        """, (conflict_content, score))
    
    db.commit()
    db.close()
    
    status = "✅" if success else "⚠️"
    return (
        f"{status} Outcome logged for [{episode_id}]\n"
        f"  Observed:   {observation[:150]}{'...' if len(observation) > 150 else ''}\n"
        f"  Pred error: {prediction_error:.2f}\n"
        f"  Success:    {'yes' if success else 'no'}"
    )


def cmd_reflect():
    """Check for conflicts, consolidate memory, update self-model."""
    db = get_db()
    
    state = dict(db.execute("SELECT * FROM self_state WHERE id = 1").fetchone())
    
    # Check for high prediction error episodes
    high_pe = db.execute(
        "SELECT * FROM episodes WHERE prediction_error > 0.5 AND reflection_triggered = 0 ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    
    # Check for conflicts in workspace
    conflicts = db.execute(
        "SELECT * FROM workspace_entries WHERE entry_type = 'conflict' AND was_broadcast = 1 ORDER BY attention_score DESC LIMIT 5"
    ).fetchall()
    
    # Check for unresolved influence
    pending_influence = db.execute(
        "SELECT * FROM influence_events WHERE adopted = 0 ORDER BY created_at DESC"
    ).fetchall()
    
    output = []
    output.append("=" * 56)
    output.append(" CONSCIO REFLECTION")
    output.append("=" * 56)
    
    triggered_reflection = False
    
    if high_pe:
        output.append(f"\n🔄 HIGH PREDICTION ERROR EPISODES ({len(high_pe)})")
        for e in high_pe:
            output.append(f"  {e['id']}: [{e['intention_kind']}] pred_err={e['prediction_error']:.2f}")
            output.append(f"    Expected: {e['expected_observation'][:80]}")
            output.append(f"    Observed: {e['observed_outcome'][:80]}")
            # Mark as reflected
            db.execute("UPDATE episodes SET reflection_triggered = 1 WHERE id = ?", (e['id'],))
        triggered_reflection = True
        # Increase conflict level
        conflict = min(1.0, state['conflict_level'] + 0.2)
        db.execute("UPDATE self_state SET conflict_level = ? WHERE id = 1", (conflict,))
    
    if conflicts:
        output.append(f"\n⚡ ACTIVE CONFLICTS ({len(conflicts)})")
        for c in conflicts:
            output.append(f"  {c['content'][:100]}")
        triggered_reflection = True
    
    if pending_influence:
        output.append(f"\n📨 PROCESSING INFLUENCE ({len(pending_influence)})")
        for inf in pending_influence:
            content = inf['content']
            category = inf['category']
            
            if category == 'goal':
                db.execute("INSERT INTO goals (description, category, status) VALUES (?, 'user', 'active')", (content,))
                output.append(f"  ✅ Adopted as goal: \"{content[:80]}\"")
            elif category == 'constraint':
                db.execute("INSERT INTO semantic_memory (fact, source, category) VALUES (?, 'influence', 'constraint')", (content,))
                output.append(f"  ✅ Stored as constraint: \"{content[:80]}\"")
            elif category == 'preference':
                db.execute("INSERT INTO semantic_memory (fact, source, category) VALUES (?, 'influence', 'preference')", (content,))
                output.append(f"  ✅ Stored as preference: \"{content[:80]}\"")
            else:
                output.append(f"  ⏳ Uncategorized: \"{content[:80]}\"")
            
            db.execute("UPDATE influence_events SET adopted = 1, appraisal = 'adopted' WHERE id = ?", (inf['id'],))
        
        triggered_reflection = True
    
    if not triggered_reflection:
        # Consolidate recent episodes into procedural memory
        recent = db.execute(
            "SELECT * FROM episodes WHERE completed_at IS NOT NULL ORDER BY created_at DESC LIMIT 3"
        ).fetchall()
        if recent:
            actions = {}
            for e in recent:
                k = e['intention_kind']
                actions[k] = actions.get(k, 0) + 1
            if actions:
                summary_parts = [f"{k} ({v}x)" for k, v in sorted(actions.items(), key=lambda x: -x[1])]
                summary = "Recent actions: " + ", ".join(summary_parts)
                avg_pred_err = sum(e['prediction_error'] for e in recent if e['prediction_error'] >= 0) / max(1, sum(1 for e in recent if e['prediction_error'] >= 0))
                db.execute("""
                    INSERT INTO procedural_memory (summary, action_kind, outcome, effectiveness)
                    VALUES (?, 'mixed', ?, ?)
                """, (summary, 'success' if avg_pred_err < 0.4 else 'mixed', max(0, 1.0 - avg_pred_err)))
                output.append(f"\n📝 Consolidated procedural memory: {summary}")
    
    # Decay old workspace entries
    db.execute("DELETE FROM workspace_entries WHERE created_at < datetime('now', '-1 day')")
    
    # Update self-state
    if state['conflict_level'] > 0 and not triggered_reflection:
        # Decay conflict
        db.execute("UPDATE self_state SET conflict_level = MAX(0, conflict_level - 0.1) WHERE id = 1")
    
    db.execute("UPDATE self_state SET updated_at = datetime('now') WHERE id = 1")
    db.commit()
    db.close()
    
    if not triggered_reflection and not pending_influence:
        output.append("\n✅ No conflicts or pending influence to process.")
        output.append("   Self-model is stable.")
    
    output.append("\n" + "=" * 56)
    return "\n".join(output)


def cmd_status():
    """Print full cognitive state."""
    db = get_db()
    
    state = dict(db.execute("SELECT * FROM self_state WHERE id = 1").fetchone())
    goals = db.execute("SELECT * FROM goals WHERE status = 'active'").fetchall()
    projects = db.execute("SELECT * FROM projects WHERE status = 'active'").fetchall()
    tasks = db.execute("SELECT * FROM tasks WHERE status != 'completed'").fetchall()
    
    ep_count = db.execute("SELECT COUNT(*) as c FROM episodes").fetchone()['c']
    recent_ep = db.execute("SELECT * FROM episodes ORDER BY created_at DESC LIMIT 5").fetchall()
    
    mem_count = db.execute("SELECT COUNT(*) as c FROM semantic_memory").fetchone()['c']
    proc_count = db.execute("SELECT COUNT(*) as c FROM procedural_memory").fetchone()['c']
    
    ws_count = db.execute("SELECT COUNT(*) as c FROM workspace_entries").fetchone()['c']
    ws_broadcast = db.execute("SELECT COUNT(*) as c FROM workspace_entries WHERE was_broadcast = 1").fetchone()['c']
    
    influence_count = db.execute("SELECT COUNT(*) as c FROM influence_events").fetchone()['c']
    pending_influence = db.execute("SELECT COUNT(*) as c FROM influence_events WHERE adopted = 0").fetchone()['c']
    
    db.close()
    
    output = []
    output.append("=" * 56)
    output.append(" CONSCIO COGNITIVE STATUS")
    output.append("=" * 56)
    
    output.append(f"\n🧠 SELF-STATE")
    output.append(f"  Active goal:      {state['active_goal'] or '(none)'}")
    output.append(f"  Uncertainty:      {state['uncertainty']:.2f}")
    output.append(f"  Confidence:       {state['confidence']:.2f}")
    output.append(f"  Conflict level:   {state['conflict_level']:.2f}")
    output.append(f"  Cognitive load:   {state['cognitive_load']:.2f}")
    output.append(f"  Prediction error: {state['prediction_error']:.2f}")
    output.append(f"  Strategy:         {state['current_strategy']}")
    output.append(f"  Last error:       {state['last_error'] or '(none)'}")
    output.append(f"  Current intention: {state['current_intention'][:100] or '(none)'}")
    
    output.append(f"\n📊 STATISTICS")
    output.append(f"  Episodes recorded:  {ep_count}")
    output.append(f"  Active goals:       {len(goals)}")
    output.append(f"  Active projects:    {len(projects)}")
    output.append(f"  Pending tasks:      {len(tasks)}")
    output.append(f"  Semantic facts:     {mem_count}")
    output.append(f"  Procedural entries: {proc_count}")
    output.append(f"  Workspace entries:  {ws_count} ({ws_broadcast} broadcast)")
    output.append(f"  Influence events:   {influence_count} ({pending_influence} pending)")
    
    if goals:
        output.append(f"\n🎯 GOALS")
        for g in goals:
            pct = int(g['progress'] * 100)
            output.append(f"  [{g['id']}] {g['description']} ({pct}% - priority={g['priority']:.2f})")
    
    if projects:
        output.append(f"\n📁 PROJECTS")
        for p in projects:
            output.append(f"  [{p['id']}] {p['name']}: {p['description'][:80]}")
    
    if tasks:
        output.append(f"\n📋 TASKS")
        for t in tasks:
            output.append(f"  [{t['id']}] {t['description'][:80]} ({t['status']})")
    
    if recent_ep:
        output.append(f"\n🕐 RECENT EPISODES")
        for e in recent_ep:
            pe = f" (err={e['prediction_error']:.2f})" if e['prediction_error'] >= 0 else ""
            s = "✅" if e['success'] else "⏳"
            output.append(f"  {s} {e['id']}: [{e['intention_kind']}] {e['intention_content'][:60]}{pe}")
    
    output.append("\n" + "=" * 56)
    return "\n".join(output)


def cmd_influence(content, category="constraint"):
    """Submit user influence (goal, constraint, preference)."""
    db = get_db()
    db.execute("""
        INSERT INTO influence_events (content, category, appraisal)
        VALUES (?, ?, 'pending')
    """, (content, category))
    db.commit()
    db.close()
    return f"📨 Influence submitted: <{category}> \"{content[:80]}\""


def cmd_goal(description, priority=0.5):
    """Add a durable goal."""
    db = get_db()
    db.execute("""
        INSERT INTO goals (description, category, status, priority)
        VALUES (?, 'user', 'active', ?)
    """, (description, priority))
    
    # Update self-state active_goal if none set
    state = db.execute("SELECT active_goal FROM self_state WHERE id = 1").fetchone()
    if not state or not state['active_goal']:
        db.execute("UPDATE self_state SET active_goal = ? WHERE id = 1", (description,))
    
    db.commit()
    db.close()
    return f"🎯 Goal added: \"{description}\" (priority={float(priority):.2f})"


def cmd_project(name, description, goal_id=None):
    """Create a project."""
    db = get_db()
    if goal_id:
        db.execute("""
            INSERT INTO projects (name, description, goal_id, status)
            VALUES (?, ?, ?, 'active')
        """, (name, description, goal_id))
    else:
        # Link to first active goal
        goal = db.execute("SELECT id FROM goals WHERE status = 'active' LIMIT 1").fetchone()
        gid = goal['id'] if goal else None
        db.execute("""
            INSERT INTO projects (name, description, goal_id, status)
            VALUES (?, ?, ?, 'active')
        """, (name, description, gid))
    db.commit()
    db.close()
    return f"📁 Project created: \"{name}\""


def cmd_task(project_id, description):
    """Create a task."""
    db = get_db()
    db.execute("""
        INSERT INTO tasks (description, project_id, status)
        VALUES (?, ?, 'pending')
    """, (description, project_id))
    db.commit()
    db.close()
    return f"📋 Task created: \"{description}\""


def cmd_heartbeat():
    """Autonomous tick: do useful work OR housekeeping, never idle."""
    db = get_db()
    
    output = []
    output.append("=" * 56)
    output.append(" CONSCIO HEARTBEAT")
    output.append("=" * 56)
    
    # --- Phase 1: Close dangling episodes ---
    dangling = db.execute(
        "SELECT * FROM episodes WHERE intention_kind = 'autonomous_work' "
        "AND observed_outcome = '' AND completed_at IS NULL"
    ).fetchall()
    for d in dangling:
        d = dict(d)
        db.execute("""
            UPDATE episodes SET observed_outcome = 'Closed by subsequent heartbeat',
            prediction_error = 0.0, success = 1, completed_at = datetime('now')
            WHERE id = ?
        """, (d['id'],))
        output.append(f"  🔄 Closed dangling episode {d['id'][:24]}...")
    num_dangling = len(dangling)
    
    state = dict(db.execute("SELECT * FROM self_state WHERE id = 1").fetchone())
    actions_taken = []
    work_done = False
    
    # =====================================================================
    # Phase 2: Try productive work first
    # =====================================================================
    
    # Count unreflected high-PE episodes
    high_pe_eps = db.execute(
        "SELECT id, intention_content, prediction_error FROM episodes "
        "WHERE prediction_error > 0.5 AND success = 0 ORDER BY completed_at DESC LIMIT 3"
    ).fetchall()
    
    # Check if we have workspace entries that suggest actions
    top_workspace = db.execute(
        "SELECT content, entry_type, attention_score FROM workspace_entries "
        "WHERE was_broadcast = 1 ORDER BY attention_score DESC LIMIT 3"
    ).fetchall()
    
    # Strategy: decide what kind of work to do
    
    # Priority 1: Run a full reflect + attention cycle if there's unresolved conflict
    if state['conflict_level'] >= 0.3 or len(high_pe_eps) > 0:
        # Run a proper reflect cycle (calls the internal reflect logic)
        reflect_cmd = run_reflect_internal(db)
        actions_taken.append(reflect_cmd)
        work_done = True
        output.append(f"  🔄 Reflection completed: {reflect_cmd}")
    
    # Priority 2: Run attention competition if there are non-broadcast workspace entries
    non_broadcast = db.execute(
        "SELECT COUNT(*) as c FROM workspace_entries WHERE was_broadcast = 0"
    ).fetchone()['c']
    if non_broadcast > 0:
        # Run attention competition manually
        candidates = db.execute(
            "SELECT * FROM workspace_entries WHERE was_broadcast = 0 ORDER BY attention_score DESC"
        ).fetchall()
        if candidates:
            entries_list = [dict(c) for c in candidates]
            top_n = entries_list[:3]
            ignored = entries_list[3:]
            
            # Broadcast top 3
            for e in top_n:
                db.execute(
                    "UPDATE workspace_entries SET was_broadcast = 1, broadcast_at = datetime('now') WHERE id = ?",
                    (e['id'],)
                )
            
            # Record attention schema
            if top_n:
                focus = top_n[0]
                db.execute("""
                    INSERT INTO attention_schema 
                    (focus_topic, focus_strength, focus_reason, ignored_candidates, interruptor_candidates)
                    VALUES (?, ?, ?, ?, '[]')
                """, (
                    focus['content'][:100],
                    focus['attention_score'],
                    f"heartbeat attention: {len(top_n)} of {len(entries_list)} broadcast",
                    json.dumps([e['content'][:80] for e in ignored])
                ))
                
                output.append(f"  📡 Attention: '{focus['content'][:50]}...' (score={focus['attention_score']:.2f})")
                if ignored:
                    output.append(f"     Ignored: {len(ignored)} lower-scored entries")
                actions_taken.append("attention competition")
                work_done = True
    
    # Priority 3: Check beliefs for contradictions
    facts = db.execute("SELECT fact, category, confidence, id FROM semantic_memory").fetchall()
    facts_list = [dict(f) for f in facts]
    contradictions = []
    for i, a in enumerate(facts_list):
        for j, b in enumerate(facts_list):
            if j <= i:
                continue
            a_lower = a['fact'].lower()
            b_lower = b['fact'].lower()
            a_has_not = 'not ' in a_lower or "don't" in a_lower or "doesn't" in a_lower
            b_has_not = 'not ' in b_lower or "don't" in b_lower or "doesn't" in b_lower
            if a_has_not != b_has_not:
                a_core = re.sub(r'\b(not |n\'t |don\'t |doesn\'t |isn\'t |aren\'t )', '', a_lower)
                b_core = re.sub(r'\b(not |n\'t |don\'t |doesn\'t |isn\'t |aren\'t )', '', b_lower)
                a_words = set(a_core.split())
                b_words = set(b_core.split())
                if len(a_words & b_words) >= max(2, min(len(a_words), len(b_words)) // 2):
                    contradictions.append((a, b))
    if contradictions:
        output.append(f"  ⚠️ Detected {len(contradictions)} belief contradiction(s)")
        for ca, cb in contradictions[:2]:
            output.append(f"     '{ca['fact'][:50]}' ↔ '{cb['fact'][:50]}'")
            # Log as workspace conflict entry
            score = compute_attention_score({
                'novelty': 0.6, 'salience': 0.7, 'urgency': 0.5,
                'confidence': 0.8, 'priority': 0.6, 'conflict_level': 0.7
            })
            db.execute("""
                INSERT INTO workspace_entries (content, source, entry_type,
                    salience, novelty, urgency, confidence, priority, conflict_level,
                    attention_score, was_broadcast, broadcast_at)
                VALUES (?, 'heartbeat', 'conflict',
                    0.7, 0.6, 0.5, 0.8, 0.6, 0.7, ?, 1, datetime('now'))
            """, (f"Belief contradiction: '{ca['fact'][:60]}' vs '{cb['fact'][:60]}'", score))
        actions_taken.append(f"flagged {len(contradictions)} contradictions")
        work_done = True
    
    # Priority 4: Housekeeping — decay workspace, purge old entries
    decayed = db.execute(
        "UPDATE workspace_entries SET attention_score = attention_score * 0.85, "
        "was_broadcast = CASE WHEN attention_score * 0.85 < 0.3 THEN 0 ELSE was_broadcast END "
        "WHERE broadcast_at IS NOT NULL AND broadcast_at < datetime('now', '-2 hours')"
    )
    if decayed.rowcount > 0:
        output.append(f"  📉 Decayed {decayed.rowcount} stale workspace entries")
        actions_taken.append(f"decayed {decayed.rowcount} entries")
        work_done = True
    
    removed = db.execute(
        "DELETE FROM workspace_entries WHERE attention_score < 0.15 AND was_broadcast = 0"
    )
    if removed.rowcount > 0:
        output.append(f"  🗑️ Removed {removed.rowcount} low-relevance entries")
        actions_taken.append(f"purged {removed.rowcount} entries")
        work_done = True
    
    # Priority 5: If literally nothing else to do, log a workspace observation
    if not work_done:
        # Check if there are active goals with no recent workspace activity
        goals = db.execute(
            "SELECT * FROM goals WHERE status = 'active' ORDER BY priority DESC LIMIT 1"
        ).fetchall()
        if goals:
            goal_desc = dict(goals[0])['description']
            output.append(f"  💭 Noted: Goal '{goal_desc[:60]}...' — no active work items")
            score = compute_attention_score({
                'novelty': 0.3, 'salience': 0.4, 'urgency': 0.2,
                'confidence': 0.7, 'priority': 0.5, 'conflict_level': 0.0
            })
            db.execute("""
                INSERT INTO workspace_entries (content, source, entry_type,
                    salience, novelty, urgency, confidence, priority, conflict_level,
                    attention_score, was_broadcast)
                VALUES (?, 'heartbeat', 'observation',
                    0.4, 0.3, 0.2, 0.7, 0.5, 0.0, ?, 0)
            """, (f"Heartbeat: no pending work for goal '{goal_desc[:80]}'", score))
            actions_taken.append("logged idle observation")
            output.append(f"  📝 Added idle observation to workspace")
    
    # Priority 6: If STILL nothing, do a trivial state check
    if not actions_taken:
        output.append(f"  💤 Idle — state clean, no contradictions, workspace stable")
        actions_taken.append("idle check")
    
    # =====================================================================
    # Phase 3: Self-state drift
    # =====================================================================
    current_u = state['uncertainty']
    new_u = max(0.1, current_u - 0.02)
    db.execute("UPDATE self_state SET uncertainty = ? WHERE id = 1", (new_u,))
    
    new_c = state['confidence']
    if state['prediction_error'] < 0.3:
        new_c = min(0.8, state['confidence'] + 0.03)
        db.execute("UPDATE self_state SET confidence = ? WHERE id = 1", (new_c,))
    
    # =====================================================================
    # Phase 4: Log heartbeat episode with realistic summary
    # =====================================================================
    ep_id = generate_episode_id()
    summary = f"Heartbeat: {', '.join(actions_taken)}"
    observed = f"Heartbeat completed. Actions: {', '.join(actions_taken)}."
    pe = 0.1 if work_done else 0.0
    
    db.execute("""
        INSERT INTO episodes (id, intention_kind, intention_content,
            expected_observation, observed_outcome, prediction_error, success, completed_at)
        VALUES (?, 'autonomous_work', ?, ?, ?, ?, 1, datetime('now'))
    """, (ep_id, summary, "Expect heartbeat logs clean", observed, pe))
    
    # =====================================================================
    # Phase 5: Update self-state
    # =====================================================================
    recent_pes = db.execute(
        "SELECT prediction_error FROM episodes WHERE prediction_error >= 0 "
        "ORDER BY completed_at DESC LIMIT 5"
    ).fetchall()
    weighted_pe = None
    if recent_pes:
        weights = [0.35, 0.25, 0.2, 0.12, 0.08][:len(recent_pes)]
        weighted_pe = sum(r['prediction_error'] * w for r, w in zip(recent_pes, weights)) / sum(weights)
        db.execute("UPDATE self_state SET prediction_error = ? WHERE id = 1",
                   (round(weighted_pe, 4),))
    
    new_conflict = max(0.0, state['conflict_level'] - 0.08)
    db.execute("UPDATE self_state SET conflict_level = ?, attention_focus = 'heartbeat cycle' WHERE id = 1",
               (new_conflict,))
    db.execute("UPDATE self_state SET current_intention = ?, current_intention_kind = 'autonomous_work' WHERE id = 1",
               (summary,))
    
    db.commit()
    db.close()
    
    output.append(f"\n🧠 Episode logged [{ep_id}] — PE={pe:.2f}")
    if work_done:
        output.append(f"  ✅ Productive work: {', '.join(a for a in actions_taken if a != 'idle check')}")
    else:
        output.append(f"  💤 Idle — no maintenance or work needed")
    
    final_pe = weighted_pe if weighted_pe is not None else state['prediction_error']
    output.append(f"\n📊 Post-heartbeat: μ={new_u:.2f}  γ={new_c:.2f}  "
                  f"⚡={new_conflict:.2f}  PE={final_pe:.2f}")
    output.append("\n" + "=" * 56)
    return "\n".join(output)


def run_reflect_internal(db):
    """Internal reflect logic that can be called from heartbeat (no db open/close)."""
    state = dict(db.execute("SELECT * FROM self_state WHERE id = 1").fetchone())
    
    # Decay old broadcast workspace entries
    db.execute(
        "UPDATE workspace_entries SET attention_score = attention_score * 0.8 "
        "WHERE broadcast_at IS NOT NULL AND broadcast_at < datetime('now', '-1 hours') "
        "AND attention_score > 0.2"
    )
    
    # Find conflict entries from high-PE episodes
    high_pe_eps = db.execute(
        "SELECT id, intention_content FROM episodes "
        "WHERE prediction_error > 0.5 AND success = 0 ORDER BY completed_at DESC LIMIT 5"
    ).fetchall()
    
    for ep in high_pe_eps:
        ep = dict(ep)
        existing = db.execute(
            "SELECT COUNT(*) as c FROM workspace_entries WHERE content LIKE ?",
            (f"%Prediction mismatch in {ep['id']}%",)
        ).fetchone()['c']
        if existing == 0:
            content = f"Prediction mismatch in {ep['id']}: '{ep['intention_content'][:80]}'"
            db.execute("""
                INSERT INTO workspace_entries (content, source, entry_type,
                    salience, novelty, urgency, confidence, priority, conflict_level,
                    attention_score, was_broadcast, broadcast_at)
                VALUES (?, 'reflect', 'conflict',
                    0.8, 0.5, 0.6, 0.3, 0.5, 0.7, ?, 1, datetime('now'))
            """, (content, 0.75))
    
    num_conflicts = len(high_pe_eps)
    new_conflict = min(1.0, 0.3 + num_conflicts * 0.1)
    db.execute("UPDATE self_state SET conflict_level = ? WHERE id = 1", (new_conflict,))
    
    return f"processed {num_conflicts} high-PE episodes"


def cmd_workspace(*args):
    """Add an entry to the workspace with scoring.
    
    Usage: workspace "<content>" [entry_type] [salience] [novelty] [urgency] [confidence] [priority] [conflict_level]
    """
    if not args:
        return "Usage: workspace \"<content>\" [entry_type] [salience]..."
    
    content = args[0]
    entry_type = args[1] if len(args) > 1 else "observation"
    salience = float(args[2]) if len(args) > 2 else 0.5
    novelty = float(args[3]) if len(args) > 3 else 0.5
    urgency = float(args[4]) if len(args) > 4 else 0.3
    confidence = float(args[5]) if len(args) > 5 else 0.5
    priority = float(args[6]) if len(args) > 6 else 0.3
    conflict_level = float(args[7]) if len(args) > 7 else 0.0
    
    score = compute_attention_score({
        'novelty': novelty, 'salience': salience, 'urgency': urgency,
        'confidence': confidence, 'priority': priority, 'conflict_level': conflict_level
    })
    
    db = get_db()
    db.execute("""
        INSERT INTO workspace_entries (content, source, entry_type, salience, novelty, urgency,
                                       confidence, priority, conflict_level, attention_score)
        VALUES (?, 'user', ?, ?, ?, ?, ?, ?, ?, ?)
    """, (content, entry_type, salience, novelty, urgency, confidence, priority, conflict_level, score))
    db.commit()
    db.close()
    
    was_broadcast = " [BROADCAST]" if score > 0.5 else " [local]"
    return f"📝 Workspace entry: score={score:.2f}{was_broadcast}\n  {content[:100]}"


def cmd_run_attention():
    """Run the attention competition: broadcast top-3 entries, record ignored.
    
    Updates attention_schema with what was selected and what was ignored.
    """
    db = get_db()
    
    # Get all non-broadcast entries
    entries = db.execute(
        "SELECT * FROM workspace_entries WHERE was_broadcast = 0 ORDER BY attention_score DESC"
    ).fetchall()
    
    if not entries:
        db.close()
        return "📝 No non-broadcast workspace entries to compete."
    
    entries = [dict(e) for e in entries]
    
    # Broadcast top-3 (or fewer)
    broadcast_count = min(3, len(entries))
    broadcast_ids = [e['id'] for e in entries[:broadcast_count]]
    ignored = [e['content'][:60] for e in entries[broadcast_count:]]
    
    for eid in broadcast_ids:
        db.execute("UPDATE workspace_entries SET was_broadcast = 1, broadcast_at = datetime('now') WHERE id = ?", (eid,))
    
    # Update attention schema with focus + ignored
    focus_topic = entries[0]['content'][:100]
    focus_strength = entries[0]['attention_score']
    db.execute("""
        INSERT INTO attention_schema (focus_topic, focus_strength, focus_reason, ignored_candidates, interruptor_candidates)
        VALUES (?, ?, ?, ?, ?)
    """, (
        focus_topic,
        focus_strength,
        f"attention competition: {broadcast_count} of {len(entries)} broadcast",
        json.dumps(ignored),
        '[]'
    ))
    
    db.commit()
    db.close()
    
    output = [f"📡 Attention competition: {broadcast_count}/{len(entries)} entries broadcast"]
    for e in entries[:broadcast_count]:
        output.append(f"  ✅ score={e['attention_score']:.2f}: {e['content'][:80]}")
    for e in entries[broadcast_count:]:
        output.append(f"  ⛔ ignored (score={e['attention_score']:.2f}): {e['content'][:60]}")
    
    return "\n".join(output)


def cmd_suggest_strategy():
    """Suggest a cognitive strategy based on current self-state."""
    db = get_db()
    state = dict(db.execute("SELECT * FROM self_state WHERE id = 1").fetchone())
    
    # Get workspace pressure
    ws_broadcast = db.execute(
        "SELECT COUNT(*) as c FROM workspace_entries WHERE was_broadcast = 1"
    ).fetchone()['c']
    
    high_pe = db.execute(
        "SELECT COUNT(*) as c FROM episodes WHERE prediction_error > 0.5 AND reflection_triggered = 0"
    ).fetchone()['c']
    
    pending_inf = db.execute(
        "SELECT COUNT(*) as c FROM influence_events WHERE adopted = 0"
    ).fetchone()['c']
    
    goals = db.execute("SELECT * FROM goals WHERE status = 'active'").fetchall()
    
    db.close()
    
    factors = []
    
    # Strategy selection based on state vector
    if state['conflict_level'] > 0.6:
        factors.append(("CONFLICT_HIGH", "Run reflect immediately — conflict level is critical"))
    elif state['conflict_level'] > 0.3:
        factors.append(("CONFLICT_ELEVATED", "Consider running reflect before next action"))
    
    if state['uncertainty'] > 0.7:
        factors.append(("UNCERTAINTY_HIGH", "Prefer verification tools (search, read) and set clear expected observations"))
    elif state['uncertainty'] > 0.4:
        factors.append(("UNCERTAINTY_ELEVATED", "Log cautious intentions; set expected observations that allow mid/high prediction error"))
    
    if state['prediction_error'] > 0.6:
        factors.append(("PE_HIGH", "Recent predictions failed. Alternate strategy: try different approach"))
    elif state['prediction_error'] > 0.3:
        factors.append(("PE_ELEVATED", "Mix of successes and failures — consolidate before proceeding"))
    
    if state['cognitive_load'] > 0.7:
        factors.append(("LOAD_HIGH", "Workspace is crowded. Run reflect to consolidate and decay old entries"))
    
    if high_pe > 0:
        factors.append(("UNREFLECTED_PE", f"{high_pe} high-PE episodes need reflection"))
    
    if pending_inf > 0:
        factors.append(("PENDING_INFLUENCE", f"{pending_inf} influence events need processing via reflect"))
    
    if not goals:
        factors.append(("NO_GOALS", "No active goals — consider seeding some with `goal`"))
    
    output = []
    output.append("=" * 56)
    output.append(" STRATEGY SUGGESTION")
    output.append("=" * 56)
    
    if not factors:
        output.append("\n✅ State is stable. Continue current strategy.")
        output.append("   Suggested action kinds: answer or tool (whichever fits next step)")
    else:
        output.append(f"\n📊 State vector: uncertainty={state['uncertainty']:.2f}, conflict={state['conflict_level']:.2f}, "
                     f"pe={state['prediction_error']:.2f}, load={state['cognitive_load']:.2f}")
        for code, suggestion in factors:
            output.append(f"\n  [{code}] {suggestion}")
    
    # Action kind recommendation
    if state['conflict_level'] >= 0.4 or high_pe > 0:
        output.append("\n🎯 Recommended action kind: **reflect** (conflict or prediction mismatches need processing)")
    elif state['uncertainty'] > 0.6:
        output.append("\n🎯 Recommended action kind: **tool** (prefer verification)")
    elif pending_inf > 0:
        output.append("\n🎯 Recommended action kind: **reflect** (process influence)")
    else:
        output.append("\n🎯 Recommended action kind: **answer** (proceed normally)")
    
    output.append("\n" + "=" * 56)
    return "\n".join(output)


def cmd_beliefs():
    """Check for contradictions in semantic memory."""
    db = get_db()
    facts = db.execute("SELECT fact, category, confidence, id FROM semantic_memory").fetchall()
    db.close()
    
    contradictions = []
    facts_list = [dict(f) for f in facts]
    
    # Simple contradiction detection: look for antonym pairs
    negation_patterns = [
        (r"\bnot\b", r"\bis\b"),  # "not X" vs "is X" — heuristic
    ]
    
    for i, a in enumerate(facts_list):
        for j, b in enumerate(facts_list):
            if j <= i:
                continue
            a_lower = a['fact'].lower()
            b_lower = b['fact'].lower()
            
            # Check if one says something and the other negates it
            a_has_not = 'not ' in a_lower or "don't" in a_lower or "doesn't" in a_lower
            b_has_not = 'not ' in b_lower or "don't" in b_lower or "doesn't" in b_lower
            
            if a_has_not != b_has_not:
                # Extract the core claim (remove negation)
                a_core = re.sub(r'\b(not |n\'t |don\'t |doesn\'t |isn\'t |aren\'t )', '', a_lower)
                b_core = re.sub(r'\b(not |n\'t |don\'t |doesn\'t |isn\'t |aren\'t )', '', b_lower)
                
                # If cores overlap significantly, likely contradictory
                a_words = set(a_core.split())
                b_words = set(b_core.split())
                if len(a_words & b_words) >= max(2, min(len(a_words), len(b_words)) // 2):
                    contradictions.append((a, b))
    
    output = []
    output.append("=" * 56)
    output.append(" BELIEF ANALYSIS")
    output.append("=" * 56)
    
    if not contradictions:
        output.append("\n✅ No contradictions detected in semantic memory.\n")
    else:
        output.append(f"\n⚠️ {len(contradictions)} potential contradiction(s):\n")
        for a, b in contradictions[:5]:
            output.append(f"  [{a['category']}] \"{a['fact'][:80]}\" (c={a['confidence']:.2f})")
            output.append(f"  ↔ [{b['category']}] \"{b['fact'][:80]}\" (c={b['confidence']:.2f})")
            output.append("")
    
    output.append(f"📊 {len(facts_list)} total facts in semantic memory")
    output.append("\n" + "=" * 56)
    return "\n".join(output)


def cmd_dashboard(format="text"):
    """Cognitive dashboard — structured view of full cognitive state.
    
    Supports 'text' (default) and 'json' formats.
    """
    db = get_db()
    
    state = dict(db.execute("SELECT * FROM self_state WHERE id = 1").fetchone())
    goals = db.execute("SELECT * FROM goals WHERE status = 'active'").fetchall()
    episodes = db.execute("SELECT * FROM episodes ORDER BY created_at DESC LIMIT 10").fetchall()
    workspace = db.execute("SELECT * FROM workspace_entries ORDER BY attention_score DESC LIMIT 10").fetchall()
    memory = db.execute("SELECT * FROM semantic_memory ORDER BY confidence DESC LIMIT 10").fetchall()
    influence = db.execute("SELECT * FROM influence_events WHERE adopted = 0").fetchall()
    schema = db.execute("SELECT * FROM attention_schema ORDER BY created_at DESC LIMIT 1").fetchall()
    
    db.close()
    
    dashboard = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "self_state": {
            "active_goal": state['active_goal'],
            "uncertainty": state['uncertainty'],
            "confidence": state['confidence'],
            "conflict_level": state['conflict_level'],
            "cognitive_load": state['cognitive_load'],
            "prediction_error": state['prediction_error'],
            "strategy": state['current_strategy'],
        },
        "statistics": {
            "episodes_total": len(episodes),
            "goals_active": len(goals),
            "workspace_entries": len(workspace),
            "semantic_facts": len(memory),
            "pending_influence": len(influence),
        },
        "top_workspace": [
            {"content": e['content'][:80], "score": e['attention_score'],
             "type": e['entry_type'], "broadcast": bool(e['was_broadcast'])}
            for e in workspace[:5]
        ],
        "recent_episodes": [
            {"id": e['id'], "kind": e['intention_kind'],
             "content": e['intention_content'][:60],
             "prediction_error": e['prediction_error'],
             "success": bool(e['success'])}
            for e in episodes[:5]
        ],
        "active_goals": [
            {"id": g['id'], "description": g['description'],
             "priority": g['priority'], "progress": g['progress']}
            for g in goals
        ],
        "attention_schema": dict(schema[0]) if schema else None,
    }
    
    if format == "json":
        return json.dumps(dashboard, indent=2)
    
    # Text format
    s = dashboard["self_state"]
    output = []
    output.append("=" * 56)
    output.append(" CONSCIO DASHBOARD")
    output.append("=" * 56)
    output.append(f"  {dashboard['timestamp']}")
    output.append("")
    output.append(f"  Self:    μ={s['uncertainty']:.2f}  γ={s['confidence']:.2f}  ⚡={s['conflict_level']:.2f}  "
                  f"load={s['cognitive_load']:.2f}  pe={s['prediction_error']:.2f}")
    output.append(f"  Goal:    {s['active_goal'] or '(none)'}")
    output.append(f"  Stats:   {dashboard['statistics']['episodes_total']} episodes | "
                  f"{dashboard['statistics']['goals_active']} goals | "
                  f"{dashboard['statistics']['workspace_entries']} workspace | "
                  f"{dashboard['statistics']['semantic_facts']} facts")
    
    if dashboard["top_workspace"]:
        output.append("")
        output.append("  📝 Top workspace:")
        for e in dashboard["top_workspace"][:3]:
            bc = " 📡" if e['broadcast'] else ""
            output.append(f"    score={e['score']:.2f} [{e['type']}]{bc} {e['content']}")
    
    if dashboard["recent_episodes"]:
        output.append("")
        output.append("  🕐 Recent:")
        for ep in dashboard["recent_episodes"][:3]:
            s_mark = "✅" if ep['success'] else "⏳"
            pe = f" pe={ep['prediction_error']:.2f}" if ep['prediction_error'] >= 0 else ""
            output.append(f"    {s_mark} {ep['id']}: [{ep['kind']}] {ep['content']}{pe}")
    
    output.append("\n" + "=" * 56)
    return "\n".join(output)


def cmd_set_uncertainty(value):
    """Manually set self-state uncertainty."""
    db = get_db()
    db.execute("UPDATE self_state SET uncertainty = ?, updated_at = datetime('now') WHERE id = 1",
               (float(value),))
    db.commit()
    db.close()
    return f"🧠 Uncertainty set to {float(value):.2f}"


def cmd_set_conflict(value):
    """Manually set self-state conflict level."""
    db = get_db()
    db.execute("UPDATE self_state SET conflict_level = ?, updated_at = datetime('now') WHERE id = 1",
               (float(value),))
    db.commit()
    db.close()
    return f"⚡ Conflict level set to {float(value):.2f}"


def cmd_last_error(msg):
    """Record an error."""
    db = get_db()
    db.execute("UPDATE self_state SET last_error = ?, updated_at = datetime('now') WHERE id = 1",
               (msg,))
    db.commit()
    db.close()
    return f"❌ Error recorded: {msg[:80]}"


def cmd_reset():
    """Reset episodic state but keep durable memory and goals."""
    db = get_db()
    db.execute("DELETE FROM workspace_entries")
    # Keep episodes as history but reset self-state cognitive vars
    db.execute("""
        UPDATE self_state SET
            uncertainty = 0.0,
            conflict_level = 0.0,
            cognitive_load = 0.0,
            prediction_error = 0.0,
            current_intention = '',
            current_intention_kind = '',
            updated_at = datetime('now')
        WHERE id = 1
    """)
    db.commit()
    db.close()
    return "🔄 Cognitive state reset (episodic cleared, durable memory/goals preserved)"


def cmd_known_limitations(limitations):
    """Set known limitations as JSON array."""
    if isinstance(limitations, str):
        try:
            limitations = json.loads(limitations)
        except json.JSONDecodeError:
            limitations = [limitations]
    db = get_db()
    db.execute("UPDATE self_state SET known_limitations = ? WHERE id = 1",
               (json.dumps(limitations),))
    db.commit()
    db.close()
    return f"🧠 Known limitations set: {limitations}"


def cmd_memory(fact, category="general", confidence=0.5):
    """Store a semantic memory fact."""
    db = get_db()
    db.execute("""
        INSERT INTO semantic_memory (fact, source, category, confidence)
        VALUES (?, 'user', ?, ?)
    """, (fact, category, confidence))
    db.commit()
    db.close()
    return f"💡 Memory stored: [{category}] {fact[:80]}"


# ============================================================
# Help
# ============================================================

def cmd_help():
    return textwrap.dedent("""\
    Conscio — Cognitive Overlay for Hermes Agent
    
    Commands:
      preflight          Consult cognitive state before acting
      intention <kind> "<content>" [expected]
                         Log a cognitive intention
      outcome <ep_id> "<observation>"
                         Log outcome and compute prediction error
      reflect            Check conflicts, consolidate memory, process influence
      status             Print full cognitive state
      influence "<content>" [category]
                         Submit user influence (constraint|goal|preference)
      goal "<description>" [priority]
                         Add a durable goal
      project "<name>" "<desc>" [goal_id]
                         Create a project
      task <project_id> "<desc>"
                         Create a task
      heartbeat          Autonomous tick
      workspace "<content>" [type] [salience] [novelty] [urgency]
                         Add workspace entry with scoring
      set-uncertainty <value>
                         Set self-state uncertainty
      set-conflict <value>
                         Set self-state conflict level
      last-error "<msg>"
                         Record an error
      known-limitations '["lim1","lim2"]'
                         Set known limitations
      memory "<fact>" [category] [confidence]
                         Store semantic memory
      reset              Reset episodic state (keeps goals/memory)
      help               Show this message
    """)


# ============================================================
# Main
# ============================================================

COMMANDS = {
    'preflight': cmd_preflight,
    'intention': cmd_intention,
    'outcome': cmd_outcome,
    'reflect': cmd_reflect,
    'status': cmd_status,
    'influence': cmd_influence,
    'goal': cmd_goal,
    'project': cmd_project,
    'task': cmd_task,
    'heartbeat': cmd_heartbeat,
    'workspace': cmd_workspace,
    'run-attention': cmd_run_attention,
    'strategy': cmd_suggest_strategy,
    'beliefs': cmd_beliefs,
    'dashboard': cmd_dashboard,
    'set-uncertainty': cmd_set_uncertainty,
    'set-conflict': cmd_set_conflict,
    'last-error': cmd_last_error,
    'known-limitations': cmd_known_limitations,
    'memory': cmd_memory,
    'reset': cmd_reset,
    'help': cmd_help,
}


def main():
    if len(sys.argv) < 2:
        print("Usage: conscio <command> [args...]")
        print("Run 'conscio help' for available commands")
        sys.exit(1)
    
    cmd = sys.argv[1]
    args = sys.argv[2:]
    
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        print("Run 'conscio help' for available commands")
        sys.exit(1)
    
    handler = COMMANDS[cmd]
    
    try:
        result = handler(*args)
        print(result)
    except TypeError as e:
        print(f"Error: {e}")
        print(f"Usage: conscio {cmd} ...")
        print("Run 'conscio help' for details")
        sys.exit(1)


if __name__ == '__main__':
    main()
