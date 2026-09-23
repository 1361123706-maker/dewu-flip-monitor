import json
import re
import time
from urllib.parse import quote

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


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

# 页面打开后，最多等待商品列表加载的时间
PAGE_WAIT_MAX = 15

OUTPUT_FILE = "market_data_input.json"


def extract_price(text):
    if not text:
        return None

    patterns = [
        r"(?:到手价|券后价|优惠价|售价|价格|低至|起价|起)\s*[¥￥]?\s*(\d+(?:\.\d+)?)",
        r"[¥￥]\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*元",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            try:
                price = float(match.group(1))
                if 1 <= price <= 100000:
                    return price
            except Exception:
                pass

    return None


def clean_text(text):
    if not text:
        return ""

    return re.sub(r"\s+", " ", text).strip()


def get_nearby_text(element):
    """
    商品名称和价格经常不在同一个 DOM 节点。
    向父级逐层寻找商品卡片附近文字。
    """
    try:
        texts = []

        own_text = element.inner_text(timeout=1000)
        if own_text:
            texts.append(own_text)

        parent = element.locator("..")

        for _ in range(3):
            try:
                text = parent.inner_text(timeout=1000)
                if text:
                    texts.append(text)
            except Exception:
                pass

            try:
                parent = parent.locator("..")
            except Exception:
                break

        return clean_text(" ".join(texts))

    except Exception:
        return ""


def is_product_url(href):
    if not href:
        return False

    href = href.lower()

    keywords = [
        "/goods/",
        "/product/",
        "/item/",
        "/detail/",
        "/goodsdetail/",
    ]

    return any(x in href for x in keywords)


def looks_like_product_text(text):
    if not text:
        return False

    text = clean_text(text)

    if len(text) < 4:
        return False

    bad_words = [
        "全部",
        "商品",
        "优惠",
        "晒物",
        "首页",
        "分类",
        "登录",
        "注册",
        "搜索",
        "我的",
        "购物车",
        "关注",
    ]

    if text in bad_words:
        return False

    return True


def wait_for_product_list(page, keyword):
    """
    识货是动态页面。

    page.goto() 成功并不代表商品列表已经加载。
    这里最多等待 15 秒，每秒检查一次。

    出现明显商品迹象后立即继续。
    """

    start = time.time()

    last_body_length = 0
    last_link_count = 0
    last_candidate_count = 0

    while time.time() - start < PAGE_WAIT_MAX:

        try:
            body = page.locator("body").inner_text(timeout=1500)
            body = clean_text(body)
            body_length = len(body)
        except Exception:
            body = ""
            body_length = 0

        try:
            links = page.locator("a")
            link_count = links.count()
        except Exception:
            link_count = 0

        candidate_count = 0

        try:
            for i in range(min(link_count, 80)):
                try:
                    a = links.nth(i)

                    href = a.get_attribute("href", timeout=500)

                    text = clean_text(
                        a.inner_text(timeout=500)
                    )

                    if is_product_url(href) or looks_like_product_text(text):
                        candidate_count += 1

                except Exception:
                    continue

        except Exception:
            pass

        print(
            f"等待商品列表："
            f"{int(time.time() - start)}秒 | "
            f"正文={body_length} | "
            f"链接={link_count} | "
            f"候选={candidate_count}"
        )

        last_body_length = body_length
        last_link_count = link_count
        last_candidate_count = candidate_count

        # 出现明显商品内容
        if (
            body_length > 80
            and candidate_count >= 5
        ):
            print("✅ 检测到商品列表，开始解析")
            return True

        # 链接明显增加，也说明动态内容出来了
        if link_count >= 30:
            print("✅ 检测到动态商品链接，开始解析")
            return True

        # 页面正文已经明显变长
        if body_length >= 200:
            print("✅ 页面内容已加载，开始解析")
            return True

        # 等待期间轻微滚动一次，触发懒加载
        if int(time.time() - start) in (3, 7):
            try:
                page.mouse.wheel(0, 1000)
            except Exception:
                pass

        time.sleep(1)

    print(
        f"⚠️ 等待 {PAGE_WAIT_MAX} 秒后商品列表仍未充分加载："
        f"正文={last_body_length}，"
        f"链接={last_link_count}，"
        f"候选={last_candidate_count}"
    )

    return False


def collect_from_page(page, keyword):
    url = SEARCH_URL.format(keyword=quote(keyword))

    print("")
    print("=" * 70)
    print(f"开始搜索关键词：{keyword}")
    print(f"URL：{url}")

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=PAGE_LOAD_TIMEOUT,
        )
    except PlaywrightTimeoutError:
        print(f"⚠️ 页面打开超时：{keyword}")
        return []

    except Exception as e:
        print(f"⚠️ 页面打开失败：{keyword} | {e}")
        return []

    print(f"页面标题：{page.title()}")

    # 给 SPA 前端一点初始渲染时间
    try:
        page.wait_for_timeout(2000)
    except Exception:
        pass

    # 等待真正的商品列表
    loaded = wait_for_product_list(page, keyword)

    if not loaded:
        try:
            body = clean_text(
                page.locator("body").inner_text(timeout=2000)
            )

            print(
                "⚠️ 识货商品列表未加载，本关键词跳过"
            )

            print(
                f"页面正文前500字：{body[:500]}"
            )

        except Exception:
            pass

        return []

    # 商品出现以后再做滚动
    try:
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1000)

        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1000)

    except Exception:
        pass

    try:
        body = clean_text(
            page.locator("body").inner_text(timeout=3000)
        )

        print(f"页面文字长度：{len(body)}")
        print(f"页面文字前500字：{body[:500]}")

    except Exception:
        body = ""

    try:
        links = page.locator("a")
        link_count = links.count()

        print(f"页面链接数量：{link_count}")

    except Exception:
        print("⚠️ 无法读取页面链接")
        return []

    products = []
    seen = set()

    for i in range(min(link_count, 200)):

        if len(products) >= MAX_PRODUCTS:
            break

        try:
            anchor = links.nth(i)

            href = anchor.get_attribute(
                "href",
                timeout=800,
            )

            anchor_text = clean_text(
                anchor.inner_text(timeout=800)
            )

            # 只处理看起来像商品的链接
            if not (
                is_product_url(href)
                or looks_like_product_text(anchor_text)
            ):
                continue

            nearby_text = get_nearby_text(anchor)

            if not nearby_text:
                nearby_text = anchor_text

            price = extract_price(nearby_text)

            if price is None:
                continue

            # 商品名称优先使用链接文字
            name = anchor_text

            if not looks_like_product_text(name):
                # 从附近文本里取一个合理名称
                name = nearby_text[:100]

            name = clean_text(name)

            if not name:
                name = "未知商品"

            # 去掉明显纯价格文本
            if re.fullmatch(
                r"[¥￥]?\s*\d+(?:\.\d+)?\s*(?:元)?",
                name,
            ):
                name = "未知商品"

            key = (
                name.lower(),
                round(price, 2),
            )

            if key in seen:
                continue

            seen.add(key)

            product = {
                "name": name,
                "buy_price": round(price, 2),
                "source": "识货公开搜索页",
                "keyword": keyword,
                "url": href or "",
                "raw_text": nearby_text[:500],
            }

            products.append(product)

            print(
                f"发现商品：{name} | "
                f"价格：¥{price:.2f}"
            )

        except Exception:
            continue

    print(
        f"关键词「{keyword}」有效商品："
        f"{len(products)}"
    )

    return products


def merge_products(all_products):
    """
    去重。
    同名商品保留更低价格。
    """

    result = {}

    for product in all_products:

        name = clean_text(
            product.get("name", "")
        )

        if not name:
            continue

        price = product.get("buy_price")

        try:
            price = float(price)
        except Exception:
            continue

        key = name.lower()

        if key not in result:
            result[key] = product
            continue

        old_price = result[key].get(
            "buy_price"
        )

        try:
            old_price = float(old_price)
        except Exception:
            old_price = 999999

        if price < old_price:
            result[key] = product

    return list(result.values())


def save_products(products):
    """
    写入 market_data_input.json。

    兼容后面的 market_data_collector.py。
    """

    data = {
        "products": products,
        "buy_prices": [
            p.get("buy_price")
            for p in products
            if p.get("buy_price") is not None
        ],
        "data_source": "识货公开搜索页",
        "data_time": time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("")
    print("=" * 70)
    print(
        f"最终写入商品：{len(products)} 个"
    )
    print(
        f"保存文件：{OUTPUT_FILE}"
    )


def main():

    all_products = []

    keywords = KEYWORDS[:MAX_KEYWORDS]

    print("=" * 70)
    print("识货公开商品搜索采集器")
    print(
        f"关键词数量：{len(keywords)}"
    )
    print(
        f"最多商品：{MAX_PRODUCTS}"
    )
    print(
        f"单关键词最长等待：{PAGE_WAIT_MAX} 秒"
    )
    print("=" * 70)

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

            for index, keyword in enumerate(
                keywords,
                start=1,
            ):

                if len(all_products) >= MAX_PRODUCTS:
                    print(
                        "已经达到最大商品数量，停止搜索。"
                    )
                    break

                print("")
                print(
                    f"########## "
                    f"{index}/{len(keywords)} "
                    f"{keyword} ##########"
                )

                context = None
                page = None

                try:

                    context = browser.new_context(
                        viewport={
                            "width": 390,
                            "height": 844,
                        },
                        locale="zh-CN",
                        user_agent=(
                            "Mozilla/5.0 "
                            "(iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                            "AppleWebKit/605.1.15 "
                            "(KHTML, like Gecko) "
                            "Version/17.0 Mobile/15E148 "
                            "Safari/604.1"
                        ),
                    )

                    page = context.new_page()

                    # 单关键词总超时控制
                    result = []

                    start_time = time.time()

                    try:
                        result = collect_from_page(
                            page,
                            keyword,
                        )

                    except Exception as e:
                        print(
                            f"⚠️ 关键词处理异常："
                            f"{keyword} | {e}"
                        )

                    elapsed = (
                        time.time() - start_time
                    )

                    print(
                        f"关键词「{keyword}」"
                        f"耗时 {elapsed:.1f} 秒"
                    )

                    all_products.extend(result)

                    if result:
                        print(
                            f"本次新增："
                            f"{len(result)} 个"
                        )
                    else:
                        print(
                            "本次没有提取到有效商品"
                        )

                except Exception as e:
                    print(
                        f"⚠️ 创建浏览器页面失败："
                        f"{keyword} | {e}"
                    )

                finally:
                    try:
                        if context:
                            context.close()
                    except Exception:
                        pass

                # 每个关键词之间稍微停一下
                time.sleep(1)

        finally:
            try:
                if browser:
                    browser.close()
            except Exception:
                pass

    # 最终去重
    all_products = merge_products(
        all_products
    )

    # 最大商品数量限制
    all_products = all_products[:MAX_PRODUCTS]

    save_products(all_products)

    print("")
    print("=" * 70)
    print("采集完成")
    print(
        f"最终商品数量：{len(all_products)}"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
