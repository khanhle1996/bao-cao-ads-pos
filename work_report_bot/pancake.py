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


# Pancake dùng mã số cho status (không phải text).
# Mapping xác nhận qua phân tích log thực tế:
#   0           = mới nhận (initial receipt)         → loại (chưa xác nhận)
#   1, 2        = chưa xác nhận (mới / chờ xử lý)  → loại
#   8           = đã hoàn trả                        → loại
#   9           = đã hủy                             → loại
#   3,4,5,6,11,13,15 = đã xác nhận trở lên          → giữ
#   '' (rỗng)   = không có status                    → giữ (an toàn)
_NUMERIC_EXCLUDE = frozenset({"0", "1", "2", "8", "9"})

# Status đã xác nhận (dùng để tìm ngày xác nhận trong status_history)
_NUMERIC_CONFIRMED = frozenset({"3", "4", "5", "6", "11", "13", "15"})

# Fallback cho hệ thống trả text thay vì số
_TEXT_CANCEL_SUB  = ("hoàn", "hoan", "hủy", "huy", "cancel", "return", "refund")
_TEXT_CANCEL_SAFE = ("hoàn thành", "hoan thanh")   # "hoàn thành" ≠ hoàn trả
_TEXT_PENDING     = frozenset({"new", "pending", "draft", "waiting", "chờ xác nhận", "chờ xử lý"})


def _is_fulfilled(order: dict[str, Any]) -> bool:
    raw = str(order.get("status") or order.get("order_status") or "").strip()
    if not raw:
        return True  # không có status → giữ như code gốc
    # Numeric status (Pancake thực tế)
    if raw.isdigit():
        return raw not in _NUMERIC_EXCLUDE
    # Text status (fallback)
    s = raw.lower()
    if s in _TEXT_PENDING:
        return False
    if any(kw in s for kw in _TEXT_CANCEL_SUB) and not any(ok in s for ok in _TEXT_CANCEL_SAFE):
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


def _confirmed_date(order: dict[str, Any]) -> date | None:
    """Ngày đơn đầu tiên đạt trạng thái đã xác nhận (3,4,5,6,11,13,15) từ status_history.
    Khớp với cách Pancake dashboard tính 'Doanh thu theo ngày xác nhận'."""
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


def _effective_date(order: dict[str, Any]) -> date | None:
    return _confirmed_date(order)


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
    n_created_in = n_history_in = n_lus_in = n_date_out = n_status_out = 0
    orders = []
    for record in records:
        created = _created_date(record)
        lus_dt = _parse_datetime(record.get("last_update_status_at"))
        lus = lus_dt.date() if lus_dt else None

        history = record.get("status_history")
        hist_date: date | None = None
        if isinstance(history, list):
            times: list[datetime] = []
            for entry in history:
                if not isinstance(entry, dict):
                    continue
                rs = str(entry.get("status") or "").strip()
                if rs in _NUMERIC_CONFIRMED:
                    for tk in ("updated_at", "created_at", "inserted_at", "time"):
                        dt = _parse_datetime(entry.get(tk))
                        if dt:
                            times.append(dt)
                            break
            if times:
                hist_date = min(times).date()

        effective = hist_date or lus or created

        if effective is not None and not (since <= effective <= until):
            n_date_out += 1
            # Log orders that are in created/lus range but filtered out by history
            if (created is not None and since <= created <= until) or (lus is not None and since <= lus <= until):
                print(
                    f"[pos-mismatch] status={record.get('status')} hist={hist_date} lus={lus} created={created}",
                    file=sys.stderr, flush=True,
                )
            continue
        if not _is_fulfilled(record):
            n_status_out += 1
            continue
        if hist_date and since <= hist_date <= until:
            n_history_in += 1
        elif lus and since <= lus <= until:
            n_lus_in += 1
        else:
            n_created_in += 1
        orders.append(record)
    print(
        f"[pos-count] {since}→{until} total={len(orders)} "
        f"by_history={n_history_in} by_lus={n_lus_in} by_created={n_created_in} "
        f"date_out={n_date_out} status_out={n_status_out}",
        file=sys.stderr, flush=True,
    )
    return PosMetrics(orders=len(orders), revenue=sum((_total(order) for order in orders), Decimal("0")))


class PartialPosError(RuntimeError):
    def __init__(self, metrics: PosMetrics, message: str) -> None:
        self.metrics = metrics
        super().__init__(message)
