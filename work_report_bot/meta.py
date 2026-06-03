from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
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


@dataclass(frozen=True)
class BillingInfo:
    account_id: str
    name: str
    currency: str
    yesterday_spend: Decimal
    today_spend: Decimal
    spend_cap: Decimal
    amount_spent: Decimal
    three_day_spend: Decimal
    error: str | None = None

    @property
    def remaining_cap(self) -> Decimal | None:
        """Remaining spend cap. None if no cap is set (spend_cap == 0)."""
        if self.spend_cap > 0:
            return max(Decimal("0"), self.spend_cap - self.amount_spent)
        return None

    @property
    def forecast_2days(self) -> Decimal:
        if self.three_day_spend <= 0:
            return Decimal("0")
        return self.three_day_spend * Decimal("2") / Decimal("3")


class MetaClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = f"https://graph.facebook.com/{settings.meta_api_version}"

    def _fetch_account_info(self, account: str) -> dict[str, Any]:
        return get_json(
            f"{self.base_url}/{account}",
            {
                "access_token": self.settings.meta_access_token,
                "fields": "name,currency,spend_cap,amount_spent",
            },
            timeout=self.settings.http_timeout_seconds,
            retries=self.settings.http_retries,
        )

    def fetch_account_billing(self, account_id: str, name: str, today: date) -> BillingInfo:
        account = account_id if account_id.startswith("act_") else f"act_{account_id}"
        yesterday = today - timedelta(days=1)
        three_days_ago = today - timedelta(days=3)

        with ThreadPoolExecutor(max_workers=4) as executor:
            f_info = executor.submit(self._fetch_account_info, account)
            f_yest = executor.submit(self.account_insights, account_id, yesterday, yesterday)
            f_today = executor.submit(self.account_insights, account_id, today, today)
            f_3day = executor.submit(self.account_insights, account_id, three_days_ago, yesterday)

        try:
            info = f_info.result()
            currency = str(info.get("currency", "VND"))
            spend_cap = _decimal(info.get("spend_cap", "0"))
            amount_spent = _decimal(info.get("amount_spent", "0"))
        except Exception:
            currency = "VND"
            spend_cap = Decimal("0")
            amount_spent = Decimal("0")

        def _spend(f) -> Decimal:  # noqa: ANN001
            try:
                return f.result().spend
            except Exception:
                return Decimal("0")

        return BillingInfo(
            account_id=account_id,
            name=name,
            currency=currency,
            yesterday_spend=_spend(f_yest),
            today_spend=_spend(f_today),
            spend_cap=spend_cap,
            amount_spent=amount_spent,
            three_day_spend=_spend(f_3day),
        )

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
