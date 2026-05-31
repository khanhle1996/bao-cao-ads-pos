# Configuration

This skill sends branded Meta Ads and Pancake POS reports to Telegram.

## Required external secrets

Do not store secrets inside the skill folder. Point the script at existing `.env` files:

- `WORK_REPORT_FB_ENV_PATH`: `.env` containing `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_ID`, `META_ACCESS_TOKEN`, and optional `META_API_VERSION`.
- `WORK_REPORT_POS_ENV_PATH`: `.env` containing `PANCAKE_ACCESS_TOKEN` and optional `PANCAKE_BASE_URL`.

Optional overrides:

- `WORK_REPORT_TELEGRAM_CHAT_ID`: send to a specific Telegram chat/group instead of `TELEGRAM_ALLOWED_CHAT_ID`.
- `WORK_REPORT_HTTP_TIMEOUT_SECONDS`: default `30`.
- `WORK_REPORT_HTTP_RETRIES`: default `1`.
- `WORK_REPORT_WINDOWS`: default `3,5,7`.
- `WORK_REPORT_SLOT_LABEL`: default `08:00`.
- `WORK_REPORT_BRANDS_PATH`: custom brand mapping JSON.
- `WORK_REPORT_STATE_PATH`: scheduler state SQLite path.

## Current brand mapping

Default mapping is in `scripts/config/brands.json`.

- Lysilk: Meta ad accounts `333437301521518`, `3219708974940795`; POS shop `638801`.
- Jennie Choo: Meta ad account `692061999078661`; POS shop `20094936`.
- Say Studios: Meta ad account `1738022036969927`; POS shop `2619361`.

## Standard command

```bash
WORK_REPORT_TELEGRAM_CHAT_ID=-5034668361 scripts/send_report.sh
```

The script sends 3 Telegram messages, one per brand, using HTML formatting with bold brand names and icon-prefixed rows.
