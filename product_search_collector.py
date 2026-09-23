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
    """
    尽可能从商品卡片文字中提取价格。

    支持：
    ¥123
    ￥123
    123元
    123.00
    价格：123
    到手价123
    """

    if not text:
        return None

    text = clean_text(text)

    patterns = [
        r"[¥￥]\s*(\d+(?:\.\d+)?)",
        r"(?:到手价|券后价|优惠价|售价|价格|低至|起)\s*[：:]?\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*元",
    ]

    for pattern in patterns:
        matches = re.findall(
            pattern,
            text,
        )

        for value_text in matches:
            try:
                value = float(value_text)

                # 排除明显不可能是商品价格的数字
                if 5 <= value <= 100000:
                    return round(value, 2)

            except Exception:
                continue

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


def get_nearby_text(anchor):
    """
    读取商品链接附近的文字。

    不只读取 <a> 自己，
    还读取父级、上一级、上两级，
    解决价格写在商品卡片其他 DOM 节点的问题。
    """

    texts = []

    try:
        text = clean_text(
            anchor.inner_text(
                timeout=1500
            )
        )

        if text:
            texts.append(text)

    except Exception:
        pass

    current = anchor

    for level in range(1, 4):

        try:
            current = current.locator(
                ".."
            )

            text = clean_text(
                current.inner_text(
                    timeout=1500
                )
            )

            if text:
                texts.append(text)

        except Exception:
            break

    # 去重，同时限制长度
    unique = []

    for text in texts:

        if not text:
            continue

        if text in unique:
            continue

        unique.append(text)

        if len(unique) >= 4:
            break

    return unique


def make_product(
    name,
    price,
    source_url,
):
    return {
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
            source_url,
    }


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
            "⚠️ 页面加载超过20秒，"
            "跳过本关键词"
        )
        return results

    except Exception as e:
        print(
            "⚠️ 打开页面失败：",
            e,
        )
        return results

    # 给动态商品一点时间
    time.sleep(3)

    # 滚动触发更多商品
    try:
        page.mouse.wheel(
            0,
            1500,
        )

        time.sleep(1)

        page.mouse.wheel(
            0,
            1500,
        )

        time.sleep(1)

    except Exception as e:
        print(
            "滚动失败：",
            e,
        )

    if time.time() - start_time > KEYWORD_TIMEOUT:
        print(
            "⚠️ 本关键词超过60秒"
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
        body_text = clean_text(
            page.locator(
                "body"
            ).inner_text(
                timeout=BODY_TIMEOUT
            )
        )

    except Exception:
        body_text = ""

    print(
        "页面文字长度：",
        len(body_text),
    )

    if body_text:
        print(
            "页面文字前500字："
        )
        print(
            body_text[:500]
        )

    # ==================================================
    # 第一阶段：
    # 找页面上的所有链接
    # ==================================================

    candidates = []

    try:
        anchors = page.locator(
            "a"
        ).all()

        print(
            "页面链接数量：",
            len(anchors),
        )

        for anchor in anchors:

            if (
                time.time()
                - start_time
                > KEYWORD_TIMEOUT
            ):
                print(
                    "⚠️ 读取链接超过60秒"
                )
                break

            try:
                href = anchor.get_attribute(
                    "href"
                )

                if not href:
                    continue

                full_url = urljoin(
                    page.url,
                    href,
                )

                anchor_text = clean_text(
                    anchor.inner_text(
                        timeout=1000
                    )
                )

                # 商品链接优先
                product_url = is_product_url(
                    full_url
                )

                # 即使 URL 不明显像商品，
                # 只要链接文字有一定长度，
                # 也先保留，后面根据价格判断
                possible_product = (
                    product_url
                    or len(anchor_text) >= 4
                )

                if not possible_product:
                    continue

                candidates.append(
                    {
                        "anchor": anchor,
                        "url": full_url,
                        "text": anchor_text,
                    }
                )

            except Exception:
                continue

    except Exception as e:
        print(
            "读取页面链接失败：",
            e,
        )

    print(
        "发现候选链接：",
        len(candidates),
    )

    # ==================================================
    # 第二阶段：
    # 从商品链接附近的整个商品卡片找价格
    # ==================================================

    seen_names = set()
    seen_urls = set()

    for item in candidates:

        if len(results) >= MAX_PRODUCTS:
            break

        if (
            time.time()
            - start_time
            > KEYWORD_TIMEOUT
        ):
            print(
                "⚠️ 商品解析达到60秒"
            )
            break

        anchor = item["anchor"]
        url = item["url"]
        anchor_text = item["text"]

        if url in seen_urls:
            continue

        seen_urls.add(url)

        nearby_texts = get_nearby_text(
            anchor
        )

        if not nearby_texts:
            continue

        # 最长的附近文本通常是商品卡片
        card_text = max(
            nearby_texts,
            key=len,
        )

        card_text = clean_text(
            card_text
        )

        if len(card_text) < 4:
            continue

        # ==================================================
        # 找价格
        # ==================================================

        price = None

        for text in nearby_texts:

            price = extract_price(
                text
            )

            if price is not None:
                break

        if price is None:
            continue

        # ==================================================
        # 找商品名称
        # ==================================================

        name = anchor_text

        # 如果链接本身文字太短，
        # 从商品卡片文字里找一个合理名称
        if len(name) < 4:

            name = card_text

            # 去掉常见价格部分
            name = re.sub(
                r"[¥￥]\s*\d+(?:\.\d+)?",
                "",
                name,
            )

            name = re.sub(
                r"\d+(?:\.\d+)?\s*元",
                "",
                name,
            )

            name = clean_text(
                name
            )

        if len(name) < 4:
            continue

        # 防止把纯数字、导航、按钮当商品
        if re.fullmatch(
            r"[\d\s\.\-]+",
            name,
        ):
            continue

        # 商品名称去重
        name_key = name.lower()

        if name_key in seen_names:
            continue

        seen_names.add(
            name_key
        )

        result = make_product(
            name=name,
            price=price,
            source_url=url,
        )

        results.append(
            result
        )

        print(
            "✓ 商品：",
            name[:80],
            "| 识货价：",
            price,
        )

    print("")
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

    # 保留已有数据
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

        if not name:
            continue

        merged[name] = product

    # 新数据覆盖同名旧数据
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

    return (
        browser,
        context,
        page,
    )


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

                # 每个关键词最多尝试2次
                for attempt in range(
                    1,
                    3
                ):

                    print(
                        f"关键词第 "
                        f"{attempt}/2 次尝试"
                    )

                    try:

                        products = (
                            collect_from_page(
                                page,
                                keyword,
                            )
                        )

                        if products:

                            collected.extend(
                                products
                            )

                            success = True

                            print(
                                "本关键词采集成功：",
                                len(products),
                            )

                            break

                        print(
                            "本次没有提取到有效商品"
                        )

                    except Exception as e:

                        print(
                            "⚠️ 关键词异常：",
                            e,
                        )

                    # 失败就重启浏览器
                    if not success:

                        print(
                            "关闭当前浏览器，"
                            "重新启动..."
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
                        f"⚠️ 「{keyword}」"
                        f"连续失败，跳过"
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
        print("前20个实际结果：")

        for product in collected[:20]:

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
            "有效商品"
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
