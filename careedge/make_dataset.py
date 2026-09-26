"""Generate the synthetic CareEdge dataset. Every name, date and record here is
invented. Dates are relative to the day you run this, so "next appointment"
and "this week" questions always make sense.

    python make_dataset.py

Writes:
  data/seed/residents.csv, medications.csv, appointments.csv, vitals.csv
  data/docs/*.pdf, *.txt         pre-loaded documents (typed, one page each)
  data/demo_uploads/*.pdf        two files kept back for the live upload demo
"""
import csv
import random
from datetime import date, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from config import DEMO_DIR, DOCS_DIR, SEED_DIR

TODAY = date.today()


def d(days):
    return (TODAY + timedelta(days=days)).isoformat()


def nice(days):
    return (TODAY + timedelta(days=days)).strftime("%d %B %Y")


# ---------------------------------------------------------------------------
# Structured data
# ---------------------------------------------------------------------------

RESIDENTS = [
    dict(id=1, name="Lakshmi Rao", date_of_birth="1948-03-14", room="101",
         conditions="Type 2 diabetes; Hypertension; Orthostatic hypotension",
         allergies="None known", primary_doctor="Dr. Anita Menon"),
    dict(id=2, name="Joseph Mathew", date_of_birth="1942-07-02", room="104",
         conditions="Right hip replacement (recovering); Osteoporosis",
         allergies="Penicillin (rash)", primary_doctor="Dr. Kevin Brooks"),
    dict(id=3, name="Maria Gonzalez", date_of_birth="1945-11-20", room="107",
         conditions="COPD; Hypothyroidism",
         allergies="Shellfish (anaphylaxis); Sulfa drugs (hives)",
         primary_doctor="Dr. Kevin Brooks"),
    dict(id=4, name="Robert Chen", date_of_birth="1938-05-09", room="110",
         conditions="Early-stage Alzheimer's disease; Hypertension",
         allergies="Aspirin (stomach bleeding)", primary_doctor="Dr. Omar Siddiqui"),
]
for r in RESIDENTS:
    b = date.fromisoformat(r["date_of_birth"])
    r["age"] = TODAY.year - b.year - ((TODAY.month, TODAY.day) < (b.month, b.day))

M = "drug dose route times purpose status start_date end_date prescriber notes".split()
MEDICATIONS = [
    (1, "Metformin", "500 mg", "oral", "08:00, 20:00", "Diabetes", "active", d(-400), "", "Dr. Anita Menon", "With meals"),
    (1, "Amlodipine", "10 mg", "oral", "08:00", "Blood pressure", "stopped", d(-300), d(-3), "Dr. Anita Menon", "Reduced at hospital discharge"),
    (1, "Amlodipine", "5 mg", "oral", "08:00", "Blood pressure", "active", d(-3), "", "Dr. Priya Nair", "New dose after discharge"),
    (1, "Atorvastatin", "10 mg", "oral", "22:00", "Cholesterol", "active", d(-500), "", "Dr. Anita Menon", ""),
    (2, "Apixaban", "2.5 mg", "oral", "08:00, 20:00", "Prevent blood clots after surgery", "active", d(-9), d(21), "Dr. Sarah Thomas", "30 days after hip surgery"),
    (2, "Paracetamol", "500 mg", "oral", "As needed", "Pain", "active", d(-9), "", "Dr. Sarah Thomas", "2 tablets up to 3 times a day; nurse approval needed"),
    (2, "Calcium + Vitamin D3", "500 mg", "oral", "13:00", "Bone health", "active", d(-200), "", "Dr. Kevin Brooks", "After lunch"),
    (2, "Cetirizine", "10 mg", "oral", "As needed", "Allergic rash or itching (penicillin allergy)", "active", d(-200), "", "Dr. Kevin Brooks", "Nurse approval needed"),
    (3, "Tiotropium", "18 mcg", "inhaled", "08:00", "COPD maintenance", "active", d(-600), "", "Dr. Lena Park", ""),
    (3, "Salbutamol", "100 mcg", "inhaled", "As needed", "Breathlessness", "active", d(-600), "", "Dr. Lena Park", "Up to 2 puffs; tell the nurse if used more than twice a day"),
    (3, "Levothyroxine", "50 mcg", "oral", "06:30", "Thyroid", "active", d(-700), "", "Dr. Kevin Brooks", "30 minutes before breakfast"),
    (3, "Epinephrine auto-injector", "0.3 mg", "injection", "Emergency only", "Severe allergic reaction (shellfish)", "active", d(-300), "", "Dr. Kevin Brooks", "Kept at nurse station; nurse or trained staff per care plan; call 911"),
    (3, "Cetirizine", "10 mg", "oral", "As needed", "Hives (sulfa allergy)", "active", d(-300), "", "Dr. Kevin Brooks", "Nurse approval needed"),
    (4, "Donepezil", "5 mg", "oral", "21:00", "Memory (Alzheimer's)", "active", d(-150), "", "Dr. Omar Siddiqui", ""),
    (4, "Lisinopril", "10 mg", "oral", "08:00", "Blood pressure", "active", d(-800), "", "Dr. Omar Siddiqui", ""),
    (4, "Melatonin", "2 mg", "oral", "22:00", "Sleep", "active", d(-60), "", "Dr. Omar Siddiqui", ""),
]

# Allergies: what happens, what to avoid, and the medication on file for each
AL = "allergen reaction severity avoid emergency_medication notes".split()
ALLERGIES = [
    (2, "Penicillin", "Skin rash", "Moderate",
     "Penicillin-family antibiotics such as amoxicillin and ampicillin",
     "Cetirizine 10 mg tablet, as needed for rash or itching, only with nurse approval",
     "Recorded by Dr. Kevin Brooks"),
    (3, "Shellfish", "Throat swelling and trouble breathing (anaphylaxis)", "Severe",
     "Shrimp, crab, lobster and any dish made with them",
     "Epinephrine auto-injector 0.3 mg, kept at the nurse station, given by the nurse or trained "
     "staff as set out in her care plan; call 911 when it is used",
     "Kitchen informed"),
    (3, "Sulfa drugs", "Hives", "Moderate",
     "Sulfonamide antibiotics such as sulfamethoxazole (Bactrim)",
     "Cetirizine 10 mg tablet, as needed for hives, only with nurse approval", ""),
    (4, "Aspirin", "Stomach bleeding", "Severe",
     "Aspirin, and other anti-inflammatory pain relievers such as ibuprofen and naproxen "
     "unless his doctor says otherwise",
     "None on file", ""),
]

A = "date time type provider location notes".split()
APPOINTMENTS = [
    (1, d(-12), "10:00", "GP review", "Dr. Anita Menon", "Sunrise Family Clinic", "Completed"),
    (1, d(5), "10:00", "GP review after discharge", "Dr. Anita Menon", "Sunrise Family Clinic", "Recheck blood pressure sitting and standing"),
    (1, d(9), "10:30", "Cardiology follow-up", "Dr. Rahul Mehta", "City Heart Clinic, Room 214", "Bring medication list, ECG reports, BP log"),
    (2, d(1), "11:00", "Physiotherapy (home)", "Arun Kumar", "Room 104", "Every Monday, Wednesday and Friday"),
    (2, d(12), "14:15", "Orthopaedic review", "Dr. Sarah Thomas", "Greenfield Orthopaedic Centre, Clinic B", "Wound check and X-ray"),
    (3, d(3), "07:30", "Thyroid blood test", "Lab technician", "On site", "Before breakfast and before levothyroxine"),
    (3, d(6), "09:30", "Pulmonology review", "Dr. Lena Park", "Bayview Lung Clinic", "Bring inhaler use log"),
    (4, d(14), "11:00", "Memory clinic", "Dr. Omar Siddiqui", "Northside Memory Clinic", "Daughter Mei Chen to attend"),
    (4, d(20), "15:00", "Dental check-up", "Dr. Helen Ward", "Smile Dental", ""),
]


def vitals():
    rng = random.Random(42)
    rows = []
    for day in range(-13, 1):
        for rid in (1, 2, 3, 4):
            if rid == 1 and -5 <= day <= -3:
                continue  # in hospital
            if rid == 1:
                sys_, dia = (rng.randint(142, 152), rng.randint(84, 90)) if day < -5 else \
                    (rng.randint(122, 132), rng.randint(72, 80))
                glucose = rng.randint(118, 148)
                notes = "Dizzy on standing" if day == -6 else ""
            elif rid == 2:
                sys_, dia, glucose, notes = rng.randint(126, 136), rng.randint(76, 84), None, ""
            elif rid == 3:
                sys_, dia, glucose, notes = rng.randint(118, 128), rng.randint(70, 78), None, ""
            else:
                sys_, dia, glucose, notes = rng.randint(136, 146), rng.randint(82, 90), None, ""
            spo2 = rng.randint(90, 93) if rid == 3 else rng.randint(95, 99)
            rows.append((rid, d(day), "07:30", sys_, dia, rng.randint(64, 84), spo2, glucose, notes))
    return rows


def write_csvs():
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    cols = ["id", "name", "date_of_birth", "age", "room", "conditions", "allergies", "primary_doctor"]
    with open(SEED_DIR / "residents.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(RESIDENTS)
    for name, header, rows in (
            ("allergies", ["id", "resident_id"] + AL, ALLERGIES),
            ("medications", ["id", "resident_id"] + M, MEDICATIONS),
            ("appointments", ["id", "resident_id"] + A, APPOINTMENTS),
            ("vitals", ["id", "resident_id", "date", "time", "systolic", "diastolic", "pulse",
                        "spo2", "glucose", "notes"], vitals())):
        with open(SEED_DIR / f"{name}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            for i, row in enumerate(rows, start=1):
                w.writerow([i, *("" if v is None else v for v in row)])


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

styles = getSampleStyleSheet()
ORG = ParagraphStyle("org", parent=styles["Title"], fontSize=16, alignment=0, spaceAfter=2)
SUB = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9.5, textColor=colors.HexColor("#555555"))
H = ParagraphStyle("h", parent=styles["Heading3"], fontSize=11, spaceBefore=10, spaceAfter=3)
BODY = ParagraphStyle("b", parent=styles["Normal"], fontSize=10.5, leading=14)
FOOT = ParagraphStyle("f", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#888888"))


def pdf(path, org, subtitle, header_lines, sections, signed=None):
    """header_lines: plain 'Label: value' lines. sections: [(HEADING, [lines])].
    Headings are written in capitals so the ingester can split on them."""
    story = [Paragraph(org, ORG), Paragraph(subtitle, SUB), Spacer(1, 10)]
    story += [Paragraph(line, BODY) for line in header_lines]
    for heading, lines in sections:
        story.append(Paragraph(heading.upper(), H))
        story += [Paragraph(line, BODY) for line in lines]
    if signed:
        story += [Spacer(1, 16), Paragraph(f"Signed: {signed}", BODY)]
    story += [Spacer(1, 20), Paragraph("Synthetic document for demonstration. Not real patient data.", FOOT)]
    SimpleDocTemplate(str(path), pagesize=letter, leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                      topMargin=0.8 * inch, bottomMargin=0.8 * inch,
                      title=org).build(story)


def patient(r, extra=""):
    b = date.fromisoformat(r["date_of_birth"]).strftime("%d %B %Y")
    return [f"Patient: {r['name']}", f"Date of birth: {b}", f"Room: {r['room']}" + extra]


def write_docs():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    L, J, Mg, R = RESIDENTS

    pdf(DOCS_DIR / "lakshmi_rao_discharge_summary.pdf", "St. Mary's Hospital",
        "Department of Internal Medicine | Discharge Summary",
        patient(L) + [f"Admitted: {nice(-5)}", f"Discharged: {nice(-3)}"],
        [("Reason for admission", [
            "Dizziness and light-headedness when standing up, with one near-fall at home. "
            "Diagnosed with orthostatic hypotension (a drop in blood pressure on standing)."]),
         ("Hospital course", [
             "Blood pressure dropped by 22 points on standing. Fluids given. No fracture or head "
             "injury. Blood sugar well controlled."]),
         ("Medication changes", [
             "Amlodipine reduced from 10 mg to 5 mg, once daily at 08:00.",
             "All other medications unchanged: metformin 500 mg twice daily, atorvastatin 10 mg at night."]),
         ("Instructions for care staff", [
             "1. Sit on the edge of the bed for one minute before standing up.",
             "2. Encourage 1.5 to 2 litres of fluid a day unless the doctor says otherwise.",
             "3. Check blood pressure sitting and standing once a day and record both.",
             "4. Tell the nurse on duty if she feels dizzy, and call 911 if she faints or falls."]),
         ("Follow-up", [f"GP review with Dr. Anita Menon on {nice(5)}.",
                        f"Cardiology follow-up with Dr. Rahul Mehta on {nice(9)}."])],
        signed="Dr. Priya Nair, Consultant Physician")

    pdf(DOCS_DIR / "lakshmi_rao_cardiology_letter.pdf", "City Heart Clinic",
        "Department of Cardiology | Appointment Letter",
        patient(L),
        [("Appointment", [f"Date: {nice(9)} at 10:30",
                          "Doctor: Dr. Rahul Mehta, Room 214, second floor"]),
         ("Please bring", ["Current medication list, previous ECG reports and the blood pressure log "
                           "(sitting and standing readings)."]),
         ("Please note", ["Fasting is not required. Arrive 15 minutes early. To reschedule, call the "
                          "clinic at least 24 hours in advance."])],
        signed="Appointments Desk")

    pdf(DOCS_DIR / "joseph_mathew_postop_care_plan.pdf", "Greenfield Orthopaedic Centre",
        "Post-operative Care Plan | Right Hip Replacement",
        patient(J) + [f"Surgery date: {nice(-9)}", "Allergies: Penicillin (rash)"],
        [("Medications", [
            "Apixaban 2.5 mg twice daily (08:00 and 20:00) for 30 days to prevent blood clots. Do not skip doses.",
            "Paracetamol 500 mg, 2 tablets up to 3 times a day if needed for pain, with nurse approval.",
            "Calcium + Vitamin D3 500 mg once daily after lunch."]),
         ("Mobility", ["Use the walker at all times when walking. Do not bend the hip past 90 degrees. "
                       "Do not cross the legs. Use the raised toilet seat."]),
         ("Warning signs", ["Tell the nurse on duty straight away about calf pain or swelling, "
                            "unusual bleeding or bruising, blood in urine, or redness or discharge "
                            "at the wound. He is on a blood thinner, so any fall must be reported."]),
         ("Physiotherapy", ["Home physiotherapy every Monday, Wednesday and Friday at 11:00 with "
                            "physiotherapist Arun Kumar."])],
        signed="Dr. Sarah Thomas, Orthopaedic Surgeon")

    pdf(DOCS_DIR / "joseph_mathew_physiotherapy_plan.pdf", "Greenfield Orthopaedic Centre",
        "Physiotherapy Plan", patient(J),
        [("Goals", ["Week 1 to 2: walk 20 metres with the walker. Week 3 to 4: walk 50 metres and "
                    "climb 3 steps with support."]),
         ("Before each session", ["Ask the nurse whether pain relief is due about 30 minutes before "
                                  "the session. Make sure he wears non-slip footwear."]),
         ("Daily exercises", ["Ankle pumps, 10 times every hour while awake. Gentle knee bends, "
                              "10 times twice a day, supervised."])],
        signed="Arun Kumar, Physiotherapist")

    pdf(DOCS_DIR / "maria_gonzalez_copd_care_plan.pdf", "Sunrise Care Home",
        "Care Plan | COPD and Thyroid",
        patient(Mg) + ["Allergies: Shellfish (anaphylaxis, severe); Sulfa drugs (hives)"],
        [("Breathing", ["Encourage pursed-lip breathing when breathless. Sit her upright. "
                        "Oxygen saturation usually runs between 90 and 93 percent."]),
         ("Inhalers", ["Tiotropium 18 mcg inhaled once daily at 08:00.",
                       "Salbutamol 100 mcg, up to 2 puffs as needed for breathlessness. Tell the "
                       "nurse if she needs it more than twice in a day."]),
         ("When to get help", ["Call the nurse on duty if oxygen saturation is below 88 percent or "
                               "she is breathless at rest. Call 911 if her lips look blue or she "
                               "cannot speak in full sentences."]),
         ("Thyroid", ["Levothyroxine 50 mcg at 06:30, 30 minutes before breakfast."]),
         ("Allergies", ["Severe shellfish allergy: no shrimp, crab or lobster; the kitchen is informed. "
                        "An epinephrine auto-injector 0.3 mg is kept at the nurse station, for the "
                        "nurse or trained staff to use; call 911 whenever it is used.",
                        "Sulfa drugs cause hives. Cetirizine 10 mg as needed, with nurse approval."])],
        signed="Dr. Kevin Brooks, GP")

    pdf(DOCS_DIR / "robert_chen_memory_care_plan.pdf", "Sunrise Care Home",
        "Care Plan | Memory Care", patient(R) + ["Allergies: Aspirin (stomach bleeding)"],
        [("Routine", ["Keep the same daily routine. Breakfast 08:00, walk 10:30, rest 14:00."]),
         ("Communication", ["Use short sentences and ask one question at a time. Introduce yourself "
                            "each time. He responds well to music from the 1960s."]),
         ("Sundowning", ["He may become restless in the late afternoon. Keep lights on, reduce noise "
                         "and offer a calm activity."]),
         ("Safety", ["Door alarm on at night. Check on him every 2 hours overnight."]),
         ("Medications", ["Donepezil 5 mg at 21:00. Lisinopril 10 mg at 08:00. Melatonin 2 mg at 22:00."]),
         ("Family", ["Daughter Mei Chen visits on Sundays and is the main family contact."])],
        signed="Dr. Omar Siddiqui, Geriatrician")

    pdf(DOCS_DIR / "policy_fall_response.pdf", "Sunrise Care Home",
        "Facility Policy | Fall Response Protocol", ["Policy number: CH-07", "Applies to: all care staff"],
        [("First steps", ["1. Do not move the resident if they are hurt or cannot get up.",
                          "2. Check whether they are responsive and breathing.",
                          "3. Call the nurse on duty immediately."]),
         ("Call 911 when", ["The resident hit their head, is on a blood thinner such as apixaban, "
                            "cannot move a limb, is not fully alert, or is in severe pain."]),
         ("After the fall", ["Record the time and what happened. Neurological checks by the nurse "
                             "for 24 hours. Complete an incident report before the end of the shift."])],
        signed="Director of Nursing")

    pdf(DOCS_DIR / "policy_allergic_reaction.pdf", "Sunrise Care Home",
        "Facility Policy | Allergic Reaction Response", ["Policy number: CH-09",
                                                        "Applies to: all care staff"],
        [("Warning signs", ["A new rash or hives, swelling of the face, lips, tongue or throat, "
                            "trouble breathing or wheezing, dizziness or fainting, or vomiting "
                            "soon after a new medication or food."]),
         ("Call 911 when", ["There is any swelling of the face, lips, tongue or throat, any trouble "
                            "breathing or swallowing, the resident faints, or they are getting "
                            "worse quickly."]),
         ("First steps", ["1. Call the nurse on duty immediately.",
                          "2. Stay with the resident. Keep them sitting up if breathing is "
                          "difficult, or lying down if they feel faint.",
                          "3. Do not give any food, drink or medication unless the nurse or the "
                          "dispatcher says so.",
                          "4. If the resident has a prescribed adrenaline auto-injector, the nurse "
                          "or trained staff use it as set out in the resident's care plan."]),
         ("Afterwards", ["Record the time, the signs, and anything new the resident ate or took in "
                         "the last 24 hours. Keep the allergy list and medication list ready for "
                         "the responders. Complete an incident report before the end of the shift."])],
        signed="Director of Nursing")

    pdf(DOCS_DIR / "policy_medication_administration.pdf", "Sunrise Care Home",
        "Facility Policy | Medication Administration", ["Policy number: CH-03",
                                                         "Applies to: all staff trained to give medication"],
        [("The five rights", ["Right resident, right medication, right dose, right route, right time. "
                              "Check the allergy list before any new medication."]),
         ("Missed or refused doses", ["Never give a double dose to make up for a missed one. Record "
                                      "the missed or refused dose and tell the nurse on duty, who "
                                      "decides what to do."]),
         ("As-needed (PRN) medication", ["PRN medication needs nurse approval each time. Record the "
                                         "time, dose and reason."]),
         ("Errors", ["Report any medication error to the nurse on duty immediately, even if the "
                     "resident seems well."])],
        signed="Director of Nursing")

    notes = {
        "shift_note_lakshmi_rao.txt": (L, f"""SHIFT HANDOVER NOTE
Patient: Lakshmi Rao
Date of birth: 14 March 1948
Shift: Night, {nice(-1)}

OVERNIGHT
02:10 got up to use the bathroom and felt dizzy on standing. Sat back down straight away. No fall.
Blood pressure sitting 124/74, standing 104/64. Nurse on duty informed.
06:30 blood pressure 126/76 sitting. No dizziness. Drank 300 ml water.

FOR THE DAY TEAM
Remind her to sit for one minute before standing. Fluids chart started.
"""),
        "shift_note_robert_chen.txt": (R, f"""SHIFT HANDOVER NOTE
Patient: Robert Chen
Date of birth: 09 May 1938
Shift: Evening, {nice(-2)}

EVENING
17:30 restless and asking for his car keys (sundowning). Settled with 1960s music and tea.
22:00 refused melatonin. Recorded as refused and the nurse on duty informed.
23:40 door alarm sounded. Found in the hallway, calm, walked back to bed.

FOR THE NEXT SHIFT
Check on him every 2 hours. Daughter Mei Chen asked to be called if he is unsettled again.
"""),
        "shift_note_maria_gonzalez.txt": (Mg, f"""SHIFT HANDOVER NOTE
Patient: Maria Gonzalez
Date of birth: 20 November 1945
Shift: Day, {nice(-1)}

DAY
Used salbutamol inhaler twice (10:15 and 15:40) for breathlessness after walking. Nurse informed.
Oxygen saturation 91 to 93 percent. Ate well. Pursed-lip breathing helped.

FOR THE NEXT SHIFT
Watch for breathlessness at rest. Thyroid blood test on {nice(3)} at 07:30, before breakfast.
"""),
    }
    for name, (_, text) in notes.items():
        (DOCS_DIR / name).write_text(text, encoding="utf-8")

    # Held back for the live upload demo
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    pdf(DEMO_DIR / "maria_gonzalez_gp_review_letter.pdf", "Sunrise Family Clinic",
        "GP Review Letter", patient(Mg),
        [("Results", ["Thyroid blood test: TSH raised, showing her thyroid dose is too low."]),
         ("Medication changes", ["Levothyroxine increased from 50 mcg to 75 mcg once daily at 06:30, "
                                 "30 minutes before breakfast. Please update the medication record.",
                                 "Continue tiotropium 18 mcg daily and salbutamol 100 mcg as needed."]),
         ("Follow-up", ["Repeat thyroid blood test in 6 weeks."])],
        signed="Dr. Kevin Brooks, GP")
    pdf(DEMO_DIR / "referral_note_r_chen.pdf", "Westside Podiatry",
        "Referral Note", ["Patient: R. Chen", "Referred by: care home nurse"],
        [("Reason", ["Thickened toenails, difficult to cut. Routine podiatry visit requested."]),
         ("Plan", ["Podiatrist visit on site in 3 weeks. No action needed from care staff before then."])],
        signed="Westside Podiatry reception")


if __name__ == "__main__":
    write_csvs()
    write_docs()
    print(f"Wrote seed CSVs to {SEED_DIR}")
    print(f"Wrote {len(list(DOCS_DIR.glob('*')))} documents to {DOCS_DIR}")
    print(f"Wrote {len(list(DEMO_DIR.glob('*')))} demo uploads to {DEMO_DIR}")
