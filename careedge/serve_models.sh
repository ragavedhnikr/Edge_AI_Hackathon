#!/usr/bin/env bash
# Serve the two CareEdge models with ZRT (HP Z Runtime, a vLLM wrapper).
# ZRT chooses the ports and routes both models through its proxy; check the
# API ENDPOINT column in `zrt status` and put it in .env.
#
#   ./serve_models.sh pull      download both models
#   ./serve_models.sh llm       chat model (Qwen2.5-7B-Instruct), label careedge-llm
#   ./serve_models.sh embed     Qwen3-Embedding-0.6B, label careedge-embed
#   ./serve_models.sh llm27b    optional experiment: Qwen3.8-27B NVFP4 (see README)
#   ./serve_models.sh stop      stop both
#
# Start the chat model first, then the embedding model. Memory on the Nano is
# shared by CPU and GPU, so each server is capped (--gpu-memory-fraction).
set -euo pipefail
cd "$(dirname "$0")"
LLM_HF="${CAREEDGE_LLM_HF:-Qwen/Qwen2.5-7B-Instruct}"
EMBED_HF="${CAREEDGE_EMBED_HF:-Qwen/Qwen3-Embedding-0.6B}"

case "${1:-}" in
  pull)
    zrt pull "$LLM_HF"
    zrt pull "$EMBED_HF"
    ;;
  llm)
    zrt serve "hf:$LLM_HF" --gpu-memory-fraction 0.4 --label careedge-llm --force \
      -- --max-model-len 8192
    ;;
  embed)
    # If your vLLM rejects --runner pooling, replace it with --task embed
    zrt serve "hf:$EMBED_HF" --gpu-memory-fraction 0.05 --label careedge-embed --force \
      -- --runner pooling --max-model-len 8192 --enforce-eager
    ;;
  llm27b)
    # Ran out of memory during GPU kernel compilation next to the embedding model
    # on our Nano. Try it alone, after: zrt stop --all, and clearing caches with
    #   sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
    zrt serve "hf:Inferact/Qwen3.8-27B-NVFP4" --gpu-memory-fraction 0.45 --label careedge-llm --force \
      -- --max-model-len 8192 --enforce-eager --reasoning-parser qwen3
    ;;
  stop)
    zrt service stop careedge-llm || true
    zrt service stop careedge-embed || true
    ;;
  *)
    echo "usage: ./serve_models.sh [pull|llm|embed|llm27b|stop]"; exit 1 ;;
esac
