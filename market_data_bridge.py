import json
import re
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
    try:
        return float(value)
    except Exception:
        return None


def get_products(data):
    products = data.get("products", [])

    if not isinstance(products, list):
        return []

    return products


def normalize_price(value, detail_text=""):
    price = number(value)

    if price is None:
        return None

    text = clean_text(detail_text)

    # 修复 1.08万 / 1 .08 万
    if price < 100 and text:

        matches = re.findall(
            r"(\d+(?:\.\d+)?)\s*万",
            text
        )

        for match in matches:
            candidate = float(match) * 10000

            if candidate >= 1000:
                return candidate

    return price


def valid_product_name(name):
    name = clean_text(name)

    if not name:
        return False

    if len(name) < 2:
        return False

    bad_names = {
        "未知商品",
        "商品",
        "详情",
        "价格",
        "购买",
        "立即购买",
        "加入购物车",
        "256GB",
        "512GB",
        "1TB",
        "2TB",
    }

    if name in bad_names:
        return False

    return True


def product_key(item):

    url = clean_text(
        item.get("shihuo_url")
    )

    if url:
        return (
            "url",
            url.lower()
        )

    code = clean_text(
        item.get("product_code")
    )

    name = clean_text(
        item.get("name")
    )

    if code and valid_product_name(name):
        return (
            "code_name",
            code.lower(),
            name.lower()
        )

    if valid_product_name(name):
        return (
            "name",
            name.lower()
        )

    return (
        "unknown",
        ""
    )


def copy_discovery_fields(result, discovery):

    detail_text = clean_text(
        discovery.get("detail_text")
    )

    # ========================================================
    # 商品名称
    # ========================================================

    name = clean_text(
        discovery.get("name")
    )

    if valid_product_name(name):
        result["name"] = name

    # ========================================================
    # 买入价
    # ========================================================

    buy = normalize_price(
        discovery.get("buy_price"),
        detail_text
    )

    if buy is not None:

        prices = result.get(
            "buy_prices"
        )

        if not isinstance(prices, dict):
            prices = {}

        prices = dict(prices)

        prices["识货公开发现"] = buy

        result["buy_prices"] = prices
        result["buy_price"] = buy

    # ========================================================
    # 得物公开售价
    # ========================================================

    dewu = normalize_price(
        discovery.get(
            "dewu_display_price"
        ),
        detail_text
    )

    if dewu is not None:

        result["dewu_price"] = dewu

        result["dewu_display_price"] = dewu

        result["dewu_price_source"] = (
            "识货公开商品详情"
        )

        result["dewu_price_evidence"] = (
            "公开页面可见数据；"
            "不是得物内部出价接口"
        )

    # ========================================================
    # 关键：完整传递行情数据
    # ========================================================

    fields = [

        "shihuo_url",
        "source_url",
        "product_code",

        # 价格
        "lowest_price",
        "price_current",
        "trend_current_price",

        # 7日价格
        "price_7d_high",
        "price_7d_low",
        "price_position_7d",
        "downside_to_7d_low",

        # 销量
        "sales",
        "sales_7d",
        "sales_30d",
        "sales_velocity_7d",

        # 周转证据
        "turnover_evidence",
        "turnover_confidence",

        # 历史价格
        "price_history",
        "price_1d",
        "price_7d",
        "price_30d",

        # 价格变化
        "price_change_1d",
        "price_change_7d",
        "price_change_30d",

        # 趋势
        "price_trend",

        # 风控
        "category",
        "authenticity_evidence",
        "new_condition_evidence",
        "dewu_check_evidence",
        "detail_status",

        # 原始证据
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

        result[field] = value

    # ========================================================
    # 如果没有单独的当前价
    # 使用走势当前价
    # ========================================================

    if (
        result.get("price_current") is None
        and result.get("trend_current_price")
        is not None
    ):
        result["price_current"] = (
            result["trend_current_price"]
        )

    # ========================================================
    # 如果没有价格走势当前价
    # 使用7日最低价
    # ========================================================

    if (
        result.get("price_current") is None
        and result.get("price_7d_low")
        is not None
    ):
        result["price_current"] = (
            result["price_7d_low"]
        )

    # ========================================================
    # 如果没有直接下跌风险
    # 根据当前价和7日最低价计算
    # ========================================================

    current = number(
        result.get("price_current")
    )

    low = number(
        result.get("price_7d_low")
    )

    if (
        result.get("downside_to_7d_low")
        is None
        and current
        and low is not None
        and current > 0
        and low >= 0
    ):
        result["downside_to_7d_low"] = round(
            (current - low)
            / current
            * 100,
            2
        )

    # ========================================================
    # 数据来源
    # ========================================================

    result["discovery_data_source"] = (
        "识货公开页面"
    )

    return result


def merge_product(base, discovery):

    result = dict(base)

    return copy_discovery_fields(
        result,
        discovery
    )


def clean_buy_prices(item):

    prices = item.get(
        "buy_prices"
    )

    if not isinstance(prices, dict):
        return {}

    cleaned = {}

    for source, value in prices.items():

        price = number(value)

        if (
            price is not None
            and price > 0
        ):
            cleaned[source] = price

    return cleaned


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

    merged = {}

    # ========================================================
    # 原市场数据
    # ========================================================

    for item in market_products:

        if not isinstance(item, dict):
            continue

        merged[
            product_key(item)
        ] = dict(item)

    # ========================================================
    # 公开发现数据
    # ========================================================

    for discovery in discovery_products:

        if not isinstance(discovery, dict):
            continue

        if not valid_product_name(
            discovery.get("name")
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

            merged[key] = merge_product(
                {},
                discovery
            )

    # ========================================================
    # 最终清理
    # ========================================================

    products = []

    for item in merged.values():

        if not isinstance(item, dict):
            continue

        if not valid_product_name(
            item.get("name")
        ):
            continue

        prices = clean_buy_prices(
            item
        )

        if not prices:
            continue

        item["buy_prices"] = prices

        products.append(item)

    output = {

        "updated_at":
            market_data.get(
                "updated_at"
            ),

        "discovery_updated_at":
            discovery_data.get(
                "updated_at"
            ),

        "source":
            "市场行情 + 识货公开商品发现",

        "products":
            products,
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
    print("市场原有商品：", len(market_products))
    print("公开发现商品：", len(discovery_products))
    print("最终有效商品：", len(products))
    print("=" * 70)

    for index, item in enumerate(
        products[:20],
        start=1
    ):

        print()
        print(
            f"#{index} {item.get('name')}"
        )

        print(
            "买入：",
            item.get("buy_price")
        )

        print(
            "得物：",
            item.get("dewu_price")
        )

        print(
            "月销：",
            item.get("sales_30d")
        )

        print(
            "销量速度：",
            item.get("sales_velocity_7d")
        )

        print(
            "周转证据：",
            item.get("turnover_evidence")
        )

        print(
            "7日最高：",
            item.get("price_7d_high")
        )

        print(
            "7日最低：",
            item.get("price_7d_low")
        )

        print(
            "当前价：",
            item.get("price_current")
        )

        print(
            "7日回落风险：",
            item.get("downside_to_7d_low")
        )

        print(
            "价格趋势：",
            item.get("price_trend")
        )


if __name__ == "__main__":
    main()
