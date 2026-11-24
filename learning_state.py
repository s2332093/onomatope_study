"""Small, participant-scoped retry/review state in the research database."""
import json
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from copy import deepcopy

import study_logging



# Feedback needs fast working state; it is not an analytics log upload.
# Render may replace this working file on restart; pending browser logs are independent.
STATE_PATH=Path(os.environ.get('STUDY_STATE_PATH', str(study_logging.LOG_PATH)+'.working'))
@contextmanager
def connect():
    db=sqlite3.connect(STATE_PATH,timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS learning_state (participant_id TEXT, study_group TEXT, word_id TEXT, state TEXT NOT NULL, PRIMARY KEY(participant_id,study_group,word_id))')
    try:
        with db: yield db
    finally: db.close()


def read(participant, group, word_id):
    with connect() as db:
        row = db.execute('SELECT state FROM learning_state WHERE participant_id=? AND study_group=? AND word_id=?',
                         (participant, group, word_id)).fetchone()
    return json.loads(row[0]) if row else {}


def completed_words(participant, group):
    with connect() as db:
        rows = db.execute('SELECT word_id,state FROM learning_state WHERE participant_id=? AND study_group=?',
                          (participant, group)).fetchall()
    return {wid for wid, raw in rows if json.loads(raw).get('completed')}


PHASE1_STEPS = {'1', '2', '3', 'kind', '4', '5'}


def phase1_complete(state):
    # Existing completed lessons and confirmed answers remain usable after upgrades.
    confirmed = {str(k) for k, v in state.get('feature_confirmed', {}).items() if v}
    confirmed.update(str(a['k']) for a in state.get('feature_submissions', []) if a.get('ok'))
    return bool(state.get('completed') or state.get('context_passed') or PHASE1_STEPS <= confirmed)


def phase1_words(participant, group):
    with connect() as db:
        rows = db.execute('SELECT word_id,state FROM learning_state WHERE participant_id=? AND study_group=?',
                          (participant, group)).fetchall()
    return {wid for wid, raw in rows if phase1_complete(json.loads(raw))}


def update(participant, group, word_id, change):
    """Read/modify/write under one SQLite transaction, including concurrent tabs."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT state FROM learning_state WHERE participant_id=? AND study_group=? AND word_id=?',
                         (participant, group, word_id)).fetchone()
        state = json.loads(row[0]) if row else {}
        change(state)
        db.execute('''INSERT INTO learning_state VALUES (?,?,?,?)
                   ON CONFLICT(participant_id,study_group,word_id) DO UPDATE SET state=excluded.state''',
                   (participant, group, word_id, json.dumps(state, ensure_ascii=False)))
    return state


def feature_attempt(participant, group, word_id, k, ok, attempt_id):
    outcome = {}

    def change(state):
        recent = state.setdefault('feature_submissions', [])
        previous = next((s for s in recent if s['id'] == attempt_id and s['k'] == k), None)
        if previous:
            outcome.update(previous)
            return
        failures = state.setdefault('feature_failures', {})
        count = 0 if ok else failures.get(str(k), 0) + 1
        failures[str(k)] = count
        outcome.update(id=attempt_id, k=k, failures=count, ok=ok)
        recent.append(deepcopy(outcome))
        state['feature_submissions'] = recent[-100:]

    update(participant, group, word_id, change)
    return outcome
