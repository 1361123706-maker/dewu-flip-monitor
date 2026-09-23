import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


ROOT = Path(__file__).resolve().parent

OUTPUT_FILE = ROOT / "discovery_data.json"

HOME_URL = "https://www.shihuo.cn/page/pcHome"

MAX_PRODUCTS = 60
MAX_DETAIL_PAGES = 40

PAGE_TIMEOUT = 20000
DETAIL_TIMEOUT = 15000


def clean_text(text):
    if not text:
        return ""

    return re.sub(r"\s+", " ", text).strip()


def to_number(value):
    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


def extract_first_price(text):
    if not text:
        return None

    patterns = [
        r"[¥￥]\s*(\d+(?:\.\d+)?)",
        r"到手价\s*(\d+(?:\.\d+)?)",
        r"售价\s*(\d+(?:\.\d+)?)",
        r"最低价\s*(\d+(?:\.\d+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            try:
                price = float(match.group(1))

                if 1 <= price <= 100000:
                    return price

            except Exception:
                pass

    return None


def extract_sales(text):
    if not text:
        return None

    patterns = [
        r"总销\s*(\d+(?:\.\d+)?[万wW]?)",
        r"月销\s*(\d+(?:\.\d+)?[万wW]?)",
        r"已售\s*(\d+(?:\.\d+)?[万wW]?)",
        r"(\d+(?:\.\d+)?[万wW]?)人付款",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            return match.group(1)

    return None


def extract_product_code(text):
    if not text:
        return None

    patterns = [
        r"货号[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_\/\.]+)",
        r"款号[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_\/\.]+)",
        r"SKU[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_\/\.]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            return match.group(1).strip()

    return None


def extract_dewu_price(text):
    if not text:
        return None

    # 例如：
    # 其他渠道：得物渠道售价500.00元
    patterns = [
        r"得物渠道售价\s*(\d+(?:\.\d+)?)",
        r"得物.*?售价\s*(\d+(?:\.\d+)?)",
        r"得物.*?(\d+(?:\.\d+)?)\s*元",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            try:
                value = float(match.group(1))

                if value > 0:
                    return value

            except Exception:
                pass

    return None


def extract_channel_lowest_price(text):
    if not text:
        return None

    patterns = [
        r"最低价为\s*[¥￥]?\s*(\d+(?:\.\d+)?)",
        r"全网最低价\s*[¥￥]?\s*(\d+(?:\.\d+)?)",
        r"全网价格区间.*?(\d+(?:\.\d+)?)\s*元",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            try:
                value = float(match.group(1))

                if value > 0:
                    return value

            except Exception:
                pass

    return None


def is_detail_url(href):
    if not href:
        return False

    return (
        "pcGoodsDetail" in href
        or "/page/pcGoodsDetail" in href
    )


def collect_home_products(page):
    print("=" * 70)
    print("开始读取识货公开商品首页")
    print(HOME_URL)
    print("=" * 70)

    try:
        page.goto(
            HOME_URL,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT,
        )

    except PlaywrightTimeoutError:
        print("⚠️ 识货首页打开超时")
        return []

    except Exception as e:
        print(f"⚠️ 识货首页打开失败：{e}")
        return []

    page.wait_for_timeout(3000)

    try:
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(1500)

        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(1500)

    except Exception:
        pass

    products = []
    seen_urls = set()

    try:
        links = page.locator("a")

        count = links.count()

        print(f"首页链接数量：{count}")

    except Exception:
        return []

    for i in range(min(count, 300)):

        if len(products) >= MAX_PRODUCTS:
            break

        try:
            link = links.nth(i)

            href = link.get_attribute(
                "href",
                timeout=1000,
            )

            if not href:
                continue

            href = urljoin(
                "https://www.shihuo.cn",
                href,
            )

            if not is_detail_url(href):
                continue

            if href in seen_urls:
                continue

            name = clean_text(
                link.inner_text(timeout=1000)
            )

            if len(name) < 5:
                continue

            price = extract_first_price(name)

            if price is None:
                continue

            seen_urls.add(href)

            products.append(
                {
                    "name": name,
                    "buy_price": price,
                    "shihuo_url": href,
                    "source": "识货公开PC首页",
                    "observed_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ",
                        time.gmtime(),
                    ),
                }
            )

            print(
                f"发现候选：{name[:70]} | "
                f"¥{price:.2f}"
            )

        except Exception:
            continue

    print(
        f"首页发现候选商品：{len(products)}"
    )

    return products


def collect_detail(page, product):
    url = product.get("shihuo_url")

    if not url:
        return product

    print()
    print("-" * 70)
    print("读取商品详情：")
    print(product.get("name"))
    print(url)

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=DETAIL_TIMEOUT,
        )

    except Exception as e:
        print(f"⚠️ 商品详情打开失败：{e}")
        product["detail_status"] = "failed"
        return product

    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass

    try:
        body = clean_text(
            page.locator("body").inner_text(
                timeout=3000
            )
        )

    except Exception:
        body = ""

    if not body:
        product["detail_status"] = "empty"
        return product

    product["detail_status"] = "ok"

    product["product_code"] = (
        extract_product_code(body)
    )

    product["dewu_display_price"] = (
        extract_dewu_price(body)
    )

    product["lowest_price"] = (
        extract_channel_lowest_price(body)
    )

    product["sales"] = extract_sales(body)

    # 从详情页重新确认价格
    detail_price = extract_first_price(body)

    if detail_price is not None:
        product["buy_price"] = detail_price

    product["detail_text"] = body[:1500]

    # 如果详情页明确出现得物渠道价格
    if product["dewu_display_price"] is not None:
        print(
            "识货详情页发现得物渠道售价："
            f"¥{product['dewu_display_price']:.2f}"
        )

    if product["product_code"]:
        print(
            f"货号：{product['product_code']}"
        )

    if product["sales"]:
        print(
            f"销量信号：{product['sales']}"
        )

    print(
        f"买入侧价格："
        f"¥{product.get('buy_price')}"
    )

    return product


def deduplicate(products):
    result = {}

    for item in products:

        name = clean_text(
            item.get("name", "")
        )

        if not name:
            continue

        code = clean_text(
            item.get("product_code", "")
        )

        url = item.get(
            "shihuo_url",
            ""
        )

        key = (
            code.lower()
            if code
            else url.lower()
            if url
            else name.lower()
        )

        if key not in result:
            result[key] = item
            continue

        old = result[key]

        old_price = to_number(
            old.get("buy_price")
        )

        new_price = to_number(
            item.get("buy_price")
        )

        if (
            new_price is not None
            and (
                old_price is None
                or new_price < old_price
            )
        ):
            result[key] = item

    return list(result.values())


def save(products):
    data = {
        "updated_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(),
        ),

        "source": (
            "识货公开PC首页及商品详情页"
        ),

        "stale": (
            len(products) == 0
        ),

        "products": products,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 70)
    print(
        f"最终发现商品：{len(products)}"
    )
    print(
        f"写入：{OUTPUT_FILE}"
    )
    print("=" * 70)


def main():

    products = []

    with sync_playwright() as p:

        browser = None

        try:

            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            context = browser.new_context(
                viewport={
                    "width": 1440,
                    "height": 1000,
                },
                locale="zh-CN",
            )

            page = context.new_page()

            products = collect_home_products(
                page
            )

            detail_products = []

            for index, product in enumerate(
                products[:MAX_DETAIL_PAGES],
                start=1,
            ):

                print(
                    f"\n######## "
                    f"{index}/{min(len(products), MAX_DETAIL_PAGES)} "
                    f"########"
                )

                detail_products.append(
                    collect_detail(
                        page,
                        product,
                    )
                )

            products = detail_products

            context.close()

        finally:

            try:
                if browser:
                    browser.close()
            except Exception:
                pass

    products = deduplicate(
        products
    )

    products = products[:MAX_PRODUCTS]

    save(products)


if __name__ == "__main__":
    main()
