from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Settings
from .report import build_reports, render_telegram
from .state import ReportState
from .telegram import send_messages


def slot_key(now: datetime, schedule_time: str) -> str:
    return f"{now.date().isoformat()}-{schedule_time.replace(':', '')}"


def due_schedule_time(settings: Settings, now: datetime) -> str | None:
    for schedule_time in settings.schedule_times:
        hour, minute = [int(part) for part in schedule_time.split(":", 1)]
        if now.hour == hour and now.minute >= minute:
            return schedule_time
    return None


def run_due_once(settings: Settings, windows: tuple[int, ...]) -> bool:
    tz = ZoneInfo(settings.report_timezone)
    now = datetime.now(tz)
    schedule_time = due_schedule_time(settings, now)
    if schedule_time is None:
        return False

    key = slot_key(now, schedule_time)
    state = ReportState(settings.state_path)
    if state.already_sent(key):
        return False

    try:
        reports = build_reports(settings, windows, now)
        messages = render_telegram(schedule_time, reports)
        send_messages(settings, messages)
        state.record(key, schedule_time, "sent", len(messages))
        return True
    except Exception as exc:
        state.record(key, schedule_time, "failed", 0, str(exc)[:500])
        raise


def run_daemon(settings: Settings, windows: tuple[int, ...], poll_seconds: int = 30) -> None:
    while True:
        run_due_once(settings, windows)
        time.sleep(poll_seconds)
