#!/bin/sh
# Startuje Ollamę w tle, pullsuje wymagany model, czeka na proces ollama.
set -e

MODEL="${OLLAMA_MODEL_NAME:-llama3.1:8b}"

# Start serwera w tle
ollama serve &
SERVER_PID=$!

# Czekaj aż serwer odpowiada
echo "[entrypoint] Czekam na Ollama API..."
for i in $(seq 1 60); do
    if ollama list >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Pull modelu (idempotentne — ollama pomija jeśli już jest)
echo "[entrypoint] Pull modelu: $MODEL"
ollama pull "$MODEL" || echo "[entrypoint] OSTRZEŻENIE: pull modelu nie powiódł się (sprawdź sieć)"

# Trzymaj proces serwera
wait "$SERVER_PID"
