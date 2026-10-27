"""Small, participant-scoped retry/review state in the research database."""
import json
from copy import deepcopy

import study_logging

# Change this one value to adjust the knowledge-reveal threshold.
FEATURE_REVEAL_AFTER = 3


def read(participant, group, word_id):
    with study_logging.connect() as db:
        row = db.execute('SELECT state FROM learning_state WHERE participant_id=? AND study_group=? AND word_id=?',
                         (participant, group, word_id)).fetchone()
    return json.loads(row[0]) if row else {}


def update(participant, group, word_id, change):
    """Read/modify/write under one SQLite transaction, including concurrent tabs."""
    with study_logging.connect() as db:
        if study_logging.DATABASE_URL:
            # Serialize updates for this learner/word across server workers.
            db.execute('SELECT pg_advisory_xact_lock(hashtext(?))', (participant + group + word_id,))
        else:
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
