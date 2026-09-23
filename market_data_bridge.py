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


def normalize_price(value, detail_text=""):
    """
    修复识货页面常见的“1.08万”被解析成 1.08 的问题。

    例如：
    1.08万 -> 10800
    1.2万  -> 12000
    7500   -> 7500
    """

    price = number(value)

    if price is None:
        return None

    text = clean_text(detail_text)

    # 如果原始价格很小，同时详情中存在“X万”
    # 优先从详情文本恢复真正价格。
    if price < 100 and text:

        matches = re.findall(
            r"(\d+(?:\.\d+)?)\s*万",
            text
        )

        if matches:

            candidates = []

            for match in matches:
                try:
                    candidates.append(
                        float(match) * 10000
                    )
                except Exception:
                    pass

            if candidates:

                # 优先选择最接近原始价格语义的万元价格。
                # 对于 1.08 -> 10800 这种情况直接恢复。
                for candidate in candidates:
                    if candidate >= 1000:
                        return candidate

    return price


def valid_product_name(name):
    name = clean_text(name)

    if not name:
        return False

    bad_names = {
        "未知商品",
        "商品",
        "详情",
        "价格",
        "购买",
        "立即购买",
        "加入购物车",
    }

    if name in bad_names:
        return False

    if len(name) < 2:
        return False

    return True


def product_key(item):
    """
    商品身份优先级：

    1. 识货完整 URL
    2. product_code + name
    3. 商品名称

    不再单独使用 product_code。
    因为当前采集器出现过：
    adidas
    Nike/
    Li
    Coach/

    这种明显不是完整货号的情况。
    """

    url = clean_text(
        item.get("shihuo_url")
    )

    if url:
        return (
            "url:",
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
            "code_name:",
            code.lower(),
            name.lower()
        )

    if valid_product_name(name):
        return (
            "name:",
            name.lower()
        )

    if code:
        return (
            "code:",
            code.lower()
        )

    return (
        "unknown:",
        ""
    )


def merge_product(base, discovery):

    result = dict(base)

    detail_text = clean_text(
        discovery.get("detail_text")
    )

    # --------------------------------------------------
    # 商品名称
    # --------------------------------------------------

    discovery_name = clean_text(
        discovery.get("name")
    )

    if valid_product_name(discovery_name):

        # discovery 有真实商品名时，
        # 必须进入最终 products。
        result["name"] = discovery_name

    # --------------------------------------------------
    # 买入价
    # --------------------------------------------------

    discovery_buy_price = normalize_price(
        discovery.get("buy_price"),
        detail_text
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

        if "识货" not in existing_buy_prices:

            existing_buy_prices[
                "识货公开发现"
            ] = discovery_buy_price

        result[
            "buy_prices"
        ] = existing_buy_prices

    # --------------------------------------------------
    # 得物展示价
    # --------------------------------------------------

    discovery_dewu_price = normalize_price(
        discovery.get(
            "dewu_display_price"
        ),
        detail_text
    )

    if discovery_dewu_price is not None:

        if result.get("dewu_price") is None:

            result[
                "dewu_price"
            ] = discovery_dewu_price

        result[
            "dewu_display_price"
        ] = discovery_dewu_price

    # --------------------------------------------------
    # 其他身份和行情信息
    # --------------------------------------------------

    fields = [
        "shihuo_url",
        "product_code",
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

        if result.get(field) in (
            None,
            "",
            [],
            {},
        ):
            result[field] = value

    # --------------------------------------------------
    # 来源
    # --------------------------------------------------

    if not result.get("source_note"):

        result["source_note"] = (
            "识货公开商品发现层 + 市场行情数据"
        )

    # --------------------------------------------------
    # 防止明显异常价格进入最终数据
    # --------------------------------------------------

    buy_prices = result.get(
        "buy_prices"
    )

    if isinstance(buy_prices, dict):

        cleaned_prices = {}

        for source, value in buy_prices.items():

            price = number(value)

            if price is None:
                continue

            # 负数当然不可能是正常商品价格
            if price <= 0:
                continue

            cleaned_prices[source] = price

        result[
            "buy_prices"
        ] = cleaned_prices

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

    merged = {}

    # --------------------------------------------------
    # 先放已有可靠市场数据
    # --------------------------------------------------

    for item in market_products:

        if not isinstance(item, dict):
            continue

        key = product_key(item)

        merged[key] = dict(item)

    # --------------------------------------------------
    # 加入公开发现商品
    # --------------------------------------------------

    for discovery in discovery_products:

        if not isinstance(
            discovery,
            dict
        ):
            continue

        # 没有商品名称的发现数据不要进入最终监控
        discovery_name = clean_text(
            discovery.get("name")
        )

        if not valid_product_name(
            discovery_name
        ):
            print(
                "过滤无效商品名称：",
                discovery_name
            )
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

            new_item = merge_product(
                {},
                discovery
            )

            merged[key] = new_item

    # --------------------------------------------------
    # 最终再次清理
    # --------------------------------------------------

    products = []

    for item in merged.values():

        if not isinstance(item, dict):
            continue

        name = clean_text(
            item.get("name")
        )

        if not valid_product_name(name):
            continue

        buy_prices = item.get(
            "buy_prices"
        )

        if not isinstance(
            buy_prices,
            dict
        ):
            continue

        # 没有任何有效买入价的商品不要进入监控
        valid_prices = {}

        for source, value in buy_prices.items():

            price = number(value)

            if price is None:
                continue

            if price <= 0:
                continue

            valid_prices[source] = price

        if not valid_prices:
            continue

        item[
            "buy_prices"
        ] = valid_prices

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
    print(
        "市场原有商品：",
        len(market_products)
    )
    print(
        "公开发现商品：",
        len(discovery_products)
    )
    print(
        "最终有效商品：",
        len(products)
    )
    print(
        "写入：",
        OUTPUT_FILE
    )
    print("=" * 70)

    # 打印前几条，方便 Actions 直接看
    for item in products[:20]:

        print(
            "商品：",
            item.get("name")
        )

        print(
            "买入价：",
            item.get("buy_prices")
        )

        print(
            "得物价：",
            item.get("dewu_price")
        )

        print("-" * 50)


if __name__ == "__main__":
    main()
