from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import get_api_settings, get_settings
from .html_render import render_html
from .meta import MetaClient
from .pancake import PancakeClient
from .product_html import render_product_html
from .product_report import build_product_report
from .report import build_billing_data, build_reports, render_telegram
from .scheduler import run_daemon
from .telegram import send_messages


def parse_windows(value: str) -> tuple[int, ...]:
    windows = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not windows:
        raise argparse.ArgumentTypeError("windows must not be empty")
    if any(days <= 0 for days in windows):
        raise argparse.ArgumentTypeError("windows must be positive")
    return windows


def cmd_run_once(args: argparse.Namespace) -> int:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.report_timezone))
    slot_label = args.slot_label or now.strftime("%H:%M")
    reports = build_reports(settings, args.windows, now)
    messages = render_telegram(slot_label, reports, split_by_brand=args.split_by_brand)
    if args.dry_run:
        for index, message in enumerate(messages, start=1):
            if len(messages) > 1:
                print(f"--- message {index}/{len(messages)} ---")
            print(message)
        return 0
    send_messages(settings, messages)
    print(f"Sent {len(messages)} Telegram message(s).")
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    settings = get_settings()
    run_daemon(settings, args.windows, args.poll_seconds)
    return 0


def cmd_generate_product_html(args: argparse.Namespace) -> int:
    settings = get_api_settings()
    now = datetime.now(ZoneInfo(settings.report_timezone))
    since = (now - timedelta(days=7)).date()
    until = now.date()
    brand = settings.brands[0]  # Lysilk
    meta = MetaClient(settings)
    pancake = PancakeClient(settings)
    print(f"Fetching campaign data {since} → {until} ...")
    campaigns = meta.campaign_diagnose(list(brand.ad_account_ids), since, until)
    print(f"Fetched {len(campaigns)} campaigns. Fetching POS stock/sales (30 days) ...")
    pos_data = pancake.product_stock_and_sales(brand.pos_shop_ids[0], days=30)
    print(f"POS: {len(pos_data)} product codes. Building report ...")
    rows = build_product_report(campaigns, pos_data)
    total_spend = sum((c.spend for c in campaigns), Decimal("0"))
    total_revenue = sum((c.revenue for c in campaigns), Decimal("0"))
    html = render_product_html(rows, total_spend, total_revenue, generated_at=now)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Product report written to {output_path} ({len(rows)} products)")
    return 0


def cmd_generate_html(args: argparse.Namespace) -> int:
    settings = get_api_settings()
    now = datetime.now(ZoneInfo(settings.report_timezone))
    reports = build_reports(settings, args.windows, now)
    billing_data = build_billing_data(settings, now)
    html = render_html(reports, generated_at=now, billing_data=billing_data)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"HTML written to {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Daily Ads/POS work report bot.")
    sub = parser.add_subparsers(dest="command", required=True)

    run_once = sub.add_parser("run-once", help="Build and optionally send one report now.")
    run_once.add_argument("--windows", type=parse_windows, default=(3, 5, 7))
    run_once.add_argument("--dry-run", action="store_true")
    run_once.add_argument("--slot-label", help="Override report title time label, e.g. 08:00 or 21:00.")
    run_once.add_argument("--split-by-brand", action="store_true", help="Send one Telegram message per brand.")
    run_once.set_defaults(func=cmd_run_once)

    daemon = sub.add_parser("daemon", help="Run scheduler for 08:00 and 21:00 reports.")
    daemon.add_argument("--windows", type=parse_windows, default=(3, 5, 7))
    daemon.add_argument("--poll-seconds", type=int, default=30)
    daemon.set_defaults(func=cmd_daemon)

    gen_html = sub.add_parser("generate-html", help="Generate static HTML dashboard to docs/index.html.")
    gen_html.add_argument("--windows", type=parse_windows, default=(1, 3, 5, 7))
    gen_html.add_argument("--output", default="docs/index.html", help="Output file path.")
    gen_html.set_defaults(func=cmd_generate_html)

    gen_product = sub.add_parser("generate-product-html", help="Generate product ads/stock report to docs/san-pham.html.")
    gen_product.add_argument("--output", default="docs/san-pham.html", help="Output file path.")
    gen_product.set_defaults(func=cmd_generate_product_html)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))
