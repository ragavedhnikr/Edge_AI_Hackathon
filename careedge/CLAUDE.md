# Notes for Claude Code

CareEdge is a hackathon project: an on-device records assistant for care-home caregivers, running on an HP ZGX Nano (NVIDIA GB10, Arm64, Ubuntu-based DGX OS). Read README.md, ARCHITECTURE.md and SAFETY.md first.

## Commands

- `./setup.sh`: create `.venv`, install packages, generate data, build the patient database
- `./serve_models.sh llm`, then `./serve_models.sh embed`: serve the two models with ZRT (background services; check `zrt status`)
- `./run.sh test`: check both model servers
- `./run.sh ingest`: load `data/docs` into `data/rag.db`
- `./run.sh app`: Streamlit on port 8501
- `./run.sh bench`: writes `benchmarks/RESULTS.md`
- `./run.sh reset`: rebuild the databases

## Rules for changes

- Never weaken the safety layers: `prompts/assistant_rules.md`, `guardrails.py` (emergency check, output check), and the read-only SQL path in `patient_db.run_readonly()`.
- Record data must never be sent off the device. Cloud calls stay off (`CAREEDGE_CLOUD_ENABLED=0`).
- Keep all data synthetic. Never add real patient information.
- The model servers are shared GPU resources: don't start training or extra model servers without asking.
- After changing the pipeline, run `./run.sh bench` and check the headline numbers didn't get worse.
