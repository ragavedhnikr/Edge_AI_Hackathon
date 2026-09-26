"""Check both local models before running the app or the demo.

    ./run.sh test
"""
import sys
import time

import models
from config import DISABLE_THINKING, EMBED_BASE, EMBED_DISPLAY, LLM_BASE, LLM_DISPLAY


def main():
    st = models.status()
    ok = True
    for key, label, url in (("llm", f"{LLM_DISPLAY} chat model", LLM_BASE),
                            ("embed", f"{EMBED_DISPLAY} embedding model", EMBED_BASE)):
        good, detail = st[key]
        print(f"{'OK  ' if good else 'FAIL'} {label} at {url}: {detail}")
        ok &= good
    if not ok:
        sys.exit("\nStart the missing model with ./serve_models.sh llm or embed, then check "
                 "that .env matches the API ENDPOINT and SERVED AS columns of `zrt status`.")

    print(f"\nUsing chat model '{models.llm_name()}' and embedding model '{models.embed_name()}'.")

    t0 = time.time()
    reply = models.chat([{"role": "user", "content": "Reply with exactly one word: ready"}],
                        max_tokens=20, temperature=0, logprobs=True)
    print(f"OK   Chat reply in {time.time() - t0:.1f} s: {reply.text!r}")
    if reply.reasoned and DISABLE_THINKING:
        print("WARN The model still produced 'thinking' tokens. Answers will be slower. "
              "Check the chat template supports enable_thinking.")
    print("OK   Confidence scores available" if reply.confidence is not None else
          "WARN No logprobs returned; escalation falls back to detecting hedged answers.")

    t0 = time.time()
    reply = models.chat([{"role": "user", "content": "In two sentences, what does a care-home "
                                                     "caregiver do?"}], max_tokens=120)
    secs = time.time() - t0
    print(f"OK   Generation: {reply.tokens_out} tokens in {secs:.1f} s "
          f"(about {reply.tokens_out / max(secs, 1e-6):.0f} tokens/s)")

    t0 = time.time()
    vecs = models.embed(["Amlodipine reduced from 10 mg to 5 mg", "Fall response protocol"])
    q = models.embed("What is her blood pressure medicine dose?", is_query=True)
    sims = (vecs @ q[0]).round(3).tolist()
    print(f"OK   Embeddings: dimension {vecs.shape[1]}, {time.time() - t0:.2f} s, "
          f"similarity to a dose question {sims} (first should be higher)")
    print("\nAll checks passed. Next: ./run.sh ingest, then ./run.sh app")


if __name__ == "__main__":
    main()
