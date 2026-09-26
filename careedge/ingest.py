"""PDF / TXT ingestion: the "scanner" that adds uploaded documents to a
resident's record for retrieval.

  1. Extract text (PDF text layer; vision only for scanned pages, which needs a
     vision-capable chat model; Qwen2.5-7B-Instruct is text-only)
  2. Read metadata and tags with the chat model: title, type, patient name, DOB,
     medications, doctors, conditions
  3. Identify the patient against the residents table
       name + DOB match      -> attach automatically
       anything uncertain    -> the caregiver confirms
       facility policy       -> shared with everyone
  4. Split into sections, embed with Qwen3-Embedding, store vectors + graph links
  5. Compare the document's medications with the medications table and flag
     differences for a nurse to review (never changes the database)
"""
import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import doc_store
import models
import patient_db
from config import EMBED_MODEL, MIN_PAGE_CHARS, UPLOAD_DIR

VISION_PROMPT = ("Transcribe all the text on this page, top to bottom, exactly as written. "
                 "Plain text only. Keep line breaks. Write headings in capital letters.")

META_PROMPT = """Read this care-home document and reply with ONLY a JSON object:
{{
  "title": "<short title, e.g. Discharge summary>",
  "doc_type": "<discharge_summary | care_plan | clinic_letter | shift_note | policy | other>",
  "patient_name": "<the patient's full name as written, or empty if this is not about one patient>",
  "date_of_birth": "<YYYY-MM-DD, or empty>",
  "medications": [{{"name": "<drug>", "dose": "<current dose as written, e.g. 5 mg>"}}],
  "doctors": ["<doctor or clinician names>"],
  "conditions": ["<conditions or diagnoses named>"]
}}
Only list medications the patient is currently prescribed, with the dose after any change.
Do not list allergies as medications. Use empty lists when there are none.

Document:
{text}"""


@dataclass
class Analysis:
    file_path: str
    file_name: str
    file_hash: str
    pages: list                    # [(page_number, text)]
    text_method: str
    meta: dict
    suggested_id: int | None       # best-guess resident
    confidence: float              # 0..1 patient-match confidence
    scope: str                     # resident | facility
    reason: str                    # human-readable match explanation
    auto: bool                     # True = attach without asking
    ms: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 1. Text extraction
# ---------------------------------------------------------------------------

def extract_pages(path):
    """Return ([(page, text)], method)."""
    path = Path(path)
    if path.suffix.lower() == ".txt":
        return [(1, path.read_text(encoding="utf-8", errors="replace"))], "txt"
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    pages, method = [], "text"
    for i in range(len(pdf)):
        page = pdf[i]
        text = page.get_textpage().get_text_range().replace("\r\n", "\n").replace("\r", "\n")
        if len(text.strip()) < MIN_PAGE_CHARS:  # scanned page: needs a vision model
            png = models.pil_to_png(page.render(scale=2).to_pil())
            try:
                text = models.chat(models.image_message(png, VISION_PROMPT),
                                   max_tokens=2000, temperature=0).text
            except Exception as exc:  # noqa: BLE001
                pdf.close()
                raise ValueError(f"page {i + 1} is a scanned image with no text layer, and the "
                                 "current chat model can't read images. Upload a typed PDF "
                                 "or text file instead.") from exc
            method = "vision"
        pages.append((i + 1, text))
    pdf.close()
    return pages, method


def render_page_png(path, page_number, scale=1.5):
    """PNG bytes of one PDF page, for showing sources in the app."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    try:
        return models.pil_to_png(pdf[page_number - 1].render(scale=scale).to_pil())
    finally:
        pdf.close()


# ---------------------------------------------------------------------------
# 2-3. Metadata, tags and patient identification
# ---------------------------------------------------------------------------

def _norm(s):
    return re.sub(r"[^a-z ]", "", (s or "").lower()).split()


_DOB_FORMATS = ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d/%m/%Y",
                "%m/%d/%Y", "%d-%m-%Y")


def normalize_dob(value):
    value = (value or "").strip()
    for fmt in _DOB_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def regex_meta(text):
    """Fallback if the model's JSON can't be read."""
    name = re.search(r"(?:patient|resident)\s*(?:name)?\s*:\s*([A-Z][A-Za-z.\- ]+?)(?:\s{2,}|\n|$|date)",
                     text, re.I)
    dob = re.search(r"(?:date of birth|dob)\s*:\s*([0-9A-Za-z ,/\-]+?)(?:\s{2,}|\n|$|room)", text, re.I)
    policy = re.search(r"\bpolicy\b", text[:300], re.I)
    return {"title": text.strip().splitlines()[0][:80] if text.strip() else "Document",
            "doc_type": "policy" if policy and not name else "other",
            "patient_name": name.group(1).strip() if name else "",
            "date_of_birth": dob.group(1).strip() if dob else "",
            "medications": [], "doctors": [], "conditions": []}


def read_metadata(text):
    reply = models.chat([{"role": "user", "content": META_PROMPT.format(text=text[:6000])}],
                        max_tokens=700, temperature=0)
    try:
        meta = models.parse_json(reply.text)
    except (ValueError, json.JSONDecodeError):
        meta = regex_meta(text)
    fallback = regex_meta(text)
    for key in ("patient_name", "date_of_birth"):  # prefer what is literally printed
        if fallback[key] and not meta.get(key):
            meta[key] = fallback[key]
    meta.setdefault("title", "Document")
    meta.setdefault("doc_type", "other")
    for key in ("medications", "doctors", "conditions"):
        meta[key] = meta.get(key) or []
    return meta, reply.ms


def identify_patient(meta, residents):
    """Return (resident_id | None, confidence, scope, reason, auto)."""
    name, dob = meta.get("patient_name", ""), normalize_dob(meta.get("date_of_birth", ""))
    if not name:
        if meta.get("doc_type") == "policy":
            return None, 1.0, "facility", "facility policy, shared with all residents", True
        return None, 0.0, "resident", "no patient name found in the document", False

    words = set(_norm(name))
    full = [r for r in residents if set(_norm(r["name"])) <= words]
    partial = [r for r in residents if set(_norm(r["name"])) & words]
    if len(full) == 1:
        r = full[0]
        if dob and dob == r["date_of_birth"]:
            return r["id"], 1.0, "resident", f"name and date of birth match {r['name']}", True
        if dob:
            return r["id"], 0.3, "resident", (f"name matches {r['name']} but the date of birth "
                                              f"({dob}) does not"), False
        return r["id"], 0.7, "resident", f"name matches {r['name']}, no date of birth to confirm", False
    if len(partial) == 1:
        r = partial[0]
        return r["id"], 0.5, "resident", f"partial name '{name}' may be {r['name']}", False
    if len(partial) > 1:
        return None, 0.2, "resident", f"'{name}' could be more than one resident", False
    return None, 0.0, "resident", f"'{name}' is not a current resident", False


def analyze(path, original_name=None):
    """Steps 1-3. Nothing is stored yet."""
    path = Path(path)
    t0 = time.perf_counter()
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    pages, method = extract_pages(path)
    t1 = time.perf_counter()
    full_text = "\n".join(t for _, t in pages)
    meta, meta_ms = read_metadata(full_text)
    rid, conf, scope, reason, auto = identify_patient(meta, patient_db.residents())
    return Analysis(file_path=str(path), file_name=original_name or path.name,
                    file_hash=file_hash, pages=pages, text_method=method, meta=meta,
                    suggested_id=rid, confidence=conf, scope=scope, reason=reason, auto=auto,
                    ms={"extract": (t1 - t0) * 1000, "metadata": meta_ms})


# ---------------------------------------------------------------------------
# 4. Sections
# ---------------------------------------------------------------------------

def _is_heading(line):
    s = line.strip().rstrip(":")
    return 2 < len(s) <= 60 and any(c.isalpha() for c in s) and s.upper() == s


def split_sections(pages, max_words=180):
    """Split on ALL-CAPS headings; long sections are windowed."""
    out = []
    for page_no, text in pages:
        section, buf = "Overview", []

        def flush():
            words = " ".join(buf).split()
            i = 0
            while i < len(words):  # windows of max_words with a 30-word overlap
                out.append((page_no, section, " ".join(words[i:i + max_words])))
                if i + max_words >= len(words):
                    break
                i += max_words - 30

        for line in text.splitlines():
            if _is_heading(line):
                flush()
                section, buf = line.strip().rstrip(":").title(), []
            elif line.strip():
                buf.append(line.strip())
        flush()
    return out


# ---------------------------------------------------------------------------
# 5. Medication reconciliation (advisory only)
# ---------------------------------------------------------------------------

_DOSE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|iu|units?)\b", re.I)


def _dose_key(text):
    m = _DOSE.search(text or "")
    return (float(m.group(1)), m.group(2).lower().rstrip("s")) if m else None


def _drug_key(name):
    words = _norm(name)
    return words[0] if words else ""


def reconcile(doc_meds, resident_id):
    """Flags where the document and the medications table disagree."""
    active = patient_db.active_meds(resident_id)
    by_drug = {}
    for m in active:
        by_drug.setdefault(_drug_key(m["drug"]), []).append(m)
    doc_by_drug = {}
    for m in doc_meds:
        if isinstance(m, dict) and m.get("name"):
            doc_by_drug.setdefault(_drug_key(m["name"]), []).append(m)

    flags = []
    for drug, mentions in doc_by_drug.items():
        if not drug:
            continue
        records = by_drug.get(drug)
        label = mentions[0]["name"]
        if not records:
            flags.append({"drug": label, "document": mentions[0].get("dose", ""),
                          "record": "not in current medication list"})
            continue
        doc_doses = {_dose_key(m.get("dose")) for m in mentions} - {None}
        rec_doses = {_dose_key(r["dose"]) for r in records} - {None}
        if doc_doses and rec_doses and not doc_doses & rec_doses:
            flags.append({"drug": label,
                          "document": ", ".join(m.get("dose", "") for m in mentions),
                          "record": ", ".join(r["dose"] for r in records)})
    return flags


# ---------------------------------------------------------------------------
# Commit: store the analysed document
# ---------------------------------------------------------------------------

def commit(analysis, resident_id=None, scope=None, match_method=None, copy_file=True):
    """Store the document for the given resident (or facility). Returns
    (doc_id, flags, ms)."""
    scope = scope or analysis.scope
    resident_id = None if scope == "facility" else resident_id
    t0 = time.perf_counter()
    stored = Path(analysis.file_path)
    if copy_file:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        stored = UPLOAD_DIR / f"{analysis.file_hash[:12]}_{analysis.file_name}"
        if Path(analysis.file_path).resolve() != stored.resolve():
            shutil.copyfile(analysis.file_path, stored)

    meta = analysis.meta
    person = patient_db.resident(resident_id) if resident_id else None
    owner = person["name"] if person else "Facility policy"
    sections = split_sections(analysis.pages)
    texts = [f"{meta['title']} | {owner} | {sec}\n{body}" for _, sec, body in sections]
    vectors = models.embed(texts) if texts else []
    t_embed = time.perf_counter()

    flags = reconcile(meta.get("medications", []), resident_id) if resident_id else []
    entities = {
        "medication": [m["name"] for m in meta.get("medications", []) if isinstance(m, dict)
                       and m.get("name")],
        "doctor": [d for d in meta.get("doctors", []) if isinstance(d, str)],
        "condition": [c for c in meta.get("conditions", []) if isinstance(c, str)],
    }
    doc_id = doc_store.add_document(
        {"file_path": str(stored), "file_name": analysis.file_name,
         "file_hash": analysis.file_hash, "title": meta["title"],
         "doc_type": meta.get("doc_type", "other"), "resident_id": resident_id, "scope": scope,
         "pages": len(analysis.pages), "text_method": analysis.text_method,
         "match_method": match_method or ("facility" if scope == "facility" else
                                          "auto" if analysis.auto else "confirmed"),
         "match_note": analysis.reason, "flags": json.dumps(flags), "embed_model": EMBED_MODEL},
        [(p, s, t) for (p, s, _), t in zip(sections, texts)], vectors, entities,
        patient_label=owner)
    ms = dict(analysis.ms, embed=(t_embed - t0) * 1000,
              store=(time.perf_counter() - t_embed) * 1000)
    return doc_id, flags, ms


def ingest_folder(folder):
    """Add every PDF/TXT in a folder. Uncertain matches are skipped and reported."""
    doc_store.init()
    report = []
    for path in sorted(Path(folder).glob("*")):
        if path.suffix.lower() not in (".pdf", ".txt"):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if doc_store.has_hash(digest):
            report.append((path.name, "already added"))
            continue
        a = analyze(path)
        if not a.auto:
            report.append((path.name, f"needs confirmation: {a.reason}"))
            continue
        doc_id, flags, _ = commit(a, a.suggested_id)
        who = patient_db.resident(a.suggested_id)["name"] if a.suggested_id else "facility"
        report.append((path.name, f"added as DOC-{doc_id} for {who}"
                                  + (f", {len(flags)} medication flag(s)" if flags else "")))
    return report


if __name__ == "__main__":
    import sys
    from config import DOCS_DIR
    for name, result in ingest_folder(sys.argv[1] if len(sys.argv) > 1 else DOCS_DIR):
        print(f"  {name}: {result}")
