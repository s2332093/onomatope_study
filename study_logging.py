"""Anonymous research events, stored separately from rebuildable teaching data."""
from contextlib import contextmanager
import csv
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(os.environ.get('STUDY_LOG_PATH', Path(__file__).with_name('study_logs.db')))

@contextmanager
def connect():
    con = sqlite3.connect(LOG_PATH, timeout=15)
    con.execute('''CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY, participant_id TEXT NOT NULL, study_group TEXT NOT NULL,
        server_time TEXT NOT NULL, client_time TEXT, page_id TEXT, path TEXT NOT NULL,
        event_type TEXT NOT NULL, elapsed_ms REAL, detail TEXT NOT NULL)''')
    con.execute('CREATE INDEX IF NOT EXISTS events_participant ON events(participant_id, study_group, server_time)')
    try:
        with con:
            yield con
    finally:
        con.close()

def record(participant, group, path, kind, detail=None, *, event_id=None,
           client_time=None, page_id=None, elapsed_ms=None):
    with connect() as con:
        con.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?)', (
            event_id or str(uuid.uuid4()), participant, group, datetime.now(timezone.utc).isoformat(),
            client_time, page_id, path[:300], kind, elapsed_ms,
            json.dumps(detail or {}, ensure_ascii=False)))

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Export anonymous study events to CSV')
    parser.add_argument('output', help='CSV output path')
    args = parser.parse_args()
    with connect() as con, open(args.output, 'w', newline='', encoding='utf-8-sig') as out:
        rows = con.execute('SELECT * FROM events ORDER BY server_time')
        writer = csv.writer(out)
        writer.writerow([d[0] for d in rows.description])
        writer.writerows(rows)
