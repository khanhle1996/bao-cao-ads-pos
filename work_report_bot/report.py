from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import escape
from zoneinfo import ZoneInfo

from .config import Settings
from .meta import AdsMetrics, BillingInfo, MetaClient
from .pancake import PancakeClient, PartialPosError, PosMetrics


@dataclass(frozen=True)
class SourceResult:
    source_id: str
    metrics: AdsMetrics | PosMetrics
    error: str | None = None


@dataclass(frozen=True)
class BrandWindowResult:
    brand_name: str
    ads: tuple[SourceResult, ...]
    pos: tuple[SourceResult, ...]

    @property
    def ads_total(self) -> AdsMetrics:
        total = AdsMetrics()
        for item in self.ads:
            if isinstance(item.metrics, AdsMetrics):
                total = total.add(item.metrics)
        return total

    @property
    def pos_total(self) -> PosMetrics:
        total = PosMetrics()
        for item in self.pos:
            if isinstance(item.metrics, PosMetrics):
                total = total.add(item.metrics)
        return total


@dataclass(frozen=True)
class WindowReport:
    days: int
    since: date
    until: date
    brands: tuple[BrandWindowResult, ...]


def build_reports(settings: Settings, windows: tuple[int, ...], now: datetime | None = None) -> tuple[WindowReport, ...]:
    tz = ZoneInfo(settings.report_timezone)
    current = now.astimezone(tz) if now else datetime.now(tz)
    today = current.date()
    meta = MetaClient(settings)
    pancake = PancakeClient(settings)
    reports: list[WindowReport | None] = [None] * len(windows)
    yesterday = today - timedelta(days=1)
    with ThreadPoolExecutor(max_workers=max(1, len(windows))) as executor:
        futures = {}
        for index, days in enumerate(windows):
            since = yesterday - timedelta(days=max(days, 1) - 1)
            future = executor.submit(_build_window_report, settings, meta, pancake, days, since, yesterday)
            futures[future] = index
        for future in as_completed(futures):
            reports[futures[future]] = future.result()
    return tuple(report for report in reports if report is not None)


def _build_window_report(
    settings: Settings,
    meta: MetaClient,
    pancake: PancakeClient,
    days: int,
    since: date,
    until: date,
) -> WindowReport:
    brand_results: list[BrandWindowResult | None] = [None] * len(settings.brands)
    ads_by_brand: dict[int, list[SourceResult | None]] = {
        index: [None] * len(brand.ad_account_ids)
        for index, brand in enumerate(settings.brands)
    }
    pos_by_brand: dict[int, list[SourceResult | None]] = {
        index: [None] * len(brand.pos_shop_ids)
        for index, brand in enumerate(settings.brands)
    }

    workers = max(1, sum(len(brand.ad_account_ids) + len(brand.pos_shop_ids) for brand in settings.brands))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for brand_index, brand in enumerate(settings.brands):
            for source_index, account_id in enumerate(brand.ad_account_ids):
                future = executor.submit(_fetch_ads, meta, account_id, since, until)
                futures[future] = ("ads", brand_index, source_index)
            for source_index, shop_id in enumerate(brand.pos_shop_ids):
                future = executor.submit(_fetch_pos, pancake, shop_id, since, until, brand.pos_delivering_statuses)
                futures[future] = ("pos", brand_index, source_index)

        for future in as_completed(futures):
            source_type, brand_index, source_index = futures[future]
            if source_type == "ads":
                ads_by_brand[brand_index][source_index] = future.result()
            else:
                pos_by_brand[brand_index][source_index] = future.result()

    for brand_index, brand in enumerate(settings.brands):
        ads_results = tuple(item for item in ads_by_brand[brand_index] if item is not None)
        pos_results = tuple(item for item in pos_by_brand[brand_index] if item is not None)
        brand_results[brand_index] = BrandWindowResult(brand.name, ads_results, pos_results)

    return WindowReport(days=days, since=since, until=until, brands=tuple(brand_results))


def _fetch_ads(meta: MetaClient, account_id: str, since: date, until: date) -> SourceResult:
    try:
        return SourceResult(account_id, meta.account_insights(account_id, since, until))
    except Exception as exc:
        return SourceResult(account_id, AdsMetrics(), _safe_error(exc))


def _fetch_pos(
    pancake: PancakeClient,
    shop_id: str,
    since: date,
    until: date,
    delivering_statuses: frozenset[str] = frozenset(),
) -> SourceResult:
    try:
        return SourceResult(shop_id, pancake.analytics_sale(shop_id, since, until))
    except Exception as analytics_exc:
        import sys as _sys
        print(f"[analytics-fallback] shop={shop_id}: {analytics_exc}", file=_sys.stderr)
    try:
        return SourceResult(shop_id, pancake.shop_orders(shop_id, since, until, delivering_statuses=delivering_statuses))
    except PartialPosError as exc:
        return SourceResult(shop_id, exc.metrics, _safe_error(exc))
    except Exception as exc:
        return SourceResult(shop_id, PosMetrics(), _safe_error(exc))


def build_billing_data(settings: Settings, now: datetime | None = None) -> list[BillingInfo]:
    tz = ZoneInfo(settings.report_timezone)
    current = now.astimezone(tz) if now else datetime.now(tz)
    today = current.date()
    meta = MetaClient(settings)

    accounts = [
        (acc.name, acc.account_id, acc.billing_threshold)
        for acc in settings.billing_accounts if acc.account_id
    ]
    if not accounts:
        return []

    results: list[BillingInfo | None] = [None] * len(accounts)
    with ThreadPoolExecutor(max_workers=len(accounts)) as executor:
        futures = {
            executor.submit(_fetch_billing, meta, name, account_id, threshold, today): i
            for i, (name, account_id, threshold) in enumerate(accounts)
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()

    return [r for r in results if r is not None]


def _fetch_billing(meta: MetaClient, name: str, account_id: str, billing_threshold: int, today: date) -> BillingInfo:
    from decimal import Decimal as D
    try:
        return meta.fetch_account_billing(account_id, name, D(str(billing_threshold)), today)
    except Exception as exc:
        return BillingInfo(
            account_id=account_id,
            name=name,
            currency="VND",
            yesterday_spend=D("0"),
            today_spend=D("0"),
            billing_threshold=D(str(billing_threshold)),
            monthly_spend=D("0"),
            three_day_spend=D("0"),
            error=_safe_error(exc),
        )


def render_telegram(slot_label: str, reports: tuple[WindowReport, ...], split_by_brand: bool = False) -> list[str]:
    if not reports:
        return [f"Báo cáo Ads/POS {slot_label}: không có dữ liệu."]
    if split_by_brand:
        return _render_by_brand(slot_label, reports)

    messages = []
    header = f"Báo cáo Ads/POS {slot_label}\nNgày gửi: {reports[0].until.isoformat()}"
    sections = [header]
    for report in reports:
        section = _render_window(report)
        candidate = "\n\n".join([*sections, section])
        if len(candidate) > 3600 and len(sections) > 1:
            messages.append("\n\n".join(sections))
            sections = [header, section]
        else:
            sections.append(section)
    if sections:
        messages.append("\n\n".join(sections))
    return messages


def _render_window(report: WindowReport) -> str:
    lines = [f"{report.days} ngày ({report.since.isoformat()} đến {report.until.isoformat()})"]
    for brand in report.brands:
        lines.extend(_render_brand_lines(brand, prefix="- "))
    return "\n".join(lines)


def _render_by_brand(slot_label: str, reports: tuple[WindowReport, ...]) -> list[str]:
    brand_names = [brand.brand_name for brand in reports[0].brands]
    messages = []
    for brand_name in brand_names:
        lines = [
            f"📊 <b>BÁO CÁO ADS/POS {escape(slot_label)}</b>",
            f"🏷️ Nhãn: <b>{escape(brand_name)}</b>",
            f"📅 Ngày: {reports[0].until.isoformat()}",
        ]
        breakdown_lines: list[str] = []
        for report in reports:
            brand = next((item for item in report.brands if item.brand_name == brand_name), None)
            if brand is None:
                continue
            lines.extend(["", *_render_brand_summary(report, brand)])
            if not breakdown_lines:
                breakdown_lines = _render_breakdown_lines(brand)
        if breakdown_lines:
            lines.extend(["", "🔎 <b>Chi tiết nguồn</b>", *breakdown_lines])
        messages.append("\n".join(lines))
    return messages


def _render_brand_summary(report: WindowReport, brand: BrandWindowResult) -> list[str]:
    ads = brand.ads_total
    pos = brand.pos_total
    return [
        f"🕒 <b>{report.days} ngày</b> | {report.since.isoformat()} đến {report.until.isoformat()}",
        f"💸 Chi Ads: {_money(ads.spend)}",
        f"🧾 DT POS: {_money(pos.revenue)} | Đơn: {pos.orders} | CP/DT: {_percent(ads.spend, pos.revenue)} | ROAS: {_ratio(pos.revenue, ads.spend)}",
        f"📈 DT Ads Manager: {_money(ads.meta_revenue)} | CP/DT: {_percent(ads.spend, ads.meta_revenue)} | ROAS: {_ratio(ads.meta_revenue, ads.spend)}",
        f"💬 Tin nhắn: {ads.messages:,.0f} | Mua Meta: {ads.purchases:,.0f}",
        *_render_warning_lines(brand),
    ]


def _render_breakdown_lines(brand: BrandWindowResult) -> list[str]:
    return [
        f"• Ads: {_source_breakdown(brand.ads)}",
        f"• POS: {_source_breakdown(brand.pos)}",
    ]


def _render_brand_lines(brand: BrandWindowResult, prefix: str) -> list[str]:
    ads = brand.ads_total
    pos = brand.pos_total
    pos_cpdt = _percent(ads.spend, pos.revenue)
    pos_roas = _ratio(pos.revenue, ads.spend)
    meta_cpdt = _percent(ads.spend, ads.meta_revenue)
    meta_roas = _ratio(ads.meta_revenue, ads.spend)
    lines = [
        f"{prefix}{brand.brand_name}: Chi phí Ads {_money(ads.spend)} | Tin nhắn {ads.messages:,.0f} | Mua Meta {ads.purchases:,.0f}",
        f"  Doanh thu POS: {_money(pos.revenue)} | Đơn POS {pos.orders} | CP/DT POS {pos_cpdt} | ROAS POS {pos_roas}",
        f"  Doanh thu Ads Manager: {_money(ads.meta_revenue)} | CP/DT Ads Manager {meta_cpdt} | ROAS Ads Manager {meta_roas}",
        f"  Tài khoản Ads: {_source_breakdown(brand.ads)}",
        f"  POS shop: {_source_breakdown(brand.pos)}",
    ]
    return [*lines, *_render_warning_lines(brand, indent="  ")]


def _render_warning_lines(brand: BrandWindowResult, indent: str = "") -> list[str]:
    warnings = [f"{item.source_id}: {item.error}" for item in (*brand.ads, *brand.pos) if item.error]
    if not warnings:
        return []
    return [indent + "📣 Cảnh báo: " + " | ".join(escape(item) for item in warnings)]


def _source_breakdown(items: tuple[SourceResult, ...]) -> str:
    parts = []
    for item in items:
        if isinstance(item.metrics, AdsMetrics):
            parts.append(f"{item.source_id} {_money(item.metrics.spend)}")
        elif isinstance(item.metrics, PosMetrics):
            parts.append(f"{item.source_id} {_money(item.metrics.revenue)}/{item.metrics.orders} đơn")
    return "; ".join(parts) if parts else "không có"


def _money(value: Decimal) -> str:
    return f"{value:,.0f} VND".replace(",", ".")


def _percent(numerator: Decimal, denominator: Decimal) -> str:
    if denominator <= 0:
        return "0.00%"
    return f"{(numerator / denominator * Decimal('100')):.2f}%"


def _ratio(numerator: Decimal, denominator: Decimal) -> str:
    if denominator <= 0:
        return "0.00"
    return f"{(numerator / denominator):.2f}"


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    if len(text) > 180:
        return text[:177] + "..."
    return text
