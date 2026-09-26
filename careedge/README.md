# CareEdge

**A private, on-device records assistant for night-shift caregivers, running on the HP ZGX Nano.**

Built for the HP Edge AI SJSUHack. CareEdge answers caregivers' questions from a resident's structured records (with SQL) and their medical paperwork (with retrieval over documents), helps with general requests, and files new PDFs into the right resident's record automatically. All inference runs on the ZGX Nano. No patient data leaves the device, and this build makes no cloud calls.

> **CareEdge is an information assistant, not a clinician.** It does not diagnose, recommend treatment or advise on doses. See [SAFETY.md](SAFETY.md). All data in this repository is synthetic.

## Who it's for

A night-shift caregiver in a small care home. There's no nurse on site at 2 a.m., the residents' paperwork is a stack of prescriptions, discharge summaries and care plans, and questions come up fast: *Who gets medication at 22:00? Why was Lakshmi in hospital? Joseph just fell, what does our policy say?* Cloud AI isn't an option: the records are protected health information, and the building's internet isn't reliable.

## What it does

| Input | What happens | Where it runs |
|---|---|---|
| Question about residents or the care home | The chat model writes SQL for the patient database and/or searches the documents, then answers with citations | On device |
| General request (explain, summarize, draft) | The chat model answers with a confidence score; low confidence is logged as "would escalate" | On device |
| PDF or TXT upload | Text extracted, patient identified by name and date of birth, sections embedded and linked in a graph, medications checked against the record | On device |
| Emergency language | Instant safety prompt and medication list for paramedics, before any model runs | On device |

Two models, both open-weight and used without fine-tuning, served by ZRT through its proxy:

- **Qwen2.5-7B-Instruct** (served as `careedge-llm`): routing, SQL, answers
- **Qwen3-Embedding-0.6B** (served as `careedge-embed`): vectors for document search

### Model choice: what we measured

We first planned to use **Qwen3.8-27B (NVFP4)**, the model in the hackathon handout. Its weights loaded in 24.2 GB in about 2 minutes, but it was killed by the out-of-memory handler during startup, while vLLM compiled GPU kernels (the `cicc` CUDA compiler used over 6 GB per process), with the embedding model running alongside it on the Nano's 128 GB of shared memory. We shipped on **Qwen2.5-7B-Instruct**, which runs next to the embedding model with room to spare. `./serve_models.sh llm27b` has settings to retry the 27B model on its own (no kernel compilation, shorter context).

One trade-off: Qwen2.5-7B-Instruct reads text only, so CareEdge can't read **scanned** (image-only) PDF pages with it. All of the included documents are typed, and an upload with a scanned page gets a clear error instead of a wrong answer.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the flow maps and [ESCALATION_POLICY.md](ESCALATION_POLICY.md) for the edge-versus-cloud decision.

## Files

| File | Purpose |
|---|---|
| `app.py` | Web app: Ask, Upload, Patients, Edge vs cloud |
| `assistant.py` | Connects the steps for each question |
| `router.py` | Record question or general request? Which sources? |
| `sql_agent.py` | Question to read-only SQL on the patient database |
| `doc_store.py` | Vector store and graph (documents, sections, links) in `rag.db` |
| `ingest.py` | Upload pipeline: extract, identify patient, split, embed, tag, reconcile |
| `guardrails.py` | Rules loader, emergency detection, output safety check |
| `escalation.py` | Escalation decision and decision log |
| `models.py` | Connections to both local models |
| `patient_db.py` | Patient database schema, loading and read-only queries |
| `prompts/assistant_rules.md` | The rules the model receives in every prompt |
| `make_dataset.py` | Generates all synthetic data in `data/` |
| `benchmark.py` | Writes `benchmarks/RESULTS.md` |
| `test_models.py` | Checks both model servers |
| `setup.sh`, `serve_models.sh`, `run.sh` | Setup, model serving and running |

---

## Setup on the ZGX Nano, step by step

These steps follow the hackathon handout. Allow about an hour the first time, most of it downloading the model.

### Step 1. Connect to your Nano (handout: "Accessing Your ZGX Nano")

1. Connect your laptop to the same SJSU network as the Nano (edroam, logged in with your .edu email) and make sure Tailscale is installed and running.
2. Open VS Code and install the **ZGX Toolkit (ZTK)** extension from the Marketplace.
3. Click the ZTK extension, then **Add Device**, then **Discover Devices**. Select your team's device ID, or enter the Tailscale IP the admins gave you.
4. Use the default device name, enter your username (`hp1` ... `hp25`) and the password `edgehack`, and click **Add Device**.
5. Select **Linux**, follow the prompts to test the connection, install ZRT if it isn't already installed, then click **Connect**.
6. In the VS Code window connected to the Nano, open a terminal: **Terminal > New Terminal**. All commands below run in this terminal, on the Nano.

### Step 2. Put the code on GitHub and clone it to the Nano

The Nano is wiped after the event, and the repo is a required deliverable, so GitHub is the home of this project.

On your **laptop**:

1. On github.com, create a new **public** repository called `careedge`, with no README (this project has one).
2. Unzip this project, then in a terminal:

```bash
cd careedge
git init
git add .
git commit -m "CareEdge: initial version"
git branch -M main
git remote add origin https://github.com/<your-username>/careedge.git
git push -u origin main
```

On the **Nano** terminal in VS Code:

```bash
cd ~/Desktop
git clone https://github.com/<your-username>/careedge.git
cd careedge
chmod +x *.sh
```

### Step 3. Set up ZRT and the app (handout: "Pulling and Serving Models")

```bash
# Only if ZRT is not installed yet
sudo snap install --classic zrt

# Disable the proxy and security certificate for localhost (from the handout)
zrt config set proxy.auth.type none && zrt config set proxy.tls.enabled false
zrt status

# Python environment, packages, synthetic data, patient database
./setup.sh
```

### Step 4. Download and serve the two models

```bash
./serve_models.sh pull      # Qwen2.5-7B-Instruct (about 15 GB) and Qwen3-Embedding-0.6B
```

If a download fails because the model is gated, set your Hugging Face token as in the handout (`export HF_TOKEN="<your token>"`) and run it again.

Free up memory, then start the chat model first and the embedding model second. ZRT runs each one as a background service:

```bash
zrt stop --all                                   # only if other models are running
sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
./serve_models.sh llm
./serve_models.sh embed
zrt status
```

Wait until both show **Ready**. Then check the **API ENDPOINT** column (ZRT's proxy, usually `http://127.0.0.1:8080`) and the **SERVED AS** column (`careedge-llm` and `careedge-embed`), and make sure `.env` matches them:

```
CAREEDGE_LLM_BASE=http://localhost:8080/v1
CAREEDGE_LLM_MODEL=careedge-llm
CAREEDGE_EMBED_BASE=http://localhost:8080/v1
CAREEDGE_EMBED_MODEL=careedge-embed
```

If the embedding model fails on `--runner pooling`, your vLLM is older: change it to `--task embed` in `serve_models.sh`. The models and the app use separate ports (ZRT's proxy and 8501), as the handout requires. The Nano's memory is shared by your whole team, so don't train or serve other models while these are running.

### Step 5. Check the models

```bash
./run.sh test
```

This confirms both servers answer, reports generation speed in tokens per second, checks that confidence scores are available, and tests an embedding. It should end with `All checks passed`.

### Step 6. Load the sample documents

```bash
./run.sh ingest
```

This reads the 12 documents in `data/docs/` on the Nano, files each one to the right resident (or as a facility policy), and builds the vector store and graph. You can also do this from the app's Upload page with **Add sample documents**.

### Step 7. Run the app

```bash
./run.sh app
```

Open it on your laptop in either of two ways:

- VS Code usually forwards the port automatically. Open `http://localhost:8501`. If it doesn't, open the **Ports** tab, click **Forward a Port** and enter `8501`.
- Or open `http://<your-nano-tailscale-ip>:8501` directly.

This is the "driven over SSH or a tunneled port" demo setup the deliverables describe.

### Step 8. Run the benchmark and push the results

```bash
./run.sh bench
```

This builds its own copies of the databases, runs the full pipeline on the synthetic dataset, and writes `benchmarks/RESULTS.md` and `benchmarks/results.json`. Push them to GitHub; they are your metrics deliverable:

```bash
git add benchmarks/RESULTS.md benchmarks/results.json
git commit -m "Benchmark results on the ZGX Nano"
git push
```

To push from the Nano, GitHub asks for your username and a **personal access token** (github.com > Settings > Developer settings > Personal access tokens) in place of a password.

---

## Metrics, and why we chose them

| Metric | Why it matters |
|---|---|
| Documents filed to the correct resident automatically | Filing a document to the wrong resident is the most dangerous upload error |
| Uncertain uploads sent to a person | Shows the system knows when not to decide on its own |
| Document search hit@1 / hit@k | Retrieval only helps if it finds the right document |
| SQL queries that ran successfully | Model-written SQL must run, and only ever read |
| Routing accuracy | Each message must reach the right source |
| Answers containing the expected facts | Answers must match the records |
| Safety cases passed | No dosing advice or diagnoses, and a referral to a clinician |
| Emergencies flagged and false alarms | Every emergency flagged, without crying wolf |
| Latency per step and tokens per second | Tests a bedside time budget on the GB10 |
| Requests that would escalate, and cloud calls | The measurable edge-versus-cloud decision |

## Deliverables checklist (from the handout, due Fri. Sept 25 by 8 pm)

- [ ] **Public GitHub repo:** code, this README, `setup.sh`
- [ ] **Metrics:** `benchmarks/RESULTS.md` from a run on the Nano, pushed
- [ ] **Demo:** app running on the Nano over a tunneled port; record a backup video in case the live demo isn't possible. See [DEMO.md](DEMO.md)
- [ ] **Video:** 2 minutes maximum, public on YouTube
- [ ] **Pitch visuals:** architecture (ARCHITECTURE.md or the app's Edge vs cloud page), benchmarks (RESULTS.md), impact (the user story above)
- [ ] **SJSU Google Drive:** project brief, pitch video, links, presentation, diagrams, photos
- [ ] **Socials:** tag the accounts listed in the handout

## Troubleshooting

| Problem | Fix |
|---|---|
| A model is "Killed" or shows **Dead** in `zrt status` | It ran out of memory. Run `zrt stop --all`, clear caches (`sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'`), make sure no teammate is running another model, then start the chat model before the embedding model. Lower `--gpu-memory-fraction` in `serve_models.sh` if needed |
| "The proxy process has stopped" | `zrt stop --all`, then start both models again |
| `--runner pooling` is not recognized | Your vLLM version is older. Replace it with `--task embed` in `serve_models.sh` |
| `./run.sh test` says a model isn't found | `.env` must use the **SERVED AS** names from `zrt status` (`careedge-llm`, `careedge-embed`) |
| FlashInfer or other vLLM errors | The handout notes the stack changes often. Check the NVIDIA DGX Spark playbooks and vLLM Recipes, which cover the GB10 |
| `./run.sh test` warns about "thinking" tokens | Answers will be slower. Check the model's chat template, or set `CAREEDGE_DISABLE_THINKING=0` in `.env` to accept it |
| Port 8501 already in use | Set a different `CAREEDGE_PORT` in `.env`, or stop the other process |
| `python3 -m venv` fails | `sudo apt install -y python3-venv` |
| Start again with fresh data | `./run.sh reset`, then `./run.sh ingest` |

## Limitations

This is a hackathon prototype built on synthetic data. It is not clinically validated, not a medical device, and not certified for real patient data. See [SAFETY.md](SAFETY.md) for the full list.
