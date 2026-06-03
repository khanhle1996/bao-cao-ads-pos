from __future__ import annotations

import traceback
from datetime import datetime, timedelta
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from .meta import BillingInfo
from .report import BrandWindowResult, WindowReport, _money, _percent, _ratio

_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def render_html(
    reports: tuple[WindowReport, ...],
    generated_at: datetime | None = None,
    billing_data: list[BillingInfo] | None = None,
) -> str:
    try:
        return _render(reports, generated_at, billing_data or [])
    except Exception:
        tb = escape(traceback.format_exc())
        return f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><title>Lỗi render</title></head>
<body><h1>Lỗi khi tạo trang báo cáo</h1><pre>{tb}</pre></body></html>"""


def _render(reports: tuple[WindowReport, ...], generated_at: datetime | None, billing_data: list[BillingInfo]) -> str:
    now = (generated_at or datetime.now(_TZ)).astimezone(_TZ)
    next_update = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    generated_str = now.strftime("%H:%M %d/%m/%Y")
    next_str = next_update.strftime("%H:%M %d/%m/%Y")

    sections = ""
    if not reports:
        sections = '<p class="no-data">Không có dữ liệu.</p>'
    else:
        brand_names = [b.brand_name for b in reports[0].brands]
        for brand_name in brand_names:
            cards = ""
            for report in reports:
                brand = next((b for b in report.brands if b.brand_name == brand_name), None)
                if brand is None:
                    continue
                cards += _window_card(report, brand)
            sections += f"""
<section class="brand">
  <h2>{escape(brand_name)}</h2>
  <div class="cards">{cards}</div>
</section>"""

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Báo cáo Ads/POS — Antigravity</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           background: #f5f6fa; color: #222; font-size: 15px; }}
    .container {{ max-width: 1500px; margin: 0 auto; padding: 20px 16px 40px; }}
    header {{ margin-bottom: 24px; }}
    header h1 {{ font-size: 22px; font-weight: 700; color: #1a1a2e; }}
    .meta {{ margin-top: 6px; font-size: 13px; color: #666; }}
    .meta span {{ margin-right: 16px; }}
    section.brand {{ margin-bottom: 32px; }}
    section.brand h2 {{ font-size: 18px; font-weight: 600; color: #2c3e50;
                        border-left: 4px solid #3498db; padding-left: 10px;
                        margin-bottom: 12px; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}
    @media (max-width: 1100px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} }}
    @media (max-width: 600px)  {{ .cards {{ grid-template-columns: 1fr; }} }}
    .card {{ background: #fff; border-radius: 10px; padding: 16px;
             box-shadow: 0 1px 6px rgba(0,0,0,.08); }}
    .card-title {{ font-size: 13px; font-weight: 600; color: #888;
                   text-transform: uppercase; letter-spacing: .5px; margin-bottom: 12px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    td {{ padding: 5px 0; vertical-align: top; }}
    td:first-child {{ color: #555; width: 55%; }}
    td:last-child {{ font-weight: 600; text-align: right; }}
    .divider {{ border: none; border-top: 1px solid #eee; margin: 8px 0; }}
    details {{ margin-top: 10px; font-size: 13px; color: #555; }}
    summary {{ cursor: pointer; color: #3498db; font-weight: 500; padding: 2px 0; }}
    .breakdown {{ margin-top: 6px; line-height: 1.7; }}
    .warning {{ margin-top: 10px; background: #fff3cd; border: 1px solid #ffc107;
                border-radius: 6px; padding: 8px 10px; font-size: 13px; color: #856404; }}
    .roas-good {{ color: #27ae60; }}
    .roas-mid  {{ color: #e67e22; }}
    .roas-bad  {{ color: #e74c3c; }}
    .no-data   {{ color: #888; font-style: italic; padding: 20px 0; }}
    .cards-5 {{ grid-template-columns: repeat(5, 1fr); }}
    @media (max-width: 1300px) {{ .cards-5 {{ grid-template-columns: repeat(3, 1fr); }} }}
    @media (max-width: 900px)  {{ .cards-5 {{ grid-template-columns: repeat(2, 1fr); }} }}
    @media (max-width: 600px)  {{ .cards-5 {{ grid-template-columns: 1fr; }} }}
    .threshold-warn {{ color: #e74c3c; font-weight: 700; }}
    .billing-card td:last-child {{ white-space: nowrap; }}
    .billing-input {{ display: flex; gap: 6px; margin-top: 12px; }}
    .billing-input input {{ flex: 1; padding: 5px 8px; border: 1px solid #ddd; border-radius: 6px;
                            font-size: 13px; min-width: 0; }}
    .billing-input input:focus {{ outline: none; border-color: #3498db; }}
    .billing-input button {{ padding: 5px 12px; background: #3498db; color: #fff; border: none;
                             border-radius: 6px; cursor: pointer; font-size: 13px; white-space: nowrap; }}
    .billing-input button:hover {{ background: #2980b9; }}
    footer {{ margin-top: 32px; font-size: 12px; color: #aaa; text-align: center; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>📊 Báo cáo Ads/POS — Antigravity</h1>
      <div class="meta">
        <span>🕐 Cập nhật lúc: <strong>{generated_str}</strong></span>
        <span>⏭ Dự kiến cập nhật: {next_str}</span>
      </div>
    </header>
    {sections}
    {_render_billing_section(billing_data)}
    <footer>Dữ liệu từ Meta Ads Manager &amp; Pancake POS · Tự động cập nhật mỗi 1 tiếng</footer>
  </div>
  {_billing_js()}
</body>
</html>"""


def _window_card(report: WindowReport, brand: BrandWindowResult) -> str:
    ads = brand.ads_total
    pos = brand.pos_total
    if report.days == 1:
        title = f"Hôm qua ({report.since.isoformat()})"
    else:
        title = f"{report.days} ngày ({report.since.isoformat()} – {report.until.isoformat()})"

    pos_roas_val = _ratio(pos.revenue, ads.spend)
    ads_roas_val = _ratio(ads.meta_revenue, ads.spend)

    rows = f"""
    <tr><td>💸 Chi phí Ads</td><td>{_fmt_money(ads.spend)}</td></tr>
    <tr><td colspan="2"><hr class="divider"></td></tr>
    <tr><td>🧾 Doanh thu POS</td><td>{_fmt_money(pos.revenue)}</td></tr>
    <tr><td>📦 Số đơn POS</td><td>{pos.orders if pos.orders else "—"}</td></tr>
    <tr><td>📉 CP/DT POS</td><td>{_percent(ads.spend, pos.revenue)}</td></tr>
    <tr><td>🚀 ROAS POS</td><td class="{_roas_class(pos_roas_val)}">{pos_roas_val}</td></tr>
    <tr><td colspan="2"><hr class="divider"></td></tr>
    <tr><td>📈 DT Ads Manager</td><td>{_fmt_money(ads.meta_revenue)}</td></tr>
    <tr><td>📉 CP/DT Ads</td><td>{_percent(ads.spend, ads.meta_revenue)}</td></tr>
    <tr><td>🚀 ROAS Ads</td><td class="{_roas_class(ads_roas_val)}">{ads_roas_val}</td></tr>
    <tr><td colspan="2"><hr class="divider"></td></tr>
    <tr><td>💬 Tin nhắn</td><td>{_fmt_decimal(ads.messages)}</td></tr>
    <tr><td>🛒 Mua Meta</td><td>{_fmt_decimal(ads.purchases)}</td></tr>"""

    breakdown = _breakdown_html(brand)
    warning = _warning_html(brand)

    return f"""
<div class="card">
  <div class="card-title">{escape(title)}</div>
  <table>{rows}</table>
  {breakdown}{warning}
</div>"""


def _breakdown_html(brand: BrandWindowResult) -> str:
    ads_parts = []
    for item in brand.ads:
        from .report import AdsMetrics
        if isinstance(item.metrics, AdsMetrics):
            ads_parts.append(f"{escape(item.source_id)}: {_fmt_money(item.metrics.spend)}")
    pos_parts = []
    for item in brand.pos:
        from .report import PosMetrics
        if isinstance(item.metrics, PosMetrics):
            pos_parts.append(f"{escape(item.source_id)}: {_fmt_money(item.metrics.revenue)} / {item.metrics.orders} đơn")
    if not ads_parts and not pos_parts:
        return ""
    lines = []
    if ads_parts:
        lines.append("Ads: " + "; ".join(ads_parts))
    if pos_parts:
        lines.append("POS: " + "; ".join(pos_parts))
    content = "<br>".join(lines)
    return f'<details><summary>Chi tiết nguồn</summary><div class="breakdown">{content}</div></details>'


def _warning_html(brand: BrandWindowResult) -> str:
    warnings = [
        f"{escape(item.source_id)}: {escape(item.error)}"
        for item in (*brand.ads, *brand.pos)
        if item.error
    ]
    if not warnings:
        return ""
    text = " | ".join(warnings)
    return f'<div class="warning">⚠️ {text}</div>'


def _fmt_money(value: Decimal) -> str:
    return _money(value) if value > 0 else "—"


def _fmt_decimal(value: Decimal) -> str:
    return f"{value:,.0f}".replace(",", ".") if value > 0 else "—"


def _roas_class(roas_str: str) -> str:
    try:
        v = float(roas_str)
    except ValueError:
        return ""
    if v >= 1.0:
        return "roas-good"
    if v >= 0.5:
        return "roas-mid"
    return "roas-bad"


def _billing_js() -> str:
    return """<script>
(function () {
  function fmtVnd(n) {
    return new Intl.NumberFormat('vi-VN').format(Math.round(n)) + ' VND';
  }
  function parsePending(s) {
    return parseInt(s.replace(/[^\\d]/g, ''), 10) || 0;
  }
  function applyValue(card) {
    var input = card.querySelector('.pending-input');
    var remCell = card.querySelector('.remaining-val');
    var threshold = parseInt(card.dataset.threshold, 10) || 0;
    var forecast = parseInt(card.dataset.forecast, 10) || 0;
    var pending = parsePending(input.value);
    if (!pending || !threshold) return;
    var remaining = Math.max(0, threshold - pending);
    remCell.textContent = remaining > 0 ? fmtVnd(remaining) : '\\u2014';
    var isWarn = forecast > 0 && remaining < forecast;
    remCell.className = 'remaining-val' + (isWarn ? ' threshold-warn' : '');
    try { localStorage.setItem('bp_' + card.dataset.accountId, input.value); } catch(e) {}
  }
  document.querySelectorAll('.billing-card').forEach(function (card) {
    var input = card.querySelector('.pending-input');
    var btn = card.querySelector('.done-btn');
    try {
      var saved = localStorage.getItem('bp_' + card.dataset.accountId);
      if (saved) { input.value = saved; applyValue(card); }
    } catch(e) {}
    btn.addEventListener('click', function () { applyValue(card); });
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') applyValue(card); });
  });
}());
</script>"""


def _render_billing_section(billing_data: list[BillingInfo]) -> str:
    if not billing_data:
        return ""
    cards = "".join(_billing_card(info) for info in billing_data)
    return f"""
<section class="brand">
  <h2>💳 Ứng tiền Ads</h2>
  <div class="cards cards-5">{cards}</div>
</section>"""


def _billing_card(info: BillingInfo) -> str:
    remaining = info.remaining_cap
    forecast = info.forecast_2days

    if remaining is not None:
        is_warn = forecast > 0 and remaining < forecast
        rem_class_attr = ' class="remaining-val threshold-warn"' if is_warn else ' class="remaining-val"'
        rem_str = _fmt_money(remaining)
    else:
        rem_class_attr = ' class="remaining-val"'
        rem_str = "—"

    threshold_str = _fmt_money(info.billing_threshold) if info.billing_threshold > 0 else "—"
    rows = f"""
    <tr><td>📅 Hôm qua</td><td>{_fmt_money(info.yesterday_spend)}</td></tr>
    <tr><td>⏱ Hôm nay</td><td>{_fmt_money(info.today_spend)}</td></tr>
    <tr><td colspan="2"><hr class="divider"></td></tr>
    <tr><td>📆 Tháng này</td><td>{_fmt_money(info.monthly_spend)}</td></tr>
    <tr><td>🎯 Ngưỡng</td><td>{threshold_str}</td></tr>
    <tr><td>✅ Còn lại</td><td{rem_class_attr}>{rem_str}</td></tr>
    <tr><td colspan="2"><hr class="divider"></td></tr>
    <tr><td>📊 Dự kiến 2 ngày</td><td>~{_fmt_money(forecast)}</td></tr>"""

    warning = f'<div class="warning">⚠️ {escape(info.error)}</div>' if info.error else ""

    return f"""
<div class="card billing-card" data-account-id="{escape(info.account_id)}" data-threshold="{int(info.billing_threshold)}" data-forecast="{int(forecast)}">
  <div class="card-title">{escape(info.name)}</div>
  <table>{rows}</table>
  {warning}
  <div class="billing-input">
    <input type="text" class="pending-input" placeholder="Số đang chờ thanh toán...">
    <button class="done-btn">Xác nhận</button>
  </div>
</div>"""
