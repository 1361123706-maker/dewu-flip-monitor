#!/usr/bin/env python3

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent

INPUT_FILE = ROOT / "market_data_input.json"
DISCOVERY_FILE = ROOT / "discovery_data.json"
OUTPUT_FILE = ROOT / "products.json"


def to_number(value):
    if value is None or value == "":
        return None

    try:
        return float(value)
    except Exception:
        return None


def load_json(path):
    if not path.exists():
        return {}

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return {}


def normalize_product(item):
    return {
        "name": str(
            item.get("name") or ""
        ).strip(),

        "buy_prices":
            item.get("buy_prices") or {},

        "buy_price":
            to_number(
                item.get("buy_price")
            ),

        "dewu_price":
            to_number(
                item.get("dewu_price")
            ),

        "expected_income":
            to_number(
                item.get("expected_income")
            ),

        "recent_avg_price":
            to_number(
                item.get("recent_avg_price")
            ),

        "recent_trade_time":
            item.get(
                "recent_trade_time"
            ),

        "seller_count":
            to_number(
                item.get("seller_count")
            ),

        "days":
            to_number(
                item.get("days")
            ),

        "liquidity":
            item.get(
                "liquidity"
            ),

        "downside_loss":
            to_number(
                item.get("downside_loss")
            ),

        "technical_service_fee":
            to_number(
                item.get(
                    "technical_service_fee"
                )
            ),

        "technical_service_rate":
            to_number(
                item.get(
                    "technical_service_rate"
                )
            ),

        "transfer_fee":
            to_number(
                item.get(
                    "transfer_fee"
                )
            ),

        "transfer_fee_rate":
            to_number(
                item.get(
                    "transfer_fee_rate"
                )
            ),

        "operation_service_fee":
            to_number(
                item.get(
                    "operation_service_fee"
                )
            ),

        "consumer_shipping_subsidy":
            to_number(
                item.get(
                    "consumer_shipping_subsidy"
                )
            ),

        "after_sales_service_fee":
            to_number(
                item.get(
                    "after_sales_service_fee"
                )
            ),

        "seller_coupon_offset":
            to_number(
                item.get(
                    "seller_coupon_offset"
                )
            ),

        "authenticity_verified":
            item.get(
                "authenticity_verified",
                False
            ) is True,

        "new_condition_verified":
            item.get(
                "new_condition_verified",
                False
            ) is True,

        "dewu_check_compatible":
            item.get(
                "dewu_check_compatible",
                False
            ) is True,

        "buy_shipping_cost":
            to_number(
                item.get(
                    "buy_shipping_cost"
                )
            ),

        "source_note":
            item.get(
                "source_note",
                ""
            ),

        "data_source":
            item.get(
                "data_source",
                "unknown"
            ),

        "data_time":
            item.get(
                "data_time"
            ),

        # ==========================
        # 识货发现证据
        # ==========================

        "shihuo_url":
            item.get(
                "shihuo_url"
            ),

        "product_code":
            item.get(
                "product_code"
            ),

        "dewu_display_price":
            to_number(
                item.get(
                    "dewu_display_price"
                )
            ),

        "lowest_price":
            to_number(
                item.get(
                    "lowest_price"
                )
            ),

        "sales":
            item.get(
                "sales"
            ),

        "detail_status":
            item.get(
                "detail_status"
            ),

        "discovery_observed_at":
            item.get(
                "observed_at"
            ),
    }


def main():

    # 旧的人工/合法行情数据
    market = load_json(
        INPUT_FILE
    )

    # 新的公开发现数据
    discovery = load_json(
        DISCOVERY_FILE
    )

    market_products = market.get(
        "products",
        []
    )

    discovery_products = discovery.get(
        "products",
        []
    )

    if not isinstance(
        market_products,
        list
    ):
        market_products = []

    if not isinstance(
        discovery_products,
        list
    ):
        discovery_products = []

    # ==========================================
    # 以已有行情数据为主
    # 新采集数据只负责补充发现证据
    # ==========================================

    merged = {}

    for item in market_products:

        if not isinstance(
            item,
            dict
        ):
            continue

        name = str(
            item.get("name") or ""
        ).strip()

        if not name:
            continue

        key = name.lower()

        merged[key] = dict(item)

    for item in discovery_products:

        if not isinstance(
            item,
            dict
        ):
            continue

        name = str(
            item.get("name") or ""
        ).strip()

        if not name:
            continue

        code = str(
            item.get(
                "product_code"
            ) or ""
        ).strip()

        # 优先用货号匹配
        match_key = None

        if code:

            for old_key, old_item in merged.items():

                old_code = str(
                    old_item.get(
                        "product_code"
                    ) or ""
                ).strip()

                if (
                    old_code
                    and old_code.lower()
                    == code.lower()
                ):
                    match_key = old_key
                    break

        if match_key is None:
            match_key = name.lower()

        if match_key in merged:

            old = merged[match_key]

            # 新发现数据只补字段
            for field in [
                "buy_price",
                "shihuo_url",
                "product_code",
                "dewu_display_price",
                "lowest_price",
                "sales",
                "detail_status",
                "discovery_observed_at",
            ]:

                value = item.get(field)

                if value not in (
                    None,
                    "",
                ):
                    old[field] = value

            # 如果已有 buy_prices
            # 就补入最新发现价格
            if item.get(
                "buy_price"
            ) is not None:

                old.setdefault(
                    "buy_prices",
                    {}
                )

                if isinstance(
                    old["buy_prices"],
                    dict
                ):
                    old["buy_prices"][
                        "识货公开页"
                    ] = item[
                        "buy_price"
                    ]

        else:

            merged[match_key] = dict(
                item
            )

    normalized = []

    for item in merged.values():

        normalized.append(
            normalize_product(
                item
            )
        )

    result = {
        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "products":
            normalized,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "市场数据桥接完成"
    )

    print(
        f"原有行情数据："
        f"{len(market_products)}"
    )

    print(
        f"本次公开发现："
        f"{len(discovery_products)}"
    )

    print(
        f"最终监控商品："
        f"{len(normalized)}"
    )


if __name__ == "__main__":
    main()
