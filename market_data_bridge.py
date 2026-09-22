#!/usr/bin/env python3

"""
市场数据桥接程序

作用：
把不同来源的商品行情数据转换成统一格式，
交给现有的 monitor.py 进行风险判断。

注意：
- 不绕过平台登录、验证码、签名、加密或反爬。
- 缺失数据保持为空，不自行猜测。
- 本程序只负责数据转换，不负责判断是否值得购买。
"""

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent

INPUT_FILE = ROOT / "market_data_input.json"
OUTPUT_FILE = ROOT / "products.json"


def to_number(value):
    """把价格、数量等字段转换成数字；无法确认就返回 None。"""
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_product(item):
    """把一条外部商品数据转换成系统统一格式。"""

    buy_prices = item.get("buy_prices") or {}

    return {
        "name": str(item.get("name") or "").strip(),

        "buy_prices": buy_prices,

        "dewu_price": to_number(
            item.get("dewu_price")
        ),

        "recent_avg_price": to_number(
            item.get("recent_avg_price")
        ),

        "recent_trade_time":
            item.get("recent_trade_time"),

        "seller_count": to_number(
            item.get("seller_count")
        ),

        "days": to_number(
            item.get("days")
        ),

        "liquidity":
            item.get("liquidity"),

        "downside_loss": to_number(
            item.get("downside_loss")
        ),

        "authenticity_verified":
            bool(item.get("authenticity_verified", False)),

        "new_condition_verified":
            bool(item.get("new_condition_verified", False)),

        "dewu_check_compatible":
            bool(item.get("dewu_check_compatible", False)),

        "source_note":
            item.get("source_note", ""),

        "data_source":
            item.get("data_source", "manual"),

        "data_time":
            item.get(
                "data_time",
                datetime.now(timezone.utc).isoformat()
            )
    }


def main():

    if not INPUT_FILE.exists():
        print(
            "未找到 market_data_input.json，"
            "桥接程序没有修改 products.json。"
        )
        return

    try:
        raw = json.loads(
            INPUT_FILE.read_text(
                encoding="utf-8"
            )
        )
    except Exception as e:
        print(f"读取 market_data_input.json 失败：{e}")
        return

    products = raw.get("products", [])

    normalized_products = []

    for item in products:

        if not isinstance(item, dict):
            continue

        if not item.get("name"):
            continue

        normalized_products.append(
            normalize_product(item)
        )

    result = {
        "products": normalized_products
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        f"桥接完成："
        f"输入 {len(products)} 条，"
        f"标准化 {len(normalized_products)} 条。"
    )


if __name__ == "__main__":
    main()
