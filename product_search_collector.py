import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


INPUT_FILE = "market_data_input.json"

KEYWORDS = [
    "Nike",
    "adidas",
    "New Balance",
    "ASICS",
    "PUMA",
    "李宁",
    "安踏",
    "乔丹体育",
    "运动鞋",
    "球鞋",
    "潮鞋",
    "跑鞋",
    "服饰",
    "包袋",
]

SEARCH_URL = (
    "https://m.shihuo.cn/search/searchResult/goods"
    "?keywords={keyword}&page=1&pagesize=30"
)

MAX_KEYWORDS = 14
MAX_PRODUCTS = 80
PAGE_WAIT_SECONDS = 5


def load_existing():
    path = Path(INPUT_FILE)

    if not path.exists():
        return {"products": []}

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {"products": []}

        if not isinstance(data.get("products"), list):
            data["products"] = []

        return data

    except Exception as e:
        print("读取已有数据失败：", e)
        return {"products": []}


def save_data(data):
    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("已写入：", INPUT_FILE)


def clean_text(text):
    if not text:
        return ""

    return re.sub(r"\s+", " ", text).strip()


def extract_price(text):
    """
    从文本中寻找价格。
    例如：
    ¥299
    ￥299
    299元
    299.00
    """

    if not text:
        return None

    patterns = [
        r"[¥￥]\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*元",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            try:
                value = float(match.group(1))

                if 1 <= value <= 100000:
                    return round(value, 2)

            except Exception:
                pass

    return None


def is_product_url(url):
    if not url:
        return False

    url = url.lower()

    keywords = [
        "goods",
        "product",
        "detail",
        "item",
    ]

    return any(x in url for x in keywords)


def collect_from_page(page, keyword):
    results = []

    search_url = SEARCH_URL.format(keyword=quote(keyword))

    print("")
    print("=" * 70)
    print("正在浏览：", keyword)
    print(search_url)
    print("=" * 70)

    try:
        page.goto(
            search_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )

    except PlaywrightTimeoutError:
        print("页面加载超时，继续读取当前页面")

    except Exception as e:
        print("打开页面失败：", e)
        return results

    time.sleep(PAGE_WAIT_SECONDS)

    try:
        page.mouse.wheel(0, 1500)
        time.sleep(2)
        page.mouse.wheel(0, 1500)
        time.sleep(2)
    except Exception:
        pass

    print("当前页面标题：", page.title())

    try:
        body_text = page.locator("body").inner_text(timeout=10000)
    except Exception:
        body_text = ""

    body_text = clean_text(body_text)

    print("页面文字长度：", len(body_text))

    if body_text:
        print("页面文字前500字：")
        print(body_text[:500])

    links = []

    try:
        anchors = page.locator("a").all()

        for anchor in anchors:
            try:
                href = anchor.get_attribute("href")
                text = clean_text(anchor.inner_text())

                if not href:
                    continue

                full_url = urljoin(page.url, href)

                if is_product_url(full_url):
                    links.append(
                        {
                            "url": full_url,
                            "text": text,
                        }
                    )

            except Exception:
                continue

    except Exception as e:
        print("读取链接失败：", e)

    # 去重
    unique_links = {}

    for item in links:
        unique_links[item["url"]] = item

    links = list(unique_links.values())

    print("发现疑似商品链接：", len(links))

    for item in links[:MAX_PRODUCTS]:
        name = clean_text(item["text"])

        if len(name) < 2:
            name = "未知商品"

        price = extract_price(name)

        # 如果链接文字没有价格，则从页面附近寻找
        if price is None:
            try:
                href = item["url"]

                locator = page.locator(
                    f'a[href="{item["url"]}"]'
                ).first

                parent_text = clean_text(
                    locator.locator("..").inner_text(timeout=3000)
                )

                price = extract_price(parent_text)

                if len(name) < 4 and parent_text:
                    name = parent_text[:200]

            except Exception:
                pass

        result = {
            "name": name[:200],
            "buy_prices": {},
            "dewu_price": None,
            "recent_avg_price": None,
            "recent_trade_time": None,
            "seller_count": None,
            "days": None,
            "liquidity": None,
            "downside_loss": None,
            "authenticity_verified": False,
            "new_condition_verified": False,
            "dewu_check_compatible": False,
            "technical_service_fee": None,
            "technical_service_rate": None,
            "transfer_fee": None,
            "transfer_fee_rate": None,
            "operation_service_fee": None,
            "consumer_shipping_subsidy": None,
            "after_sales_service_fee": None,
            "seller_coupon_offset": None,
            "expected_income": None,
            "source_note": "浏览器实际打开识货公开页面采集",
            "data_source": "shihuo_browser_public_web",
            "data_time": time.strftime("%Y-%m-%d"),
            "source_url": item["url"],
        }

        if price is not None:
            result["buy_prices"]["识货"] = price

        results.append(result)

    return results


def merge_products(existing, new_products):
    """
    按商品名称去重。
    新采集到的数据优先。
    """

    merged = {}

    for product in existing:
        name = clean_text(product.get("name", ""))

        if name:
            merged[name] = product

    for product in new_products:
        name = clean_text(product.get("name", ""))

        if name:
            merged[name] = product

    return list(merged.values())


def main():
    print("")
    print("==============================================")
    print("   真实浏览器公开商品采集器")
    print("==============================================")
    print("")

    existing_data = load_existing()
    existing_products = existing_data.get("products", [])

    print("仓库原有商品数量：", len(existing_products))

    collected = []

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1280,
                "height": 900,
            },
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        for index, keyword in enumerate(KEYWORDS[:MAX_KEYWORDS], 1):

            print("")
            print(
                f"【{index}/{min(len(KEYWORDS), MAX_KEYWORDS)}】"
            )

            products = collect_from_page(
                page,
                keyword,
            )

            print(
                f"关键词「{keyword}」实际提取商品："
                f"{len(products)}"
            )

            collected.extend(products)

            # 防止连续快速访问
            time.sleep(2)

        browser.close()

    print("")
    print("==============================================")
    print("采集结束")
    print("==============================================")

    print("本次浏览器实际发现商品：", len(collected))

    if collected:
        print("")
        print("前10个实际采集结果：")

        for product in collected[:10]:
            print(
                "-",
                product.get("name"),
                "|",
                product.get("buy_prices"),
            )

    else:
        print("")
        print("⚠️ 本次没有解析到商品。")
        print("这意味着需要继续检查网站页面结构，")
        print("而不是把旧数据当成新数据。")

    merged = merge_products(
        existing_products,
        collected,
    )

    existing_data["products"] = merged

    save_data(existing_data)

    print("")
    print("最终仓库商品数量：", len(merged))
    print("新增/更新商品数量：", len(collected))
    print("")


if __name__ == "__main__":
    main()
