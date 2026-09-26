"""CareEdge web app. Run with:  ./run.sh app   (or: streamlit run app.py)

Pages
  Ask            record questions (SQL + documents) and general requests
  Upload         add a PDF/TXT to a resident's record (auto-match or confirm)
  Patients       one resident's record: profile, medications, vitals, documents, graph
  Edge vs cloud  the escalation policy, live metrics and the decision log
"""
import hashlib
import time
from pathlib import Path

import pandas as pd
import streamlit as st

import assistant
import doc_store
import escalation
import guardrails
import ingest
import models
import patient_db
from config import (CLOUD_ENABLED, DOCS_DIR, EMBED_BASE, EMBED_DISPLAY, ESCALATE_BELOW, LLM_BASE,
                    LLM_DISPLAY, PATIENT_DB, UPLOAD_DIR)

st.set_page_config(page_title="CareEdge", page_icon="🩺", layout="wide")
doc_store.init()
if not PATIENT_DB.exists():
    patient_db.build()

PAGES = ["Ask", "Upload", "Patients", "Edge vs cloud"]
MODES = ["Auto", "Record", "General"]


def md(text):
    return (text or "").replace("$", "\\$")


@st.cache_data(ttl=20, show_spinner=False)
def server_status():
    return models.status()


@st.cache_data(show_spinner=False)
def page_png(path, page):
    return ingest.render_page_png(path, page)


def secs(ms):
    return "n/a" if ms is None else f"{ms / 1000:.1f} s"


# ---------------------------------------------------------------------------
# Rendering one assistant turn
# ---------------------------------------------------------------------------

def turn_meta(turn):
    """Everything needed to redraw a turn from the chat history."""
    return {
        "emergency": turn.emergency, "emergency_ms": turn.emergency_ms,
        "route": turn.route, "sources": turn.sources, "decision": turn.decision,
        "reason": turn.reason, "confidence": turn.confidence, "guard_flags": turn.guard_flags,
        "timings": dict(turn.timings),
        "sql": None if turn.sql is None else {
            "sql": turn.sql.sql, "columns": turn.sql.columns, "rows": turn.sql.rows,
            "error": turn.sql.error, "attempts": turn.sql.attempts},
        "passages": [{"doc_id": p["document_id"], "title": p["doc"]["title"],
                      "file_path": p["doc"]["file_path"], "page": p["page"],
                      "section": p["section"], "score": p["score"],
                      "text": p["text"].split("\n", 1)[-1]} for p in turn.passages],
    }


def badge(meta):
    total = meta["timings"].get("total")
    took = f" ({secs(total)})" if total else ""
    if meta["route"] == "record":
        src = " and ".join({"sql": "the patient records", "docs": "the documents"}[x]
                           for x in meta["sources"])
        st.caption(f"🔒 Answered on this device from {src}{took}.")
    elif meta["decision"] == "would_escalate":
        st.caption(f"📋 The on-device model wasn't fully confident, so this answer is flagged for "
                   f"a nurse to confirm. Nothing was sent to the cloud{took}.")
    elif meta["decision"] == "cloud":
        st.caption(f"☁️ Answered with help from the cloud (no identifying details sent){took}.")
    else:
        st.caption(f"🔒 Answered on this device{took}.")
    if meta["guard_flags"]:
        st.caption(f"🛡️ Safety check: {', '.join(meta['guard_flags'])}.")


def render_turn(content, meta, expanded=False):
    """Chat shows text only: no query tables or document pages (those live on the
    Upload and Patients pages)."""
    if meta.get("emergency"):
        st.error(meta["emergency"])
        st.caption(f"🚨 Safety prompt shown in {meta['emergency_ms']:.2f} ms, before any model ran.")
    st.markdown(md(content))
    badge(meta)


# ---------------------------------------------------------------------------
# Ask
# ---------------------------------------------------------------------------

def page_ask(selected, threshold):
    st.header("Ask CareEdge")
    st.info(guardrails.DISCLAIMER, icon="ℹ️")
    mode = st.radio("Question type", MODES, horizontal=True, key="mode",
                    help="Auto lets CareEdge decide. Record: residents and care-home documents. "
                         "General: explanations and writing help, no records.")
    key = f"chat_{selected['id'] if selected else 'all'}"
    history = st.session_state.setdefault(key, [])
    if history and st.button("Clear conversation"):
        history.clear()
        st.rerun()

    for msg in history:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                render_turn(msg["content"], msg["meta"])
            else:
                st.markdown(md(msg["content"]))

    suggestion = None
    slot = st.empty()
    if not history:
        with slot.container():
            st.caption("Try asking")
            examples = ["Which residents get medication at 22:00?",
                        "Why was Lakshmi admitted to hospital?",
                        "What does our fall policy say to do?",
                        "What is COPD, in simple words?",
                        "Maria is having an allergic reaction"]
            for col, q in zip(st.columns(len(examples)), examples):
                if col.button(q, key=f"ex_{key}_{q}"):
                    suggestion = q
    if suggestion:
        slot.empty()

    who = selected["name"].split()[0] if selected else "any resident"
    question = st.chat_input(f"Ask about {who}, the care home, or anything general") or suggestion
    if not question:
        return

    with st.chat_message("user"):
        st.markdown(md(question))
    with st.chat_message("assistant"):
        try:
            turn = assistant.start(question, selected)
            if turn.emergency:
                st.error(turn.emergency)
            with st.spinner("Choosing a path on the device..."):
                assistant.plan(turn, "Auto" if suggestion else mode)
            if turn.route == "record":
                if "sql" in turn.sources:
                    with st.spinner("Checking the patient records..."):
                        assistant.run_sql(turn)
                if "docs" in turn.sources:
                    with st.spinner("Checking the documents..."):
                        assistant.retrieve(turn)
                box = st.empty()
                t0 = time.perf_counter()
                with box.container():
                    text = st.write_stream(models.stream(assistant.record_messages(turn, history)))
                turn.timings["answer"] = (time.perf_counter() - t0) * 1000
                assistant.finish(turn, text if isinstance(text, str) else "".join(map(str, text)))
                box.markdown(md(turn.answer))  # replace with the safety-checked version
            else:
                with st.spinner("Answering on the device..."):
                    assistant.answer_general(turn, history, threshold)
                assistant.finish(turn)
                st.markdown(md(turn.answer))
            meta = turn_meta(turn)
            badge(meta)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Something went wrong talking to the local models ({exc}). "
                     f"Check that both are running: {LLM_BASE} and {EMBED_BASE}.")
            return
    history += [{"role": "user", "content": question},
                {"role": "assistant", "content": turn.answer, "meta": meta}]


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def finish_upload(analysis, resident_id, scope, method):
    doc_id, flags, ms = ingest.commit(analysis, resident_id, scope=scope, match_method=method)
    total = sum(ms.values())
    who = patient_db.resident(resident_id)["name"] if resident_id else "the facility"
    escalation.log(kind="upload", route="upload",
                   decision={"auto": "auto_attached", "confirmed": "confirmed",
                             "facility": "facility"}[method],
                   reason=analysis.reason, total_ms=total, resident=who if resident_id else "",
                   request=analysis.file_name)
    st.session_state.last_upload = {"doc_id": doc_id, "who": who, "flags": flags,
                                    "reason": analysis.reason, "method": method, "ms": total}
    st.session_state.pop("pending", None)
    st.session_state.upload_nonce = st.session_state.get("upload_nonce", 0) + 1


def page_upload():
    st.header("Add a document")
    st.write("Upload a PDF or text file. CareEdge reads it on this device, works out which "
             "resident it belongs to and adds it to their record for search. Nothing is sent "
             "to the cloud.")
    nonce = st.session_state.get("upload_nonce", 0)
    uploaded = st.file_uploader("PDF or TXT", type=["pdf", "txt"], key=f"up_{nonce}")
    if uploaded and st.button("Read and add", type="primary"):
        data = uploaded.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        existing = doc_store.has_hash(digest)
        if existing:
            st.info(f"This file is already in the records as DOC-{existing}.")
        else:
            incoming = UPLOAD_DIR / "incoming"
            incoming.mkdir(parents=True, exist_ok=True)
            path = incoming / uploaded.name
            path.write_bytes(data)
            try:
                with st.spinner("Reading the document on this device..."):
                    analysis = ingest.analyze(path, uploaded.name)
            except ValueError as exc:
                st.error(f"Couldn't read this document: {exc}")
                return
            if analysis.auto:
                with st.spinner("Adding it to the record..."):
                    finish_upload(analysis, analysis.suggested_id, analysis.scope,
                                  "facility" if analysis.scope == "facility" else "auto")
                st.rerun()
            st.session_state.pending = analysis

    pending = st.session_state.get("pending")
    if pending:
        st.warning(f"Please confirm who **{pending.file_name}** belongs to: {pending.reason}.")
        people = patient_db.residents()
        options = [r["id"] for r in people] + ["facility"]
        labels = {r["id"]: f"{r['name']} (room {r['room']}, born {r['date_of_birth']})" for r in people}
        labels["facility"] = "Facility document (shared with everyone)"
        index = options.index(pending.suggested_id) if pending.suggested_id in options else 0
        choice = st.selectbox("Resident", options, index=index, format_func=labels.get)
        c1, c2 = st.columns([1, 5])
        if c1.button("Confirm and add", type="primary"):
            with st.spinner("Adding it to the record..."):
                if choice == "facility":
                    finish_upload(pending, None, "facility", "confirmed")
                else:
                    finish_upload(pending, choice, "resident", "confirmed")
            st.rerun()
        if c2.button("Cancel"):
            st.session_state.pop("pending", None)
            st.rerun()

    last = st.session_state.get("last_upload")
    if last:
        how = {"auto": "matched automatically", "confirmed": "confirmed by you",
               "facility": "facility document"}[last["method"]]
        st.success(f"Added as DOC-{last['doc_id']} to {last['who']} ({how}: {last['reason']}).")
        if last["flags"]:
            st.warning("The document's medications differ from the medication record. CareEdge "
                       "has not changed anything; please ask the nurse to review.")
            st.dataframe(pd.DataFrame(last["flags"]).rename(columns={
                "drug": "Medication", "document": "In the document", "record": "In the record"}),
                hide_index=True)

    st.divider()
    docs = doc_store.documents()
    c1, c2 = st.columns([3, 1])
    c1.subheader(f"Documents in the records ({len(docs)})")
    if c2.button("Add sample documents"):
        with st.spinner("Reading the sample documents on this device..."):
            report = ingest.ingest_folder(DOCS_DIR)
        for name, result in report:
            st.caption(f"{name}: {result}")
        docs = doc_store.documents()
    if docs:
        names = {r["id"]: r["name"] for r in patient_db.residents()}
        st.dataframe(pd.DataFrame([{
            "Doc": f"DOC-{d['id']}", "Title": d["title"], "Belongs to": names.get(d["resident_id"],
                                                                                 "Facility"),
            "Matched": d["match_method"], "Read by": d["text_method"],
            "Medication flags": len(doc_store.flags_of(d)), "File": d["file_name"]} for d in docs]),
            hide_index=True)


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

def graph_dot(resident, docs, entities):
    lines = ['digraph { rankdir=LR; bgcolor="transparent";',
             'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];',
             f'p [label="{resident["name"]}", fillcolor="#CFE8E1"];']
    for d in docs:
        if d["resident_id"] == resident["id"]:
            lines.append(f'd{d["id"]} [label="DOC-{d["id"]}\\n{d["title"][:28]}", fillcolor="#EEEDFE"];')
            lines.append(f"p -> d{d['id']};")
    colors = {"medication": "#FAEEDA", "doctor": "#E6F1FB", "condition": "#FBEAF0"}
    for kind, items in entities.items():
        for i, (label, titles) in enumerate(list(items.items())[:12]):
            nid = f"{kind[0]}{i}"
            lines.append(f'{nid} [label="{label[:30]}", fillcolor="{colors.get(kind, "#F1EFE8")}"];')
            for d in docs:
                if d["title"] in titles and d["resident_id"] == resident["id"]:
                    lines.append(f"d{d['id']} -> {nid};")
    lines.append("}")
    return "\n".join(lines)


def page_patients(selected):
    people = patient_db.residents()
    if selected is None:
        selected = st.selectbox("Resident", people, format_func=lambda r: r["name"])
    r = selected
    st.header(r["name"])
    c = st.columns(4)
    c[0].metric("Room", r["room"])
    c[1].metric("Age", r["age"])
    c[2].metric("Date of birth", r["date_of_birth"])
    c[3].metric("Primary doctor", r["primary_doctor"])
    st.markdown(f"**Conditions:** {r['conditions']}")
    allergy_rows = patient_db.allergies(r["id"])
    if allergy_rows:
        st.error("Allergies: " + "; ".join(f"{a['allergen']} ({a['severity'].lower()})"
                                          for a in allergy_rows))
        st.dataframe(pd.DataFrame(allergy_rows)[
            ["allergen", "reaction", "severity", "avoid", "emergency_medication"]].rename(columns={
                "allergen": "Allergy", "reaction": "Reaction", "severity": "Severity",
                "avoid": "Avoid", "emergency_medication": "Medication on file"}), hide_index=True)
    else:
        st.caption("Allergies: none known")

    left, right = st.columns(2)
    with left:
        st.subheader("Current medications")
        st.dataframe(pd.DataFrame(patient_db.active_meds(r["id"]))[
            ["drug", "dose", "route", "times", "purpose", "prescriber"]], hide_index=True)
        stopped = patient_db.stopped_meds(r["id"])
        if stopped:
            with st.expander(f"Stopped medications ({len(stopped)})"):
                st.dataframe(pd.DataFrame(stopped)[["drug", "dose", "end_date", "notes"]],
                             hide_index=True)
        st.subheader("Upcoming appointments")
        appts = patient_db.upcoming_appointments(r["id"])
        if appts:
            st.dataframe(pd.DataFrame(appts)[["date", "time", "type", "provider", "location"]],
                         hide_index=True)
        else:
            st.caption("None scheduled.")
    with right:
        st.subheader("Vitals, last 14 days")
        v = pd.DataFrame(patient_db.recent_vitals(r["id"]))
        if not v.empty:
            st.line_chart(v, x="date", y=["systolic", "diastolic"], height=220)
            extra = "glucose" if v["glucose"].notna().any() else "spo2"
            st.line_chart(v, x="date", y=[extra], height=160)

    st.subheader("Documents and connections")
    docs = doc_store.documents(r["id"])
    own = [d for d in docs if d["resident_id"] == r["id"]]
    if not own:
        st.caption("No documents yet. Add some on the Upload page.")
    else:
        st.graphviz_chart(graph_dot(r, docs, doc_store.entities_for(r["id"])))
        for d in own:
            flags = doc_store.flags_of(d)
            with st.expander(f"DOC-{d['id']}: {d['title']}"
                             + (f"  ⚠️ {len(flags)} medication flag(s)" if flags else "")):
                st.caption(f"{d['file_name']}, matched {d['match_method']} ({d['match_note']}), "
                           f"added {d['ingested_at']}")
                if flags:
                    st.dataframe(pd.DataFrame(flags), hide_index=True)
                if d["file_path"].lower().endswith(".pdf") and Path(d["file_path"]).exists():
                    st.image(page_png(d["file_path"], 1), width=520)
    facility = [d for d in docs if d["scope"] == "facility"]
    if facility:
        st.caption("Facility policies available to every resident: "
                   + ", ".join(f"DOC-{d['id']} {d['title']}" for d in facility))


# ---------------------------------------------------------------------------
# Edge vs cloud
# ---------------------------------------------------------------------------

ARCH = f"""digraph {{ rankdir=LR; bgcolor="transparent";
node [shape=box, style="rounded,filled", fillcolor="#E1F5EE", color="#0F6E56", fontname="Helvetica", fontsize=10];
q [label="Caregiver message", fillcolor="#F1EFE8"]; up [label="PDF / TXT upload", fillcolor="#F1EFE8"];
subgraph cluster_n {{ label="HP ZGX Nano: everything here stays on device"; fontname="Helvetica"; color="#0F6E56";
 em [label="Emergency check"]; rt [label="Router\\n{LLM_DISPLAY}"]; sql [label="SQL agent\\n{LLM_DISPLAY} + patient.db"];
 rag [label="Search\\n{EMBED_DISPLAY} + rag.db"]; ans [label="Answer + safety check"]; gen [label="General answer\\n+ confidence"];
 ing [label="Extract, identify patient,\\nsplit, embed, tag"]; }}
dec [label="Escalation decision\\n(cloud off: logged only)", fillcolor="#FAECE7", color="#993C1D"];
q -> em -> rt; rt -> sql [label="record"]; rt -> rag [label="record"]; sql -> ans; rag -> ans;
rt -> gen [label="general"]; gen -> dec [label="low confidence"]; up -> ing -> rag; }}"""


def pct(values, q):
    values = sorted(v for v in values if v is not None)
    return None if not values else values[min(len(values) - 1, round(q * (len(values) - 1)))]


def page_system(threshold):
    st.header("Edge vs cloud")
    st.markdown(
        "1. **Emergency language** gets an instant safety prompt, before any model runs.\n"
        "2. **Record questions** (database and documents) are always answered on the device.\n"
        "3. **Uploads** are read and filed on the device; uncertain patient matches go to a person.\n"
        f"4. **General requests** are answered on the device. When the model is less than "
        f"**{threshold:.0%}** confident, the decision is *would escalate*. "
        + ("The cloud is on, so a request with no identifying details is sent."
           if CLOUD_ENABLED else "The cloud is off in this build, so the answer stays local "
                                 "and the caregiver is told to confirm with a clinician."))
    st.graphviz_chart(ARCH)

    ev = escalation.events()
    if not ev:
        st.info("No activity yet. Ask a few questions or upload a document.")
        return
    qs = [e for e in ev if e["kind"] == "question" and e["route"] != "emergency"]
    ups = [e for e in ev if e["kind"] == "upload"]
    cloud = [e for e in ev if e["decision"] == "cloud"]
    handled = len(qs) + len(ups)
    c = st.columns(6)
    c[0].metric("Handled on device", f"{(handled - len(cloud)) / max(handled, 1):.0%}",
                help=f"{handled - len(cloud)} of {handled} requests")
    c[1].metric("Would escalate", sum(e["decision"] == "would_escalate" for e in ev))
    c[2].metric("Cloud calls", len(cloud))
    c[3].metric("Safety interventions", sum(bool(e["guard_flags"]) for e in ev))
    c[4].metric("Emergencies flagged", sum(e["route"] == "emergency" for e in ev))
    sql_runs = [e for e in qs if e["sql_ok"] is not None]
    c[5].metric("SQL success", f"{sum(e['sql_ok'] for e in sql_runs)}/{len(sql_runs)}")
    if ups:
        st.caption(f"Uploads: {sum(e['decision'] == 'auto_attached' for e in ups)} matched "
                   f"automatically, {sum(e['decision'] == 'confirmed' for e in ups)} confirmed "
                   f"by a person, {sum(e['decision'] == 'facility' for e in ups)} facility documents.")

    st.subheader("Latency (ms)")
    rows = []
    for label, vals in (("Emergency prompt", [e["total_ms"] for e in ev if e["route"] == "emergency"]),
                        ("Router", [e["router_ms"] for e in qs]),
                        ("SQL (write + run)", [e["sql_ms"] for e in qs]),
                        ("Document search", [e["retrieval_ms"] for e in qs]),
                        ("Answer", [e["answer_ms"] for e in qs]),
                        ("Record question, total", [e["total_ms"] for e in qs if e["route"] == "record"]),
                        ("General request, total", [e["total_ms"] for e in qs if e["route"] == "general"]),
                        ("Upload, total", [e["total_ms"] for e in ups])):
        vals = [v for v in vals if v]
        if vals:
            rows.append({"Step": label, "Count": len(vals), "Median": round(pct(vals, .5), 1),
                         "p95": round(pct(vals, .95), 1)})
    st.dataframe(pd.DataFrame(rows), hide_index=True)

    st.subheader("Decision log")
    st.dataframe(pd.DataFrame([{
        "Time": e["ts"][11:19], "Kind": e["kind"], "Route": e["route"], "Sources": e["sources"],
        "Decision": e["decision"], "Why": e["reason"],
        "Confidence": None if e["confidence"] is None else round(e["confidence"], 2),
        "Safety": e["guard_flags"], "Total ms": None if e["total_ms"] is None else round(e["total_ms"]),
        "Resident": e["resident"], "Request": e["request"][:80]} for e in ev[:200]]),
        hide_index=True)
    if st.button("Clear the log"):
        escalation.clear()
        st.rerun()


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("CareEdge")
    st.caption(guardrails.DISCLAIMER)
    people = patient_db.residents()
    options = [None] + [r["id"] for r in people]
    names = {r["id"]: r for r in people}
    rid = st.selectbox("Resident", options,
                       format_func=lambda i: "All residents" if i is None else
                       f"{names[i]['name']}, room {names[i]['room']}")
    selected = names.get(rid)
    page = st.radio("Go to", PAGES)
    st.divider()
    threshold = ESCALATE_BELOW
    st.caption(f"General answers the on-device model is less than {threshold:.0%} confident about "
               "are flagged for a nurse to confirm. "
               + ("Only those may use the cloud, with no identifying details."
                  if CLOUD_ENABLED else "Nothing is ever sent to the cloud."))
    st.divider()
    status = server_status()
    for key, label, url in (("llm", f"{LLM_DISPLAY} (chat)", LLM_BASE),
                            ("embed", f"{EMBED_DISPLAY} (search)", EMBED_BASE)):
        ok, detail = status[key]
        (st.success if ok else st.error)(f"{label}: {'online' if ok else 'offline'}")
        st.caption(detail if ok else f"Not reachable at {url}")
    s = doc_store.stats()
    st.caption(f"{s['documents']} documents, {s['chunks']} sections, "
               f"{s['nodes']} graph nodes, {s['edges']} links")

if page == "Ask":
    page_ask(selected, threshold)
elif page == "Upload":
    page_upload()
elif page == "Patients":
    page_patients(selected)
else:
    page_system(threshold)
