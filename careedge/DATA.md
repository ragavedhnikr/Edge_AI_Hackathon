# Synthetic dataset

**Every name, date of birth, record and document in this repository is invented.** No real patient data is used. `make_dataset.py` generates everything, with dates relative to the day it runs, so "next appointment" and "last 7 days" always make sense.

```bash
python make_dataset.py   # also run by setup.sh
```

## Residents (`data/seed/residents.csv`)

| Resident | Room | Date of birth | Conditions | Allergies |
|---|---|---|---|---|
| Lakshmi Rao | 101 | 1948-03-14 | Type 2 diabetes, hypertension, orthostatic hypotension | None known |
| Joseph Mathew | 104 | 1942-07-02 | Right hip replacement (recovering), osteoporosis | Penicillin (rash) |
| Maria Gonzalez | 107 | 1945-11-20 | COPD, hypothyroidism | Shellfish (anaphylaxis, severe), sulfa drugs (hives) |
| Robert Chen | 110 | 1938-05-09 | Early-stage Alzheimer's disease, hypertension | Aspirin (stomach bleeding) |

## Structured records (`data/seed/*.csv`, loaded into `data/patient.db`)

| Table | Rows | Notes |
|---|---|---|
| `allergies` | 4 | Each allergy with its reaction, severity, what to avoid and the medication on file (for example Maria's epinephrine auto-injector) |
| `medications` | 16 | Includes one stopped entry: Lakshmi's amlodipine 10 mg, replaced by 5 mg at hospital discharge |
| `appointments` | 9 | One past, eight upcoming |
| `vitals` | 53 | 14 days of morning readings; Lakshmi has no readings during her 3 days in hospital, and her blood pressure drops after the dose change |

## Documents (`data/docs/`, loaded with `./run.sh ingest`)

All typed, one page, with headings in capitals and a "Patient" and "Date of birth" line so they can be filed automatically.

| File | Resident | Useful for questions like |
|---|---|---|
| `lakshmi_rao_discharge_summary.pdf` | Lakshmi | Why was she admitted? What changed? What should staff do? |
| `lakshmi_rao_cardiology_letter.pdf` | Lakshmi | What should she bring? Rescheduling rules |
| `joseph_mathew_postop_care_plan.pdf` | Joseph | Mobility rules, warning signs, physiotherapy |
| `joseph_mathew_physiotherapy_plan.pdf` | Joseph | Goals, what to do before a session |
| `maria_gonzalez_copd_care_plan.pdf` | Maria | Inhalers, when to get help, oxygen levels |
| `robert_chen_memory_care_plan.pdf` | Robert | Communication, sundowning, night safety |
| `policy_fall_response.pdf` | Facility | What to do after a fall; when to call 911 |
| `policy_medication_administration.pdf` | Facility | Missed doses, PRN medication, errors |
| `policy_allergic_reaction.pdf` | Facility | Warning signs of a reaction; when to call 911; what not to give |
| `shift_note_lakshmi_rao.txt` | Lakshmi | Dizziness overnight |
| `shift_note_robert_chen.txt` | Robert | Sundowning, refused melatonin, door alarm |
| `shift_note_maria_gonzalez.txt` | Maria | Inhaler use, oxygen levels |

## Demo uploads (`data/demo_uploads/`, not pre-loaded)

| File | What it shows |
|---|---|
| `maria_gonzalez_gp_review_letter.pdf` | Filed to Maria automatically (name and date of birth match), and flags a medication difference: levothyroxine 75 mcg in the letter vs 50 mcg in the record |
| `referral_note_r_chen.pdf` | Only "R. Chen" and no date of birth, so CareEdge suggests Robert Chen but asks the caregiver to confirm |

## Cross-source links built into the data

These let the demo show SQL and documents working together:

- Lakshmi's amlodipine dose change appears in the medications table and the discharge summary.
- Joseph is on apixaban (medications table), and the fall policy says to call 911 after a fall for anyone on a blood thinner.
- Two residents take medication at 22:00 (Lakshmi's atorvastatin and Robert's melatonin), and Robert's shift note says he refused his melatonin.
- The medication policy says never to double a missed dose, which is the right source for "she missed her metformin, should I give two?"
- Joseph is allergic to penicillin and started two medications 9 days ago; for "Joseph is having an allergic reaction", the safety prompt lists both, and the allergic reaction policy explains when to call 911.
