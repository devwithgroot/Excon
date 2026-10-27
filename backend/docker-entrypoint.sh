#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

if [ "${API_RELOAD}" = "true" ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
