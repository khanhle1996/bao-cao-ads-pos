---
name: ads-pos-reporting-bot
description: Send branded Meta Ads and Pancake POS performance reports to Telegram, split by brand with readable icon-prefixed messages. Use when Codex needs to generate, resend, package, configure, or troubleshoot the Ads/POS Telegram report for Lysilk, Jennie Choo, or Say Studios using Meta Ads Manager and Pancake POS data.
---

# Ads Pos Reporting Bot

## Overview

Use this skill to send the 3/5/7-day Ads/POS report to Telegram. The bundled script reads existing external `.env` files, fetches Meta Ads account insights and Pancake POS orders, then sends one Telegram message per brand.

Never paste or store tokens in chat, markdown, or this skill folder. The report is read-only for Meta/POS; the only live mutation is sending Telegram messages.

## Quick Start

From this skill folder:

```bash
WORK_REPORT_TELEGRAM_CHAT_ID=-5034668361 scripts/send_report.sh
```

Use `--dry-run` to preview without sending:

```bash
WORK_REPORT_TELEGRAM_CHAT_ID=-5034668361 scripts/send_report.sh --dry-run
```

## Workflow

1. Confirm external `.env` files exist and do not expose secrets.
2. Run a dry-run first when changing mappings, formatting, or destination chat.
3. Send the report with `scripts/send_report.sh`.
4. If Pancake POS is slow, keep timeout at 30 seconds and retry at 1; the script falls back to per-day POS queries.
5. If Telegram fails, verify the bot is a member of the group and the group chat ID is correct.

## Output Format

The script sends one Telegram message per brand. Each message includes:

- Bold brand name.
- 3-day, 5-day, and 7-day blocks.
- Ads spend, POS revenue, POS orders, CP/DT POS, ROAS POS.
- Ads Manager revenue, CP/DT Ads Manager, ROAS Ads Manager.
- Messages and Meta purchases.
- Source breakdown for ad accounts and POS shops.

## Resources

- `scripts/send_report.sh`: standard entrypoint for sending or dry-running the report.
- `scripts/work_report_bot/`: Python implementation.
- `scripts/config/brands.json`: default brand/account/shop mapping.
- `references/configuration.md`: environment variables, mapping, and troubleshooting notes.

Read `references/configuration.md` when changing destination chat, env paths, or brand mapping.
