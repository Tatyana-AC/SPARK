#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYSTEM_PROMPT="${SYSTEM_PROMPT:-You summarize the current active application context. Describe what appears to be happening on screen, the main task or content in view, and the most likely immediate next step. Stay concise, concrete, and grounded in the provided context only.}"

if [ ! -w /dev/ttyTHS0 ]; then
  echo "Setting permissions on /dev/ttyTHS0..."
  sudo chmod 666 /dev/ttyTHS0
fi

exec python3 "$SCRIPT_DIR/pico_llm_bridge.py" \
  --port /dev/ttyTHS0 \
  --baud 115200 \
  --db "$SCRIPT_DIR/jetson_spark.db" \
  --llm-url http://127.0.0.1:8080 \
  --system-prompt "$SYSTEM_PROMPT" \
  "$@"
