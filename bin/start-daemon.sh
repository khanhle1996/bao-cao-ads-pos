#!/bin/zsh
set -euo pipefail

ROOT="/Users/thienlong/Desktop/Test Antigravity/BotAI-report"
PID_FILE="$ROOT/data/daemon.pid"

mkdir -p "$ROOT/data"
if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Daemon already running with PID $OLD_PID"
    exit 0
  fi
fi

nohup "$ROOT/bin/work-report-daemon.sh" > "$ROOT/data/daemon.out.log" 2> "$ROOT/data/daemon.err.log" &
echo "$!" > "$PID_FILE"
echo "Started work report daemon with PID $!"
