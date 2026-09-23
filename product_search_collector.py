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


# ============================================================
# 目标品类
# ============================================================

TARGET_KEYWORDS = [
    "鞋",
    "运动鞋",
    "球鞋",
    "跑鞋",
    "篮球鞋",
    "足球鞋",
    "训练鞋",
    "休闲鞋",

    "服饰",
    "卫衣",
    "外套",
    "夹克",
    "羽绒服",
    "裤",
    "T恤",
    "衬衫",
    "球衣",

    "箱包",
    "包",
    "双肩包",

    "潮玩",
    "盲盒",
    "手办",

    "运动装备",
    "帽",
    "眼镜",
    "饰品",

    "adidas",
    "nike",
    "new balance",
    "asics",
    "puma",
    "jordan",
    "air force",
    "dunk",
    "yeezy",

    "李宁",
    "安踏",
    "特步",
    "始祖鸟",
    "arc'teryx",
    "lululemon",
    "coach",
    "gucci",
    "prada",
    "lv",
    "burberry",
    "supreme",
    "stussy",
]


# ============================================================
# 明确排除
# ============================================================

EXCLUDE_KEYWORDS = [
    "猫粮",
    "狗粮",
    "宠物食品",
    "宠物粮",
    "食品",
    "零食",
    "饮料",

    "洗衣液",
    "纸巾",
    "日用品",
    "清洁用品",
    "厨房用品",
    "家居",

    "冰箱",
    "洗衣机",
    "空调",
    "电视",
    "显示器",
    "家电",

    "吉他",
    "钢琴",
    "乐器",

    "充值",
    "点券",
    "代充",
    "游戏币",
    "虚拟商品",
    "话费",
    "会员",
    "卡密",
]


# ============================================================
# 基础工具
# ============================================================

def clean_text(text):
    if text is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(text)
    ).strip()


def to_number(value):

    try:
        return float(value)

    except Exception:
        return None


def parse_amount(value):

    if value is None:
        return None

    text = clean_text(value)

    text = text.replace(
        ",",
        ""
    )

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*([万wW])?",
        text
    )

    if not match:
        return None

    number = float(
        match.group(1)
    )

    unit = match.group(2)

    if unit:
        number *= 10000

    return number


# ============================================================
# 价格
# ============================================================

def extract_first_price(text):

    if not text:
        return None

    patterns = [

        r"[¥￥]\s*(\d+(?:\.\d+)?)\s*([万wW])?",

        r"到手价\s*[¥￥]?\s*(\d+(?:\.\d+)?)\s*([万wW])?",

        r"售价\s*[¥￥]?\s*(\d+(?:\.\d+)?)\s*([万wW])?",

        r"最低价\s*[¥￥]?\s*(\d+(?:\.\d+)?)\s*([万wW])?",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if not match:
            continue

        value = float(
            match.group(1)
        )

        if match.group(2):
            value *= 10000

        if 1 <= value <= 100000:

            return value

    return None


def remove_price_text(text):

    if not text:
        return ""

    text = re.sub(
        r"[¥￥]\s*\d+(?:\.\d+)?\s*[万wW]?",
        " ",
        text,
        flags=re.I
    )

    text = re.sub(
        r"(到手价|售价|最低价)\s*[¥￥]?\s*\d+(?:\.\d+)?\s*[万wW]?",
        " ",
        text,
        flags=re.I
    )

    return clean_text(text)


# ============================================================
# 销量
# ============================================================

def extract_period_sales(text, period):

    if not text:
        return None

    patterns = [

        rf"(?:近\s*{period}\s*日|近{period}日|{period}日|{period}天)"
        rf"\s*(?:销量|销售量)"
        rf"\s*[:：]?\s*"
        rf"(\d+(?:\.\d+)?\s*[万wW]?)",

        rf"(?:销量|销售量)"
        rf"\s*\({period}[日天]\)"
        rf"\s*[:：]?\s*"
        rf"(\d+(?:\.\d+)?\s*[万wW]?)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            return parse_amount(
                match.group(1)
            )

    return None


def extract_sales(text):

    if not text:
        return None

    sales_7d = extract_period_sales(
        text,
        7
    )

    if sales_7d is not None:
        return sales_7d

    sales_30d = extract_period_sales(
        text,
        30
    )

    if sales_30d is not None:
        return sales_30d

    patterns = [

        r"总销\s*(\d+(?:\.\d+)?\s*[万wW]?)",

        r"月销\s*(\d+(?:\.\d+)?\s*[万wW]?)",

        r"已售\s*(\d+(?:\.\d+)?\s*[万wW]?)",

        r"(\d+(?:\.\d+)?\s*[万wW]?)人付款",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            return parse_amount(
                match.group(1)
            )

    return None


# ============================================================
# 价格历史
# ============================================================

def extract_price_history(text):

    if not text:
        return []

    values = []

    patterns = [

        r"(\d{1,2}月\d{1,2}日)"
        r"[^¥￥\d]{0,30}"
        r"[¥￥]?\s*(\d+(?:\.\d+)?)",

        r"(\d{1,2}[./-]\d{1,2})"
        r"[^¥￥\d]{0,30}"
        r"[¥￥]?\s*(\d+(?:\.\d+)?)",
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            text
        ):

            price = to_number(
                match.group(2)
            )

            if price is None:
                continue

            if not 1 <= price <= 100000:
                continue

            values.append({
                "date": match.group(1),
                "price": price,
            })

    result = []

    seen = set()

    for item in values:

        key = (
            item["date"],
            item["price"]
        )

        if key in seen:
            continue

        seen.add(key)

        result.append(
            item
        )

    return result[-30:]


def calculate_history_change(history):

    if len(history) < 2:
        return None

    first = history[0]["price"]

    last = history[-1]["price"]

    if first <= 0:
        return None

    return round(
        (last - first)
        / first
        * 100,
        2
    )


def extract_price_change(text, days):

    history = extract_price_history(
        text
    )

    history_change = calculate_history_change(
        history
    )

    if history_change is not None:
        return history_change

    patterns = [

        rf"{days}\s*天[^。；\n]{{0,40}}?"
        r"(上涨|下跌|下降|上升)"
        r"\s*(\d+(?:\.\d+)?)\s*%",

        r"(上涨|下跌|下降|上升)"
        r"\s*(\d+(?:\.\d+)?)\s*%",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if not match:
            continue

        direction = match.group(1)

        percentage = float(
            match.group(2)
        )

        if direction in (
            "下跌",
            "下降",
        ):

            return -percentage

        return percentage

    return None


def extract_price_trend(
    text,
    history
):

    if not text:
        return None

    if re.search(
        r"价格.{0,15}(?:持续|明显)?下跌|"
        r"价格.{0,15}下降|"
        r"跌幅",
        text
    ):

        return "falling"

    if re.search(
        r"价格.{0,15}(?:持续|明显)?上涨|"
        r"价格.{0,15}上升|"
        r"涨幅",
        text
    ):

        return "rising"

    if re.search(
        r"价格.{0,15}(?:稳定|持平)|横盘",
        text
    ):

        return "stable"

    if len(history) >= 2:

        change = calculate_history_change(
            history
        )

        if change is None:
            return None

        if change >= 5:
            return "rising"

        if change <= -5:
            return "falling"

        return "stable"

    return None


# ============================================================
# 商品信息
# ============================================================

def extract_product_code(text):

    if not text:
        return None

    patterns = [

        r"货号[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_/.]+)",

        r"款号[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_/.]+)",

        r"SKU[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_/.]+)",

        r"型号[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_/.]+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            return match.group(1).strip()

    return None


def extract_dewu_price(text):

    if not text:
        return None

    patterns = [

        r"得物渠道售价\s*[¥￥]?\s*"
        r"(\d+(?:\.\d+)?)\s*([万wW])?",

        r"得物.*?售价\s*[¥￥]?\s*"
        r"(\d+(?:\.\d+)?)\s*([万wW])?",

        r"得物.*?"
        r"(\d+(?:\.\d+)?)\s*([万wW])?\s*元",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if not match:
            continue

        value = float(
            match.group(1)
        )

        if match.group(2):
            value *= 10000

        if value > 0:
            return value

    return None


def extract_channel_lowest_price(text):

    if not text:
        return None

    patterns = [

        r"最低价为\s*[¥￥]?\s*"
        r"(\d+(?:\.\d+)?)\s*([万wW])?",

        r"全网最低价\s*[¥￥]?\s*"
        r"(\d+(?:\.\d+)?)\s*([万wW])?",

        r"全网价格区间.*?"
        r"(\d+(?:\.\d+)?)\s*([万wW])?\s*元",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if not match:
            continue

        value = float(
            match.group(1)
        )

        if match.group(2):
            value *= 10000

        if value > 0:
            return value

    return None


# ============================================================
# 正品 / 全新 / 得物查验证据
# ============================================================

def extract_evidence(text):

    if not text:
        return {
            "authenticity_evidence": None,
            "new_condition_evidence": None,
            "dewu_check_evidence": None,
        }

    authenticity = None

    match = re.search(
        r".{0,50}(?:正品|放心店|鉴定|真伪).{0,150}",
        text
    )

    if match:
        authenticity = clean_text(
            match.group(0)
        )

    new_condition = None

    match = re.search(
        r".{0,50}(?:全新|新品|未使用).{0,150}",
        text
    )

    if match:
        new_condition = clean_text(
            match.group(0)
        )

    dewu_check = None

    match = re.search(
        r".{0,50}(?:得物|查验|验货).{0,150}",
        text
    )

    if match:
        dewu_check = clean_text(
            match.group(0)
        )

    return {
        "authenticity_evidence": authenticity,
        "new_condition_evidence": new_condition,
        "dewu_check_evidence": dewu_check,
    }


# ============================================================
# 品类
# ============================================================

def classify_category(
    name,
    text
):

    value = clean_text(
        (name or "")
        + " "
        + (text or "")
    ).lower()

    for keyword in EXCLUDE_KEYWORDS:

        if keyword.lower() in value:

            return "excluded"

    for keyword in TARGET_KEYWORDS:

        if keyword.lower() in value:

            return "target"

    return "unknown"


# ============================================================
# 商品名称
# ============================================================

def looks_like_real_product_name(
    name
):

    if not name:
        return False

    name = clean_text(
        name
    )

    if len(name) < 4:
        return False

    if re.fullmatch(
        r"[\d\.\s¥￥元到手价售价最低价]+",
        name,
        re.I
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


def extract_name_from_link(
    link
):

    candidates = []

    for attr in (
        "aria-label",
        "title",
    ):

        try:

            value = link.get_attribute(
                attr,
                timeout=1000
            )

            if value:
                candidates.append(
                    value
                )

        except Exception:
            pass

    try:

        value = link.inner_text(
            timeout=1000
        )

        if value:
            candidates.append(
                value
            )

    except Exception:
        pass

    for level in range(
        1,
        5
    ):

        try:

            parent = link.locator(
                "/.." * level
            )

            value = parent.inner_text(
                timeout=1000
            )

            if value:
                candidates.append(
                    value
                )

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

        if len(candidate) > 180:

            parts = re.split(
                r"\s{2,}|\s\|\s",
                candidate
            )

            for part in parts:

                part = clean_text(
                    part
                )

                if (
                    looks_like_real_product_name(part)
                    and len(part) < len(candidate)
                ):

                    candidate = part

        if (
            not best
            or len(candidate) > len(best)
        ):

            best = candidate

    return best


def is_detail_url(
    href
):

    if not href:
        return False

    return (
        "pcGoodsDetail" in href
        or "/page/pcGoodsDetail" in href
    )


# ============================================================
# 首页采集
# ============================================================

def collect_home_products(
    page
):

    print("=" * 70)

    print(
        "开始读取识货公开商品首页"
    )

    print(
        HOME_URL
    )

    print("=" * 70)

    try:

        page.goto(
            HOME_URL,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT
        )

    except PlaywrightTimeoutError:

        print(
            "⚠️ 识货首页打开超时"
        )

        return []

    except Exception as e:

        print(
            f"⚠️ 识货首页打开失败：{e}"
        )

        return []

    page.wait_for_timeout(
        3000
    )

    for _ in range(5):

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

        links = page.locator(
            "a"
        )

        count = links.count()

        print(
            f"首页链接数量：{count}"
        )

    except Exception:

        return []

    for i in range(
        min(
            count,
            600
        )
    ):

        if len(products) >= MAX_PRODUCTS:
            break

        try:

            link = links.nth(i)

            href = link.get_attribute(
                "href",
                timeout=1000
            )

            if not href:
                continue

            href = urljoin(
                "https://www.shihuo.cn",
                href
            )

            if not is_detail_url(
                href
            ):
                continue

            if href in seen_urls:
                continue

            raw_text = clean_text(
                link.inner_text(
                    timeout=1000
                )
            )

            price = extract_first_price(
                raw_text
            )

            name = extract_name_from_link(
                link
            )

            if not name:
                continue

            if price is None:

                for level in range(
                    1,
                    5
                ):

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

            seen_urls.add(
                href
            )

            products.append({

                "name": name,

                "buy_price": price,

                "shihuo_url": href,

                "source": "识货公开PC首页",

                "observed_at":
                    time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ",
                        time.gmtime()
                    ),
            })

        except Exception:

            continue

    print(
        f"首页发现有效商品：{len(products)}"
    )

    return products


# ============================================================
# 详情页
# ============================================================

def collect_detail(
    page,
    product
):

    url = product.get(
        "shihuo_url"
    )

    if not url:
        return product

    print()

    print("-" * 70)

    print(
        f"读取商品详情：{product.get('name')}"
    )

    print(
        url
    )

    try:

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=DETAIL_TIMEOUT
        )

    except Exception as e:

        print(
            f"⚠️ 商品详情打开失败：{e}"
        )

        product[
            "detail_status"
        ] = "failed"

        return product

    page.wait_for_timeout(
        1500
    )

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

    try:

        title = clean_text(
            page.title()
        )

        title = remove_price_text(
            title
        )

        if (
            looks_like_real_product_name(title)
            and len(title) <= 150
        ):

            product[
                "name"
            ] = title

    except Exception:
        pass

    # --------------------------------------------------------
    # 基础行情
    # --------------------------------------------------------

    product[
        "product_code"
    ] = extract_product_code(
        body
    )

    product[
        "dewu_display_price"
    ] = extract_dewu_price(
        body
    )

    product[
        "lowest_price"
    ] = extract_channel_lowest_price(
        body
    )

    product[
        "sales"
    ] = extract_sales(
        body
    )

    # --------------------------------------------------------
    # 7 / 30 日销量
    # --------------------------------------------------------

    product[
        "sales_7d"
    ] = extract_period_sales(
        body,
        7
    )

    product[
        "sales_30d"
    ] = extract_period_sales(
        body,
        30
    )

    if product[
        "sales_7d"
    ] is not None:

        product[
            "sales_velocity_7d"
        ] = round(
            product["sales_7d"] / 7,
            2
        )

    else:

        product[
            "sales_velocity_7d"
        ] = None

    # --------------------------------------------------------
    # 价格历史
    # --------------------------------------------------------

    history = extract_price_history(
        body
    )

    product[
        "price_history"
    ] = history

    product[
        "price_current"
    ] = product.get(
        "dewu_display_price"
    )

    product[
        "price_1d"
    ] = None

    product[
        "price_7d"
    ] = None

    product[
        "price_30d"
    ] = None

    product[
        "price_change_1d"
    ] = extract_price_change(
        body,
        1
    )

    product[
        "price_change_7d"
    ] = extract_price_change(
        body,
        7
    )

    product[
        "price_change_30d"
    ] = extract_price_change(
        body,
        30
    )

    product[
        "price_trend"
    ] = extract_price_trend(
        body,
        history
    )

    # --------------------------------------------------------
    # 品类
    # --------------------------------------------------------

    product[
        "category"
    ] = classify_category(
        product.get("name"),
        body
    )

    # --------------------------------------------------------
    # 风险证据
    # --------------------------------------------------------

    product.update(
        extract_evidence(
            body
        )
    )

    product[
        "source_url"
    ] = url

    # --------------------------------------------------------
    # 详情页价格
    # --------------------------------------------------------

    detail_price = extract_first_price(
        body
    )

    if detail_price is not None:

        product[
            "buy_price"
        ] = detail_price

    # --------------------------------------------------------
    # 原始公开文本
    # --------------------------------------------------------

    product[
        "detail_text"
    ] = body[:5000]

    product[
        "discovery_observed_at"
    ] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime()
    )

    print(
        f"商品名称：{product.get('name')}"
    )

    print(
        f"买入侧价格：¥{product.get('buy_price')}"
    )

    print(
        f"得物公开价格：{product.get('dewu_display_price')}"
    )

    print(
        f"近7日销量：{product.get('sales_7d')}"
    )

    print(
        f"近30日销量：{product.get('sales_30d')}"
    )

    print(
        f"7日价格变化：{product.get('price_change_7d')}%"
    )

    print(
        f"价格趋势：{product.get('price_trend')}"
    )

    print(
        f"类别：{product.get('category')}"
    )

    return product


# ============================================================
# 去重
# ============================================================

def deduplicate(
    products
):

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

        if code:

            key = (
                "code:"
                + code.lower()
            )

        elif url:

            key = (
                "url:"
                + url.lower()
            )

        else:

            key = (
                "name:"
                + name.lower()
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

    return list(
        result.values()
    )


# ============================================================
# 保存
# ============================================================

def save(
    products
):

    data = {

        "updated_at":
            time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime()
            ),

        "source":
            "识货公开PC首页及商品详情页；得物字段仅使用公开可见证据",

        "stale":
            len(products) == 0,

        "products":
            products,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("=" * 70)

    print(
        f"最终有效发现商品：{len(products)}"
    )

    print(
        f"写入：{OUTPUT_FILE}"
    )

    print("=" * 70)


# ============================================================
# 主程序
# ============================================================

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
                start=1
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
                        product
                    )
                )

            products = deduplicate(
                detail_products
            )

            context.close()

        finally:

            try:

                if browser:
                    browser.close()

            except Exception:
                pass

    products = products[
        :MAX_PRODUCTS
    ]

    save(
        products
    )


if __name__ == "__main__":

    main()
