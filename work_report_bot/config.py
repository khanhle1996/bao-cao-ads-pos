from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
FB_ENV_PATH = WORKSPACE / "Facebook Ads Bot" / ".env"
POS_ENV_PATH = WORKSPACE / "Kết nối POS Pancake" / ".env"
BRANDS_PATH = ROOT / "config" / "brands.json"
STATE_PATH = ROOT / "data" / "report_runs.sqlite3"


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _pick(name: str, *sources: dict[str, str], default: str = "") -> str:
    env_value = os.getenv(name, "").strip()
    if env_value:
        return env_value
    for source in sources:
        value = source.get(name, "").strip()
        if value:
            return value
    return default


def _required(name: str, value: str) -> str:
    if not value or value.startswith("replace_") or value == "replace_me":
        raise RuntimeError(f"Missing required config: {name}")
    return value


@dataclass(frozen=True)
class Brand:
    name: str
    ad_account_ids: tuple[str, ...]
    pos_shop_ids: tuple[str, ...]


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    meta_api_version: str
    meta_access_token: str
    pancake_access_token: str
    pancake_base_url: str
    report_timezone: str
    schedule_times: tuple[str, ...]
    http_timeout_seconds: int
    http_retries: int
    state_path: Path
    brands: tuple[Brand, ...]


def load_brands(path: Path = BRANDS_PATH) -> tuple[Brand, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    brands = []
    for item in payload.get("brands", []):
        brands.append(
            Brand(
                name=str(item["name"]),
                ad_account_ids=tuple(str(value) for value in item.get("ad_account_ids", [])),
                pos_shop_ids=tuple(str(value) for value in item.get("pos_shop_ids", [])),
            )
        )
    if not brands:
        raise RuntimeError("No brands configured")
    return tuple(brands)


def get_api_settings() -> Settings:
    """Load settings for web/HTML generation — skips Telegram validation."""
    fb_env = load_dotenv(FB_ENV_PATH)
    pos_env = load_dotenv(POS_ENV_PATH)
    return Settings(
        telegram_bot_token="",
        telegram_chat_id="",
        meta_api_version=_pick("META_API_VERSION", fb_env, default="v25.0"),
        meta_access_token=_required("META_ACCESS_TOKEN", _pick("META_ACCESS_TOKEN", fb_env)),
        pancake_access_token=_required(
            "PANCAKE_ACCESS_TOKEN",
            _pick("PANCAKE_ACCESS_TOKEN", pos_env) or _pick("PANCAKE_API_KEY", pos_env),
        ),
        pancake_base_url=_pick("PANCAKE_BASE_URL", pos_env, default="https://pos.pages.fm/api/v1").rstrip("/"),
        report_timezone=_pick("REPORT_TIMEZONE", fb_env, pos_env, default="Asia/Ho_Chi_Minh"),
        schedule_times=(),
        http_timeout_seconds=int(_pick("WORK_REPORT_HTTP_TIMEOUT_SECONDS", fb_env, pos_env, default="20")),
        http_retries=int(_pick("WORK_REPORT_HTTP_RETRIES", fb_env, pos_env, default="1")),
        state_path=STATE_PATH,
        brands=load_brands(),
    )


def get_settings() -> Settings:
    fb_env = load_dotenv(FB_ENV_PATH)
    pos_env = load_dotenv(POS_ENV_PATH)
    telegram_chat_id = _pick("WORK_REPORT_TELEGRAM_CHAT_ID", fb_env)
    if not telegram_chat_id:
        telegram_chat_id = _pick("TELEGRAM_ALLOWED_CHAT_ID", fb_env)

    return Settings(
        telegram_bot_token=_required("TELEGRAM_BOT_TOKEN", _pick("TELEGRAM_BOT_TOKEN", fb_env)),
        telegram_chat_id=_required("TELEGRAM_ALLOWED_CHAT_ID", telegram_chat_id),
        meta_api_version=_pick("META_API_VERSION", fb_env, default="v25.0"),
        meta_access_token=_required("META_ACCESS_TOKEN", _pick("META_ACCESS_TOKEN", fb_env)),
        pancake_access_token=_required(
            "PANCAKE_ACCESS_TOKEN",
            _pick("PANCAKE_ACCESS_TOKEN", pos_env) or _pick("PANCAKE_API_KEY", pos_env),
        ),
        pancake_base_url=_pick("PANCAKE_BASE_URL", pos_env, default="https://pos.pages.fm/api/v1").rstrip("/"),
        report_timezone=_pick("REPORT_TIMEZONE", fb_env, pos_env, default="Asia/Ho_Chi_Minh"),
        schedule_times=tuple(
            item.strip()
            for item in _pick("WORK_REPORT_TIMES", fb_env, default="08:00,21:00").split(",")
            if item.strip()
        ),
        http_timeout_seconds=int(_pick("WORK_REPORT_HTTP_TIMEOUT_SECONDS", fb_env, pos_env, default="20")),
        http_retries=int(_pick("WORK_REPORT_HTTP_RETRIES", fb_env, pos_env, default="1")),
        state_path=STATE_PATH,
        brands=load_brands(),
    )
