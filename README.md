# Bot AI bao cao cong viec

Bot gui bao cao Ads/POS tu dong ve Telegram.

## Lenh chay

Chay trong thu muc nay:

```bash
python3 -m work_report_bot run-once --dry-run --windows 3,5,7
python3 -m work_report_bot run-once --windows 3,5,7
python3 -m work_report_bot daemon
bin/start-daemon.sh
bin/stop-daemon.sh
```

## Lich tu dong

Mac dinh daemon gui bao cao luc:

- 08:00
- 21:00

Mui gio: `Asia/Ho_Chi_Minh`.

State chong gui trung nam o `data/report_runs.sqlite3`.

## Secrets

Thu muc nay khong luu token.

Bot doc cau hinh tu:

- `../Facebook Ads Bot/.env`
- `../Kết nối POS Pancake/.env`

## Cai tu dong bang launchd

File LaunchAgent mau nam tai:

```bash
launchd/com.codex.work-report-bot.plist
```

Sau khi copy vao `~/Library/LaunchAgents/` va load bang `launchctl`, bot se tu chay daemon khi user dang nhap.

Luu y: neu project nam trong Desktop va launchd bi macOS chan quyen doc file, dung `bin/start-daemon.sh`
de chay nen trong user session hien tai.
