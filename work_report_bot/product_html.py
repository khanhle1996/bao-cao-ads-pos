from __future__ import annotations

import traceback
from datetime import datetime
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from .meta import CampaignRec
from .product_report import ProductRow

_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

_NAV = (
    '<nav style="background:#1a1a2e;padding:12px 20px;display:flex;align-items:center;gap:24px;">'
    '<a href="index.html" style="color:#aaa;text-decoration:none;font-size:14px;">📊 Báo cáo tổng hợp</a>'
    '<a href="san-pham.html" style="color:#fff;text-decoration:none;font-weight:600;font-size:14px;">🛍 Sản phẩm cần chạy Ads</a>'
    "</nav>"
)

_GROUP_META: dict[str, tuple[str, str, str]] = {
    "scale":        ("🚀 Đang Scale tốt",                                           "#e8f5e9", "#27ae60"),
    "need_media":   ("⚠️ Cần media mới — tồn hàng nhưng thiếu campaign hiệu quả",  "#fff3e0", "#e67e22"),
    "reduce_pause": ("⏸ Nên giảm / tắt",                                           "#fffde7", "#f39c12"),
    "no_stock":     ("⛔ Dừng ads — hết / sắp hết hàng",                           "#ffebee", "#e74c3c"),
}


def render_product_html(
    rows: list[ProductRow],
    total_spend: Decimal,
    total_revenue: Decimal,
    generated_at: datetime | None = None,
) -> str:
    try:
        return _render(rows, total_spend, total_revenue, generated_at)
    except Exception:
        tb = escape(traceback.format_exc())
        return (
            '<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8">'
            "<title>Lỗi render</title></head><body>"
            "<h1>Lỗi khi tạo trang báo cáo sản phẩm</h1>"
            f"<pre>{tb}</pre></body></html>"
        )


def _fmt_money(v: Decimal) -> str:
    if v <= 0:
        return "—"
    m = int(v)
    if m >= 1_000_000_000:
        return f"{m/1_000_000_000:.1f}tỷ"
    if m >= 1_000_000:
        return f"{m/1_000_000:.1f}tr"
    if m >= 1_000:
        return f"{m/1_000:.0f}k"
    return f"{m:,}"


def _fmt_num(v: int | None) -> str:
    if v is None:
        return "—"
    return f"{v:,}".replace(",", ".")


def _campaign_cell(campaigns: list[CampaignRec], css_class: str) -> str:
    if not campaigns:
        return "—"
    parts = []
    for c in campaigns[:3]:
        roas_str = f"{c.roas:.2f}" if c.roas > 0 else "—"
        name = c.campaign_name
        name_short = (name[:38] + "…") if len(name) > 38 else name
        parts.append(
            f'<span class="{css_class}" title="{escape(name)}">'
            f"{escape(name_short)} (ROAS {roas_str})</span>"
        )
    if len(campaigns) > 3:
        parts.append(f'<span style="color:#aaa">+{len(campaigns)-3} khác</span>')
    return "<br>".join(parts)


def _row_html(row: ProductRow, group: str) -> str:
    code = escape(row.product_code)
    sold = _fmt_num(row.sold_30d)
    stock = _fmt_num(row.stock_web)
    note = escape(row.stock_note)

    if group == "no_stock":
        return (
            f"<tr>"
            f'<td class="code">{code}</td>'
            f"<td>{stock}</td>"
            f"<td>{sold}</td>"
            f'<td class="bad">{note or "—"}</td>'
            f"</tr>"
        )

    good_cell = _campaign_cell(row.scale_campaigns, "good")
    bad_cell = _campaign_cell(row.reduce_campaigns + row.pause_campaigns, "bad" if row.pause_campaigns else "warn")
    note_class = "bad" if "Hết hàng" in row.stock_note else ("warn" if row.stock_note and "Chưa" not in row.stock_note else "")
    note_cell = f'<span class="{note_class}">{note}</span>' if note else "✓"

    return (
        f"<tr>"
        f'<td class="code">{code}</td>'
        f"<td>{sold}</td>"
        f"<td>{stock}</td>"
        f"<td>{good_cell}</td>"
        f"<td>{bad_cell}</td>"
        f"<td>{note_cell}</td>"
        f"</tr>"
    )


def _render(
    rows: list[ProductRow],
    total_spend: Decimal,
    total_revenue: Decimal,
    generated_at: datetime | None,
) -> str:
    now = (generated_at or datetime.now(_TZ)).astimezone(_TZ)
    gen_str = now.strftime("%H:%M %d/%m/%Y")

    roas = float(total_revenue / total_spend) if total_spend > 0 else 0.0
    cpdt = float(total_spend / total_revenue * 100) if total_revenue > 0 else None
    roas_str = f"{roas:.2f}" if roas > 0 else "—"
    cpdt_str = f"{cpdt:.1f}%" if cpdt else "—"

    by_group: dict[str, list[ProductRow]] = {}
    for row in rows:
        by_group.setdefault(row.group, []).append(row)

    sections = ""
    for group in ("scale", "need_media", "reduce_pause", "no_stock"):
        group_rows = by_group.get(group, [])
        label, bg_color, accent = _GROUP_META[group]
        count = len(group_rows)

        if not group_rows:
            sections += (
                f'<section class="group" style="--grp:{accent}">'
                f"<h2>{escape(label)} <span class=\"count\">(0)</span></h2>"
                f'<p class="empty">Không có sản phẩm nào.</p>'
                f"</section>\n"
            )
            continue

        if group == "no_stock":
            thead = "<tr><th>Mã SP</th><th>Tồn Web</th><th>Bán 30N</th><th>Cảnh báo</th></tr>"
        else:
            thead = "<tr><th>Mã SP</th><th>Bán 30N</th><th>Tồn Web</th><th>Campaign tốt (ROAS)</th><th>Campaign kém (ROAS)</th><th>Tồn kho</th></tr>"

        tbody_rows = "".join(_row_html(r, group) for r in group_rows)

        sections += (
            f'<section class="group" style="--grp:{accent}">\n'
            f"  <h2>{escape(label)} <span class=\"count\">({count})</span></h2>\n"
            f'  <div class="table-wrap">\n'
            f"    <table>\n"
            f"      <thead>{thead}</thead>\n"
            f'      <tbody style="background:{bg_color}">{tbody_rows}</tbody>\n'
            f"    </table>\n"
            f"  </div>\n"
            f"</section>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sản phẩm cần chạy Ads — Antigravity</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           background: #f5f6fa; color: #222; font-size: 14px; }}
    .container {{ max-width: 1500px; margin: 0 auto; padding: 20px 16px 48px; }}
    header {{ margin: 20px 0 28px; }}
    header h1 {{ font-size: 20px; font-weight: 700; color: #1a1a2e; }}
    .meta {{ margin-top: 8px; font-size: 13px; color: #555; }}
    .meta span {{ margin-right: 24px; }}
    .group {{ margin-bottom: 32px; }}
    .group h2 {{ font-size: 15px; font-weight: 600; color: var(--grp);
                 border-left: 4px solid var(--grp); padding-left: 10px;
                 margin-bottom: 10px; }}
    .count {{ font-size: 13px; font-weight: 400; color: #888; }}
    .table-wrap {{ overflow-x: auto; border-radius: 8px;
                   box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; font-size: 13px; }}
    th {{ background: #f0f0f0; text-align: left; padding: 8px 12px; font-size: 11px;
          font-weight: 700; color: #555; text-transform: uppercase; letter-spacing: .4px;
          white-space: nowrap; }}
    td {{ padding: 7px 12px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }}
    tr:last-child td {{ border-bottom: none; }}
    .code {{ font-weight: 700; font-size: 14px; color: #1a1a2e; white-space: nowrap; }}
    .good {{ color: #27ae60; font-weight: 500; }}
    .warn {{ color: #e67e22; }}
    .bad  {{ color: #e74c3c; font-weight: 500; }}
    .empty {{ color: #aaa; font-style: italic; padding: 6px 0; font-size: 13px; }}
    @media (max-width: 600px) {{ th, td {{ padding: 6px 8px; font-size: 12px; }} }}
  </style>
</head>
<body>
{_NAV}
<div class="container">
  <header>
    <h1>🛍 Sản phẩm cần chạy Ads — Lysilk</h1>
    <div class="meta">
      <span>📊 7 ngày — Chi: <strong>{_fmt_money(total_spend)}</strong> &nbsp;|&nbsp;
        DT: <strong>{_fmt_money(total_revenue)}</strong> &nbsp;|&nbsp;
        ROAS: <strong>{roas_str}</strong> &nbsp;|&nbsp;
        CP/DT: <strong>{cpdt_str}</strong></span>
      <span>🕐 Cập nhật: <strong>{gen_str}</strong></span>
    </div>
  </header>
  {sections}
</div>
</body>
</html>"""
