from __future__ import annotations

import json
import re
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
    billing_threshold: Decimal
    monthly_spend: Decimal
    three_day_spend: Decimal
    error: str | None = None

    @property
    def remaining_cap(self) -> Decimal | None:
        """Remaining threshold = billing_threshold - monthly_spend. None if threshold not set."""
        if self.billing_threshold > 0:
            return max(Decimal("0"), self.billing_threshold - self.monthly_spend)
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

    def fetch_account_billing(self, account_id: str, name: str, billing_threshold: Decimal, today: date) -> BillingInfo:
        yesterday = today - timedelta(days=1)
        three_days_ago = today - timedelta(days=3)
        since_month = today.replace(day=1)

        with ThreadPoolExecutor(max_workers=4) as executor:
            f_yest = executor.submit(self.account_insights, account_id, yesterday, yesterday)
            f_today = executor.submit(self.account_insights, account_id, today, today)
            f_3day = executor.submit(self.account_insights, account_id, three_days_ago, yesterday)
            f_month = executor.submit(self.account_insights, account_id, since_month, today)

        def _spend(f) -> Decimal:  # noqa: ANN001
            try:
                return f.result().spend
            except Exception:
                return Decimal("0")

        return BillingInfo(
            account_id=account_id,
            name=name,
            currency="VND",
            yesterday_spend=_spend(f_yest),
            today_spend=_spend(f_today),
            billing_threshold=billing_threshold,
            monthly_spend=_spend(f_month),
            three_day_spend=_spend(f_3day),
        )

    def campaign_diagnose(
        self,
        ad_account_ids: list[str],
        since: date,
        until: date,
        target_cpdt: float = 28.0,
        min_spend: int = 200_000,
    ) -> list[CampaignRec]:
        raw_rows: list[dict[str, Any]] = []
        for account_id in ad_account_ids:
            account = account_id if account_id.startswith("act_") else f"act_{account_id}"
            url: str | None = f"{self.base_url}/{account}/insights"
            params: dict[str, Any] = {
                "access_token": self.settings.meta_access_token,
                "level": "campaign",
                "fields": "campaign_id,campaign_name,spend,actions,action_values",
                "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
                "limit": 500,
            }
            first_call = True
            while url:
                payload = get_json(
                    url,
                    params if first_call else {},
                    timeout=self.settings.http_timeout_seconds,
                    retries=self.settings.http_retries,
                )
                first_call = False
                raw_rows.extend(row for row in payload.get("data", []) if isinstance(row, dict))
                url = (payload.get("paging") or {}).get("next")

        min_spend_dec = Decimal(str(min_spend))
        result: list[CampaignRec] = []
        for row in raw_rows:
            spend = _decimal(row.get("spend"))
            if spend < min_spend_dec:
                continue
            revenue = _sum_first([row], "action_values", PURCHASE_ACTIONS)
            roas = float(revenue / spend) if spend > 0 else 0.0
            cpdt_pct: float | None = float(spend / revenue * 100) if revenue > 0 else None
            if revenue > 0 and cpdt_pct is not None and cpdt_pct < target_cpdt:
                action = "scale"
            elif revenue == 0:
                action = "pause"
            elif cpdt_pct is not None and cpdt_pct >= target_cpdt * 1.6:
                action = "pause"
            elif cpdt_pct is not None and cpdt_pct >= target_cpdt:
                action = "reduce"
            else:
                action = "watch"
            name = str(row.get("campaign_name") or row.get("campaign_id") or "")
            result.append(CampaignRec(
                campaign_id=str(row.get("campaign_id") or ""),
                campaign_name=name,
                spend=spend,
                revenue=revenue,
                roas=roas,
                cpdt_pct=cpdt_pct,
                action=action,
                product_codes=_extract_product_codes(name),
            ))
        return result

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


_CODE_SPLIT_RE = re.compile(r'[_\s,;|/\\]+')
_CODE_PAT_RE = re.compile(r'^[A-Z]{1,3}\d{2,5}$')


def _extract_product_codes(name: str) -> tuple[str, ...]:
    tokens = _CODE_SPLIT_RE.split(name.upper())
    seen: dict[str, None] = {}
    for t in tokens:
        if _CODE_PAT_RE.match(t):
            seen[t] = None
    return tuple(seen)


@dataclass(frozen=True)
class CampaignRec:
    campaign_id: str
    campaign_name: str
    spend: Decimal
    revenue: Decimal
    roas: float
    cpdt_pct: float | None  # None if revenue == 0
    action: str  # "scale" | "reduce" | "pause" | "watch"
    product_codes: tuple[str, ...]
