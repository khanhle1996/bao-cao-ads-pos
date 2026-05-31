from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from .config import Settings
from .http import get_json


PURCHASE_ACTIONS = ("onsite_conversion.purchase", "omni_purchase", "purchase")
MESSAGE_ACTIONS = (
    "onsite_conversion.messaging_conversation_replied_7d",
    "onsite_conversion.messaging_conversation_started_7d",
)


@dataclass(frozen=True)
class AdsMetrics:
    spend: Decimal = Decimal("0")
    messages: Decimal = Decimal("0")
    purchases: Decimal = Decimal("0")
    meta_revenue: Decimal = Decimal("0")

    def add(self, other: "AdsMetrics") -> "AdsMetrics":
        return AdsMetrics(
            spend=self.spend + other.spend,
            messages=self.messages + other.messages,
            purchases=self.purchases + other.purchases,
            meta_revenue=self.meta_revenue + other.meta_revenue,
        )


class MetaClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = f"https://graph.facebook.com/{settings.meta_api_version}"

    def account_insights(self, ad_account_id: str, since: date, until: date) -> AdsMetrics:
        account = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
        payload = get_json(
            f"{self.base_url}/{account}/insights",
            {
                "access_token": self.settings.meta_access_token,
                "level": "account",
                "fields": "spend,actions,action_values",
                "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
                "limit": 100,
            },
            timeout=self.settings.http_timeout_seconds,
            retries=self.settings.http_retries,
        )
        rows = [row for row in payload.get("data", []) if isinstance(row, dict)]
        return metrics_from_rows(rows)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


def _sum_first(rows: list[dict[str, Any]], field: str, action_types: tuple[str, ...]) -> Decimal:
    for action_type in action_types:
        total = Decimal("0")
        for row in rows:
            for action in row.get(field, []) or []:
                if isinstance(action, dict) and action.get("action_type") == action_type:
                    total += _decimal(action.get("value"))
        if total > 0:
            return total
    return Decimal("0")


def metrics_from_rows(rows: list[dict[str, Any]]) -> AdsMetrics:
    return AdsMetrics(
        spend=sum((_decimal(row.get("spend")) for row in rows), Decimal("0")),
        messages=_sum_first(rows, "actions", MESSAGE_ACTIONS),
        purchases=_sum_first(rows, "actions", PURCHASE_ACTIONS),
        meta_revenue=_sum_first(rows, "action_values", PURCHASE_ACTIONS),
    )
