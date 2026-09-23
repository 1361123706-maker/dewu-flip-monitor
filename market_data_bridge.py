import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent

INPUT_FILE = ROOT / "market_data_input.json"
DISCOVERY_FILE = ROOT / "discovery_data.json"
OUTPUT_FILE = ROOT / "products.json"


def load_json(path):
    if not path.exists():
        return {}

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def number(value):
    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


def get_products(data):
    products = data.get("products", [])

    if not isinstance(products, list):
        return []

    return products


def product_key(item):
    code = clean_text(
        item.get("product_code")
    )

    if code:
        return (
            "code:",
            code.lower()
        )

    url = clean_text(
        item.get("shihuo_url")
    )

    if url:
        return (
            "url:",
            url.lower()
        )

    name = clean_text(
        item.get("name")
    )

    return (
        "name:",
        name.lower()
    )


def merge_product(base, discovery):
    result = dict(base)

    # --------------------------------------------------
    # 公开发现层的数据只负责补充，
    # 不覆盖已经存在的可靠行情数据。
    # --------------------------------------------------

    discovery_buy_price = number(
        discovery.get("buy_price")
    )

    if discovery_buy_price is not None:
        existing_buy_prices = result.get(
            "buy_prices"
        )

        if not isinstance(
            existing_buy_prices,
            dict
        ):
            existing_buy_prices = {}

        existing_buy_prices = dict(
            existing_buy_prices
        )

        # 如果原来没有识货买入价，
        # 才使用公开发现层价格。
        if not existing_buy_prices:
            existing_buy_prices[
                "识货公开发现"
            ] = discovery_buy_price

        elif "识货" not in existing_buy_prices:
            existing_buy_prices.setdefault(
                "识货公开发现",
                discovery_buy_price
            )

        result[
            "buy_prices"
        ] = existing_buy_prices

    # --------------------------------------------------
    # 补充商品身份信息
    # --------------------------------------------------

    fields = [
        "shihuo_url",
        "product_code",
        "dewu_display_price",
        "lowest_price",
        "sales",
        "detail_status",
        "detail_text",
        "observed_at",
        "discovery_observed_at",
    ]

    for field in fields:

        value = discovery.get(field)

        if value in (
            None,
            "",
            [],
            {},
        ):
            continue

        # 不用空值覆盖已有数据
        if result.get(field) in (
            None,
            "",
            [],
            {},
        ):
            result[field] = value

    # --------------------------------------------------
    # 如果 discovery 有得物展示价，
    # 但原来的 dewu_price 没有，
    # 才补进去。
    # --------------------------------------------------

    if (
        result.get("dewu_price") is None
        and discovery.get(
            "dewu_display_price"
        ) is not None
    ):
        result["dewu_price"] = number(
            discovery.get(
                "dewu_display_price"
            )
        )

    # --------------------------------------------------
    # 如果原来没有 source_note，
    # 写清楚数据来源
    # --------------------------------------------------

    if not result.get("source_note"):

        result["source_note"] = (
            "公开商品发现层 + 市场行情数据"
        )

    return result


def main():

    market_data = load_json(
        INPUT_FILE
    )

    discovery_data = load_json(
        DISCOVERY_FILE
    )

    market_products = get_products(
        market_data
    )

    discovery_products = get_products(
        discovery_data
    )

    # --------------------------------------------------
    # 先建立已有行情数据索引
    # --------------------------------------------------

    merged = {}

    for item in market_products:

        if not isinstance(item, dict):
            continue

        key = product_key(item)

        merged[key] = dict(item)

    # --------------------------------------------------
    # 再加入公开发现数据
    # --------------------------------------------------

    for discovery in discovery_products:

        if not isinstance(
            discovery,
            dict
        ):
            continue

        key = product_key(
            discovery
        )

        if key in merged:

            merged[key] = merge_product(
                merged[key],
                discovery
            )

        else:

            # 新发现商品直接进入 products
            new_item = merge_product(
                {},
                discovery
            )

            merged[key] = new_item

    # --------------------------------------------------
    # 输出
    # --------------------------------------------------

    products = list(
        merged.values()
    )

    output = {
        "updated_at": market_data.get(
            "updated_at"
        ),

        "discovery_updated_at":
            discovery_data.get(
                "updated_at"
            ),

        "source":
            "市场行情 + 识货公开商品发现",

        "products": products,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("=" * 70)
    print(
        f"市场原有商品："
        f"{len(market_products)}"
    )
    print(
        f"公开发现商品："
        f"{len(discovery_products)}"
    )
    print(
        f"最终 products："
        f"{len(products)}"
    )
    print(
        f"写入：{OUTPUT_FILE}"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
