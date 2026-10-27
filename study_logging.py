"""Private research storage. SQLite locally; PostgreSQL when STUDY_DATABASE_URL is set."""
from contextlib import contextmanager
import csv
import atexit
import json
import os
import sqlite3
import uuid
import threading
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(os.environ.get('STUDY_LOG_PATH', Path(__file__).with_name('study_logs.db')))
DATABASE_URL = os.environ.get('STUDY_DATABASE_URL', '')

_initialized = set()
_schema_lock = threading.Lock()
_pool = None
_pool_lock = threading.Lock()

def postgres_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg_pool import ConnectionPool
                _pool = ConnectionPool(DATABASE_URL, min_size=0, max_size=5,
                    max_idle=60, max_lifetime=300, timeout=15, open=True,
                    kwargs={'connect_timeout':15}, check=ConnectionPool.check_connection)
                atexit.register(_pool.close)
    return _pool

class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection
    def execute(self, sql, params=()):
        return self.connection.execute(sql.replace('?', '%s'), params)

@contextmanager
def connect():
    if DATABASE_URL:
        raw = postgres_pool().getconn(timeout=15)
        con = PostgresConnection(raw)
    else:
        raw = sqlite3.connect(LOG_PATH, timeout=15)
        con = raw
    try:
        key = DATABASE_URL or str(LOG_PATH)
        if key not in _initialized:
            with _schema_lock:
                if key not in _initialized:
                    with (raw.transaction() if DATABASE_URL else raw):
                        con.execute('''CREATE TABLE IF NOT EXISTS events (
                            event_id TEXT PRIMARY KEY, participant_id TEXT NOT NULL, study_group TEXT NOT NULL,
                            server_time TEXT NOT NULL, client_time TEXT, page_id TEXT, path TEXT NOT NULL,
                            event_type TEXT NOT NULL, elapsed_ms REAL, detail TEXT NOT NULL)''')
                        con.execute('CREATE INDEX IF NOT EXISTS events_participant ON events(participant_id, study_group, server_time)')
                        con.execute('''CREATE TABLE IF NOT EXISTS participants (
                            participant_id TEXT PRIMARY KEY, name TEXT NOT NULL, started_at TEXT NOT NULL)''')
                        con.execute('CREATE TABLE IF NOT EXISTS learning_state (\n                            participant_id TEXT NOT NULL, study_group TEXT NOT NULL, word_id TEXT NOT NULL,\n                            state TEXT NOT NULL, PRIMARY KEY (participant_id,study_group,word_id))')
                    _initialized.add(key)
        with (raw.transaction() if DATABASE_URL else raw):
            yield con
    finally:
        if DATABASE_URL:
            postgres_pool().putconn(raw)
        else:
            raw.close()

def now():
    return datetime.now(timezone.utc).isoformat()

def register(participant, name):
    with connect() as con:
        con.execute('INSERT INTO participants VALUES (?,?,?)', (participant, name, now()))

@lru_cache(maxsize=5000)
def participant_name(participant):
    with connect() as con:
        row = con.execute('SELECT name FROM participants WHERE participant_id=?', (participant,)).fetchone()
    return row[0] if row else None

def record(participant, group, path, kind, detail=None, *, event_id=None,
           client_time=None, page_id=None, elapsed_ms=None, connection=None):
    def insert(con):
        con.execute('''INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(event_id) DO NOTHING''', (
            event_id or str(uuid.uuid4()), participant, group, now(),
            client_time, page_id, path[:300], kind, elapsed_ms,
            json.dumps(detail or {}, ensure_ascii=False)))
    if connection is not None:
        insert(connection)
    else:
        with connect() as con:
            insert(con)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Export private study events to CSV')
    parser.add_argument('output', help='CSV output path')
    args = parser.parse_args()
    with connect() as con, open(args.output, 'w', newline='', encoding='utf-8-sig') as out:
        rows = con.execute('SELECT * FROM events ORDER BY server_time')
        writer = csv.writer(out)
        writer.writerow([d[0] for d in rows.description])
        writer.writerows(rows)
