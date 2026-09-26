"""Connections to the two local models, both served by ZRT (vLLM) on the Nano.

  chat   Qwen2.5-7B-Instruct (label careedge-llm): routing, SQL, answers
  embed  Qwen3-Embedding-0.6B (label careedge-embed): vectors for document search
"""
import base64
import io
import math
import re
import time
from dataclasses import dataclass

import numpy as np
from openai import OpenAI

from config import API_KEY, DISABLE_THINKING, EMBED_BASE, EMBED_MODEL, LLM_BASE, LLM_MODEL

chat_client = OpenAI(base_url=LLM_BASE, api_key=API_KEY, timeout=300)
embed_client = OpenAI(base_url=EMBED_BASE, api_key=API_KEY, timeout=120)

EMBED_QUERY_TASK = ("Given a question from a caregiver in a care home, retrieve passages "
                    "from medical documents and facility policies that answer it")


# ---------------------------------------------------------------------------
# Server checks and model names
# ---------------------------------------------------------------------------

_names = {}


def _served(client):
    quick = client.with_options(timeout=5, max_retries=0)
    return [m.id for m in quick.models.list().data]


def _resolve(key, client, configured):
    """Use the configured name, or the server's only model if they differ
    (ZRT may report names like 'hf:Qwen/...')."""
    if key in _names:
        return _names[key]
    try:
        served = _served(client)
    except Exception:  # noqa: BLE001 - server down; try again next call
        return configured
    if configured in served:
        name = configured
    elif len(served) == 1:
        name = served[0]
    else:
        tail = configured.split(":")[-1].lower()
        matches = [s for s in served if s.lower().endswith(tail)]
        name = matches[0] if matches else configured
    _names[key] = name
    return name


def llm_name():
    return _resolve("llm", chat_client, LLM_MODEL)


def embed_name():
    return _resolve("embed", embed_client, EMBED_MODEL)


def status():
    """{'llm': (ok, detail), 'embed': (ok, detail)} for the UI and test script."""
    out = {}
    for key, client in (("llm", chat_client), ("embed", embed_client)):
        try:
            out[key] = (True, ", ".join(_served(client)))
        except Exception as exc:  # noqa: BLE001
            out[key] = (False, str(exc))
    return out


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def strip_thinking(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    return text.replace("<think>", "").replace("</think>", "").strip()


@dataclass
class Reply:
    text: str
    confidence: float | None
    ms: float
    tokens_in: int
    tokens_out: int
    reasoned: bool = False  # True if the model spent tokens "thinking"


_extra_ok = True
_logprobs_ok = True


def _extra():
    return {"chat_template_kwargs": {"enable_thinking": False}} if DISABLE_THINKING else {}


def _confidence(choice):
    """Geometric-mean token probability of the reply (0..1), or None."""
    lp = getattr(choice, "logprobs", None)
    tokens = getattr(lp, "content", None) if lp else None
    values = [t.logprob for t in tokens or [] if t.logprob is not None and t.logprob > -100]
    return math.exp(sum(values) / len(values)) if values else None


def chat(messages, *, max_tokens=700, temperature=0.2, logprobs=False):
    """One non-streaming call to the chat model. Falls back gracefully if the server
    rejects the thinking switch or logprobs."""
    global _extra_ok, _logprobs_ok
    kwargs = dict(model=llm_name(), messages=messages, max_tokens=max_tokens,
                  temperature=temperature)
    if _extra_ok and _extra():
        kwargs["extra_body"] = _extra()
    if logprobs and _logprobs_ok:
        kwargs["logprobs"] = True
    start = time.perf_counter()
    try:
        resp = chat_client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "logprob" in msg and "logprobs" in kwargs:
            _logprobs_ok = False
            kwargs.pop("logprobs")
        elif "chat_template_kwargs" in msg or "enable_thinking" in msg:
            _extra_ok = False
            kwargs.pop("extra_body", None)
        else:
            raise
        resp = chat_client.chat.completions.create(**kwargs)
    ms = (time.perf_counter() - start) * 1000
    choice = resp.choices[0]
    usage = getattr(resp, "usage", None)
    text = choice.message.content or ""
    return Reply(
        text=strip_thinking(text),
        confidence=_confidence(choice),
        ms=ms,
        tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
        tokens_out=getattr(usage, "completion_tokens", 0) or max(1, len(text) // 4),
        reasoned=bool(getattr(choice.message, "reasoning_content", None)),
    )


def stream(messages, *, max_tokens=700, temperature=0.2):
    """Yield answer text as it is generated (for st.write_stream)."""
    kwargs = dict(model=llm_name(), messages=messages, max_tokens=max_tokens,
                  temperature=temperature, stream=True)
    if _extra_ok and _extra():
        kwargs["extra_body"] = _extra()
    resp = chat_client.chat.completions.create(**kwargs)
    inside_think = False
    for chunk in resp:
        if not chunk.choices:
            continue
        piece = chunk.choices[0].delta.content or ""
        if "<think>" in piece:
            inside_think, piece = True, piece.split("<think>")[0]
        if inside_think:
            if "</think>" in piece:
                inside_think, piece = False, piece.split("</think>", 1)[1]
            else:
                continue
        if piece:
            yield piece


def parse_json(text):
    """Pull the first JSON object out of a model reply."""
    import json
    text = re.sub(r"```(?:json)?", "", strip_thinking(text))
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])


def image_message(png_bytes, prompt):
    url = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
    return [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}},
                                         {"type": "text", "text": prompt}]}]


def pil_to_png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def embed(texts, *, is_query=False, batch=32):
    """Return an (n, d) float32 array of L2-normalised embeddings."""
    if isinstance(texts, str):
        texts = [texts]
    if is_query:  # Qwen3-Embedding is instruction-aware for queries only
        texts = [f"Instruct: {EMBED_QUERY_TASK}\nQuery:{t}" for t in texts]
    vectors = []
    for i in range(0, len(texts), batch):
        resp = embed_client.embeddings.create(model=embed_name(), input=texts[i:i + batch])
        vectors += [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
    arr = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / np.maximum(norms, 1e-12)
