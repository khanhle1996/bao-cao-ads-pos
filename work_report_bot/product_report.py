from __future__ import annotations

from dataclasses import dataclass

from .meta import CampaignRec
from .pancake import ProductSkuData


@dataclass
class ProductRow:
    product_code: str
    sold_30d: int | None
    stock_web: int | None
    stock_note: str
    scale_campaigns: list[CampaignRec]
    reduce_campaigns: list[CampaignRec]
    pause_campaigns: list[CampaignRec]
    group: str  # "scale" | "need_media" | "reduce_pause" | "no_stock"


_GROUP_ORDER = {"scale": 0, "need_media": 1, "reduce_pause": 2, "no_stock": 3}


def build_product_report(
    campaigns: list[CampaignRec],
    pos_data: dict[str, ProductSkuData],
) -> list[ProductRow]:
    # Map product_code → campaigns (a combo campaign appears in all its codes)
    campaign_map: dict[str, list[CampaignRec]] = {}
    for rec in campaigns:
        for code in rec.product_codes:
            campaign_map.setdefault(code, []).append(rec)

    all_codes = set(campaign_map) | set(pos_data)

    rows: list[ProductRow] = []
    for code in sorted(all_codes):
        sku_data = pos_data.get(code)
        code_campaigns = campaign_map.get(code, [])

        sold_30d = sku_data.sold_30d if sku_data else None
        stock_web = sku_data.stock_web if sku_data else None

        if sku_data is None:
            stock_note = "Chưa có SKU trong POS"
        elif sku_data.stock_web == 0:
            stock_note = "⚠️⚠️ Hết hàng"
        elif sku_data.low_stock_sizes:
            sizes_str = ", ".join(sku_data.low_stock_sizes[:3])
            stock_note = f"⚠️ Tồn thấp: {sizes_str}"
        else:
            stock_note = ""

        scale = [c for c in code_campaigns if c.action == "scale"]
        reduce = [c for c in code_campaigns if c.action == "reduce"]
        pause = [c for c in code_campaigns if c.action == "pause"]

        if stock_web is not None and stock_web == 0:
            group = "no_stock"
        elif scale:
            # Downgrade to need_media if insufficient stock for 2-week sales pace
            if stock_web is not None and sold_30d and sold_30d > 0:
                min_stock = sold_30d * 14 // 30
                group = "scale" if stock_web >= min_stock else "need_media"
            else:
                group = "scale"
        elif code_campaigns:
            group = "reduce_pause"
        else:
            group = "need_media"

        rows.append(ProductRow(
            product_code=code,
            sold_30d=sold_30d,
            stock_web=stock_web,
            stock_note=stock_note,
            scale_campaigns=scale,
            reduce_campaigns=reduce,
            pause_campaigns=pause,
            group=group,
        ))

    rows.sort(key=lambda r: (_GROUP_ORDER.get(r.group, 9), -(r.sold_30d or 0)))
    return rows
