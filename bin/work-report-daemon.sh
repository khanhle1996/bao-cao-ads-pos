#!/bin/zsh
set -euo pipefail

ROOT="/Users/thienlong/Desktop/Test Antigravity/BotAI-report"
cd "$ROOT"

export PYTHONPATH="$ROOT"
export PYTHONPYCACHEPREFIX="$ROOT/data/pycache"
export WORK_REPORT_HTTP_TIMEOUT_SECONDS="${WORK_REPORT_HTTP_TIMEOUT_SECONDS:-30}"
export WORK_REPORT_HTTP_RETRIES="${WORK_REPORT_HTTP_RETRIES:-1}"

exec /usr/bin/python3 -m work_report_bot daemon --windows 3,5,7
