import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


OUTPUT_FILE = Path("market_data_input.json")
SOURCE_URL = os.getenv("PRODUCT_SOURCE_URL", "").strip()
TIMEOUT = 20


def log(message):
    print(message, flush=True)


def fetch_json(url):
    if not url:
        return None

    if not url.startswith(("http://", "https://")):
        log("数据源地址不是 HTTP/HTTPS，已跳过")
        return None

    request = Request(
        url,
        headers={
            "User-Agent": "dewu-flip-monitor/1.0",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(
                response.read().decode("utf-8")
            )

    except HTTPError as e:
        log(f"数据源 HTTP 错误：{e.code}")
    except URLError as e:
        log(f"数据源连接失败：{e.reason}")
    except Exception as e:
        log(f"数据源读取失败：{e}")

    return None


def get_items(data):
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    if isinstance(data.get("products"), list):
        return data["products"]

    if isinstance(data.get("items"), list):
        return data["items"]

    if isinstance(data.get("data"), list):
        return data["data"]

    if isinstance(data.get("data"), dict):
        if isinstance(data["data"].get("products"), list):
            return data["data"]["products"]

        if isinstance(data["data"].get("items"), list):
            return data["data"]["items"]

    return []


def number(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    if not text:
        return None

    text = (
        text.replace("¥", "")
        .replace("￥", "")
        .replace(",", "")
        .strip()
    )

    try:
        return float(text)
    except ValueError:
        return None


def normalize(item):
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
        or item.get("source_price")
        or item.get("lowest_price")
        or item.get("price")
    )

    dewu_price = (
        item.get("dewu_price")
        or item.get("sell_price")
        or item.get("market_price")
    )

    product = {
        "name": str(name),

        "buy_prices": {
            "search_source": number(buy_price)
        },

        "dewu_price": number(dewu_price),

        "recent_avg_price": number(
            item.get("recent_avg_price")
        ),

        "recent_trade_time": (
            item.get("recent_trade_time")
        ),

        "seller_count": item.get(
            "seller_count"
        ),

        "days": number(
            item.get("days")
        ),

        "liquidity": item.get(
            "liquidity"
        ),

        "downside_loss": number(
            item.get("downside_loss")
        ),

        "authenticity_verified": bool(
            item.get(
                "authenticity_verified",
                False
            )
        ),

        "new_condition_verified": bool(
            item.get(
                "new_condition_verified",
                False
            )
        ),

        "dewu_check_compatible": bool(
            item.get(
                "dewu_check_compatible",
                False
            )
        ),

        "technical_service_fee": number(
            item.get("technical_service_fee")
        ),

        "technical_service_rate": number(
            item.get("technical_service_rate")
        ),

        "transfer_fee": number(
            item.get("transfer_fee")
        ),

        "transfer_fee_rate": number(
            item.get("transfer_fee_rate")
        ),

        "operation_service_fee": number(
            item.get("operation_service_fee")
        ),

        "consumer_shipping_subsidy": number(
            item.get(
                "consumer_shipping_subsidy"
            )
        ),

        "after_sales_service_fee": number(
            item.get(
                "after_sales_service_fee"
            )
        ),

        "seller_coupon_offset": number(
            item.get(
                "seller_coupon_offset"
            )
        ),

        "expected_income": number(
            item.get("expected_income")
        ),

        "source_note": (
            item.get(
                "source_note",
                "公开商品搜索数据"
            )
        ),

        "data_source": (
            item.get(
                "data_source",
                "product_search"
            )
        ),

        "data_time": (
            item.get(
                "data_time",
                time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )
        ),
    }

    return product


def load_existing():
    if not OUTPUT_FILE.exists():
        return []

    try:
        with OUTPUT_FILE.open(
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        products = data.get("products", [])

        if isinstance(products, list):
            return products

    except Exception as e:
        log(f"读取旧数据失败：{e}")

    return []


def merge(old_products, new_products):
    result = {}

    for product in old_products + new_products:

        name = product.get("name")

        if not name:
            continue

        key = name.strip().lower()

        if key not in result:
            result[key] = product
            continue

        old = result[key]

        old_prices = old.setdefault(
            "buy_prices",
            {}
        )

        new_prices = product.get(
            "buy_prices",
            {}
        )

        for platform, price in new_prices.items():
            if price is not None:
                old_prices[platform] = price

        for field in product:

            value = product[field]

            if field == "buy_prices":
                continue

            if value is not None:
                old[field] = value

    return list(result.values())


def save(products):
    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            {
                "products": products
            },
            f,
            ensure_ascii=False,
            indent=2
        )


def main():

    log("")
    log("=" * 60)
    log("       商品搜索采集器")
    log("=" * 60)

    if not SOURCE_URL:
        log("当前没有配置商品搜索数据源")
        log("保留已有商品，不清空数据")

        existing = load_existing()

        log(
            f"现有商品：{len(existing)} 条"
        )

        save(existing)

        return

    log("正在读取商品搜索数据源")

    data = fetch_json(SOURCE_URL)

    if data is None:
        log("数据源暂时不可用")
        log("保留已有商品，不清空数据")

        existing = load_existing()
        save(existing)

        return

    items = get_items(data)

    log(
        f"搜索数据返回：{len(items)} 条"
    )

    products = []

    for item in items:

        product = normalize(item)

        if product:
            products.append(product)

    log(
        f"成功标准化：{len(products)} 条"
    )

    existing = load_existing()

    merged = merge(
        existing,
        products
    )

    save(merged)

    log(
        f"最终商品数量：{len(merged)}"
    )

    log("=" * 60)


if __name__ == "__main__":
    main()
