#!/bin/zsh
set -euo pipefail

ROOT="/Users/thienlong/Desktop/Test Antigravity/BotAI-report"
PID_FILE="$ROOT/data/daemon.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No daemon pid file found"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "Stopped work report daemon with PID $PID"
else
  echo "Daemon PID $PID is not running"
fi
rm -f "$PID_FILE"
