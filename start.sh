#!/bin/sh

# Exit immediately if any command fails
set -e

echo "Starting GitRAG in role: $ROLE on port: $PORT"

if [ "$ROLE" = "worker" ]; then
    echo "Launching RQ ingestion worker process..."
    exec python -m rq worker ingest --url "$REDIS_URL"
else
    echo "Launching FastAPI web server process..."
    exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
fi
