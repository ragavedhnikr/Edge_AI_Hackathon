"""Decide what kind of message this is, on the device, with one short the chat model (Qwen2.5-7B) call.

  record   about residents or the care home: answered from the patient database
           (SQL) and/or the documents (RAG). Never leaves the device.
  general  a general request: explain a term, summarize pasted text, draft a note.
"""
import models
import patient_db

ROUTER_PROMPT = """Classify a caregiver's message in a care home. Reply with ONLY JSON:
{{"route": "record" or "general", "sources": ["sql"] or ["docs"] or ["sql", "docs"]}}

route:
- record: about a resident or the care home (medications, doses, times, allergies,
  appointments, vitals, rooms, hospital stays, care plans, shift notes, facility policies
  and procedures), or a summary of a resident.
- general: general knowledge or a writing task not about a specific resident's records
  (what a condition is, what a medicine is usually for, summarize or rewrite pasted text).

sources (only for record):
- sql: facts stored in tables: medications, doses, times, allergies, conditions, rooms,
  appointments, vitals and trends, questions across all residents.
- docs: what documents say: why something happened, instructions in a care plan or
  discharge summary, shift notes, who signed something, facility policies and procedures.
- both for summaries or when unsure.

Residents: {residents}

Message: {message}"""


def route(message):
    """Return (route, sources, ms). On any doubt: record with both sources,
    which keeps the answer grounded and on the device."""
    names = ", ".join(r["name"] for r in patient_db.residents())
    reply = models.chat([{"role": "user", "content": ROUTER_PROMPT.format(
        residents=names, message=message)}], max_tokens=40, temperature=0)
    try:
        data = models.parse_json(reply.text)
        kind = str(data.get("route", "record")).lower()
        sources = [s for s in data.get("sources", []) if s in ("sql", "docs")]
    except (ValueError, AttributeError):
        kind, sources = "record", []
    if kind not in ("record", "general"):
        kind = "record"
    if kind == "record" and not sources:
        sources = ["sql", "docs"]
    return kind, (sources if kind == "record" else []), reply.ms


def residents_mentioned(message):
    """Residents named in the message (first or last name)."""
    words = {w.strip(".,?!'s").lower() for w in message.split()}
    return [r for r in patient_db.residents()
            if any(part.lower() in words for part in r["name"].split())]
