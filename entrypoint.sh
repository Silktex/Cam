#!/bin/bash
set -e

echo "=== Camera Control System ==="

# Seed colorchecker profiles into mounted media volume if missing
if [ -d /app/seed/colorchecker ] && [ ! -d /app/api/media/colorchecker/profiles ]; then
  echo "Seeding colorchecker profiles into media volume..."
  cp -r /app/seed/colorchecker /app/api/media/colorchecker
fi

echo "Starting API server on :8000 and Web UI on :3000"

# Start API server in background
cd /app/api
python -m uvicorn main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# Start Web server in background
cd /app/web
npx next start -p 3000 -H 0.0.0.0 &
WEB_PID=$!

echo "API PID: $API_PID, Web PID: $WEB_PID"

# Wait for either process to exit — if one crashes, container exits
# and docker restart policy handles recovery
wait -n $API_PID $WEB_PID
