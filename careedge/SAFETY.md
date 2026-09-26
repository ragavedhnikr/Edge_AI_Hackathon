# CareEdge safety case

CareEdge works in a setting where mistakes can hurt people. This document sets out what CareEdge is for, what it must never do, where a person always decides, and how each safety rule is enforced in the code. The model's actual instructions are in [prompts/assistant_rules.md](prompts/assistant_rules.md); they are loaded into every prompt, so this document and the model's behavior cannot drift apart.

## 1. Intended use

CareEdge is an **information assistant** for trained caregivers in a residential care home. It helps them:

- find what is written in a resident's records (medications, appointments, vitals, allergies) and documents (discharge summaries, care plans, clinic letters, shift notes)
- find what the facility's policies say
- summarize a resident's records and documents
- understand general health terms in plain language
- file uploaded documents to the right resident's record

**Intended users:** trained care staff working under the supervision of a nurse. Not residents, not family members, not the public.

## 2. What CareEdge is not

CareEdge is **not a doctor, nurse, pharmacist or other clinician**, and it is **not a medical device**. It must never:

- diagnose, or suggest what a resident "has" or "probably has"
- recommend starting, stopping, skipping, doubling, increasing, decreasing or re-timing any medication
- tell a caregiver whether to give a medication, including an extra, missed or as-needed dose
- recommend a treatment, procedure or change to a care plan
- guess a dose, allergy, date or instruction that is not in the records
- resolve a disagreement between records by choosing one
- change any record on its own

Clinical decisions belong to the nurse on duty, the resident's doctor or the pharmacist.

## 3. Required behavior

| Behavior | Why |
|---|---|
| Answer questions about residents only from the records and documents retrieved for that question | Prevents invented facts |
| Cite the source of every fact (database table, or document and section) | Lets the caregiver check the answer |
| Say "I don't see that in the records" when the answer isn't there | A confident wrong answer is worse than no answer |
| Point out disagreements between records, cite both, and ask the nurse to confirm | Dose changes are a common source of error |
| Refer anything needing a clinical decision to the nurse, doctor or pharmacist, quoting the relevant policy where there is one | Keeps decisions with qualified people |
| Label general health information as general, with a reminder to check anything specific | Separates education from instructions |

## 4. Emergencies

When a message contains emergency language (a fall, chest pain, trouble breathing, unresponsiveness, stroke signs, choking, severe bleeding, a seizure, blue lips, an allergic reaction or swelling of the face, lips or throat, or thoughts of self-harm):

1. A pattern check in `guardrails.py` catches it **before any model runs**, in well under a millisecond.
2. The app shows: call emergency services (911) and alert the nurse on duty.
3. If the resident is known, it lists their current medications and allergies for the responders.
   For a possible allergic reaction it also says to stop the exposure if it is safe to do so, and lists each allergy on record with its reaction, severity, what to avoid and the medication on file for it, plus any medication started in the last 14 days. All of this comes from the records, not from the model.
4. It never gives treatment instructions. The answer that follows may quote the facility's fall or emergency policy.

The check deliberately errs toward flagging: an unnecessary prompt costs a second, a missed emergency could cost a life.

## 5. Where a person always decides

| Situation | What CareEdge does | Who decides |
|---|---|---|
| An upload's patient match is uncertain (partial name, missing or mismatched date of birth) | Asks the caregiver to choose the resident; never guesses | Caregiver |
| A document's medication differs from the medication record | Flags the difference; never changes the record | Nurse |
| A question needs a clinical judgement | Says so and refers it, quoting policy | Nurse, doctor or pharmacist |
| A general answer has low confidence | Adds a note to confirm with a clinician | Nurse or pharmacist |

## 6. How each rule is enforced

Safety does not rely on the model behaving well. There are four independent layers:

| Layer | Where | What it does |
|---|---|---|
| Rules in every prompt | `prompts/assistant_rules.md`, `guardrails.system_prompt()` | Tells the model its role and limits |
| Emergency check | `guardrails.emergency_match()` | Deterministic, runs before any model |
| Output check | `guardrails.check_output()` | Removes sentences giving dosing advice ("you should give her an extra...") or diagnoses ("she probably has an infection"), replaces them with a note, and adds a referral to a clinician. Every intervention is logged |
| Read-only data access | `patient_db.run_readonly()` | Model-written SQL runs on a read-only connection with an authorizer that only allows reading the five care tables; only single SELECT statements are accepted |

## 7. Data handling

- All models run on the ZGX Nano. Records, documents and questions never leave it.
- This build makes **no cloud calls** (`CAREEDGE_CLOUD_ENABLED=0`). The escalation decision is still made and logged; see [ESCALATION_POLICY.md](ESCALATION_POLICY.md).
- All data in this repository is **synthetic**: every name, date of birth and record is invented (see [DATA.md](DATA.md)). No real patient information may be added to the repository or used in the demo.
- Streamlit usage statistics are switched off.

## 8. Failure modes and mitigations

| Failure | Consequence | Mitigation | Measured by |
|---|---|---|---|
| Document filed to the wrong resident | Wrong information in someone's record | Automatic filing only on an exact name **and** date-of-birth match; anything else goes to a person | Patient-matching accuracy in the benchmark |
| Wrong or unsafe SQL | Wrong facts; data changed | Read-only connection, table allow-list, SELECT only; the query and results are shown to the caregiver | SQL success rate |
| Search misses the right passage | Incomplete answer | Search restricted to the resident's documents plus policies; hybrid vector and keyword scoring; "not in the records" when nothing matches | Retrieval hit@1 / hit@k |
| Model gives dosing advice or a diagnosis | Unsafe action by staff | Rules in the prompt, plus the output check | Safety cases in the benchmark |
| Model is confidently wrong | Misleading answer | Citations shown with every answer; confidence scoring on general answers | Answer accuracy |
| Emergency missed | Delay in care | Deterministic check, tuned toward over-flagging | Emergency recall and false alarms |
| Records disagree | Old dose followed | Both shown with sources; flagged for the nurse | Medication flags |

## 9. Limitations and status

- A hackathon prototype, tested only on synthetic data.
- **Not clinically validated, not approved or cleared by any regulator, and not certified for handling real patient data** (for example under HIPAA).
- The output check uses patterns. It catches common phrasings of dosing advice and diagnoses, not every possible one.
- Confidence scores are a proxy for correctness, not a guarantee.
- The emergency check matches keywords and can miss unusual phrasings.
- A real deployment would need clinical review of the rules, user accounts and audit trails, encryption at rest, and evaluation on real (properly governed) records.
