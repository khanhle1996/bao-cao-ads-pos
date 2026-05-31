# Tac vu 001 - Bao cao Ads/POS hang ngay

## Muc tieu

Xay dung bot bao cao tu dong gui ve Telegram qua `@FB_ADS_Antigravity_Bot`.

Bot gui bao cao vao 2 moc gio Viet Nam moi ngay:

- 08:00
- 21:00

Moi lan gui gom 3 ky bao cao:

- 3 ngay gan day
- 5 ngay gan day
- 7 ngay gan day

## Pham vi v1

- Bao cao gom tong hop theo hang va breakdown theo tung tai khoan quang cao/POS shop.
- Chua them top campaign.
- Chua dua de xuat tang/giam/tat ngan sach.
- Meta Ads va Pancake POS chi dung API read-only.
- Hanh dong mutate duy nhat la gui message Telegram.

## Mapping hang

| Hang | Tai khoan quang cao | POS Pancake shop |
| --- | --- | --- |
| Lysilk | 333437301521518, 3219708974940795 | 638801 |
| Jennie Choo | 692061999078661 | 20094936 |
| Say Studios | 1738022036969927 | 2619361 |

## Chi so can tinh

Moi hang va moi ky 3/5/7 ngay can co:

- Chi phi Ads
- Tin nhan
- Mua hang Meta neu co
- Doanh thu Meta neu co
- Doanh thu POS
- So don POS
- Chi phi / Doanh thu POS
- ROAS theo POS

## Cau hinh secrets

Khong luu token trong thu muc nay.

Bot doc secrets tu cac file local hien co:

- Telegram token/chat ID: `../Facebook Ads Bot/.env`
- Meta access token/API version: `../Facebook Ads Bot/.env`
- Pancake access token/base URL: `../Kết nối POS Pancake/.env`

## Lenh van hanh

Chay trong thu muc `Bot AI báo cáo công việc`:

```bash
python3 -m work_report_bot run-once --dry-run --windows 3,5,7
python3 -m work_report_bot run-once --windows 3,5,7
python3 -m work_report_bot daemon
```

## Trang thai

- 2026-05-28: Tao tac vu dau tien va trien khai module `work_report_bot`.
