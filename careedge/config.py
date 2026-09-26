"""CareEdge settings. Every value can be overridden with an environment variable
(see .env.example)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _env(name, default):
    return os.getenv(name, default)


# --- Local models, both served by ZRT (vLLM) on the ZGX Nano -----------------
# ZRT serves every model through one proxy (port 8080 by default) and names each
# one by its --label (see serve_models.sh), so the model names here are labels.
# Chat model, Qwen2.5-7B-Instruct: routing, SQL generation, answers.
LLM_BASE = _env("CAREEDGE_LLM_BASE", "http://localhost:8080/v1")
LLM_MODEL = _env("CAREEDGE_LLM_MODEL", "careedge-llm")
LLM_DISPLAY = _env("CAREEDGE_LLM_DISPLAY", "Qwen2.5-7B-Instruct")
# Embedding model, Qwen3-Embedding-0.6B: vectors for document search.
EMBED_BASE = _env("CAREEDGE_EMBED_BASE", "http://localhost:8080/v1")
EMBED_MODEL = _env("CAREEDGE_EMBED_MODEL", "careedge-embed")
EMBED_DISPLAY = _env("CAREEDGE_EMBED_DISPLAY", "Qwen3-Embedding-0.6B")
API_KEY = _env("CAREEDGE_API_KEY", "local")  # only needed if ZRT proxy auth is on
# Some models (Qwen3.x) can "think" before answering, which costs time, so it is
# switched off. Models without a thinking mode (Qwen2.5) ignore this.
DISABLE_THINKING = _env("CAREEDGE_DISABLE_THINKING", "1") == "1"

# --- Cloud escalation: OFF in this build ------------------------------------
# With the cloud off, CareEdge still makes and logs every escalation decision
# ("would escalate, and why"), but the answer always stays on the device.
CLOUD_ENABLED = _env("CAREEDGE_CLOUD_ENABLED", "0") == "1"
CLOUD_API_BASE = _env("CAREEDGE_CLOUD_API_BASE", "")
CLOUD_API_KEY = _env("CAREEDGE_CLOUD_API_KEY", "")
CLOUD_MODEL = _env("CAREEDGE_CLOUD_MODEL", "")
ESCALATE_BELOW = float(_env("CAREEDGE_ESCALATE_BELOW", "0.75"))

# --- Retrieval ----------------------------------------------------------------
RAG_TOP_K = int(_env("CAREEDGE_RAG_TOP_K", "4"))
MIN_PAGE_CHARS = 40  # a PDF page with less text than this is treated as scanned

# --- Files --------------------------------------------------------------------
DATA_DIR = ROOT / "data"
SEED_DIR = DATA_DIR / "seed"
DOCS_DIR = DATA_DIR / "docs"
DEMO_DIR = DATA_DIR / "demo_uploads"
PATIENT_DB = Path(_env("CAREEDGE_PATIENT_DB", str(DATA_DIR / "patient.db")))
RAG_DB = Path(_env("CAREEDGE_RAG_DB", str(DATA_DIR / "rag.db")))
EVENTS_DB = Path(_env("CAREEDGE_EVENTS_DB", str(DATA_DIR / "events.db")))
UPLOAD_DIR = Path(_env("CAREEDGE_UPLOADS", str(ROOT / "uploads")))
RULES_FILE = ROOT / "prompts" / "assistant_rules.md"
