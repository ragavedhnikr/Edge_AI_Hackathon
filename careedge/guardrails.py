"""Safety layers that do not depend on the model behaving well.

1. The assistant rules (prompts/assistant_rules.md) go into every prompt.
2. Emergency language is caught by a pattern check before any model runs.
3. Every answer is checked after it is generated. Sentences that give dosing
   or diagnostic advice are removed and replaced with a referral to a clinician.
"""
import re
from functools import lru_cache

from config import RULES_FILE

DISCLAIMER = ("CareEdge is an information assistant, not a clinician. It does not diagnose "
              "or advise on treatment. Clinical decisions belong to the nurse on duty, the "
              "resident's doctor or the pharmacist.")

REFERRAL = ("Please check with the nurse on duty, the resident's doctor or the pharmacist "
            "before giving, skipping or changing any medication.")


@lru_cache(maxsize=1)
def rules():
    """The assistant rules, loaded once. They open every system prompt."""
    return RULES_FILE.read_text(encoding="utf-8").strip()


def system_prompt(task):
    """Rules first, then the task-specific instructions."""
    return f"{rules()}\n\n## Your task now\n\n{task.strip()}"


# ---------------------------------------------------------------------------
# Emergencies: deterministic, microseconds, no model needed
# ---------------------------------------------------------------------------

EMERGENCY_RE = re.compile(
    r"chest (pain|tightness|pressure)"
    r"|not breathing|stopped breathing|trouble breathing|can'?t breathe|cannot breathe"
    r"|short(ness)? of breath at rest|struggling to breathe|gasping|lips? (are |is )?(blue|grey|gray)"
    r"|unconscious|unresponsive|won'?t wake|passed out|fainted|collapsed"
    r"|stroke|face (is )?droop|slurred speech"
    r"|seizure|convuls|choking"
    r"|\bfell\b|has fallen|hit (her|his|their) head"
    r"|overdose|took too many|swallowed (too many|the whole)"
    r"|(heavy|severe) bleeding|bleeding (a lot|heavily|won'?t stop)"
    r"|suicid|kill (her|him|my|them)sel(f|ves)|wants? to die"
    # allergic reactions
    r"|allergic reaction|anaphyla|having an? (bad |severe |serious |allergic )?reaction"
    r"|(face|lips?|tongue|throat|mouth|eyes?) (is |are )?(swelling|swollen|puffing up|puffy)"
    r"|swelling (of|in) (the |her |his |their )?(face|lips?|tongue|throat|mouth)"
    r"|throat (is |feels )?(closing|tight)|can'?t swallow|hives (all over|everywhere)|epi-?pen",
    re.I,
)

ALLERGY_RE = re.compile(
    r"allerg|anaphyla|reaction|swell|swollen|puff|throat|swallow|hives|epi-?pen", re.I)


def emergency_match(text):
    m = EMERGENCY_RE.search(text or "")
    return m.group(0) if m else None


def emergency_banner(resident=None, meds=None, recent=None, allergy=False, allergy_rows=None):
    """The instant safety prompt, built only from the records (no model).
    For a possible allergic reaction: stop the exposure if safe, then every
    allergy on record with what to avoid and the medication on file for it."""
    if not allergy:
        lines = ["**If this is happening now: call emergency services (911) and alert the nurse "
                 "on duty.** Stay with the resident and follow the dispatcher's instructions."]
        if resident and meds:
            first = resident["name"].split()[0]
            lines.append(f"\nFor the responders, {first}'s current medications:")
            lines += [f"- {m}" for m in meds]
        if resident and resident.get("allergies") and resident["allergies"].lower() != "none known":
            lines.append(f"\nAllergies: {resident['allergies']}")
        return "\n".join(lines)

    first = resident["name"].split()[0] if resident else "the resident"
    lines = ["**Possible allergic reaction: alert the nurse on duty now. Call 911 if there is "
             "swelling of the face, lips, tongue or throat, trouble breathing or swallowing, "
             "or fainting.**",
             f"\n**If it is safe to do so, stop the exposure:** stop the food, medication or "
             f"product that may have caused it and move it away from {first}. Don't give food, "
             "drink or medication unless the nurse or the dispatcher says so."]
    if not resident:
        lines.append("\nSelect the resident in the sidebar, or name them, to see their allergies "
                     "and medications.")
        return "\n".join(lines)
    if allergy_rows:
        lines.append(f"\n**{first}'s allergies on record:**")
        for a in allergy_rows:
            lines.append(f"\n**{a['allergen']}** ({(a['severity'] or 'severity not recorded').lower()}): "
                         f"{a['reaction'] or 'reaction not recorded'}")
            if a.get("avoid"):
                lines.append(f"- Avoid: {a['avoid']}")
            lines.append(f"- Medication on file: {a.get('emergency_medication') or 'none on file'}")
    else:
        lines.append(f"\n**No allergies on record for {first}.** Tell the nurse and the "
                     "responders what they recently ate or took.")
    if recent:
        lines.append("\nStarted in the last 14 days (a possible cause, tell the responders):")
        lines += [f"- {m}" for m in recent]
    if meds:
        lines.append(f"\nAll of {first}'s current medications:")
        lines += [f"- {m}" for m in meds]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output check: remove dosing and diagnostic advice
# ---------------------------------------------------------------------------

_DIRECTIVE = (r"\b(you should|you can|you could|you may|go ahead and|i recommend|i'?d recommend"
              r"|i suggest|i advise|it'?s (fine|ok|okay|safe) to|it is (fine|ok|okay|safe) to"
              r"|feel free to|make sure (you|to))\b")
_ACTION = r"\b(give|administer|increase|decrease|double|skip|stop|hold|start|reduce|take|add|restart|crush)\b"
_MED = r"\b(dose|doses|dosage|mg|mcg|tablet|tablets|pill|pills|medication|medicine|insulin|inhaler|puffs?)\b"

_GAP = r"(?:[^.!?\n]|\.(?=\d))"  # any text in the same sentence, allowing "2.5"
DOSING_RE = re.compile(rf"{_DIRECTIVE}{_GAP}{{0,80}}{_ACTION}{_GAP}{{0,60}}{_MED}", re.I)
EXTRA_DOSE_RE = re.compile(
    r"\b(give|administer)\s+(her|him|them|the resident)\s+(an?\s+)?(extra|another|additional|second)\b",
    re.I)
DIAGNOSIS_RE = re.compile(
    r"\b(she|he|they|the resident)\s+(has|probably has|likely has|most likely has|may have|might have"
    r"|is having|is probably having)\s+(an?\s+)?(stroke|heart attack|infection|sepsis|pneumonia"
    r"|fracture|broken|uti|urinary tract infection|dementia|delirium|dvt|blood clot|embolism)",
    re.I)

# Split after ! ? or a newline, or after a full stop that ends a sentence
# (not the "." inside "2.5 mg"). Each piece keeps its punctuation and newline.
_SPLIT = re.compile(r"(?<=[!?\n])|(?<=\.)(?=\s|$)")


def check_output(text):
    """Return (safe_text, flags). Offending sentences are replaced, and a
    referral is appended if anything was removed."""
    flags = []
    out = []
    for sentence in _SPLIT.split(text or ""):
        if not sentence:
            continue
        if DOSING_RE.search(sentence) or EXTRA_DOSE_RE.search(sentence):
            flags.append("dosing advice removed")
            out.append(" [Removed: CareEdge doesn't give dosing advice.]"
                       + ("\n" if sentence.endswith("\n") else ""))
        elif DIAGNOSIS_RE.search(sentence):
            flags.append("diagnosis removed")
            out.append(" [Removed: CareEdge doesn't diagnose.]"
                       + ("\n" if sentence.endswith("\n") else ""))
        else:
            out.append(sentence)
    safe = "".join(out).strip()
    if flags and REFERRAL not in safe:
        safe += f"\n\n{REFERRAL}"
    return safe, sorted(set(flags))
