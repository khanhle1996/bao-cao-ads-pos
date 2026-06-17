from __future__ import annotations

import re as _re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .http import get_json, post_json

_ANALYTICS_BASE = "https://pos.pancake.vn/api/v1"
_HCM = ZoneInfo("Asia/Ho_Chi_Minh")


@dataclass(frozen=True)
class PosMetrics:
    orders: int = 0
    revenue: Decimal = Decimal("0")

    def add(self, other: "PosMetrics") -> "PosMetrics":
        return PosMetrics(orders=self.orders + other.orders, revenue=self.revenue + other.revenue)


class PancakeClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _fetch_products(self, shop_id: str, max_pages: int = 20, page_size: int = 100) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for page_number in range(1, max_pages + 1):
            payload = get_json(
                f"{self.settings.pancake_base_url}/shops/{shop_id}/products/variations",
                {
                    "access_token": self.settings.pancake_access_token,
                    "page_number": page_number,
                    "page_size": page_size,
                    "product_status": "not_locked",
                },
                timeout=self.settings.http_timeout_seconds,
                retries=self.settings.http_retries,
            )
            page = _extract_records(payload, ("products", "variations"))
            if not page:
                break
            records.extend(page)
            if len(page) < page_size:
                break
        return records

    def _fetch_raw_orders(self, shop_id: str, since: date, until: date, max_pages: int = 30, page_size: int = 100) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for page_number in range(1, max_pages + 1):
            payload = get_json(
                f"{self.settings.pancake_base_url}/shops/{shop_id}/orders",
                {
                    "access_token": self.settings.pancake_access_token,
                    "page": page_number,
                    "page_number": page_number,
                    "page_size": page_size,
                    "start_date": since.isoformat(),
                    "start_time": since.isoformat(),
                    "end_date": until.isoformat(),
                    "end_time": until.isoformat(),
                },
                timeout=self.settings.http_timeout_seconds,
                retries=self.settings.http_retries,
            )
            page = _extract_records(payload, ("orders",))
            if not page:
                break
            records.extend(page)
            if len(page) < page_size:
                break
            if page_number >= 10:
                print(f"[product-warn] shop={shop_id} {len(records)} orders at page {page_number}", file=sys.stderr)
        return records

    def product_stock_and_sales(self, shop_id: str, days: int = 30) -> dict[str, ProductSkuData]:
        until = date.today()
        since = until - timedelta(days=days - 1)

        # 1. Fetch all product variations → stock by code
        products = self._fetch_products(shop_id)
        code_variations: dict[str, list[tuple[str, int]]] = {}
        for product in products:
            variations = product.get("variations")
            if isinstance(variations, list) and variations:
                for v in variations:
                    if not isinstance(v, dict):
                        continue
                    sku = str(v.get("barcode") or v.get("custom_id") or product.get("custom_id") or "").strip().upper()
                    if not sku:
                        continue
                    stock = max(0, int(v.get("remain_quantity") or 0))
                    code = extract_product_code_from_sku(sku)
                    code_variations.setdefault(code, []).append((_variation_label(product, v), stock))
            else:
                sku = str(product.get("barcode") or product.get("custom_id") or "").strip().upper()
                if not sku:
                    continue
                stock = max(0, int(product.get("remain_quantity") or 0))
                code = extract_product_code_from_sku(sku)
                code_variations.setdefault(code, []).append((_variation_label(product, product), stock))

        # 2. Fetch orders → count sold per product code
        sold_by_code: dict[str, int] = {}
        try:
            orders = self._fetch_raw_orders(shop_id, since, until)
            for order in orders:
                if not _is_fulfilled(order):
                    continue
                for item in _order_items(order):
                    sku = _item_sku(item)
                    if not sku:
                        continue
                    qty = _item_quantity(item)
                    code = extract_product_code_from_sku(sku)
                    sold_by_code[code] = sold_by_code.get(code, 0) + qty
        except Exception as exc:
            print(f"[product-warn] order fetch failed: {exc}", file=sys.stderr)

        # 3. Build result
        result: dict[str, ProductSkuData] = {}
        for code, variations in code_variations.items():
            stock_web = sum(stock for _, stock in variations)
            sold = sold_by_code.get(code, 0)
            low = tuple(f"{label} ({stock})" for label, stock in variations if 0 < stock < 5)
            out = tuple(label for label, stock in variations if stock == 0)
            result[code] = ProductSkuData(
                product_code=code,
                sold_30d=sold,
                stock_web=stock_web,
                low_stock_sizes=low,
                out_of_stock_sizes=out,
            )
        return result

    def analytics_sale(self, shop_id: str, since: date, until: date) -> PosMetrics:
        since_str = datetime(since.year, since.month, since.day, 0, 0, 0, tzinfo=_HCM).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        until_str = datetime(until.year, until.month, until.day, 23, 59, 59, tzinfo=_HCM).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.999Z")
        payload = {
            "params": {
                "returned_record": "updated_at",
                "success_record": "inserted_at",
                "success_status": 1,
                "since": since_str,
                "until": until_str,
                "split_by": ["Time.day"],
                "select_fields": ["cod", "prepaid", "partner_fee", "total_order_count", "order_count", "shipping_fee", "exchange_order_count", "canceled_order_count", "price", "discount", "surcharge", "fee_marketplace", "exchange_payment", "affiliate_price", "marketplace_voucher", "diff_shipping_fee"],
                "render_fields": ["total_order_count", "success_order_count", "canceled_order_count", "revenue", "sales"],
                "pagination": {"pageSize": 100, "current": 1},
            }
        }
        response = post_json(
            f"{_ANALYTICS_BASE}/shops/{shop_id}/analytics/sale",
            params={"access_token": self.settings.pancake_access_token},
            body=payload,
            timeout=self.settings.http_timeout_seconds,
            retries=self.settings.http_retries,
        )
        summary = response.get("summary") or {}
        data = response.get("data") or []
        print(f"[analytics-debug] shop={shop_id} {since}→{until} top_keys={list(response.keys())} summary={dict(summary)}", file=sys.stderr)
        for row in data:
            day = row.get("Time.day", "?")
            print(f"[analytics-debug]   row {day}: ok={row.get('success_order_count')} rev={row.get('revenue')} sales={row.get('sales')} price={row.get('price')}", file=sys.stderr)
        orders = int(summary.get("success_order_count") or 0)
        revenue = _decimal(summary.get("revenue") or 0)
        print(f"[analytics] shop={shop_id} {since}→{until} orders={orders} revenue={revenue}", file=sys.stderr)
        return PosMetrics(orders=orders, revenue=revenue)

    def shop_orders(self, shop_id: str, since: date, until: date, max_pages: int = 20, page_size: int = 100, delivering_statuses: frozenset[str] = frozenset()) -> PosMetrics:
        try:
            return self._shop_orders_range(shop_id, since, until, max_pages=max_pages, page_size=page_size, delivering_statuses=delivering_statuses)
        except Exception as range_error:
            if since >= until:
                raise
            return self._shop_orders_by_day(shop_id, since, until, range_error, max_pages=max_pages, page_size=page_size, delivering_statuses=delivering_statuses)

    def _shop_orders_range(
        self,
        shop_id: str,
        since: date,
        until: date,
        max_pages: int = 20,
        page_size: int = 100,
        timeout_seconds: int | None = None,
        retries: int | None = None,
        delivering_statuses: frozenset[str] = frozenset(),
    ) -> PosMetrics:
        records: list[dict[str, Any]] = []
        timeout = timeout_seconds if timeout_seconds is not None else self.settings.http_timeout_seconds
        retry_count = retries if retries is not None else self.settings.http_retries
        for page_number in range(1, max_pages + 1):
            payload = get_json(
                f"{self.settings.pancake_base_url}/shops/{shop_id}/orders",
                {
                    "access_token": self.settings.pancake_access_token,
                    "page": page_number,
                    "page_number": page_number,
                    "page_size": page_size,
                    "start_date": since.isoformat(),
                    "start_time": since.isoformat(),
                    "end_date": until.isoformat(),
                    "end_time": until.isoformat(),
                },
                timeout=timeout,
                retries=retry_count,
            )
            page_records = _extract_records(payload, ("orders",))
            if not page_records:
                break
            records.extend(page_records)
            if len(page_records) < page_size:
                break
        print(f"[pos-debug] shop={shop_id} {since}→{until} fetched={len(records)}", file=sys.stderr)
        result = metrics_from_orders(records, since, until, delivering_statuses=delivering_statuses)
        print(f"[pos-debug] shop={shop_id} after_filter orders={result.orders} revenue={result.revenue}", file=sys.stderr)
        return result

    def _shop_orders_by_day(
        self,
        shop_id: str,
        since: date,
        until: date,
        range_error: Exception,
        max_pages: int = 20,
        page_size: int = 100,
        delivering_statuses: frozenset[str] = frozenset(),
    ) -> PosMetrics:
        total = PosMetrics()
        failed_days: list[str] = []
        days = []
        current = since
        while current <= until:
            days.append(current)
            current += timedelta(days=1)

        fallback_timeout = min(self.settings.http_timeout_seconds, 8)
        with ThreadPoolExecutor(max_workers=min(len(days), 7)) as executor:
            futures = {
                executor.submit(
                    self._shop_orders_range,
                    shop_id,
                    day,
                    day,
                    max_pages,
                    page_size,
                    fallback_timeout,
                    0,
                    delivering_statuses,
                ): day
                for day in days
            }
            for future in as_completed(futures):
                day = futures[future]
                try:
                    total = total.add(future.result())
                except Exception:
                    failed_days.append(day.isoformat())

        if failed_days:
            failed_days.sort()
            if total.orders == 0 and total.revenue == 0:
                raise RuntimeError(f"{range_error}; fallback theo ngày cũng lỗi: {', '.join(failed_days)}") from range_error
            raise PartialPosError(total, f"POS timeout khoảng lớn; đã cộng được một phần, lỗi ngày: {', '.join(failed_days)}")
        return total


def _extract_records(payload: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list) and value:
            return [item for item in value if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list) and value:
                return [item for item in value if isinstance(item, dict)]
    return []


# Pancake dùng mã số cho status (không phải text).
# Mapping xác nhận qua phân tích log thực tế:
#   0           = mới nhận (initial receipt)         → loại
#   1           = chưa xác nhận (mới)               → loại
#   2           = tuỳ shop: "pending" (loại) hoặc "đang giao" (GIỮ nếu đã qua 3+)
#                 Cấu hình per-shop qua pos_delivering_statuses trong brands.json
#   9           = đã hủy                             → loại
#   8           = đã hoàn trả — GIỮ nếu đơn đã từng xác nhận trước đó
#                 (Pancake config: "Hoàn trả trừ khi Chốt đơn" — chưa chốt = vẫn tính DT)
#   3,4,5,6,11,13,15 = đã xác nhận trở lên          → giữ
#   '' (rỗng)   = không có status                    → giữ (an toàn)
_NUMERIC_HARD_EXCLUDE = frozenset({"0", "1", "2", "9"})

# Status dùng để tìm ngày xác nhận trong status_history (KHÔNG bao gồm 8 — tránh lấy nhầm ngày hoàn)
_NUMERIC_CONFIRMED = frozenset({"3", "4", "5", "6", "11", "13", "15"})

# Fallback cho hệ thống trả text thay vì số
_TEXT_CANCEL_SUB  = ("hủy", "huy", "cancel")
_TEXT_PENDING     = frozenset({"new", "pending", "draft", "waiting", "chờ xác nhận", "chờ xử lý"})


def _is_fulfilled(order: dict[str, Any], delivering_statuses: frozenset[str] = frozenset()) -> bool:
    raw = str(order.get("status") or order.get("order_status") or "").strip()
    if not raw:
        return True  # không có status → giữ
    # Numeric status (Pancake thực tế)
    if raw.isdigit():
        if raw in _NUMERIC_HARD_EXCLUDE:
            # Status có thể là "đang giao" per-shop config: giữ nếu đã từng qua status 3+
            if raw in delivering_statuses:
                return _has_prior_confirmed(order)
            return False
        # Status 8 (hoàn trả): chỉ tính nếu đơn đã từng được xác nhận trước đó
        if raw == "8":
            return _has_prior_confirmed(order)
        return True
    # Text status (fallback)
    s = raw.lower()
    if s in _TEXT_PENDING:
        return False
    if any(kw in s for kw in _TEXT_CANCEL_SUB):
        return False
    return True


def _has_prior_confirmed(order: dict[str, Any]) -> bool:
    history = order.get("status_history")
    if isinstance(history, list):
        for entry in history:
            if isinstance(entry, dict):
                rs = str(entry.get("status") or "").strip()
                if rs in _NUMERIC_CONFIRMED:
                    return True
    return False


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "").strip() or "0")
    except Exception:
        return Decimal("0")


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _created_date(order: dict[str, Any]) -> date | None:
    created = (
        _parse_datetime(order.get("inserted_at"))
        or _parse_datetime(order.get("created_at"))
        or _parse_datetime(order.get("created_time"))
        or _parse_datetime(order.get("order_time"))
    )
    return created.date() if created else None


def _confirmed_date(order: dict[str, Any]) -> date | None:
    """Ngày đơn đầu tiên đạt trạng thái đã xác nhận (3,4,5,6,11,13,15) từ status_history."""
    history = order.get("status_history")
    if isinstance(history, list):
        confirmed_times: list[datetime] = []
        for entry in history:
            if not isinstance(entry, dict):
                continue
            raw_status = str(entry.get("status") or "").strip()
            if raw_status in _NUMERIC_CONFIRMED:
                for time_key in ("updated_at", "created_at", "inserted_at", "time"):
                    dt = _parse_datetime(entry.get(time_key))
                    if dt:
                        confirmed_times.append(dt)
                        break
        if confirmed_times:
            return min(confirmed_times).date()
    # Fallback: last_update_status_at nếu không có history hợp lệ
    dt = _parse_datetime(order.get("last_update_status_at"))
    if dt:
        return dt.date()
    return _created_date(order)


def _total(order: dict[str, Any]) -> Decimal:
    # Ưu tiên sub_total (tiền hàng thuần, không bao gồm ship khách trả)
    # Fallback về total_price nếu không có sub_total
    # Tránh dùng cod/money_to_collect vì bao gồm tiền ship khách trả
    return _decimal(
        order.get("sub_total")
        or order.get("subtotal")
        or order.get("total_price")
        or order.get("total")
    )


def _in_window(order: dict[str, Any], since: date, until: date) -> bool:
    # Pancake tính đơn vào ngày D nếu ngày tạo HOẶC ngày xác nhận đầu tiên nằm trong [since, until].
    # Đơn không có ngày nào → giữ (an toàn, không có thông tin để loại).
    created = _created_date(order)
    confirmed = _confirmed_date(order)
    if created is None and confirmed is None:
        return True
    return (created is not None and since <= created <= until) or (
        confirmed is not None and since <= confirmed <= until
    )


def metrics_from_orders(
    records: list[dict[str, Any]],
    since: date,
    until: date,
    delivering_statuses: frozenset[str] = frozenset(),
) -> PosMetrics:
    from collections import Counter
    orders = []
    status_out: Counter = Counter()
    date_detail = {"created_only": 0, "confirmed_only": 0, "both": 0, "neither_kept": 0, "out": 0}
    for record in records:
        created = _created_date(record)
        confirmed = _confirmed_date(record)
        c_in = created is not None and since <= created <= until
        k_in = confirmed is not None and since <= confirmed <= until
        in_win = c_in or k_in or (created is None and confirmed is None)
        if not in_win:
            date_detail["out"] += 1
            continue
        if c_in and k_in:
            date_detail["both"] += 1
        elif c_in:
            date_detail["created_only"] += 1
        elif k_in:
            date_detail["confirmed_only"] += 1
        else:
            date_detail["neither_kept"] += 1
        if not _is_fulfilled(record, delivering_statuses=delivering_statuses):
            raw = str(record.get("status") or record.get("order_status") or "").strip()
            status_out[raw] += 1
            continue
        orders.append(record)
    print(
        f"[pos-filter] {since}→{until} in_window={sum(v for k,v in date_detail.items() if k!='out')} "
        f"({date_detail}) status_out={dict(status_out)} kept={len(orders)}",
        file=sys.stderr,
    )
    return PosMetrics(orders=len(orders), revenue=sum((_total(order) for order in orders), Decimal("0")))


class PartialPosError(RuntimeError):
    def __init__(self, metrics: PosMetrics, message: str) -> None:
        self.metrics = metrics
        super().__init__(message)


# ── Product-level stock & sales ────────────────────────────────────────────────

_PANCAKE_SIZES = frozenset({"XS", "S", "M", "L", "XL", "XXL", "XXXL", "FREESIZE", "FREE", "FS"})
_PANCAKE_COLORS = frozenset({
    "DEN", "ĐEN", "TRANG", "TRẮNG", "KEM", "HONG", "HỒNG", "DO", "ĐỎ", "DA", "NUDE",
    "XANH", "VANG", "VÀNG", "GHI", "NAU", "NÂU", "BE", "TIM", "TÍM", "CAM",
})
_SKU_CODE_RE = _re.compile(r'^([A-Z]{1,3})0*(\d+)$')


def extract_product_code_from_sku(sku: str) -> str:
    """'LBN00619-KE HONG-M' → 'BN619'. Strips color/size suffixes, L prefix, leading zeros."""
    parts = [p for p in sku.strip().upper().split("-") if p]
    if not parts:
        return sku.strip().upper()
    while len(parts) > 1:
        tail = parts[-1].strip()
        if tail in _PANCAKE_SIZES or tail in _PANCAKE_COLORS or any(c in tail for c in _PANCAKE_COLORS):
            parts.pop()
            continue
        break
    raw = parts[0]  # e.g. "LBN00619"
    if raw.startswith("L") and len(raw) > 1 and raw[1].isalpha():
        raw = raw[1:]  # strip Lysilk prefix → "BN00619"
    m = _SKU_CODE_RE.match(raw)
    if m:
        return m.group(1) + m.group(2)  # "BN" + "619"
    return raw


@dataclass(frozen=True)
class ProductSkuData:
    product_code: str
    sold_30d: int
    stock_web: int
    low_stock_sizes: tuple[str, ...]    # size labels with 1–4 units
    out_of_stock_sizes: tuple[str, ...]  # size labels with 0 units


def _order_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("bill_products", "items", "order_items", "products", "order_details"):
        items = order.get(key)
        if isinstance(items, list) and items:
            return [item for item in items if isinstance(item, dict)]
    return []


def _item_sku(item: dict[str, Any]) -> str:
    variation = item.get("variation") or item.get("variation_info") or {}
    if not isinstance(variation, dict):
        variation = {}
    product = item.get("product") or item.get("product_info") or {}
    if not isinstance(product, dict):
        product = {}
    for source in (item, variation, product):
        for key in ("barcode", "custom_id", "sku"):
            val = str(source.get(key) or "").strip()
            if val:
                return val.upper()
    return ""


def _item_quantity(item: dict[str, Any]) -> int:
    for key in ("quantity", "qty", "count", "product_quantity"):
        val = item.get(key)
        if val is not None:
            try:
                return max(0, int(float(str(val))))
            except (ValueError, TypeError):
                continue
    return 1


def _variation_label(product: dict[str, Any], variation: dict[str, Any]) -> str:
    fields = variation.get("fields") or product.get("fields")
    if isinstance(fields, list):
        for f in fields:
            if not isinstance(f, dict):
                continue
            name = str(f.get("name") or f.get("key") or "").lower()
            if any(kw in name for kw in ("size", "kich", "kích", "co", "cỡ")):
                val = str(f.get("value") or "").strip()
                if val:
                    return val
    sku = str(variation.get("barcode") or variation.get("custom_id") or "")
    if "-" in sku:
        return sku.rsplit("-", 1)[-1]
    return str(variation.get("name") or product.get("name") or "?")
