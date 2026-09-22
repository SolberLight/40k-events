#!/usr/bin/env bash
# Serve site/ locally on port 8040 and expose it through ngrok.
# First run: ngrok config add-authtoken <token>   (token from dashboard.ngrok.com)
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8040}"
NGROK="${NGROK:-$HOME/.local/bin/ngrok}"

if ! curl -s -o /dev/null "http://127.0.0.1:$PORT/index.html"; then
  nohup python3 -m http.server "$PORT" -d "$PWD/site" --bind 127.0.0.1 > /dev/null 2>&1 &
  sleep 1
fi
echo "local:  http://127.0.0.1:$PORT"

pkill -f "ngrok http $PORT" 2>/dev/null || true
nohup "$NGROK" http "$PORT" --log=stdout --log-format=json > "$PWD/cache/ngrok.log" 2>&1 &
for _ in $(seq 1 20); do
  sleep 0.5
  URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c 'import json,sys; t=json.load(sys.stdin).get("tunnels",[]); print(t[0]["public_url"] if t else "")' 2>/dev/null || true)
  [ -n "$URL" ] && break
done
if [ -n "${URL:-}" ]; then
  echo "public: $URL"
else
  echo "ngrok did not come up; last log lines:" >&2
  tail -3 "$PWD/cache/ngrok.log" >&2
  exit 1
fi
