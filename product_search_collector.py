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

    return re.sub(r"\s+", " ", str(text)).strip()


def to_number(value):
    try:
        return float(value)
    except Exception:
        return None


def extract_first_price(text):
    if not text:
        return None

    patterns = [
        r"[¥￥]\s*(\d+(?:\.\d+)?)",
        r"到手价\s*[¥￥]?\s*(\d+(?:\.\d+)?)",
        r"售价\s*[¥￥]?\s*(\d+(?:\.\d+)?)",
        r"最低价\s*[¥￥]?\s*(\d+(?:\.\d+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            value = to_number(match.group(1))

            if value is not None and 1 <= value <= 100000:
                return value

    return None


def remove_price_text(text):
    if not text:
        return ""

    text = re.sub(
        r"[¥￥]\s*\d+(?:\.\d+)?",
        " ",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"到手价\s*[¥￥]?\s*\d+(?:\.\d+)?",
        " ",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"售价\s*[¥￥]?\s*\d+(?:\.\d+)?",
        " ",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"最低价\s*[¥￥]?\s*\d+(?:\.\d+)?",
        " ",
        text,
        flags=re.I,
    )

    return clean_text(text)


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
        match = re.search(pattern, text, re.I)

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
        r"型号[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_\/\.]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            return match.group(1).strip()

    return None


def extract_dewu_price(text):
    if not text:
        return None

    patterns = [
        r"得物渠道售价\s*[¥￥]?\s*(\d+(?:\.\d+)?)",
        r"得物.*?售价\s*[¥￥]?\s*(\d+(?:\.\d+)?)",
        r"得物.*?(\d+(?:\.\d+)?)\s*元",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            value = to_number(match.group(1))

            if value is not None and value > 0:
                return value

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
        match = re.search(pattern, text, re.I)

        if match:
            value = to_number(match.group(1))

            if value is not None and value > 0:
                return value

    return None


def is_detail_url(href):
    if not href:
        return False

    return (
        "pcGoodsDetail" in href
        or "/page/pcGoodsDetail" in href
    )


def looks_like_real_product_name(name):
    if not name:
        return False

    name = clean_text(name)

    if len(name) < 4:
        return False

    # 过滤明显只有价格/按钮文字的内容
    if re.fullmatch(
        r"[\d\.\s¥￥元到手价售价最低价]+",
        name,
        re.I,
    ):
        return False

    bad_words = [
        "立即购买",
        "去购买",
        "点击购买",
        "查看详情",
        "详情",
        "收藏",
        "分享",
    ]

    if name in bad_words:
        return False

    return True


def extract_name_from_link(link):
    candidates = []

    # 1. aria-label
    try:
        value = link.get_attribute(
            "aria-label",
            timeout=1000,
        )

        if value:
            candidates.append(value)
    except Exception:
        pass

    # 2. title
    try:
        value = link.get_attribute(
            "title",
            timeout=1000,
        )

        if value:
            candidates.append(value)
    except Exception:
        pass

    # 3. 链接本身文字
    try:
        value = link.inner_text(
            timeout=1000
        )

        if value:
            candidates.append(value)
    except Exception:
        pass

    # 4. 找最近的父级卡片
    for level in range(1, 5):

        try:
            parent = link.locator(
                "/.." * level
            )

            text = parent.inner_text(
                timeout=1000
            )

            if text:
                candidates.append(text)

        except Exception:
            continue

    best = ""

    for candidate in candidates:

        candidate = remove_price_text(
            candidate
        )

        candidate = clean_text(
            candidate
        )

        if not looks_like_real_product_name(
            candidate
        ):
            continue

        # 去掉太长的整卡片文本
        if len(candidate) > 180:
            parts = re.split(
                r"\s{2,}| \| ",
                candidate
            )

            for part in parts:
                part = clean_text(part)

                if looks_like_real_product_name(
                    part
                ) and len(part) < len(candidate):
                    candidate = part

        if not best or len(candidate) > len(best):
            best = candidate

    return best


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

    # 多次滚动，让公开商品尽可能加载
    for _ in range(4):

        try:
            page.mouse.wheel(
                0,
                1800
            )

            page.wait_for_timeout(
                1200
            )

        except Exception:
            break

    products = []
    seen_urls = set()

    try:
        links = page.locator("a")

        count = links.count()

        print(
            f"首页链接数量：{count}"
        )

    except Exception:
        return []

    for i in range(
        min(count, 500)
    ):

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

            raw_text = ""

            try:
                raw_text = clean_text(
                    link.inner_text(
                        timeout=1000
                    )
                )
            except Exception:
                pass

            price = extract_first_price(
                raw_text
            )

            name = extract_name_from_link(
                link
            )

            if not name:
                continue

            # 如果链接自身没有价格，
            # 从父级卡片中寻找价格
            if price is None:

                for level in range(1, 5):

                    try:

                        parent = link.locator(
                            "/.." * level
                        )

                        parent_text = clean_text(
                            parent.inner_text(
                                timeout=1000
                            )
                        )

                        price = extract_first_price(
                            parent_text
                        )

                        if price is not None:
                            break

                    except Exception:
                        continue

            if price is None:
                continue

            seen_urls.add(href)

            item = {
                "name": name,
                "buy_price": price,
                "shihuo_url": href,
                "source": "识货公开PC首页",
                "observed_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(),
                ),
            }

            products.append(item)

            print(
                f"发现商品：{name[:80]} | "
                f"买入 ¥{price:.2f}"
            )

        except Exception:
            continue

    print(
        f"首页发现有效商品："
        f"{len(products)}"
    )

    return products


def collect_detail(page, product):

    url = product.get(
        "shihuo_url"
    )

    if not url:
        return product

    print()
    print("-" * 70)
    print(
        f"读取商品详情："
        f"{product.get('name')}"
    )
    print(url)

    try:

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=DETAIL_TIMEOUT,
        )

    except Exception as e:

        print(
            f"⚠️ 商品详情打开失败：{e}"
        )

        product[
            "detail_status"
        ] = "failed"

        return product

    try:
        page.wait_for_timeout(
            1500
        )
    except Exception:
        pass

    try:

        body = clean_text(
            page.locator(
                "body"
            ).inner_text(
                timeout=3000
            )
        )

    except Exception:
        body = ""

    if not body:

        product[
            "detail_status"
        ] = "empty"

        return product

    product[
        "detail_status"
    ] = "ok"

    # --------------------------------------------------
    # 详情页重新确认商品名称
    # --------------------------------------------------

    detail_name = ""

    try:

        title = page.title()

        if title:
            detail_name = clean_text(
                title
            )

            detail_name = remove_price_text(
                detail_name
            )

    except Exception:
        pass

    if looks_like_real_product_name(
        detail_name
    ):

        if len(detail_name) <= 150:
            product["name"] = detail_name

    # --------------------------------------------------
    # 货号
    # --------------------------------------------------

    product[
        "product_code"
    ] = extract_product_code(
        body
    )

    # --------------------------------------------------
    # 得物价格
    # --------------------------------------------------

    product[
        "dewu_display_price"
    ] = extract_dewu_price(
        body
    )

    # --------------------------------------------------
    # 全网最低价
    # --------------------------------------------------

    product[
        "lowest_price"
    ] = extract_channel_lowest_price(
        body
    )

    # --------------------------------------------------
    # 销量
    # --------------------------------------------------

    product[
        "sales"
    ] = extract_sales(
        body
    )

    # --------------------------------------------------
    # 详情页重新确认买入价
    # --------------------------------------------------

    detail_price = extract_first_price(
        body
    )

    if detail_price is not None:
        product[
            "buy_price"
        ] = detail_price

    # 保存少量原始证据
    product[
        "detail_text"
    ] = body[:3000]

    product[
        "discovery_observed_at"
    ] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(),
    )

    print(
        f"商品名称："
        f"{product.get('name')}"
    )

    print(
        f"买入侧价格："
        f"¥{product.get('buy_price')}"
    )

    if product.get(
        "dewu_display_price"
    ) is not None:

        print(
            "得物渠道售价："
            f"¥{product['dewu_display_price']:.2f}"
        )

    if product.get(
        "product_code"
    ):

        print(
            "货号："
            f"{product['product_code']}"
        )

    if product.get(
        "sales"
    ):

        print(
            "销量："
            f"{product['sales']}"
        )

    return product


def deduplicate(products):

    result = {}

    for item in products:

        if not isinstance(
            item,
            dict
        ):
            continue

        name = clean_text(
            item.get(
                "name",
                ""
            )
        )

        if not looks_like_real_product_name(
            name
        ):
            continue

        code = clean_text(
            item.get(
                "product_code",
                ""
            )
        )

        url = clean_text(
            item.get(
                "shihuo_url",
                ""
            )
        )

        key = (
            "code:"
            + code.lower()
            if code
            else
            "url:"
            + url.lower()
            if url
            else
            "name:"
            + name.lower()
        )

        if key not in result:

            result[key] = item

            continue

        old = result[key]

        old_price = to_number(
            old.get(
                "buy_price"
            )
        )

        new_price = to_number(
            item.get(
                "buy_price"
            )
        )

        if (
            new_price is not None
            and (
                old_price is None
                or new_price < old_price
            )
        ):

            result[key] = item

    return list(
        result.values()
    )


def save(products):

    data = {
        "updated_at":
            time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(),
            ),

        "source":
            "识货公开PC首页及商品详情页",

        "stale":
            len(products) == 0,

        "products":
            products,
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
        f"最终有效发现商品："
        f"{len(products)}"
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
                    f"{index}/"
                    f"{min(len(products), MAX_DETAIL_PAGES)} "
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

    products = products[
        :MAX_PRODUCTS
    ]

    save(
        products
    )


if __name__ == "__main__":
    main()
