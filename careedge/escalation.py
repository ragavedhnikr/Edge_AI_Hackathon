"""Escalation policy and decision log.

The hackathon brief asks for an explicit, defensible, measurable decision about
when to escalate to the cloud. CareEdge makes that decision for every general
request, and logs it, but in this build the cloud is OFF (CLOUD_ENABLED=0):

  record questions          never escalate: patient data stays on the device
  document uploads          never escalate: uncertain matches go to a person
  general requests          answered on the device; if confidence is below the
                            threshold or the answer hedges, the decision is
                            "would escalate", the answer stays local, and the
                            caregiver is told to confirm with a clinician
  emergencies               instant on-device safety prompt, never escalate

If CLOUD_ENABLED=1 is ever set, a general request that would escalate is sent
only after the privacy check finds nothing identifying in it.
"""
import re
import sqlite3
import time
from contextlib import contextmanager

from config import (CLOUD_API_BASE, CLOUD_API_KEY, CLOUD_ENABLED, CLOUD_MODEL, ESCALATE_BELOW,
                    EVENTS_DB)

HEDGE_RE = re.compile(r"not (entirely )?sure|not certain|uncertain|i don'?t know"
                      r"|cannot (determine|say)|can'?t (determine|say for sure)", re.I)

# ---------------------------------------------------------------------------
# Privacy check (used only if the cloud is ever switched on)
# ---------------------------------------------------------------------------

_MONTHS = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
           r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
PHI_PATTERNS = {
    "date": re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b"
                       rf"|\b\d{{1,2}}\s+(?:{_MONTHS})\b|\b(?:{_MONTHS})\s+\d{{1,2}}\b", re.I),
    "phone": re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    "id number": re.compile(r"\b\d{6,}\b"),
    "room": re.compile(r"\broom\s*\d+\b", re.I),
}


def find_phi(text, resident_names):
    hits = [n for n in resident_names for part in n.split()
            if re.search(rf"\b{re.escape(part)}\b", text, re.I)]
    for kind, pattern in PHI_PATTERNS.items():
        hits += [f"{kind}: {m.group(0)}" for m in pattern.finditer(text)]
    return hits


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

def decide(confidence, answer, threshold=ESCALATE_BELOW):
    """Return (decision, reason). decision is 'local' or 'would_escalate'."""
    conf = "n/a" if confidence is None else f"{confidence:.2f}"
    if confidence is not None and confidence < threshold:
        return "would_escalate", f"low confidence ({conf} < {threshold:.2f})"
    if HEDGE_RE.search(answer or ""):
        return "would_escalate", "the on-device answer says it isn't sure"
    return "local", f"confident on device ({conf})"


def maybe_cloud(question, resident_names):
    """Only reached if CLOUD_ENABLED. Returns (text or None, note)."""
    if not (CLOUD_ENABLED and CLOUD_API_BASE and CLOUD_API_KEY and CLOUD_MODEL):
        return None, "cloud is off in this build, answer kept on device"
    hits = find_phi(question, resident_names)
    if hits:
        return None, f"blocked by privacy check ({', '.join(hits[:3])})"
    from openai import OpenAI
    client = OpenAI(base_url=CLOUD_API_BASE, api_key=CLOUD_API_KEY, timeout=60)
    resp = client.chat.completions.create(model=CLOUD_MODEL, max_tokens=500, messages=[
        {"role": "system", "content": "Give general, educational health information in plain "
                                      "language. Never give dosing or treatment advice."},
        {"role": "user", "content": question}])
    return resp.choices[0].message.content, "sent to cloud (no identifying details)"


# ---------------------------------------------------------------------------
# Decision log
# ---------------------------------------------------------------------------

EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    kind        TEXT NOT NULL,     -- question | upload
    route       TEXT NOT NULL,     -- emergency | record | general | upload
    sources     TEXT NOT NULL DEFAULT '',
    decision    TEXT NOT NULL,     -- local | would_escalate | cloud | emergency
                                   -- | auto_attached | confirmed | facility
    reason      TEXT NOT NULL DEFAULT '',
    confidence  REAL,
    guard_flags TEXT NOT NULL DEFAULT '',
    router_ms   REAL, sql_ms REAL, retrieval_ms REAL, answer_ms REAL, total_ms REAL,
    sql_ok      INTEGER,
    resident    TEXT NOT NULL DEFAULT '',
    request     TEXT NOT NULL DEFAULT ''
);
"""
FIELDS = ("kind", "route", "sources", "decision", "reason", "confidence", "guard_flags",
          "router_ms", "sql_ms", "retrieval_ms", "answer_ms", "total_ms", "sql_ok",
          "resident", "request")


@contextmanager
def _db():
    EVENTS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(EVENTS_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(EVENTS_SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def log(**fields):
    row = {k: fields.get(k) for k in FIELDS}
    for k in ("sources", "reason", "guard_flags", "resident", "request"):
        row[k] = row[k] or ""
    with _db() as conn:
        conn.execute(f"INSERT INTO events ({', '.join(FIELDS)}) VALUES "
                     f"({', '.join('?' for _ in FIELDS)})", [row[k] for k in FIELDS])


def events(limit=None):
    with _db() as conn:
        sql = "SELECT * FROM events ORDER BY id DESC" + (f" LIMIT {int(limit)}" if limit else "")
        return [dict(r) for r in conn.execute(sql)]


def clear():
    with _db() as conn:
        conn.execute("DELETE FROM events")


def now_ms():
    return time.perf_counter() * 1000
