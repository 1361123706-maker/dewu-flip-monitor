import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote, urljoin

from promotion_engine import (
    calculate_best_price,
)

from playwright.async_api import async_playwright


# ============================================================
# 基础配置
# ============================================================

HOME_URL = "https://www.shihuo.cn/page/pcHome"

OUTPUT_FILE = "discovery_data.json"

MAX_DETAIL_PAGES = 30

HOME_TIMEOUT = 20000

DETAIL_TIMEOUT = 15000

WAIT_AFTER_HOME = 2500

WAIT_AFTER_DETAIL = 1500


# ============================================================
# 中国大陆主要电商平台
# ============================================================

PLATFORM_RULES = [
    {
        "name": "天猫",
        "domains": [
            "tmall.com",
        ],
        "official_markers": [
            "官方旗舰店",
            "旗舰店",
            "官方店",
        ],
    },
    {
        "name": "淘宝",
        "domains": [
            "taobao.com",
        ],
        "official_markers": [
            "官方旗舰店",
            "旗舰店",
            "官方店",
        ],
    },
    {
        "name": "京东",
        "domains": [
            "jd.com",
        ],
        "official_markers": [
            "京东自营",
            "自营旗舰店",
            "官方旗舰店",
            "旗舰店",
        ],
    },
    {
        "name": "拼多多",
        "domains": [
            "yangkeduo.com",
            "pinduoduo.com",
        ],
        "official_markers": [
            "官方旗舰店",
            "旗舰店",
            "品牌店",
        ],
    },
    {
        "name": "唯品会",
        "domains": [
            "vip.com",
        ],
        "official_markers": [
            "官方",
            "旗舰店",
            "品牌",
        ],
    },
    {
        "name": "抖音商城",
        "domains": [
            "douyin.com",
        ],
        "official_markers": [
            "官方旗舰店",
            "旗舰店",
            "官方店",
        ],
    },
]


# ============================================================
# 工具
# ============================================================

def clean_line(value):

    if value is None:
        return None

    value = str(value)

    value = value.replace(
        "\u200b",
        "",
    )

    value = value.replace(
        "\xa0",
        " ",
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def to_float(value):

    if value is None:
        return None

    try:

        text = str(value)

        text = text.replace(
            ",",
            "",
        )

        text = text.replace(
            "¥",
            "",
        )

        text = text.replace(
            "￥",
            "",
        )

        text = text.replace(
            "元",
            "",
        )

        text = text.strip()

        number = float(text)

        if number <= 0:
            return None

        return number

    except Exception:
        return None


def money(value):

    number = to_float(value)

    if number is None:
        return None

    return round(
        number,
        2,
    )


def unique_list(values):

    result = []

    for value in values:

        if not value:
            continue

        value = str(value).strip()

        if not value:
            continue

        if value not in result:
            result.append(value)

    return result


def absolute_url(
    base_url,
    url,
):

    if not url:
        return None

    return urljoin(
        base_url,
        url,
    )


# ============================================================
# 商品身份
# ============================================================

def extract_product_code(text):

    if not text:
        return None

    patterns = [

        r"(?:货号|商品货号|产品货号)"
        r"\s*(?:为|是|[:：])?\s*"
        r"([A-Za-z0-9][A-Za-z0-9._\-/]{3,40})",

        r"(?:款号|款式号|款式编号)"
        r"\s*(?:为|是|[:：])?\s*"
        r"([A-Za-z0-9][A-Za-z0-9._\-/]{3,40})",

        r"([A-Z]{1,8}\d{2,}[A-Z0-9._\-/]*)"
        r"\s*货号",

    ]

    blacklist = {
        "adidas",
        "nike",
        "newbalance",
        "asics",
        "puma",
        "jordan",
        "apple",
        "coach",
        "originals",
        "superstar",
    }

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I,
        )

        if not match:
            continue

        value = clean_line(
            match.group(1)
        )

        if not value:
            continue

        if value.lower() in blacklist:
            continue

        return value

    return None


def extract_color(text):

    if not text:
        return None

    patterns = [

        r"(?:当前配色|当前颜色|已选配色|已选颜色)"
        r"\s*[:：]?\s*"
        r"([^，,。；;\n]{1,80})",

        r"(?:商品配色|商品颜色)"
        r"\s*[:：]\s*"
        r"([^，,。；;\n]{1,80})",

        r"([^\s,，]{1,30}"
        r"(?:/[^\s,，]{1,30})+)"
        r"\s*,\s*"
        r"[0-9A-Za-z./\-½⅓⅔]+",

    ]

    blacklist = {
        "可选配色",
        "可选尺码",
        "颜色",
        "尺码",
        "货号",
        "品牌",
        "商品名称",
        "价格信息",
    }

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I,
        )

        if not match:
            continue

        value = clean_line(
            match.group(1)
        )

        if not value:
            continue

        value = value.strip(
            "：:，,。；; "
        )

        if value in blacklist:
            continue

        if len(value) > 80:
            continue

        return value

    return None


def extract_current_size(text):

    if not text:
        return None

    patterns = [

        r"[^\s,，]{1,30}"
        r"(?:/[^\s,，]{1,30})+"
        r"\s*,\s*"
        r"([0-9A-Za-z./\-½⅓⅔]+)",

        r"(?:当前尺码|已选尺码|选中尺码|当前鞋码)"
        r"\s*[:：]?\s*"
        r"([A-Za-z0-9./\-½⅓⅔]{1,12})",

        r"(?:当前规格|已选规格|选中规格)"
        r"\s*[:：]?\s*"
        r"[^，,；;]{0,30}?"
        r"(?:尺码|鞋码)"
        r"\s*[:：]?\s*"
        r"([A-Za-z0-9./\-½⅓⅔]{1,12})",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I,
        )

        if not match:
            continue

        value = clean_line(
            match.group(1)
        )

        if not value:
            continue

        if value in {
            "请选择",
            "未选择",
            "信息",
        }:
            continue

        return value

    return None


# ============================================================
# 尺码价格
# ============================================================

def extract_size_price_map(text):

    result = {}

    if not text:
        return result

    patterns = [

        r"([0-9A-Za-z./\-½⅓⅔]+)"
        r"\s*"
        r"[¥￥]"
        r"\s*"
        r"([0-9]+(?:\.[0-9]+)?)",

        r"([0-9A-Za-z./\-½⅓⅔]+)"
        r"\s+"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*元",

    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            re.I,
        )

        for size, price in matches:

            price_number = to_float(
                price
            )

            if price_number is None:
                continue

            size = clean_line(
                size
            )

            if not size:
                continue

            if len(size) > 12:
                continue

            result[size] = money(
                price_number
            )

    return result


# ============================================================
# 价格
# ============================================================

def extract_dewu_channel_price(text):

    if not text:
        return None

    patterns = [

        r"得物渠道售价"
        r"\s*[:：]?\s*"
        r"[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",

        r"得物售价"
        r"\s*[:：]?\s*"
        r"[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",

        r"得物"
        r"[^0-9]{0,20}"
        r"[¥￥]\s*"
        r"([0-9]+(?:\.[0-9]+)?)",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I,
        )

        if match:

            value = to_float(
                match.group(1)
            )

            if value is not None:
                return money(value)

    return None


def extract_current_price(text):

    if not text:
        return None

    patterns = [

        r"当前同款同规格"
        r"[^¥￥0-9]{0,40}"
        r"[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",

        r"当前价格"
        r"\s*[:：]?\s*"
        r"[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",

        r"当前价"
        r"\s*[:：]?\s*"
        r"[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I,
        )

        if match:

            value = to_float(
                match.group(1)
            )

            if value is not None:
                return money(value)

    return None


def extract_7d_low(text):

    if not text:
        return None

    patterns = [

        r"(?:近7天|过去7天|7日|7天)"
        r"[^。；;\n]{0,80}?"
        r"(?:最低价|最低)"
        r"[^¥￥0-9]{0,20}"
        r"[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",

        r"7天最低价"
        r"\s*[:：r"：]?\s*[¥￥]?\s*"
r"([0-9]+(?:\.[0-9]+)?)",
]

for pattern in patterns:
    match = re.search(
        pattern,
        text,
        re.I | re.S,
    )

    if match:
        value = to_float(
            match.group(1)
        )

        if value is not None:
            return money(value)

return None


def extract_7d_high(text):
    if not text:
        return None

    patterns = [
        r"(?:近7天|过去7天|7日|7天)"
        r"[^。；;\n]{0,80}?"
        r"(?:最高价|最高)"
        r"[^¥￥0-9]{0,20}"
        r"[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",

        r"7天最高价"
        r"\s*[:：]?\s*[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.I | re.S,
        )

        if match:
            value = to_float(
                match.group(1)
            )

            if value is not None:
                return money(value)

    return None


def extract_trend_current_price(text):
    if not text:
        return None

    patterns = [
        r"当前同款同规格到手价为"
        r"\s*[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",

        r"当前同款同规格到手价"
        r"\s*[:：]?\s*[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",

        r"当前到手价"
        r"\s*[:：]?\s*[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.I | re.S,
        )

        if match:
            value = to_float(
                match.group(1)
            )

            if value is not None:
                return money(value)

    return None


# ============================================================
# 销量 / 周转
# ============================================================

def extract_sales(text):
    if not text:
        return {
            "sales_7d": None,
            "sales_30d": None,
            "sales_total": None,
            "sales_velocity_7d": None,
            "turnover_evidence": None,
            "turnover_confidence": "unknown",
        }

    sales_7d = None
    sales_30d = None
    sales_total = None

    patterns_7d = [
        r"(?:近7天|近7日|7天销量|7日销量)"
        r"\s*[:：]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?",

        r"7天"
        r"[^。；;\n]{0,40}?"
        r"销量"
        r"\s*[:：]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?",
    ]

    patterns_30d = [
        r"(?:月销|月销量|近30天销量|近30日销量)"
        r"\s*[:：]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?",
    ]

    patterns_total = [
        r"(?:全网销量|总销|总销量|累计销量)"
        r"\s*[:：]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?",
    ]

    for pattern in patterns_7d:
        match = re.search(
            pattern,
            text,
            re.I,
        )

        if match:
            sales_7d = to_float(
                match.group(1)
            )

            if match.group(2) == "万":
                sales_7d *= 10000

            break

    for pattern in patterns_30d:
        match = re.search(
            pattern,
            text,
            re.I,
        )

        if match:
            sales_30d = to_float(
                match.group(1)
            )

            if match.group(2) == "万":
                sales_30d *= 10000

            break

    for pattern in patterns_total:
        match = re.search(
            pattern,
            text,
            re.I,
        )

        if match:
            sales_total = to_float(
                match.group(1)
            )

            if match.group(2) == "万":
                sales_total *= 10000

            break

    if sales_7d:
        velocity = round(
            sales_7d / 7,
            2,
        )

        confidence = "high"

        evidence = (
            f"近7日销量 {sales_7d:g}，"
            f"日均约 {velocity:.2f}"
        )

    elif sales_30d:
        velocity = round(
            sales_30d / 30,
            2,
        )

        confidence = "medium"

        evidence = (
            f"月销 {sales_30d:g}，"
            f"日均约 {velocity:.2f}"
        )

    elif sales_total:
        velocity = None

        confidence = "low"

        evidence = (
            f"累计/全网销量 {sales_total:g}，"
            "不能直接作为7日周转速度"
        )

    else:
        velocity = None
        confidence = "unknown"
        evidence = None

    return {
        "sales_7d": sales_7d,
        "sales_30d": sales_30d,
        "sales_total": sales_total,
        "sales_velocity_7d": velocity,
        "turnover_evidence": evidence,
        "turnover_confidence": confidence,
    }


# ============================================================
# 活动 / 优惠券
# ============================================================

def extract_discount_price(text):
    if not text:
        return None

    patterns = [
        r"(?:券后价|券后|优惠后|折后价|活动后价)"
        r"\s*[:：]?\s*[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",

        r"(?:最终价|实付价|预计到手价|到手价)"
        r"\s*[:：]?\s*[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.I,
        )

        if match:
            value = to_float(
                match.group(1)
            )

            if value is not None:
                return money(value)

    return None


def extract_coupon_evidence(text):
    if not text:
        return []

    keywords = [
        "优惠券",
        "领券",
        "券后",
        "店铺券",
        "品牌券",
        "平台券",
        "满减",
        "补贴",
        "立减",
        "直降",
        "到手价",
        "实付",
    ]

    result = []

    for keyword in keywords:
        start = 0

        while True:
            index = text.find(
                keyword,
                start,
            )

            if index < 0:
                break

            part = text[
                max(0, index - 60):
                min(
                    len(text),
                    index + 180,
                )
            ]

            part = clean_line(part)

            if part and part not in result:
                result.append(part)

            start = index + len(keyword)

            if len(result) >= 20:
                return result

    return result


# ============================================================
# 官方店 / 平台链接
# ============================================================

def detect_platform(url):
    if not url:
        return None

    host = urlparse(
        url
    ).netloc.lower()

    for platform_name, domains in PLATFORMS.items():

        for domain in domains:

            if domain in host:
                return platform_name

    return None


def detect_store_type(text):
    if not text:
        return None

    text = clean_line(text)

    if (
        "京东自营" in text
        or "官方直营" in text
        or "官方直营店" in text
        or "品牌直营" in text
        or "自营旗舰店" in text
    ):
        return "官方直营/自营"

    if (
        "官方旗舰店" in text
        or "品牌旗舰店" in text
    ):
        return "官方旗舰店"

    if "旗舰店" in text:
        return "旗舰店"

    return None
# ============================================================
# 外部平台链接 / 官方店 / 优惠券
# ============================================================

def collect_external_links(page):

    results = []

    try:
        links = page.locator("a")
        count = min(links.count(), 500)
    except Exception:
        return []

    for i in range(count):

        try:
            link = links.nth(i)

            href = link.get_attribute(
                "href",
                timeout=1000
            )

            if not href:
                continue

            href = urljoin(
                page.url,
                href
            )

            anchor_text = clean_line(
                link.inner_text(
                    timeout=1000
                )
            )

            platform_name = detect_platform(
                href
            )

            if not platform_name:
                continue

            store_type = detect_store_type(
                anchor_text
            )

            is_coupon = any(
                word in anchor_text
                for word in COUPON_KEYWORDS
            )

            results.append({
                "platform": platform_name,
                "url": href,
                "anchor_text": anchor_text[:200],
                "store_type": store_type,
                "is_coupon": is_coupon,
            })

        except Exception:
            continue

    unique = []
    seen = set()

    for item in results:

        key = (
            item.get("platform"),
            item.get("url"),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(item)

    return unique


def build_platform_search_urls(
    product_code,
    product_name,
):

    keyword = (
        product_code
        or product_name
        or ""
    )

    keyword = quote(
        str(keyword)
    )

    if not keyword:
        return {}

    return {
        "淘宝":
            f"https://s.taobao.com/search?q={keyword}",

        "天猫":
            f"https://list.tmall.com/search_product.htm?q={keyword}",

        "京东":
            f"https://search.jd.com/Search?keyword={keyword}",

        "拼多多":
            f"https://mobile.yangkeduo.com/search_result.html?search_key={keyword}",

        "唯品会":
            f"https://category.vip.com/suggest.php?keyword={keyword}",
    }


# ============================================================
# 优惠券证据
# ============================================================

def extract_coupon_evidence(text):

    if not text:
        return []

    results = []

    for keyword in COUPON_KEYWORDS:

        for match in list(
            re.finditer(
                re.escape(keyword),
                text,
                re.I
            )
        )[:5]:

            start = max(
                0,
                match.start() - 80
            )

            end = min(
                len(text),
                match.end() + 180
            )

            evidence = clean_line(
                text[start:end]
            )

            if evidence and evidence not in results:
                results.append(evidence)

    return results[:30]


def extract_coupon_amounts(text):

    if not text:
        return []

    results = []

    patterns = [
        r"(?:优惠券|店铺券|品牌券|平台券|领券)[^。；;\n]{0,80}?减\s*([0-9]+(?:\.[0-9]+)?)\s*元",
        r"(?:满\s*[0-9]+(?:\.[0-9]+)?\s*元?\s*)?减\s*([0-9]+(?:\.[0-9]+)?)\s*元",
        r"([0-9]+(?:\.[0-9]+)?)\s*元优惠券",
        r"优惠券\s*([0-9]+(?:\.[0-9]+)?)\s*元",
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            text,
            re.I
        ):

            value = money(
                match.group(1)
            )

            if value is not None:
                results.append(value)

    return sorted(
        set(results),
        reverse=True
    )


def extract_effective_price(text):

    if not text:
        return None

    patterns = [

        r"(?:券后价|券后价格|优惠后价格|活动后价格|最终到手价|预计到手价|到手价|实付价)"
        r"\s*[:：]?\s*[¥￥]?\s*"
        r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",

        r"(?:券后|优惠后|活动后|最终价|实付)"
        r"\s*[¥￥]?\s*"
        r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)"
        r"\s*元",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if not match:
            continue

        value = money(
            match.group(1)
        )

        if value is not None:
            return value

    return None


# ============================================================
# 7日价格趋势
# ============================================================

def extract_7d_low(text):

    if not text:
        return None

    patterns = [

        r"(?:近7天|过去7天|最近7天|7日|7天)"
        r".{0,150}?"
        r"(?:最低价|最低)"
        r"\s*[:：]?\s*"
        r"[¥￥]?\s*"
        r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",

        r"(?:7天最低价|近7日最低价)"
        r"\s*[:：]?\s*"
        r"[¥￥]?\s*"
        r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I | re.S
        )

        if match:

            value = money(
                match.group(1)
            )

            if value is not None:
                return value

    return None


def extract_7d_high(text):

    if not text:
        return None

    patterns = [

        r"(?:近7天|过去7天|最近7天|7日|7天)"
        r".{0,150}?"
        r"(?:最高价|最高)"
        r"\s*[:：]?\s*"
        r"[¥￥]?\s*"
        r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",

        r"(?:7天最高价|近7日最高价)"
        r"\s*[:：]?\s*"
        r"[¥￥]?\s*"
        r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I | re.S
        )

        if match:

            value = money(
                match.group(1)
            )

            if value is not None:
                return value

    return None


def calculate_downside(
    current_price,
    low_7d
):

    if (
        current_price is None
        or low_7d is None
        or current_price <= 0
        or low_7d > current_price
    ):
        return None

    return round(
        (
            current_price
            - low_7d
        )
        / current_price
        * 100,
        2
    )


# ============================================================
# 销量 / 周转
# ============================================================

def extract_sales_evidence(text):

    sales_7d = None
    sales_30d = None
    sales_total = None

    patterns_7d = [
        r"(?:近7天销量|近7日销量|7天销量|7日销量)"
        r"\s*[:：]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?"
    ]

    patterns_30d = [
        r"(?:月销|月销量|近30天销量|近30日销量)"
        r"\s*[:：]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?"
    ]

    patterns_total = [
        r"(?:全网销量|总销|总销量|累计销量)"
        r"\s*[:：]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?"
    ]

    for pattern in patterns_7d:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            value = float(
                match.group(1)
            )

            if match.group(2) == "万":
                value *= 10000

            sales_7d = value
            break

    for pattern in patterns_30d:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            value = float(
                match.group(1)
            )

            if match.group(2) == "万":
                value *= 10000

            sales_30d = value
            break

    for pattern in patterns_total:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            value = float(
                match.group(1)
            )

            if match.group(2) == "万":
                value *= 10000

            sales_total = value
            break

    if sales_7d:
        velocity = round(
            sales_7d / 7,
            2
        )

        confidence = "high"

        evidence = (
            f"近7日销量 {sales_7d:g}，"
            f"日均约 {velocity:g}"
        )

    elif sales_30d:

        velocity = round(
            sales_30d / 30,
            2
        )

        confidence = "medium"

        evidence = (
            f"月销 {sales_30d:g}，"
            f"折算日均约 {velocity:g}"
        )

    elif sales_total:

        velocity = None

        confidence = "low"

        evidence = (
            f"累计/全网销量 {sales_total:g}，"
            "不能直接证明7日周转"
        )

    else:

        velocity = None

        confidence = "unknown"

        evidence = None

    return {
        "sales_7d": sales_7d,
        "sales_30d": sales_30d,
        "sales_total": sales_total,
        "sales_velocity_7d": velocity,
        "turnover_confidence": confidence,
        "turnover_evidence":evidence,
    ｝
# ==============================================================
# 这里先停
# ============================================================
# ============================================================
# 构建最终商品
# ============================================================

def build_product(item):

    product = dict(item)

    product["name"] = first_value(
        item,
        "name",
        "title",
        "product_name",
    )

    product["product_code"] = get_product_code(
        item
    )

    product["color"] = get_color(
        item
    )

    product["current_size"] = get_size(
        item
    )

    product["selected_variant"] = get_variant(
        item
    )

    # --------------------------------------------------------
    # SKU 尺码价格
    # --------------------------------------------------------

    size_price_map = get_size_price_map(
        item
    )

    product["size_price_map"] = (
        size_price_map
    )

    sku_buy_price = (
        get_current_size_buy_price(
            item,
            size_price_map,
        )
    )

    if sku_buy_price is not None:

        product["sku_buy_price"] = money(
            sku_buy_price
        )

        product["sku_price_status"] = (
            "confirmed_current_size"
        )

    elif (
        size_price_map
        and product["current_size"] is None
    ):

        product["sku_buy_price"] = None

        product["sku_price_status"] = (
            "size_prices_available_but_current_size_unknown"
        )

    else:

        product["sku_buy_price"] = None

        product["sku_price_status"] = (
            "no_sku_price"
        )

    # --------------------------------------------------------
    # 活动 / 优惠券
    # --------------------------------------------------------

    effective_buy_price = (
        get_effective_buy_price(item)
    )

    product["effective_buy_price"] = (
        effective_buy_price
    )

    product["buy_price_before_discount"] = (
        money(
            item.get(
                "buy_price_before_discount"
            )
        )
    )

    product["discount_total"] = (
        money(
            item.get(
                "discount_total"
            )
        )
    )

    product["coupon_urls"] = (
        get_coupon_urls(item)
    )

    product["official_store_links"] = (
        get_official_store_links(item)
    )

    # --------------------------------------------------------
    # 最终买入价
    # --------------------------------------------------------

    (
        buy_price,
        buy_source,
        buy_status,
    ) = get_buy_price_info(item)

    if effective_buy_price is not None:

        final_buy_price = (
            effective_buy_price
        )

        final_buy_source = (
            "活动后明确到手价"
        )

        final_buy_status = (
            "estimated_after_discount"
        )

    elif buy_price is not None:

        final_buy_price = buy_price
        final_buy_source = buy_source
        final_buy_status = buy_status

    else:

        final_buy_price = None
        final_buy_source = None
        final_buy_status = (
            "no_buy_price"
        )

    product["buy_price"] = (
        final_buy_price
    )

    product["buy_price_source"] = (
        final_buy_source
    )

    product["buy_price_status"] = (
        final_buy_status
    )

    # --------------------------------------------------------
    # 得物价格
    # --------------------------------------------------------

    (
        dewu_price,
        dewu_source,
        dewu_status,
    ) = build_dewu_price(item)

    product["dewu_channel_price"] = (
        get_dewu_channel_price(item)
    )

    product["trend_current_price"] = (
        get_trend_current_price(item)
    )

    product["dewu_price"] = dewu_price

    product["dewu_price_source"] = (
        dewu_source
    )

    product["dewu_price_status"] = (
        dewu_status
    )

    # --------------------------------------------------------
    # 7 日价格趋势
    # --------------------------------------------------------

    low_7d = get_7d_low(item)

    high_7d = get_7d_high(item)

    current_price = (
        product["trend_current_price"]
        or product["dewu_channel_price"]
    )

    (
        downside,
        position,
    ) = calculate_price_risk(
        current_price,
        low_7d,
        high_7d,
    )

    product["price_7d_low"] = low_7d

    product["price_7d_high"] = high_7d

    product["price_current"] = (
        money(current_price)
        if current_price is not None
        else None
    )

    product["downside_to_7d_low"] = (
        downside
    )

    product["price_position_7d"] = (
        position
    )

    product["price_evidence_status"] = (
        "confirmed"
        if current_price is not None
        else "missing"
    )

    # --------------------------------------------------------
    # 销量 / 周转
    # --------------------------------------------------------

    sales = get_sales(item)

    product.update(sales)

    # --------------------------------------------------------
    # 正品
    # --------------------------------------------------------

    (
        authenticity_ok,
        authenticity_reason,
    ) = get_authenticity_status(item)

    product["authenticity_verified"] = (
        authenticity_ok
    )

    product["authenticity_evidence"] = (
        authenticity_reason
    )

    # --------------------------------------------------------
    # 全新 / 得物兼容
    # --------------------------------------------------------

    product["new_condition_verified"] = (
        get_new_condition(item)
    )

    product["dewu_check_compatible"] = (
        get_dewu_compatible(item)
    )

    # --------------------------------------------------------
    # 活动渠道信息
    # --------------------------------------------------------

    product["buy_platform"] = item.get(
        "buy_platform"
    )

    product["store_type"] = item.get(
        "store_type"
    )

    product["buy_url"] = item.get(
        "buy_url"
    )

    product["coupon_evidence"] = item.get(
        "coupon_evidence",
        [],
    )

    # --------------------------------------------------------
    # 估算利润状态
    # --------------------------------------------------------

    if (
        dewu_price is not None
        and final_buy_price is not None
    ):

        product[
            "estimated_profit_status"
        ] = "estimated_ready"

        product[
            "estimated_profit_confirmation"
        ] = (
            "已具备买入价和得物售价，"
            "可以按统一估算公式计算"
        )

    elif dewu_price is not None:

        product[
            "estimated_profit_status"
        ] = "missing_buy_price"

        product[
            "estimated_profit_confirmation"
        ] = (
            "已有得物售价，但缺少有效买入价"
        )

    elif final_buy_price is not None:

        product[
            "estimated_profit_status"
        ] = "missing_dewu_price"

        product[
            "estimated_profit_confirmation"
        ] = (
            "已有买入价，但缺少有效得物售价"
        )

    else:

        product[
            "estimated_profit_status"
        ] = "not_ready"

        product[
            "estimated_profit_confirmation"
        ] = (
            "买入价和得物售价均不足"
        )

    # --------------------------------------------------------
    # 兼容旧字段
    # --------------------------------------------------------

    product["income_confirmed"] = (
        product[
            "estimated_profit_status"
        ] == "estimated_ready"
    )

    product[
        "income_confirmation_reason"
    ] = product[
        "estimated_profit_confirmation"
    ]

    # --------------------------------------------------------
    # 证据完整度
    # --------------------------------------------------------

    evidence = {
        "product_code": bool(
            product.get(
                "product_code"
            )
        ),

        "color": bool(
            product.get(
                "color"
            )
        ),

        "size_price_map": bool(
            product.get(
                "size_price_map"
            )
        ),

        "current_size": bool(
            product.get(
                "current_size"
            )
        ),

        "buy_price": (
            final_buy_price is not None
        ),

        "dewu_price": (
            dewu_price is not None
        ),

        "price_7d_low": (
            low_7d is not None
        ),

        "price_7d_high": (
            high_7d is not None
        ),

        "turnover": (
            sales[
                "turnover_confidence"
            ] != "unknown"
        ),

        "official_store": bool(
            product.get(
                "official_store_links"
            )
        ),

        "coupon": bool(
            product.get(
                "coupon_urls"
            )
            or product.get(
                "coupon_evidence"
            )
        ),
    }

    product["evidence"] = evidence

    product["evidence_count"] = sum(
        1
        for value in evidence.values()
        if value
    )

    product["bridge_updated_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    return product


# ============================================================
# 主程序
# ============================================================

def main():

    data = load_json(
        INPUT_FILE
    )

    items = get_items(
        data
    )

    products = []

    for item in items:

        if not isinstance(
            item,
            dict,
        ):
            continue

        try:

            product = build_product(
                item
            )

            products.append(
                product
            )

        except Exception as e:

            print(
                "整理商品失败：",
                item.get("name"),
                e,
            )

    output = {
        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "count":
            len(products),

        "source":
            "识货",

        "products":
            products,
    }

    Path(
        OUTPUT_FILE
    ).write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "=============================="
    )

    print(
        f"输入商品数：{len(items)}"
    )

    print(
        f"输出商品数：{len(products)}"
    )

    print(
        "货号：",
        sum(
            bool(
                x.get("product_code")
            )
            for x in products
        )
    )

    print(
        "配色：",
        sum(
            bool(
                x.get("color")
            )
            for x in products
        )
    )

    print(
        "SKU尺码价格表：",
        sum(
            bool(
                x.get("size_price_map")
            )
            for x in products
        )
    )

    print(
        "得物渠道售价：",
        sum(
            x.get(
                "dewu_channel_price"
            ) is not None
            for x in products
        )
    )

    print(
        "7日最低价：",
        sum(
            x.get(
                "price_7d_low"
            ) is not None
            for x in products
        )
    )

    print(
        "周转证据：",
        sum(
            x.get(
                "turnover_confidence"
            ) != "unknown"
            for x in products
        )
    )

    print(
        "活动后价格：",
        sum(
            x.get(
                "effective_buy_price"
            ) is not None
            for x in products
        )
    )

    print(
        "=============================="
    )


if __name__ == "__main__":
    main()