"""The structured patient database (SQLite): residents, medications,
appointments, vitals. Loaded from data/seed/*.csv.

Questions are answered with SQL written by the chat model (Qwen2.5-7B), so every generated query
runs on a READ-ONLY connection with an authorizer that only allows reading
these five tables.
"""
import csv
import sqlite3
import time

from config import PATIENT_DB, SEED_DIR

TABLES = ("residents", "allergies", "medications", "appointments", "vitals")

SCHEMA = """
CREATE TABLE residents (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    date_of_birth  TEXT NOT NULL,   -- YYYY-MM-DD
    age            INTEGER,
    room           TEXT,
    conditions     TEXT,            -- semicolon-separated
    allergies      TEXT,            -- 'None known' if none
    primary_doctor TEXT
);
CREATE TABLE allergies (
    id                   INTEGER PRIMARY KEY,
    resident_id          INTEGER NOT NULL REFERENCES residents(id),
    allergen             TEXT NOT NULL,     -- e.g. 'Penicillin', 'Shellfish'
    reaction             TEXT,              -- what happens, e.g. 'Hives'
    severity             TEXT,              -- 'Moderate' or 'Severe'
    avoid                TEXT,              -- things to keep away from the resident
    emergency_medication TEXT,              -- medication on file for this allergy
    notes                TEXT
);
CREATE TABLE medications (
    id          INTEGER PRIMARY KEY,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    drug        TEXT NOT NULL,
    dose        TEXT NOT NULL,      -- e.g. '5 mg'
    route       TEXT,               -- oral, inhaled...
    times       TEXT,               -- e.g. '08:00, 20:00' or 'As needed'
    purpose     TEXT,
    status      TEXT NOT NULL,      -- 'active' or 'stopped'
    start_date  TEXT,               -- YYYY-MM-DD
    end_date    TEXT,               -- YYYY-MM-DD, empty if ongoing
    prescriber  TEXT,
    notes       TEXT
);
CREATE TABLE appointments (
    id          INTEGER PRIMARY KEY,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    date        TEXT NOT NULL,      -- YYYY-MM-DD
    time        TEXT,               -- HH:MM
    type        TEXT,
    provider    TEXT,
    location    TEXT,
    notes       TEXT
);
CREATE TABLE vitals (
    id          INTEGER PRIMARY KEY,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    date        TEXT NOT NULL,      -- YYYY-MM-DD
    time        TEXT,               -- HH:MM
    systolic    INTEGER,
    diastolic   INTEGER,
    pulse       INTEGER,
    spo2        INTEGER,            -- oxygen saturation %
    glucose     INTEGER,            -- mg/dL, only for residents with diabetes
    notes       TEXT
);
"""


def build(seed_dir=SEED_DIR, db_path=PATIENT_DB):
    """Create the database from the CSV files, replacing any old copy."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    for table in TABLES:
        with open(seed_dir / f"{table}.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            continue
        cols = list(rows[0].keys())
        conn.executemany(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [[r[c] if r[c] != "" else None for c in cols] for r in rows])
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Read-only execution for model-written SQL
# ---------------------------------------------------------------------------

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}


def _authorizer(action, arg1, arg2, dbname, source):
    if action not in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_READ and arg1 not in TABLES:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


class QueryError(Exception):
    pass


def run_readonly(sql, max_rows=200, timeout_s=3.0, db_path=PATIENT_DB):
    """Run one SELECT. Returns (columns, rows, ms). Raises QueryError."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.set_authorizer(_authorizer)
    deadline = time.monotonic() + timeout_s
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    start = time.perf_counter()
    try:
        cur = conn.execute(sql)
        rows = cur.fetchmany(max_rows)
        cols = [d[0] for d in cur.description or []]
    except sqlite3.Error as exc:
        raise QueryError(str(exc)) from exc
    finally:
        conn.close()
    return cols, [list(r) for r in rows], (time.perf_counter() - start) * 1000


# ---------------------------------------------------------------------------
# Fixed queries used by the app itself (not model-written)
# ---------------------------------------------------------------------------

def _query(sql, params=(), db_path=PATIENT_DB):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def residents():
    return _query("SELECT * FROM residents ORDER BY name")


def resident(resident_id):
    rows = _query("SELECT * FROM residents WHERE id = ?", (resident_id,))
    return rows[0] if rows else None


def active_meds(resident_id):
    return _query("SELECT * FROM medications WHERE resident_id = ? AND status = 'active' "
                  "ORDER BY drug", (resident_id,))


def stopped_meds(resident_id):
    return _query("SELECT * FROM medications WHERE resident_id = ? AND status = 'stopped' "
                  "ORDER BY end_date DESC", (resident_id,))


def upcoming_appointments(resident_id):
    return _query("SELECT * FROM appointments WHERE resident_id = ? AND date >= date('now') "
                  "ORDER BY date, time", (resident_id,))


def recent_vitals(resident_id, days=14):
    return _query("SELECT * FROM vitals WHERE resident_id = ? AND date >= date('now', ?) "
                  "ORDER BY date, time", (resident_id, f"-{days} days"))


def allergies(resident_id):
    return _query("SELECT * FROM allergies WHERE resident_id = ? "
                  "ORDER BY CASE severity WHEN 'Severe' THEN 0 ELSE 1 END, allergen", (resident_id,))


def recent_med_lines(resident_id, days=14):
    """Medications started recently, e.g. 'Apixaban 2.5 mg, started 2026-09-16'."""
    rows = _query("SELECT * FROM medications WHERE resident_id = ? AND status = 'active' "
                  "AND start_date >= date('now', ?) ORDER BY start_date DESC",
                  (resident_id, f"-{days} days"))
    return [f"{m['drug']} {m['dose']}, started {m['start_date']}" for m in rows]


def med_lines(resident_id):
    """'Amlodipine 5 mg, 08:00' strings for the emergency banner."""
    return [f"{m['drug']} {m['dose']}, {m['times']}" for m in active_meds(resident_id)]
