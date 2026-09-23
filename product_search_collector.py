import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urljoin

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


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

PAGE_LOAD_TIMEOUT = 20000
KEYWORD_TIMEOUT = 60
BODY_TIMEOUT = 5000
SCROLL_WAIT = 1


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
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("已写入：", INPUT_FILE)


def clean_text(text):
    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def extract_price(text):
    if not text:
        return None

    patterns = [
        r"[¥￥]\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*元",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
        )

        if match:
            try:
                value = float(
                    match.group(1)
                )

                if 1 <= value <= 100000:
                    return round(
                        value,
                        2,
                    )

            except Exception:
                pass

    return None


def is_product_url(url):
    if not url:
        return False

    lower_url = url.lower()

    keywords = [
        "goods",
        "product",
        "detail",
        "item",
    ]

    return any(
        keyword in lower_url
        for keyword in keywords
    )


def collect_from_page(
    page,
    keyword,
):
    results = []

    search_url = SEARCH_URL.format(
        keyword=quote(keyword)
    )

    print("")
    print("=" * 70)
    print("正在浏览：", keyword)
    print(search_url)
    print("=" * 70)

    start_time = time.time()

    try:
        page.goto(
            search_url,
            wait_until="domcontentloaded",
            timeout=PAGE_LOAD_TIMEOUT,
        )

    except PlaywrightTimeoutError:
        print(
            "⚠️ 页面加载超过 20 秒，"
            "判定本关键词失败"
        )
        return results

    except Exception as e:
        print(
            "⚠️ 打开页面失败：",
            e,
        )
        return results

    if time.time() - start_time > KEYWORD_TIMEOUT:
        print("⚠️ 本关键词超过时间限制")
        return results

    time.sleep(2)

    try:
        page.mouse.wheel(
            0,
            1200,
        )

        time.sleep(
            SCROLL_WAIT
        )

        page.mouse.wheel(
            0,
            1200,
        )

        time.sleep(
            SCROLL_WAIT
        )

    except Exception as e:
        print(
            "滚动页面失败：",
            e,
        )

    if time.time() - start_time > KEYWORD_TIMEOUT:
        print(
            "⚠️ 页面操作超过 60 秒，"
            "判定本关键词失败"
        )
        return results

    try:
        title = page.title()

    except Exception:
        title = ""

    print(
        "当前页面标题：",
        title,
    )

    try:
        body_text = page.locator(
            "body"
        ).inner_text(
            timeout=BODY_TIMEOUT
        )

    except Exception:
        body_text = ""

    body_text = clean_text(
        body_text
    )

    print(
        "页面文字长度：",
        len(body_text),
    )

    if body_text:
        print(
            "页面文字前300字："
        )
        print(
            body_text[:300]
        )

    links = []

    try:
        anchors = page.locator(
            "a"
        ).all()

        for anchor in anchors:

            if time.time() - start_time > KEYWORD_TIMEOUT:
                print(
                    "⚠️ 读取链接超过 60 秒"
                )
                return results

            try:
                href = anchor.get_attribute(
                    "href"
                )

                text = clean_text(
                    anchor.inner_text()
                )

                if not href:
                    continue

                full_url = urljoin(
                    page.url,
                    href,
                )

                if not is_product_url(
                    full_url
                ):
                    continue

                links.append(
                    {
                        "url": full_url,
                        "text": text,
                    }
                )

            except Exception:
                continue

    except Exception as e:
        print(
            "读取链接失败：",
            e,
        )

    unique_links = {}

    for item in links:
        unique_links[
            item["url"]
        ] = item

    links = list(
        unique_links.values()
    )

    print(
        "发现疑似商品链接：",
        len(links),
    )

    for item in links[
        :MAX_PRODUCTS
    ]:

        if time.time() - start_time > KEYWORD_TIMEOUT:
            print(
                "⚠️ 商品解析超过 60 秒，"
                "提前结束本关键词"
            )
            break

        name = clean_text(
            item["text"]
        )

        if len(name) < 2:
            continue

        price = extract_price(
            name
        )

        if price is None:

            try:
                locator = page.locator(
                    "a"
                ).filter(
                    has_text=name
                ).first

                parent_text = clean_text(
                    locator.locator(
                        ".."
                    ).inner_text(
                        timeout=2000
                    )
                )

                price = extract_price(
                    parent_text
                )

            except Exception:
                pass

        # 没有价格的数据暂时不进入商品数据库
        if price is None:
            continue

        result = {
            "name": name[:200],

            "buy_prices": {
                "识货": price
            },

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

            "source_note":
                "浏览器实际打开识货公开页面采集",

            "data_source":
                "shihuo_browser_public_web",

            "data_time":
                time.strftime(
                    "%Y-%m-%d"
                ),

            "source_url":
                item["url"],
        }

        results.append(
            result
        )

    print(
        f"关键词「{keyword}」"
        f"有效商品：{len(results)}"
    )

    return results


def merge_products(
    existing,
    new_products,
):
    merged = {}

    for product in existing:

        if not isinstance(
            product,
            dict
        ):
            continue

        name = clean_text(
            product.get(
                "name",
                ""
            )
        )

        if name:
            merged[name] = product

    for product in new_products:

        if not isinstance(
            product,
            dict
        ):
            continue

        name = clean_text(
            product.get(
                "name",
                ""
            )
        )

        buy_prices = product.get(
            "buy_prices",
            {}
        )

        if not name:
            continue

        if not isinstance(
            buy_prices,
            dict
        ):
            continue

        if not buy_prices:
            continue

        merged[name] = product

    return list(
        merged.values()
    )


def create_browser(p):
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
            "Mozilla/5.0 "
            "(X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0.0.0 "
            "Safari/537.36"
        ),
    )

    page = context.new_page()

    return browser, context, page


def main():

    print("")
    print("=" * 60)
    print(
        "真实浏览器公开商品采集器"
    )
    print("=" * 60)

    existing_data = load_existing()

    existing_products = (
        existing_data.get(
            "products",
            []
        )
    )

    print(
        "仓库原有商品数量：",
        len(existing_products)
    )

    collected = []

    with sync_playwright() as p:

        browser = None
        context = None
        page = None

        try:
            browser, context, page = (
                create_browser(p)
            )

            total_keywords = min(
                len(KEYWORDS),
                MAX_KEYWORDS,
            )

            for index, keyword in enumerate(
                KEYWORDS[:MAX_KEYWORDS],
                1,
            ):

                print("")
                print(
                    f"【{index}/{total_keywords}】"
                )

                success = False

                for attempt in range(
                    1,
                    3
                ):

                    print(
                        f"本关键词第 "
                        f"{attempt}/2 次尝试"
                    )

                    start = time.time()

                    try:

                        products = (
                            collect_from_page(
                                page,
                                keyword,
                            )
                        )

                        elapsed = (
                            time.time()
                            - start
                        )

                        if products:

                            collected.extend(
                                products
                            )

                            print(
                                f"采集成功，"
                                f"耗时 {elapsed:.1f} 秒"
                            )

                            success = True

                            break

                        print(
                            f"没有获得有效商品，"
                            f"耗时 {elapsed:.1f} 秒"
                        )

                    except Exception as e:

                        print(
                            "⚠️ 本关键词发生异常：",
                            e,
                        )

                    # 当前关键词失败：
                    # 关闭浏览器并重新启动
                    print(
                        "关闭当前浏览器，"
                        "准备重新启动..."
                    )

                    try:
                        if context:
                            context.close()
                    except Exception:
                        pass

                    try:
                        if browser:
                            browser.close()
                    except Exception:
                        pass

                    browser, context, page = (
                        create_browser(p)
                    )

                    time.sleep(2)

                if not success:

                    print(
                        f"⚠️ 关键词「{keyword}」"
                        f"连续失败，跳过。"
                    )

                time.sleep(1)

        finally:

            try:
                if context:
                    context.close()
            except Exception:
                pass

            try:
                if browser:
                    browser.close()
            except Exception:
                pass

    print("")
    print("=" * 60)
    print("采集结束")
    print("=" * 60)

    print(
        "本次浏览器实际发现有效商品：",
        len(collected),
    )

    if collected:

        print("")
        print("前10个采集结果：")

        for product in collected[:10]:

            print(
                "-",
                product.get(
                    "name"
                ),
                "|",
                product.get(
                    "buy_prices"
                ),
            )

    else:

        print("")
        print(
            "⚠️ 本次没有获得新的"
            "有效商品数据。"
        )

    merged = merge_products(
        existing_products,
        collected,
    )

    existing_data[
        "products"
    ] = merged

    save_data(
        existing_data
    )

    print("")
    print(
        "最终仓库商品数量：",
        len(merged)
    )

    print(
        "本次新增/更新：",
        len(collected)
    )

    print("")


if __name__ == "__main__":
    main()
