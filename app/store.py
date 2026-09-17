import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from contextlib import contextmanager


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS groups(id TEXT PRIMARY KEY,name TEXT NOT NULL,calendar_id TEXT NOT NULL,
                calendar_name TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 0,mode TEXT NOT NULL DEFAULT 'auto',
                since INTEGER NOT NULL,cursor TEXT NOT NULL,created REAL NOT NULL,last_scan REAL,last_error TEXT DEFAULT '');
              CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,group_id TEXT NOT NULL,text TEXT NOT NULL,
                timestamp INTEGER NOT NULL,sender TEXT,type TEXT,state TEXT NOT NULL DEFAULT 'new',error TEXT DEFAULT '',created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,message_id TEXT NOT NULL,group_id TEXT,
                calendar_id TEXT NOT NULL,calendar_name TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL,
                reasons TEXT NOT NULL DEFAULT '[]',lark_id TEXT DEFAULT '',app_link TEXT DEFAULT '',error TEXT DEFAULT '',
                fingerprint TEXT DEFAULT '',created REAL NOT NULL,updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS claims(calendar_id TEXT,fingerprint TEXT,event_id TEXT NOT NULL,
                PRIMARY KEY(calendar_id,fingerprint));
              CREATE INDEX IF NOT EXISTS messages_status ON messages(state,created);
              CREATE INDEX IF NOT EXISTS events_status ON events(state,updated);
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(events)')}
            if 'operation_target' not in columns:
                db.execute("ALTER TABLE events ADD COLUMN operation_target TEXT NOT NULL DEFAULT ''")
            message_columns = {row[1] for row in db.execute('PRAGMA table_info(messages)')}
            for name, declaration in [('metadata', "TEXT NOT NULL DEFAULT '{}'"), ('attempts', 'INTEGER NOT NULL DEFAULT 0'), ('next_retry', 'REAL NOT NULL DEFAULT 0')]:
                if name not in message_columns: db.execute(f'ALTER TABLE messages ADD COLUMN {name} {declaration}')
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=15)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback(); raise
            finally: db.close()

    def rows(self, sql, params=()):
        with self.connect() as db: return [dict(x) for x in db.execute(sql, params)]

    def one(self, sql, params=()):
        rows = self.rows(sql, params); return rows[0] if rows else None

    def execute(self, sql, params=()):
        with self.connect() as db: return db.execute(sql, params).rowcount

    def get(self, key, default=None):
        row = self.one('SELECT value FROM settings WHERE key=?', (key,))
        return json.loads(row['value']) if row else default

    def set(self, key, value):
        self.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (key, json.dumps(value, ensure_ascii=False)))

    def events(self, limit=200):
        rows = self.rows('SELECT e.*,g.name AS group_name FROM events e LEFT JOIN groups g ON e.group_id=g.id ORDER BY e.updated DESC LIMIT ?', (limit,))
        for row in rows:
            row['event'] = json.loads(row.pop('payload')); row['reasons'] = json.loads(row['reasons'])
        return rows
