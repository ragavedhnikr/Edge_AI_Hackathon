# Demo guide

## Before you start

- Both models running (`./serve_models.sh llm`, then `./serve_models.sh embed`; both **Ready** in `zrt status`), `./run.sh test` passes
- Sample documents loaded (`./run.sh ingest`), demo uploads **not** loaded yet
- App open at `http://localhost:8501` (or the Nano's Tailscale IP), sidebar resident set to **All residents**
- Edge vs cloud log cleared (button at the bottom of that page)
- Record a backup video of a full run in case the live demo isn't possible

## 5-minute demo

| Time | Step | Say |
|---|---|---|
| 0:00 | Title | A night-shift caregiver, a stack of paperwork, no nurse on site, and records that can't go to the cloud |
| 0:30 | **Ask:** "Which residents get medication at 22:00?" | The on-device model looked this up in the patient records with a read-only query |
| 1:10 | **Ask:** "Why was Lakshmi admitted to hospital?" | The answer comes from her discharge summary, and says so |
| 1:50 | **Ask:** "Maria is having an allergic reaction" | Instant safety prompt: stop the exposure if safe, then each of her allergies (shellfish, severe; sulfa drugs) with what to avoid and the medication on file, including the epinephrine auto-injector |
| 2:30 | **Ask:** "Lakshmi missed her morning metformin. Should I give her two tonight?" | It won't give dosing advice: it quotes the policy (never double a dose) and refers to the nurse |
| 3:00 | **Upload** `maria_gonzalez_gp_review_letter.pdf` | Filed to Maria automatically, and it flags the levothyroxine dose difference for the nurse |
| 3:40 | **Upload** `referral_note_r_chen.pdf` | Only "R. Chen", no date of birth, so it asks a person to confirm |
| 4:10 | **Patients** page, Maria | Her record and the graph of documents, medications and doctors |
| 4:30 | **Edge vs cloud** page | 100% on device, 0 cloud calls, escalation decisions, latency per step |

## 2-minute video (YouTube)

1. 0:00 to 0:15: the user and the problem
2. 0:15 to 1:15: one database question, one document question, the allergic reaction emergency, the upload with a medication flag
3. 1:15 to 1:45: Edge vs cloud page and the benchmark headline numbers
4. 1:45 to 2:00: "Everything you saw ran on this box. No patient data left it."

## Three pitch visuals (from the handout)

1. **Architecture:** the flow diagrams in ARCHITECTURE.md, or the Edge vs cloud page
2. **Benchmarks:** the headline table in `benchmarks/RESULTS.md`
3. **Impact:** time to answer a question from paperwork (seconds instead of minutes of searching), zero records leaving the building, and dangerous errors caught (wrong-patient filing, dose differences, unsafe dosing questions)

## More questions to try

| Question | Shows |
|---|---|
| What medications is Lakshmi taking? | SQL; the answer reflects the 5 mg dose after discharge |
| What was Lakshmi's average blood pressure over the last 7 days? | SQL calculation over vitals |
| Is Robert allergic to anything? | SQL, allergy lookup |
| What happened with Robert on the evening shift? | Search over a shift note |
| What should staff do if Maria's oxygen saturation drops below 88 percent? | Search over a care plan |
| Summarize Lakshmi's situation this week. | SQL and documents together |
| What is COPD, in simple words? | General request with a confidence score |
| Robert is confused and has a fever. What does he have? | Refuses to diagnose, refers to the nurse |
| Joseph is having an allergic reaction and his lips are swelling | Emergency prompt with his penicillin allergy and recently started medications first, then the allergic reaction policy |
