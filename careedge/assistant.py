"""The assistant: connects the router, SQL agent, document search, guardrails
and escalation policy. Used by the app (step by step, with streaming) and by
the benchmark (run(), all at once)."""
import re
import time
from dataclasses import dataclass, field

import doc_store
import escalation
import guardrails
import models
import patient_db
import router
import sql_agent
from config import ESCALATE_BELOW, RAG_TOP_K

RECORD_TASK = """Answer the caregiver's question using ONLY the database results and document
passages below, in short plain sentences (no tables, no code, no document ID numbers).
Say where each fact came from in plain words, for example "(medication records)" or
"(discharge summary)". If they don't contain the answer, say "I don't see that in the
records." If sources disagree, show both and say the nurse should confirm which is current."""

GENERAL_TASK = """This is a general request, not about a specific resident's records. Help with
it in plain language, in at most 8 sentences, following the rules above."""

# Questions that ask for a care decision must always see the facility policies
# and care plans, even if the router only picked the database.
DECISION_Q = re.compile(r"\bshould i\b|\bcan i (give|skip|stop)|\bmissed\b|\bdouble\b|\bskip\b"
                        r"|\bextra (dose|tablet|pill)|what (do|should) (i|we) do", re.I)

UNSURE_NOTE = ("\n\n*The on-device model wasn't fully confident about this general answer. "
               "Please confirm with the nurse on duty or the pharmacist.*")


@dataclass
class Turn:
    question: str
    resident: dict | None = None        # resident the question is about, if known
    route: str = ""                     # record | general
    sources: list = field(default_factory=list)
    emergency: str | None = None
    emergency_ms: float = 0.0
    sql: sql_agent.SqlResult | None = None
    passages: list = field(default_factory=list)
    answer: str = ""
    decision: str = "local"
    reason: str = ""
    confidence: float | None = None
    guard_flags: list = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    started: float = field(default_factory=time.perf_counter)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def start(question, selected=None):
    """Emergency check (instant) and working out which resident it's about."""
    turn = Turn(question=question)
    mentioned = router.residents_mentioned(question)
    turn.resident = mentioned[0] if len(mentioned) == 1 else selected
    t0 = time.perf_counter()
    hit = guardrails.emergency_match(question)
    if hit:
        allergy = bool(guardrails.ALLERGY_RE.search(hit))
        rid = turn.resident["id"] if turn.resident else None
        meds = patient_db.med_lines(rid) if rid else None
        recent = patient_db.recent_med_lines(rid) if rid and allergy else None
        rows = patient_db.allergies(rid) if rid and allergy else None
        turn.emergency = guardrails.emergency_banner(turn.resident, meds, recent, allergy, rows)
        turn.emergency_ms = (time.perf_counter() - t0) * 1000
        escalation.log(kind="question", route="emergency", decision="emergency",
                       reason=f"matched '{hit}'", total_ms=turn.emergency_ms,
                       resident=turn.resident["name"] if turn.resident else "",
                       request=question)
    return turn


def plan(turn, mode="Auto"):
    """Pick the route: the router decides in Auto mode, otherwise the caregiver."""
    if mode == "Record":
        turn.route, turn.sources = "record", ["sql", "docs"]
        turn.timings["router"] = 0.0
    elif mode == "General":
        turn.route, turn.sources = "general", []
        turn.timings["router"] = 0.0
    else:
        turn.route, turn.sources, turn.timings["router"] = router.route(turn.question)
    if turn.emergency or DECISION_Q.search(turn.question):
        turn.route = "record"
        if "docs" not in turn.sources:
            turn.sources = [*turn.sources, "docs"]
    return turn


def run_sql(turn):
    turn.sql = sql_agent.query(turn.question, turn.resident)
    turn.timings["sql"] = turn.sql.gen_ms + turn.sql.exec_ms
    return turn


def retrieve(turn, k=RAG_TOP_K):
    t0 = time.perf_counter()
    qvec = models.embed(turn.question, is_query=True)[0]
    rid = turn.resident["id"] if turn.resident else None
    turn.passages = doc_store.search(qvec, turn.question, rid, k=k)
    turn.timings["retrieval"] = (time.perf_counter() - t0) * 1000
    return turn


def record_messages(turn, history=()):
    parts = []
    if turn.sql is not None:
        parts.append(f"DATABASE RESULT\nQuery: {turn.sql.sql}\n{sql_agent.rows_as_text(turn.sql)}")
    if "docs" in turn.sources:
        if turn.passages:
            parts.append("DOCUMENT PASSAGES\n" + "\n\n".join(
                f"[DOC-{p['document_id']}, {p['section']}] ({p['doc']['title']}, page {p['page']})\n"
                f"{p['text'].split(chr(10), 1)[-1]}" for p in turn.passages))
        else:
            parts.append("DOCUMENT PASSAGES\n(no documents matched)")
    who = f"The caregiver is asking about {turn.resident['name']}.\n\n" if turn.resident else ""
    system = guardrails.system_prompt(RECORD_TASK) + "\n\n" + who + "\n\n".join(parts)
    recent = [{"role": m["role"], "content": m["content"]} for m in list(history)[-4:]]
    return [{"role": "system", "content": system}, *recent,
            {"role": "user", "content": turn.question}]


def general_messages(turn, history=()):
    recent = [{"role": m["role"], "content": m["content"]} for m in list(history)[-4:]]
    return [{"role": "system", "content": guardrails.system_prompt(GENERAL_TASK)}, *recent,
            {"role": "user", "content": turn.question}]


def answer_general(turn, history=(), threshold=ESCALATE_BELOW):
    """Local answer with a confidence score, then the escalation decision."""
    reply = models.chat(general_messages(turn, history), max_tokens=600, logprobs=True)
    turn.timings["answer"] = reply.ms
    turn.confidence = reply.confidence
    text, turn.guard_flags = guardrails.check_output(reply.text)
    turn.decision, turn.reason = escalation.decide(turn.confidence, text, threshold)
    if turn.decision == "would_escalate":
        names = [r["name"] for r in patient_db.residents()]
        cloud_text, note = escalation.maybe_cloud(turn.question, names)
        turn.reason += f"; {note}"
        if cloud_text:
            turn.decision = "cloud"
            text, more = guardrails.check_output(cloud_text)
            turn.guard_flags += more
        else:
            text += UNSURE_NOTE
    turn.answer = text
    return turn


def finish(turn, text=None):
    """Apply the output check to a streamed record answer and log the turn."""
    if text is not None:
        turn.answer, turn.guard_flags = guardrails.check_output(text)
        turn.reason = turn.reason or "record data never leaves the device"
    turn.timings["total"] = (time.perf_counter() - turn.started) * 1000
    escalation.log(
        kind="question", route=turn.route, sources=",".join(turn.sources),
        decision=turn.decision, reason=turn.reason, confidence=turn.confidence,
        guard_flags=", ".join(turn.guard_flags), router_ms=turn.timings.get("router"),
        sql_ms=turn.timings.get("sql"), retrieval_ms=turn.timings.get("retrieval"),
        answer_ms=turn.timings.get("answer"), total_ms=turn.timings["total"],
        sql_ok=None if turn.sql is None else int(turn.sql.ok),
        resident=turn.resident["name"] if turn.resident else "", request=turn.question)
    return turn


# ---------------------------------------------------------------------------
# All at once (benchmark)
# ---------------------------------------------------------------------------

def run(question, selected=None, mode="Auto", history=(), threshold=ESCALATE_BELOW):
    turn = plan(start(question, selected), mode)
    if turn.route == "general":
        answer_general(turn, history, threshold)
        return finish(turn)
    if "sql" in turn.sources:
        run_sql(turn)
    if "docs" in turn.sources:
        retrieve(turn)
    reply = models.chat(record_messages(turn, history), max_tokens=700)
    turn.timings["answer"] = reply.ms
    return finish(turn, reply.text)
