import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


HOME_URL = "https://www.shihuo.cn/page/pcHome"
OUTPUT_FILE = "discovery_data.json"
MAX_DETAIL_PAGES = 40

VIEWPORT = {
    "width": 1440,
    "height": 1000,
}


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def normalize_price(value, unit=None):
    """
    正确处理：
    7500
    8,000
    1.08万 -> 10800
    1万 -> 10000
    """

    if value is None:
        return None

    try:
        text = str(value).strip()
        text = text.replace(",", "")
        text = text.replace("¥", "")
        text = text.replace("￥", "")
        text = text.replace("元", "")
        text = text.strip()

        number = float(text)

        if unit == "万":
            number *= 10000

        if number <= 0 or number > 1000000:
            return None

        return round(number, 2)

    except Exception:
        return None


def price_from_match(match):
    if not match:
        return None

    value = match.group(1)
    unit = None

    try:
        unit = match.group(2)
    except Exception:
        pass

    return normalize_price(value, unit)


def extract_price(text):
    if not text:
        return None

    patterns = [
        r"[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)\s*元",
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*元",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            price = price_from_match(match)

            if price is not None:
                return price

    return None


def extract_product_name(text):
    """
    优先使用识货页面明确的：
    商品名称：xxxx。品牌：xxxx
    """

    if not text:
        return None

    patterns = [
        r"商品名称[:：]\s*(.+?)(?:。品牌[:：])",
        r"商品名称[:：]\s*(.+?)(?:\s+品牌[:：])",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            name = clean_text(match.group(1))

            if len(name) >= 4:
                return name

    return None


def extract_trend_current_price(text):
    if not text:
        return None

    patterns = [
        r"当前同款同规格到手价为\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",

        r"当前同款同规格到手价为\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?\s*元",

        r"当前(?:同款同规格)?到手价为\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            price = price_from_match(match)

            if price is not None:
                return price

    return None


def extract_7d_prices(text):
    """
    只接受明确的：
    当前同款同规格到手价为¥820，是过去7天内监测到的最高价
    当前同款同规格到手价为¥7510，是过去7天内监测到的最低价
    """

    if not text:
        return None, None

    high = None
    low = None

    high_patterns = [
        r"当前同款同规格到手价为\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?"
        r"[^。；\n]{0,100}"
        r"过去\s*7\s*天内"
        r"[^。；\n]{0,50}"
        r"最高价",

        r"当前同款同规格到手价为\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?"
        r"\s*元[^。；\n]{0,100}"
        r"过去\s*7\s*天内"
        r"[^。；\n]{0,50}"
        r"最高价",
    ]

    low_patterns = [
        r"当前同款同规格到手价为\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?"
        r"[^。；\n]{0,100}"
        r"过去\s*7\s*天内"
        r"[^。；\n]{0,50}"
        r"最低价",

        r"当前同款同规格到手价为\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?"
        r"\s*元[^。；\n]{0,100}"
        r"过去\s*7\s*天内"
        r"[^。；\n]{0,50}"
        r"最低价",
    ]

    for pattern in high_patterns:
        match = re.search(pattern, text)

        if match:
            high = price_from_match(match)
            if high is not None:
                break

    for pattern in low_patterns:
        match = re.search(pattern, text)

        if match:
            low = price_from_match(match)
            if low is not None:
                break

    if high is not None and low is not None:
        if high < low:
            return None, None

    return high, low


def extract_price_position(current, high, low):
    if current is None or high is None or low is None:
        return None

    if high <= low:
        return None

    value = (current - low) / (high - low) * 100

    return round(
        max(0, min(100, value)),
        2,
    )


def extract_downside_to_low(current, low):
    if current is None or low is None:
        return None

    if current <= 0:
        return None

    value = (current - low) / current * 100

    return round(
        max(0, value),
        2,
    )


def extract_month_sales(text):
    if not text:
        return None

    patterns = [
        r"(?:月销|月销量)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?\+?",

        r"(?:近30天销量|近30日销量)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?\+?",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if not match:
            continue

        try:
            value = float(match.group(1))
        except Exception:
            continue

        if match.group(2) == "万":
            value *= 10000

        if value > 0:
            return value

    return None


def extract_total_sales(text):
    if not text:
        return None

    pattern = (
        r"(?:总销|累计销量|总销量)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?\+?"
    )

    match = re.search(pattern, text)

    if not match:
        return None

    try:
        value = float(match.group(1))
    except Exception:
        return None

    if match.group(2) == "万":
        value *= 10000

    return value if value > 0 else None


def extract_dewu_price(text):
    """
    识货页面里的：
    得物渠道售价8000.00元
    得物渠道售价10685.17元
    """

    if not text:
        return None

    patterns = [
        r"得物渠道售价\s*[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?\s*元?",

        r"得物渠道售价为\s*[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?\s*元?",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            price = price_from_match(match)

            if price is not None:
                return price

    return None


def calculate_turnover(sales_30d, sales):
    if sales_30d is not None and sales_30d > 0:
        return {
            "sales_velocity_7d": round(
                sales_30d / 30,
                2,
            ),
            "turnover_evidence": (
                f"近30日/月销 {sales_30d:g}，"
                f"折算日均约 {sales_30d / 30:.2f}"
            ),
            "turnover_confidence": "medium",
        }

    if sales is not None and sales > 0:
        return {
            "sales_velocity_7d": None,
            "turnover_evidence": (
                f"累计销量 {sales:g}"
            ),
            "turnover_confidence": "low",
        }

    return {
        "sales_velocity_7d": None,
        "turnover_evidence": None,
        "turnover_confidence": "unknown",
    }


def extract_price_trend(text):
    if not text:
        return None

    if re.search(
        r"价格.{0,20}下跌",
        text,
    ):
        return "下跌"

    if re.search(
        r"价格.{0,20}上涨",
        text,
    ):
        return "上涨"

    if re.search(
        r"价格.{0,20}(稳定|平稳)",
        text,
    ):
        return "稳定"

    return None


def extract_price_changes(text):
    result = {
        "price_change_1d": None,
        "price_change_7d": None,
        "price_change_30d": None,
    }

    if not text:
        return result

    periods = [
        ("1d", 1),
        ("7d", 7),
        ("30d", 30),
    ]

    for key, days in periods:
        pattern = (
            rf"(?:近|过去|最近)\s*{days}\s*"
            rf"(?:天|日)[^。；\n]{{0,40}}"
            rf"(上涨|下跌)\s*"
            rf"([0-9]+(?:\.[0-9]+)?)\s*%"
        )

        match = re.search(
            pattern,
            text,
        )

        if not match:
            continue

        try:
            value = float(match.group(2))
        except Exception:
            continue

        if match.group(1) == "下跌":
            value = -value

        result[f"price_change_{key}"] = value

    return result


def valid_name(name):
    if not name:
        return False

    name = clean_text(name)

    if len(name) < 4:
        return False

    bad_names = {
        "商品",
        "详情",
        "价格",
        "购买",
        "立即购买",
        "加入购物车",
        "未知商品",
    }

    return name not in bad_names


def product_key(item):
    url = item.get("shihuo_url")

    if url:
        return f"url:{url}"

    return f"name:{item.get('name')}"


def extract_detail(page, url):
    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(2500)

    detail_text = clean_text(
        page.locator("body").inner_text()
    )

    # ① 商品名称：优先使用页面明确字段
    name = extract_product_name(
        detail_text
    )

    # ② 页面顶部买入价
    buy_price = None

    price_info_match = re.search(
        r"全网价格区间[:：]\s*"
        r"[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"\s*(万)?"
        r"\s*元?\s*-\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"\s*(万)?",
        detail_text,
    )

    if price_info_match:
        buy_price = normalize_price(
            price_info_match.group(1),
            price_info_match.group(2),
        )

    # 如果上面没抓到，再从页面明确价格中找
    if buy_price is None:
        buy_price = extract_price(
            detail_text
        )

    # ③ 得物渠道售价
    dewu_price = extract_dewu_price(
        detail_text
    )

    # ④ 价格走势当前价
    trend_current_price = (
        extract_trend_current_price(
            detail_text
        )
    )

    # ⑤ 7日最高/最低
    price_7d_high, price_7d_low = (
        extract_7d_prices(
            detail_text
        )
    )

    # 如果明确说当前价是最高/最低，
    # 那么当前走势价就是对应值
    if trend_current_price is None:
        if price_7d_high is not None:
            trend_current_price = price_7d_high

        elif price_7d_low is not None:
            trend_current_price = price_7d_low

    # ⑥ 销量
    sales_30d = extract_month_sales(
        detail_text
    )

    sales = extract_total_sales(
        detail_text
    )

    turnover = calculate_turnover(
        sales_30d,
        sales,
    )

    # ⑦ 价格走势计算
    price_position_7d = (
        extract_price_position(
            trend_current_price,
            price_7d_high,
            price_7d_low,
        )
    )

    downside_to_7d_low = (
        extract_downside_to_low(
            trend_current_price,
            price_7d_low,
        )
    )

    changes = extract_price_changes(
        detail_text
    )

    price_trend = extract_price_trend(
        detail_text
    )

    return {
        "name": name,

        "buy_price": buy_price,

        "shihuo_url": url,

        "product_code": None,

        "dewu_display_price": dewu_price,

        "lowest_price": price_7d_low,

        "sales": sales,

        "sales_7d": None,

        "sales_30d": sales_30d,

        "sales_velocity_7d": (
            turnover["sales_velocity_7d"]
        ),

        "turnover_evidence": (
            turnover["turnover_evidence"]
        ),

        "turnover_confidence": (
            turnover["turnover_confidence"]
        ),

        "price_current": trend_current_price,

        "trend_current_price": (
            trend_current_price
        ),

        "price_7d_high": price_7d_high,

        "price_7d_low": price_7d_low,

        "price_position_7d": (
            price_position_7d
        ),

        "downside_to_7d_low": (
            downside_to_7d_low
        ),

        "price_change_1d": (
            changes["price_change_1d"]
        ),

        "price_change_7d": (
            changes["price_change_7d"]
        ),

        "price_change_30d": (
            changes["price_change_30d"]
        ),

        "price_trend": price_trend,

        "detail_text": detail_text[:12000],

        "observed_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
    }


def collect_urls(page):
    page.goto(
        HOME_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(4000)

    locator = page.locator(
        "a[href*='pcGoodsDetail']"
    )

    urls = []

    try:
        count = locator.count()
    except Exception:
        count = 0

    for i in range(
        min(count, MAX_DETAIL_PAGES)
    ):
        try:
            href = locator.nth(i).get_attribute(
                "href"
            )

            if not href:
                continue

            full_url = urljoin(
                HOME_URL,
                href,
            )

            if (
                "pcGoodsDetail" in full_url
                and full_url not in urls
            ):
                urls.append(full_url)

        except Exception:
            pass

    return urls


def merge_products(items):
    result = {}

    for item in items:
        if not valid_name(
            item.get("name")
        ):
            continue

        if item.get("buy_price") is None:
            continue

        key = product_key(item)

        if key not in result:
            result[key] = item

    return list(result.values())


def main():
    items = []

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport=VIEWPORT
        )

        detail_page = browser.new_page(
            viewport=VIEWPORT
        )

        urls = collect_urls(page)

        print(
            f"发现详情页：{len(urls)}"
        )

        for index, url in enumerate(
            urls,
            1,
        ):
            try:
                print(
                    f"\n[{index}/{len(urls)}]"
                )

                item = extract_detail(
                    detail_page,
                    url,
                )

                if not valid_name(
                    item.get("name")
                ):
                    print(
                        "跳过：没有有效商品名称"
                    )
                    continue

                if item.get("buy_price") is None:
                    print(
                        "跳过：没有有效买入价"
                    )
                    continue

                items.append(item)

                print(
                    f"商品：{item['name']}"
                )

                print(
                    f"买入价：{item['buy_price']}"
                )

                print(
                    f"得物渠道价："
                    f"{item['dewu_display_price']}"
                )

                print(
                    f"走势当前价："
                    f"{item['trend_current_price']}"
                )

                print(
                    f"7日最高："
                    f"{item['price_7d_high']}"
                )

                print(
                    f"7日最低："
                    f"{item['price_7d_low']}"
                )

                print(
                    f"月销："
                    f"{item['sales_30d']}"
                )

            except Exception as e:
                print(
                    f"采集失败：{e}"
                )

            time.sleep(1)

        browser.close()

    products = merge_products(
        items
    )

    output = {
        "updated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "count": len(products),
        "products": products,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(
        "\n=============================="
    )

    print(
        f"最终有效商品数：{len(products)}"
    )

    print(
        "=============================="
    )

    for item in products[:20]:
        print(
            f"\n商品：{item.get('name')}"
        )
        print(
            f"买入价：{item.get('buy_price')}"
        )
        print(
            f"得物渠道价："
            f"{item.get('dewu_display_price')}"
        )
        print(
            f"走势当前价："
            f"{item.get('trend_current_price')}"
        )
        print(
            f"7日最高："
            f"{item.get('price_7d_high')}"
        )
        print(
            f"7日最低："
            f"{item.get('price_7d_low')}"
        )
        print(
            f"月销："
            f"{item.get('sales_30d')}"
        )


if __name__ == "__main__":
    main()
