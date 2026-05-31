#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
export PYTHONPATH="$SCRIPT_DIR"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-$SCRIPT_DIR/data/pycache}"
export WORK_REPORT_HTTP_TIMEOUT_SECONDS="${WORK_REPORT_HTTP_TIMEOUT_SECONDS:-30}"
export WORK_REPORT_HTTP_RETRIES="${WORK_REPORT_HTTP_RETRIES:-1}"

exec /usr/bin/python3 -m work_report_bot run-once --windows "${WORK_REPORT_WINDOWS:-3,5,7}" --slot-label "${WORK_REPORT_SLOT_LABEL:-08:00}" --split-by-brand "$@"
