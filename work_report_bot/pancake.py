from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .config import Settings
from .http import get_json


@dataclass(frozen=True)
class PosMetrics:
    orders: int = 0
    revenue: Decimal = Decimal("0")

    def add(self, other: "PosMetrics") -> "PosMetrics":
        return PosMetrics(orders=self.orders + other.orders, revenue=self.revenue + other.revenue)


class PancakeClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def shop_orders(self, shop_id: str, since: date, until: date, max_pages: int = 20, page_size: int = 100) -> PosMetrics:
        try:
            return self._shop_orders_range(shop_id, since, until, max_pages=max_pages, page_size=page_size)
        except Exception as range_error:
            if since >= until:
                raise
            return self._shop_orders_by_day(shop_id, since, until, range_error, max_pages=max_pages, page_size=page_size)

    def _shop_orders_range(
        self,
        shop_id: str,
        since: date,
        until: date,
        max_pages: int = 20,
        page_size: int = 100,
        timeout_seconds: int | None = None,
        retries: int | None = None,
    ) -> PosMetrics:
        records: list[dict[str, Any]] = []
        timeout = timeout_seconds if timeout_seconds is not None else self.settings.http_timeout_seconds
        retry_count = retries if retries is not None else self.settings.http_retries
        for page_number in range(1, max_pages + 1):
            payload = get_json(
                f"{self.settings.pancake_base_url}/shops/{shop_id}/orders",
                {
                    "access_token": self.settings.pancake_access_token,
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
        return metrics_from_orders(records, since, until)

    def _shop_orders_by_day(
        self,
        shop_id: str,
        since: date,
        until: date,
        range_error: Exception,
        max_pages: int = 20,
        page_size: int = 100,
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


# Deny-list: chỉ loại đơn hoàn/hủy rõ ràng, giữ tất cả trạng thái còn lại.
# "hoàn thành" KHÔNG phải hoàn trả → được whitelist.
_CANCEL_SUBSTRINGS = ("hoàn", "hoan", "hủy", "huy", "cancel", "return", "refund")
_CANCEL_WHITELIST  = ("hoàn thành", "hoan thanh", "hoan-thanh")
_PENDING_EXACT = frozenset({
    "new", "pending", "draft", "waiting",
    "chờ xác nhận", "cho xac nhan", "chờ xử lý",
})

_status_seen: set[str] = set()


def _is_fulfilled(order: dict[str, Any]) -> bool:
    import sys
    s = str(order.get("status") or order.get("order_status") or "").strip().lower()
    # Log mỗi status value lần đầu gặp để debug
    if s and s not in _status_seen:
        _status_seen.add(s)
        print(f"[pancake-status] {s!r}", file=sys.stderr, flush=True)
    if not s:
        return True  # không có status → giữ như code gốc
    if s in _PENDING_EXACT:
        return False
    if any(kw in s for kw in _CANCEL_SUBSTRINGS):
        if not any(wl in s for wl in _CANCEL_WHITELIST):
            return False
    return True


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


def metrics_from_orders(records: list[dict[str, Any]], since: date, until: date) -> PosMetrics:
    import sys
    from collections import Counter
    status_counter: Counter[str] = Counter()
    orders = []
    for record in records:
        created = _created_date(record)
        if created is not None and not (since <= created <= until):
            continue
        s = str(record.get("status") or record.get("order_status") or "").strip()
        status_counter[s] += 1
        if not _is_fulfilled(record):
            continue
        orders.append(record)
    # Log phân bổ status để xác định mapping số → tên trạng thái
    print(f"[pancake-status-count] total={sum(status_counter.values())} accepted={len(orders)} "
          f"dist={dict(sorted(status_counter.items()))}", file=sys.stderr, flush=True)
    return PosMetrics(orders=len(orders), revenue=sum((_total(order) for order in orders), Decimal("0")))


class PartialPosError(RuntimeError):
    def __init__(self, metrics: PosMetrics, message: str) -> None:
        self.metrics = metrics
        super().__init__(message)
