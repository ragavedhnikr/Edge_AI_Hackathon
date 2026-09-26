# Escalation policy

The hackathon brief asks for an application that runs its primary inference on the ZGX Nano and makes an **explicit, defensible, measurable decision about when to escalate to the cloud**. This is CareEdge's policy. The code is in `escalation.py` and `assistant.py`.

## The rules

| # | Request | Decision | Why |
|---|---|---|---|
| 1 | Emergency language | Never escalate. Instant on-device safety prompt | Speed matters, and no model is needed |
| 2 | Question about residents or the care home | Never escalate | Resident records are protected health information and must stay on the device |
| 3 | Document upload | Never escalate. Uncertain patient matches go to a person | Documents contain patient data; a wrong match must be caught by a human, not a bigger model |
| 4 | General request, confident | Answer on device | The local model is good enough |
| 5 | General request, not confident | **Would escalate**: logged, answer kept on device with a note to confirm with a clinician | This is the only case where a larger model could add value |

**"Not confident"** means either:

- the geometric-mean token probability of the on-device answer (from vLLM logprobs) is below a fixed threshold of **0.75** (set in `.env`), or
- the answer itself says it isn't sure.

## Cloud is off in this build

`CAREEDGE_CLOUD_ENABLED=0`. CareEdge still makes the rule-5 decision and logs it with the reason and confidence, but makes **no cloud calls**. The caregiver sees the local answer with a note to confirm with the nurse or pharmacist, so the fallback for low confidence is a qualified person rather than a bigger model.

If the cloud were ever switched on, rule 5 would send only the general question, and only after a privacy check finds no resident names, dates, phone numbers, emails, ID numbers or room numbers in it. Resident records and documents would still never be sent.

## Why this is defensible

- **Data residency:** everything that identifies a resident is covered by rules 1 to 3 and never leaves the device.
- **Capability:** the only thing the cloud could help with is general knowledge, which is exactly where rule 5 applies.
- **Safety:** for anything clinical, the escalation path is a person, not a model.

## How it is measured

Every decision is written to `data/events.db` and shown on the app's **Edge vs cloud** page and in `benchmarks/RESULTS.md`:

| Measure | Meaning |
|---|---|
| Share handled on device | Requests answered without the cloud (100% in this build) |
| Would escalate | General requests below the confidence threshold, with confidence values |
| Cloud calls | 0 in this build |
| Safety interventions | Answers changed by the output check |
| Emergencies flagged | Requests caught by the emergency check |
| Uploads auto-attached vs confirmed | How often a person was needed to file a document |
| Latency per step | Router, SQL, search, answer and total, median and p95 |

The confidence of every general answer is recorded in the decision log, so the threshold can be tuned later from real use: the lowest value that catches the answers you judge weak.
