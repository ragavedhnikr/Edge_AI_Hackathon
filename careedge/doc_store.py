"""The document store (rag.db): the vector store and the graph, in one SQLite file.

  documents  one row per uploaded file, attached to a resident or the facility
  chunks     one row per section, with its Qwen3-Embedding vector
  nodes      graph nodes: patient, document, medication, doctor, condition
  edges      graph links: patient -HAS_DOCUMENT-> document -MENTIONS-> entity

Search = graph first (which documents belong to this resident, plus facility
policies), then vector similarity with a keyword boost inside those documents.
"""
import json
import re
import sqlite3
from contextlib import contextmanager

import numpy as np

from config import RAG_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path     TEXT NOT NULL,
    file_name     TEXT NOT NULL,
    file_hash     TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    doc_type      TEXT NOT NULL,          -- discharge_summary, care_plan, clinic_letter,
                                          -- shift_note, policy, other
    resident_id   INTEGER,                -- NULL for facility documents
    scope         TEXT NOT NULL,          -- resident | facility
    pages         INTEGER NOT NULL,
    text_method   TEXT NOT NULL,          -- text | vision | txt
    match_method  TEXT NOT NULL,          -- auto | confirmed | facility
    match_note    TEXT NOT NULL DEFAULT '',
    flags         TEXT NOT NULL DEFAULT '[]',   -- JSON list of reconciliation flags
    embed_model   TEXT NOT NULL,
    ingested_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page        INTEGER NOT NULL,
    section     TEXT NOT NULL,
    text        TEXT NOT NULL,
    embedding   BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS nodes (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    kind  TEXT NOT NULL,                  -- patient, document, medication, doctor, condition
    key   TEXT NOT NULL,                  -- normalised identity
    label TEXT NOT NULL,
    UNIQUE (kind, key)
);
CREATE TABLE IF NOT EXISTS edges (
    src         INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    dst         INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    relation    TEXT NOT NULL,            -- HAS_DOCUMENT, MENTIONS
    PRIMARY KEY (src, dst, relation)
);
"""


@contextmanager
def connect(db_path=None):
    conn = sqlite3.connect(db_path or RAG_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(db_path=None):
    (db_path or RAG_DB).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _node(conn, kind, key, label):
    key = key.strip().lower()
    conn.execute("INSERT OR IGNORE INTO nodes (kind, key, label) VALUES (?, ?, ?)",
                 (kind, key, label))
    return conn.execute("SELECT id FROM nodes WHERE kind = ? AND key = ?",
                        (kind, key)).fetchone()["id"]


def add_document(meta, chunks, vectors, entities, patient_label=None, db_path=None):
    """Store one document, its sections and vectors, and its graph links.
    meta: dict of documents columns. chunks: list of (page, section, text).
    entities: {'medication': [...], 'doctor': [...], 'condition': [...]}."""
    with connect(db_path) as conn:
        cols = list(meta.keys())
        cur = conn.execute(
            f"INSERT INTO documents ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [meta[c] for c in cols])
        doc_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO chunks (document_id, page, section, text, embedding) VALUES (?, ?, ?, ?, ?)",
            [(doc_id, p, s, t, np.asarray(v, dtype=np.float32).tobytes())
             for (p, s, t), v in zip(chunks, vectors)])

        doc_node = _node(conn, "document", str(doc_id), meta["title"])
        if meta.get("resident_id"):
            pat = _node(conn, "patient", str(meta["resident_id"]),
                        patient_label or f"Resident {meta['resident_id']}")
            conn.execute("INSERT OR IGNORE INTO edges VALUES (?, ?, 'HAS_DOCUMENT')",
                         (pat, doc_node))
        for kind, names in entities.items():
            for name in names:
                if name and len(name) < 80:
                    ent = _node(conn, kind, name, name)
                    conn.execute("INSERT OR IGNORE INTO edges VALUES (?, ?, 'MENTIONS')",
                                 (doc_node, ent))
        return doc_id


def delete_document(doc_id, db_path=None):
    with connect(db_path) as conn:
        conn.execute("DELETE FROM nodes WHERE kind = 'document' AND key = ?", (str(doc_id),))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def has_hash(file_hash, db_path=None):
    with connect(db_path) as conn:
        row = conn.execute("SELECT id FROM documents WHERE file_hash = ?", (file_hash,)).fetchone()
        return row["id"] if row else None


def get_document(doc_id, db_path=None):
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None


def documents(resident_id=None, include_facility=True, db_path=None):
    """Graph step: the documents linked to a resident, plus facility documents.
    With no resident, every document."""
    with connect(db_path) as conn:
        if resident_id is None:
            rows = conn.execute("SELECT * FROM documents ORDER BY ingested_at DESC").fetchall()
        else:
            rows = conn.execute(
                """SELECT d.* FROM documents d
                   JOIN nodes dn ON dn.kind = 'document' AND dn.key = CAST(d.id AS TEXT)
                   JOIN edges e ON e.dst = dn.id AND e.relation = 'HAS_DOCUMENT'
                   JOIN nodes pn ON pn.id = e.src AND pn.kind = 'patient' AND pn.key = ?
                   ORDER BY d.ingested_at DESC""", (str(resident_id),)).fetchall()
            if include_facility:
                rows += conn.execute("SELECT * FROM documents WHERE scope = 'facility' "
                                     "ORDER BY title").fetchall()
        return [dict(r) for r in rows]


def entities_for(resident_id, db_path=None):
    """Graph: everything mentioned in a resident's documents, by kind."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT DISTINCT ent.kind, ent.label, d.title FROM nodes pn
               JOIN edges e1 ON e1.src = pn.id AND e1.relation = 'HAS_DOCUMENT'
               JOIN nodes dn ON dn.id = e1.dst
               JOIN documents d ON CAST(d.id AS TEXT) = dn.key
               JOIN edges e2 ON e2.src = dn.id AND e2.relation = 'MENTIONS'
               JOIN nodes ent ON ent.id = e2.dst
               WHERE pn.kind = 'patient' AND pn.key = ?
               ORDER BY ent.kind, ent.label""", (str(resident_id),)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["kind"], {}).setdefault(r["label"], []).append(r["title"])
    return out


def chunks_for(doc_ids, db_path=None):
    if not doc_ids:
        return []
    marks = ",".join("?" for _ in doc_ids)
    with connect(db_path) as conn:
        rows = conn.execute(f"SELECT * FROM chunks WHERE document_id IN ({marks})",
                            list(doc_ids)).fetchall()
    return [dict(r) for r in rows]


def stats(db_path=None):
    with connect(db_path) as conn:
        return {k: conn.execute(f"SELECT COUNT(*) FROM {k}").fetchone()[0]
                for k in ("documents", "chunks", "nodes", "edges")}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOP = set("""a an and are as at be by can did do does for from had has have he her his how i if in
is it its me my of on or our she so that the their them there they this to was we were what when
where which who why will with you your any about into should could would""".split())


def _terms(text):
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 2
            or any(ch.isdigit() for ch in t)}


def search(query_vec, query_text, resident_id=None, k=4, db_path=None):
    """Return the top-k sections as dicts with document info and scores."""
    docs = {d["id"]: d for d in documents(resident_id, db_path=db_path)}
    rows = chunks_for(list(docs), db_path=db_path)
    if not rows:
        return []
    matrix = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    cos = matrix @ np.asarray(query_vec, dtype=np.float32).ravel()
    q_terms = _terms(query_text)
    hits = []
    for r, c in zip(rows, cos):
        overlap = len(q_terms & _terms(r["text"])) / len(q_terms) if q_terms else 0.0
        score = float(c) + 0.15 * overlap  # keyword boost helps exact doses and drug names
        hits.append({**r, "score": score, "cosine": float(c), "keyword": overlap,
                     "doc": docs[r["document_id"]]})
    hits.sort(key=lambda h: h["score"], reverse=True)
    for h in hits:
        h.pop("embedding", None)
    return hits[:k]


def flags_of(doc):
    try:
        return json.loads(doc.get("flags") or "[]")
    except json.JSONDecodeError:
        return []
