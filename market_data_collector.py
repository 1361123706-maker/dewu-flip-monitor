import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


INPUT_FILE = Path("market_data_input.json")

# 我们自己的数据入口
# 后续可以通过环境变量增加公开数据源
SEARCH_URLS = [
    os.getenv("MARKET_SEARCH_URL", "").strip(),
]

DEWU_API_URL = os.getenv("DEWU_API_URL", "").strip()
SHIHUO_API_URL = os.getenv("SHIHUO_API_URL", "").strip()

DEWU_API_KEY = os.getenv("DEWU_API_KEY", "").strip()
SHIHUO_API_KEY = os.getenv("SHIHUO_API_KEY", "").strip()

REQUEST_TIMEOUT = 15


def log(message):
    print(message, flush=True)


def safe_float(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    text = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)

    if not match:
        return None

    try:
        return float(match.group())
    except ValueError:
        return None


def get_json(url, api_key=None):
    if not url:
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; dewu-flip-monitor/1.0)"
        ),
        "Accept": "application/json",
    }

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = Request(url, headers=headers, method="GET")

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)

    except HTTPError as e:
        log(f"接口 HTTP 错误：{e.code} {url}")
        return None

    except URLError as e:
        log(f"接口连接失败：{e.reason}")
        return None

    except Exception as e:
        log(f"接口读取失败：{e}")
        return None


def normalize_product(item, source):
    if not isinstance(item, dict):
        return None

    name = (
        item.get("name")
        or item.get("title")
        or item.get("product_name")
        or item.get("goodsName")
    )

    if not name:
        return None

    buy_price = (
        item.get("buy_price")
        or item.get("price")
        or item.get("lowest_price")
        or item.get("min_price")
    )

    dewu_price = (
        item.get("dewu_price")
        or item.get("sell_price")
        or item.get("target_price")
        or item.get("market_price")
    )

    result = {
        "name": str(name),

        "buy_prices": {
            source: safe_float(buy_price)
        },

        "dewu_price": safe_float(dewu_price),

        "recent_avg_price": safe_float(
            item.get("recent_avg_price")
            or item.get("average_price")
            or item.get("recentAveragePrice")
        ),

        "recent_trade_time": (
            item.get("recent_trade_time")
            or item.get("trade_time")
            or item.get("recentTradeTime")
        ),

        "seller_count": (
            item.get("seller_count")
            or item.get("sellerCount")
        ),

        "days": safe_float(
            item.get("days")
            or item.get("turnover_days")
            or item.get("turnoverDays")
        ),

        "liquidity": (
            item.get("liquidity")
            or item.get("liquidity_level")
        ),

        "downside_loss": safe_float(
            item.get("downside_loss")
            or item.get("max_downside_loss")
            or item.get("downsideLoss")
        ),

        "authenticity_verified": bool(
            item.get("authenticity_verified", False)
        ),

        "new_condition_verified": bool(
            item.get("new_condition_verified", False)
        ),

        "dewu_check_compatible": bool(
            item.get("dewu_check_compatible", False)
        ),

        # 得物实际费用字段
        "technical_service_fee": safe_float(
            item.get("technical_service_fee")
        ),

        "technical_service_rate": safe_float(
            item.get("technical_service_rate")
        ),

        "transfer_fee": safe_float(
            item.get("transfer_fee")
        ),

        "transfer_fee_rate": safe_float(
            item.get("transfer_fee_rate")
        ),

        "operation_service_fee": safe_float(
            item.get("operation_service_fee")
        ),

        "consumer_shipping_subsidy": safe_float(
            item.get("consumer_shipping_subsidy")
        ),

        "after_sales_service_fee": safe_float(
            item.get("after_sales_service_fee")
        ),

        "seller_coupon_offset": safe_float(
            item.get("seller_coupon_offset")
        ),

        "expected_income": safe_float(
            item.get("expected_income")
        ),

        "source_note": item.get(
            "source_note",
            "由自建数据接口标准化产生"
        ),

        "data_source": item.get(
            "data_source",
            source
        ),

        "data_time": item.get(
            "data_time",
            time.strftime("%Y-%m-%d")
        ),
    }

    return result


def extract_items(data):
    """
    尽量兼容不同接口返回格式。

    支持：
    {
        "products": [...]
    }

    {
        "data": [...]
    }

    {
        "data": {
            "products": [...]
        }
    }

    以及直接返回数组。
    """

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    products = data.get("products")

    if isinstance(products, list):
        return products

    data_field = data.get("data")

    if isinstance(data_field, list):
        return data_field

    if isinstance(data_field, dict):

        products = data_field.get("products")

        if isinstance(products, list):
            return products

        items = data_field.get("items")

        if isinstance(items, list):
            return items

    items = data.get("items")

    if isinstance(items, list):
        return items

    return []


def collect_api(url, api_key, source):
    if not url:
        log(f"未配置 {source} 数据接口，跳过")
        return []

    log(f"正在读取 {source} 数据接口")

    data = get_json(url, api_key)

    if data is None:
        return []

    items = extract_items(data)

    log(f"{source} 原始商品：{len(items)}")

    products = []

    for item in items:

        product = normalize_product(
            item,
            source
        )

        if product:
            products.append(product)

    log(f"{source} 标准化商品：{len(products)}")

    return products


def merge_products(products):
    """
    合并相同商品。

    这样以后即使：
    识货发现一个商品
    +
    得物发现同一个商品

    最终也可以进入同一条商品记录。
    """

    merged = {}

    for product in products:

        name = product.get("name")

        if not name:
            continue

        key = name.strip().lower()

        if key not in merged:
            merged[key] = product
            continue

        old = merged[key]

        # 合并买入价格
        old_buy = old.setdefault("buy_prices", {})
        new_buy = product.get("buy_prices", {})

        for platform, price in new_buy.items():

            if price is None:
                continue

            old_buy[platform] = price

        # 只在新数据有值时更新
        fields = [
            "dewu_price",
            "recent_avg_price",
            "recent_trade_time",
            "seller_count",
            "days",
            "liquidity",
            "downside_loss",
            "authenticity_verified",
            "new_condition_verified",
            "dewu_check_compatible",
            "technical_service_fee",
            "technical_service_rate",
            "transfer_fee",
            "transfer_fee_rate",
            "operation_service_fee",
            "consumer_shipping_subsidy",
            "after_sales_service_fee",
            "seller_coupon_offset",
            "expected_income",
        ]

        for field in fields:

            new_value = product.get(field)

            if new_value is not None:
                old[field] = new_value

    return list(merged.values())


def load_existing_products():
    """
    如果真实接口暂时没有数据，
    保留原来的人工/公开数据。

    防止采集器再次把 market_data_input.json 清空。
    """

    if not INPUT_FILE.exists():
        return []

    try:

        with INPUT_FILE.open(
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        products = data.get("products", [])

        if isinstance(products, list):
            return products

    except Exception as e:

        log(f"读取已有市场数据失败：{e}")

    return []


def save_products(products):

    output = {
        "products": products
    }

    with INPUT_FILE.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )


def main():

    log("")
    log("=" * 60)
    log("       自建市场数据接口采集程序")
    log("=" * 60)

    collected = []

    # 得物数据
    collected.extend(
        collect_api(
            DEWU_API_URL,
            DEWU_API_KEY,
            "得物"
        )
    )

    # 识货数据
    collected.extend(
        collect_api(
            SHIHUO_API_URL,
            SHIHUO_API_KEY,
            "识货"
        )
    )

    # 未来我们的自建搜索接口
    for url in SEARCH_URLS:

        if not url:
            continue

        data = get_json(url)

        if not data:
            continue

        items = extract_items(data)

        for item in items:

            product = normalize_product(
                item,
                "自建搜索接口"
            )

            if product:
                collected.append(product)

    # 关键：
    # 如果当前没有真实数据，不清空旧数据
    if not collected:

        existing = load_existing_products()

        if existing:

            log("")
            log("当前没有新的真实接口数据")
            log(f"保留已有商品：{len(existing)} 条")

            save_products(existing)

            log("不会清空原有市场数据")

        else:

            log("")
            log("当前没有新的市场数据")
            log("暂时没有历史商品数据可保留")

            save_products([])

    else:

        merged = merge_products(collected)

        log("")
        log(f"最终标准化商品：{len(merged)}")

        save_products(merged)

    log("")
    log(f"已写入：{INPUT_FILE}")
    log("=" * 60)


if __name__ == "__main__":
    main()
