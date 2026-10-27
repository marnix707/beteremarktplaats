import json
import os
import sqlite3
import threading
import time

from .config import DATA_DIR, DB_PATH

_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS alarms(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  params TEXT NOT NULL,
  channels TEXT NOT NULL,
  interval_min INTEGER NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  seeded TEXT NOT NULL DEFAULT '[]',
  next_run REAL NOT NULL DEFAULT 0,
  last_run REAL,
  last_status TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS seen(alarm_id INTEGER NOT NULL, item_id TEXT NOT NULL, PRIMARY KEY(alarm_id, item_id));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hidden(item_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, alarm_id INTEGER, title TEXT NOT NULL, body TEXT NOT NULL, url TEXT NOT NULL, image TEXT NOT NULL
);
"""


def conn():
    global _conn
    with _lock:
        if _conn is None:
            os.makedirs(DATA_DIR, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
        return _conn


def _q(sql, args=()):
    with _lock:
        c = conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur


def _alarm(row):
    a = dict(row)
    a["params"] = json.loads(a["params"])
    a["channels"] = json.loads(a["channels"])
    a["seeded"] = json.loads(a["seeded"])
    a["enabled"] = bool(a["enabled"])
    return a


def list_alarms():
    with _lock:
        return [_alarm(r) for r in conn().execute("SELECT * FROM alarms ORDER BY id DESC")]


def get_alarm(alarm_id):
    with _lock:
        r = conn().execute("SELECT * FROM alarms WHERE id=?", (alarm_id,)).fetchone()
        return _alarm(r) if r else None


def add_alarm(name, params, channels, interval_min):
    now = time.time()
    cur = _q("INSERT INTO alarms(name, params, channels, interval_min, next_run, created) VALUES(?,?,?,?,?,?)",
             (name, json.dumps(params), json.dumps(channels), interval_min, now, now))
    return cur.lastrowid


def set_enabled(alarm_id, enabled):
    _q("UPDATE alarms SET enabled=?, next_run=? WHERE id=?", (int(enabled), time.time(), alarm_id))


def delete_alarm(alarm_id):
    _q("DELETE FROM alarms WHERE id=?", (alarm_id,))
    _q("DELETE FROM seen WHERE alarm_id=?", (alarm_id,))


def due_alarms(now):
    with _lock:
        return [_alarm(r) for r in conn().execute(
            "SELECT * FROM alarms WHERE enabled=1 AND next_run<=? ORDER BY next_run", (now,))]


def finish_run(alarm_id, seeded, next_run, status):
    _q("UPDATE alarms SET seeded=?, next_run=?, last_run=?, last_status=? WHERE id=?",
       (json.dumps(sorted(seeded)), next_run, time.time(), status, alarm_id))


def seen_ids(alarm_id):
    with _lock:
        return {r[0] for r in conn().execute("SELECT item_id FROM seen WHERE alarm_id=?", (alarm_id,))}


def mark_seen(alarm_id, ids):
    with _lock:
        c = conn()
        c.executemany("INSERT OR IGNORE INTO seen(alarm_id, item_id) VALUES(?,?)", [(alarm_id, i) for i in ids])
        c.commit()


def hidden_ids():
    with _lock:
        return {r[0] for r in conn().execute("SELECT item_id FROM hidden")}


def set_hidden(item_id, hide):
    if hide:
        _q("INSERT OR IGNORE INTO hidden(item_id) VALUES(?)", (item_id,))
    else:
        _q("DELETE FROM hidden WHERE item_id=?", (item_id,))


def add_notification(alarm_id, title, body, url, image):
    cur = _q("INSERT INTO notifications(ts, alarm_id, title, body, url, image) VALUES(?,?,?,?,?,?)",
             (time.time(), alarm_id, title, body, url, image))
    return cur.lastrowid


def notifications_after(after_id):
    with _lock:
        return [dict(r) for r in conn().execute(
            "SELECT * FROM notifications WHERE id>? ORDER BY id LIMIT 50", (after_id,))]


def last_notification_id():
    with _lock:
        return conn().execute("SELECT COALESCE(MAX(id), 0) FROM notifications").fetchone()[0]


def get_setting(key, default=None):
    with _lock:
        r = conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default


def set_setting(key, value):
    if value is None:
        _q("DELETE FROM settings WHERE key=?", (key,))
    else:
        _q("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
           (key, json.dumps(value)))
