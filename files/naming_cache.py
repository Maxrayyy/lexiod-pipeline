"""Cross-process semantic cache with per-key leases and bounded failure caching."""

import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
import uuid


class NamingCache:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS names ("
                       "key TEXT PRIMARY KEY, owner TEXT, expires REAL, status TEXT, payload TEXT)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get_or_compute(self, key, compute, *, timeout=140):
        owner = uuid.uuid4().hex
        deadline = time.monotonic() + timeout
        while True:
            now = time.time()
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT status,payload,expires FROM names WHERE key=?", (key,)).fetchone()
                if row and row[0] == "ready":
                    return json.loads(row[1]), "cache"
                if row and row[2] > now:
                    if row[0] == "failed":
                        return None, "failed"
                    claimed = False
                else:
                    db.execute("INSERT INTO names VALUES(?,?,?,'pending',NULL) "
                               "ON CONFLICT(key) DO UPDATE SET owner=excluded.owner, "
                               "expires=excluded.expires,status='pending',payload=NULL",
                               (key, owner, now + timeout + 30))
                    claimed = True
            if claimed:
                break
            if time.monotonic() >= deadline:
                return None, "pending"
            time.sleep(.05)
        try:
            value = compute()
        except Exception:
            value = None
        with self.connect() as db:
            db.execute("UPDATE names SET status=?,payload=?,expires=? WHERE key=? AND owner=?",
                       ("ready" if value is not None else "failed",
                        json.dumps(value, ensure_ascii=False) if value is not None else None,
                        time.time() + 30, key, owner))
        return value, "llm" if value is not None else "failed"
