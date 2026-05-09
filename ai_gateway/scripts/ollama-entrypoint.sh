#!/bin/sh
set -e

MODEL="${OLLAMA_MODEL_NAME:-llama3.1:8b}"

# Start serwera w tle
ollama serve &
SERVER_PID=$!

echo "[entrypoint] Czekam na Ollama API..."
for i in $(seq 1 60); do
    if ollama list >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

echo "[entrypoint] Pull modelu: $MODEL"
ollama pull "$MODEL" || echo "[entrypoint] OSTRZEZENIE: pull modelu nie powiodl sie"

wait "$SERVER_PID"
