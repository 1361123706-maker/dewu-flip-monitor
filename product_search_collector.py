import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


HOME_URL = "https://www.shihuo.cn/page/pcHome"
OUTPUT_FILE = "discovery_data.json"

MAX_DETAIL_PAGES = 40
VIEWPORT = {"width": 1440, "height": 1000}


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def normalize_price(value):
    if value is None:
        return None

    text = str(value).strip()
    text = text.replace(",", "")
    text = text.replace("￥", "").replace("¥", "").replace("元", "")

    # 只接受真正的金额
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None

    try:
        price = float(match.group(1))
    except Exception:
        return None

    if price <= 0 or price > 1000000:
        return None

    return price


def extract_first_price(text):
    if not text:
        return None

    # 必须带 ¥ / ￥ / 元，避免把尺码、日期、编号当价格
    patterns = [
        r"[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*元",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return normalize_price(match.group(1))

    return None


def extract_current_price(text):
    if not text:
        return None

    patterns = [
        r"(?:当前价|当前价格|目前价格|当前售价|售价|价格)"
        r"[^¥￥0-9]{0,30}[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",

        r"(?:当前价|当前价格|目前价格|当前售价|售价|价格)"
        r"[^0-9]{0,30}(\d+(?:,\d{3})*(?:\.\d+)?)\s*元",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return normalize_price(match.group(1))

    return None


def extract_explicit_7d_prices(text):
    """
    只从明确的“7日/过去7天最高价、最低价”文字中取价格。

    严禁：
    - 从尺码中取数字
    - 从日期中取数字
    - 从销量中取数字
    - 从普通数字附近猜价格
    """

    if not text:
        return None, None

    high = None
    low = None

    # 形式：
    # 过去7天最高价 ¥820
    # 近7日最高价格：820元
    # 7天最高价为¥820
    high_patterns = [
        r"(?:过去|近|最近)?\s*7\s*(?:天|日)"
        r"[^。；，,\n]{0,40}?"
        r"(?:最高价|最高价格|最高售价)"
        r"[^¥￥0-9]{0,30}[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",

        r"(?:过去|近|最近)?\s*7\s*(?:天|日)"
        r"[^。；，,\n]{0,40}?"
        r"(?:最高价|最高价格|最高售价)"
        r"[^0-9]{0,30}(\d+(?:,\d{3})*(?:\.\d+)?)\s*元",

        r"(?:最高价|最高价格|最高售价)"
        r"[^¥￥0-9]{0,30}[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"[^。；，,\n]{0,30}(?:过去|近|最近)?\s*7\s*(?:天|日)",
    ]

    low_patterns = [
        r"(?:过去|近|最近)?\s*7\s*(?:天|日)"
        r"[^。；，,\n]{0,40}?"
        r"(?:最低价|最低价格|最低售价)"
        r"[^¥￥0-9]{0,30}[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",

        r"(?:过去|近|最近)?\s*7\s*(?:天|日)"
        r"[^。；，,\n]{0,40}?"
        r"(?:最低价|最低价格|最低售价)"
        r"[^0-9]{0,30}(\d+(?:,\d{3})*(?:\.\d+)?)\s*元",

        r"(?:最低价|最低价格|最低售价)"
        r"[^¥￥0-9]{0,30}[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"[^。；，,\n]{0,30}(?:过去|近|最近)?\s*7\s*(?:天|日)",
    ]

    for pattern in high_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            high = normalize_price(match.group(1))
            if high is not None:
                break

    for pattern in low_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            low = normalize_price(match.group(1))
            if low is not None:
                break

    # 防止最高价低于最低价的明显错误
    if high is not None and low is not None and high < low:
        high, low = None, None

    return high, low


def extract_price_position(current, high, low):
    if current is None or high is None or low is None:
        return None

    if high <= low:
        return None

    position = (current - low) / (high - low) * 100

    if position < 0:
        position = 0

    if position > 100:
        position = 100

    return round(position, 2)


def extract_downside_to_low(current, low):
    if current is None or low is None or current <= 0:
        return None

    downside = (current - low) / current * 100

    if downside < 0:
        downside = 0

    return round(downside, 2)


def extract_month_sales(text):
    if not text:
        return None

    patterns = [
        r"(?:月销|月销量)\s*([0-9]+(?:\.[0-9]+)?)\s*万?\+?",
        r"(?:近30天销量|近30日销量)\s*([0-9]+(?:\.[0-9]+)?)\s*万?\+?",
        r"(?:月销|月销量|近30天销量|近30日销量)"
        r"[^0-9]{0,10}([0-9]+(?:\.[0-9]+)?)\s*万?\+?",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue

        try:
            value = float(match.group(1))
        except Exception:
            continue

        # 判断数字后面是否有“万”
        end_text = text[match.end():match.end() + 3]
        if "万" in end_text:
            value *= 10000

        if value > 0:
            return value

    return None


def extract_total_sales(text):
    if not text:
        return None

    patterns = [
        r"(?:总销|累计销量|总销量)\s*([0-9]+(?:\.[0-9]+)?)\s*万?\+?",
        r"(?:总销|累计销量|总销量)"
        r"[^0-9]{0,10}([0-9]+(?:\.[0-9]+)?)\s*万?\+?",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue

        try:
            value = float(match.group(1))
        except Exception:
            continue

        end_text = text[match.end():match.end() + 3]
        if "万" in end_text:
            value *= 10000

        if value > 0:
            return value

    return None


def calculate_turnover_evidence(sales_7d=None, sales_30d=None, sales=None):
    if sales_7d is not None and sales_7d > 0:
        return {
            "sales_velocity_7d": round(sales_7d / 7, 2),
            "turnover_evidence": f"近7日销量 {sales_7d:g}",
            "turnover_confidence": "high",
        }

    if sales_30d is not None and sales_30d > 0:
        return {
            "sales_velocity_7d": round(sales_30d / 30, 2),
            "turnover_evidence": f"近30日/月销 {sales_30d:g}，折算日均约 {sales_30d / 30:.2f}",
            "turnover_confidence": "medium",
        }

    if sales is not None and sales > 0:
        return {
            "sales_velocity_7d": None,
            "turnover_evidence": f"累计销量 {sales:g}",
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

    if re.search(r"(?:价格|售价).{0,15}(?:明显)?下跌|(?:明显)?下跌.{0,15}(?:价格|售价)", text):
        return "下跌"

    if re.search(r"(?:价格|售价).{0,15}(?:明显)?上涨|(?:明显)?上涨.{0,15}(?:价格|售价)", text):
        return "上涨"

    if re.search(r"(?:价格|售价).{0,15}(?:稳定|平稳)", text):
        return "稳定"

    return None


def extract_price_change(text):
    """
    只接受页面明确写出的：
    近7天上涨 X%
    近7日下跌 X%
    等。

    不根据两个随机数字自行计算。
    """

    if not text:
        return None, None, None

    patterns = [
        (
            "7d",
            r"(?:近|过去|最近)\s*7\s*(?:天|日)"
            r"[^。；，,\n]{0,30}?"
            r"(上涨|下跌)\s*([0-9]+(?:\.[0-9]+)?)\s*%"
        ),
        (
            "30d",
            r"(?:近|过去|最近)\s*30\s*(?:天|日)"
            r"[^。；，,\n]{0,30}?"
            r"(上涨|下跌)\s*([0-9]+(?:\.[0-9]+)?)\s*%"
        ),
        (
            "1d",
            r"(?:近|过去|最近)\s*1\s*(?:天|日)"
            r"[^。；，,\n]{0,30}?"
            r"(上涨|下跌)\s*([0-9]+(?:\.[0-9]+)?)\s*%"
        ),
    ]

    changes = {
        "1d": None,
        "7d": None,
        "30d": None,
    }

    for key, pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue

        try:
            value = float(match.group(2))
        except Exception:
            continue

        if match.group(1) == "下跌":
            value = -value

        changes[key] = value

    return changes["1d"], changes["7d"], changes["30d"]


def valid_product_name(name):
    if not name:
        return False

    name = clean_text(name)

    invalid = {
        "",
        "商品",
        "详情",
        "价格",
        "购买",
        "立即购买",
        "加入购物车",
        "未知商品",
    }

    if name in invalid:
        return False

    if len(name) < 4:
        return False

    return True


def product_key(item):
    name = clean_text(item.get("name"))

    shihuo_url = item.get("shihuo_url")
    if shihuo_url:
        return f"url:{shihuo_url}"

    product_code = clean_text(item.get("product_code"))

    # 防止 adidas / Nike / Li / Coach 等短品牌编码撞商品
    if product_code and len(product_code) >= 6:
        return f"code:{product_code}:{name}"

    return f"name:{name}"


def extract_detail(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)

    detail_text = clean_text(page.locator("body").inner_text())

    name = None

    selectors = [
        "h1",
        ".goods-title",
        ".product-title",
        "[class*='title']",
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                candidate = clean_text(locator.inner_text())
                if valid_product_name(candidate):
                    name = candidate
                    break
        except Exception:
            pass

    if not name:
        try:
            title = clean_text(page.title())
            if valid_product_name(title):
                name = title
        except Exception:
            pass

    buy_price = None

    price_selectors = [
        "[class*='price']",
        "[class*='Price']",
    ]

    for selector in price_selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                candidate_text = clean_text(locator.inner_text())
                price = extract_first_price(candidate_text)
                if price is not None:
                    buy_price = price
                    break
        except Exception:
            pass

    if buy_price is None:
        buy_price = extract_current_price(detail_text)

    sales_30d = extract_month_sales(detail_text)
    sales = extract_total_sales(detail_text)

    price_current = extract_current_price(detail_text)

    if price_current is None:
        price_current = buy_price

    price_7d_high, price_7d_low = extract_explicit_7d_prices(detail_text)

    price_position_7d = extract_price_position(
        price_current,
        price_7d_high,
        price_7d_low,
    )

    downside_to_7d_low = extract_downside_to_low(
        price_current,
        price_7d_low,
    )

    price_change_1d, price_change_7d, price_change_30d = extract_price_change(
        detail_text
    )

    price_trend = extract_price_trend(detail_text)

    turnover = calculate_turnover_evidence(
        sales_7d=None,
        sales_30d=sales_30d,
        sales=sales,
    )

    return {
        "name": name,
        "buy_price": buy_price,
        "shihuo_url": url,
        "product_code": None,
        "dewu_display_price": price_current,
        "lowest_price": price_7d_low,
        "sales": sales,
        "sales_7d": None,
        "sales_30d": sales_30d,
        "sales_velocity_7d": turnover["sales_velocity_7d"],
        "turnover_evidence": turnover["turnover_evidence"],
        "turnover_confidence": turnover["turnover_confidence"],
        "price_current": price_current,
        "price_7d_high": price_7d_high,
        "price_7d_low": price_7d_low,
        "price_position_7d": price_position_7d,
        "downside_to_7d_low": downside_to_7d_low,
        "price_change_1d": price_change_1d,
        "price_change_7d": price_change_7d,
        "price_change_30d": price_change_30d,
        "price_trend": price_trend,
        "detail_text": detail_text[:12000],
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def collect_discovery(page):
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    links = page.locator("a[href*='pcGoodsDetail']")

    urls = []

    try:
        count = links.count()
    except Exception:
        count = 0

    for i in range(min(count, MAX_DETAIL_PAGES)):
        try:
            href = links.nth(i).get_attribute("href")
            if not href:
                continue

            full_url = urljoin(HOME_URL, href)

            if "pcGoodsDetail" not in full_url:
                continue

            if full_url not in urls:
                urls.append(full_url)
        except Exception:
            continue

    return urls


def merge_products(items):
    merged = {}

    for item in items:
        if not valid_product_name(item.get("name")):
            continue

        if item.get("buy_price") is None:
            continue

        key = product_key(item)

        if key not in merged:
            merged[key] = item
            continue

        old = merged[key]

        for field, value in item.items():
            if value is not None and value != "":
                old[field] = value

    return list(merged.values())


def main():
    all_items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport=VIEWPORT,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
        )

        detail_page = browser.new_page(
            viewport=VIEWPORT,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
        )

        urls = collect_discovery(page)

        print(f"发现详情页：{len(urls)}")

        for index, url in enumerate(urls, start=1):
            try:
                print(f"\n[{index}/{len(urls)}] {url}")

                item = extract_detail(detail_page, url)

                if not valid_product_name(item.get("name")):
                    print("跳过：无有效商品名称")
                    continue

                if item.get("buy_price") is None:
                    print("跳过：没有有效买入价格")
                    continue

                all_items.append(item)

                print(f"商品：{item.get('name')}")
                print(f"买入价：{item.get('buy_price')}")
                print(f"当前价：{item.get('price_current')}")
                print(f"月销：{item.get('sales_30d')}")
                print(f"7日最高价：{item.get('price_7d_high')}")
                print(f"7日最低价：{item.get('price_7d_low')}")
                print(f"当前价距离7日最低价：{item.get('downside_to_7d_low')}%")
                print(f"周转证据：{item.get('turnover_evidence')}")
                print(f"周转数据可信度：{item.get('turnover_confidence')}")

            except Exception as e:
                print(f"采集失败：{e}")

            time.sleep(1)

        browser.close()

    products = merge_products(all_items)

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(products),
        "products": products,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n==============================")
    print(f"最终有效商品数：{len(products)}")
    print("==============================")

    for item in products[:20]:
        print(f"\n商品：{item.get('name')}")
        print(f"买入价：{item.get('buy_price')}")
        print(f"当前价：{item.get('price_current')}")
        print(f"7日最高价：{item.get('price_7d_high')}")
        print(f"7日最低价：{item.get('price_7d_low')}")
        print(f"当前价距离7日最低价：{item.get('downside_to_7d_low')}%")
        print(f"月销：{item.get('sales_30d')}")
        print(f"周转证据：{item.get('turnover_evidence')}")
        print(f"周转数据可信度：{item.get('turnover_confidence')}")


if __name__ == "__main__":
    main()
