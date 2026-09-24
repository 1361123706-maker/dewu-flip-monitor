import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

from promotion_engine import calculate_best_price
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


# ============================================================
# 基础配置
# ============================================================

OUTPUT_FILE = Path("discovery_data.json")

HOME_URL = "https://www.shihuo.cn/page/pcHome"
SEARCH_URL = (
    "https://m.shihuo.cn/search/searchResult/goods"
    "?keywords={keyword}&page={page}&pagesize=30"
)

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

MAX_KEYWORDS = 14
MAX_PRODUCTS = 30
MAX_DETAIL_LINKS = 30

PAGE_TIMEOUT = 30000
DETAIL_TIMEOUT = 20000
SEARCH_WAIT_SECONDS = 3
DETAIL_WAIT_SECONDS = 1.5


PLATFORM_RULES = [
    {
        "name": "天猫",
        "domains": ["tmall.com"],
        "official_markers": ["官方旗舰店", "旗舰店", "官方店"],
    },
    {
        "name": "淘宝",
        "domains": ["taobao.com"],
        "official_markers": ["官方旗舰店", "旗舰店", "官方店"],
    },
    {
        "name": "京东",
        "domains": ["jd.com"],
        "official_markers": ["京东自营", "自营旗舰店", "官方旗舰店", "旗舰店"],
    },
    {
        "name": "拼多多",
        "domains": ["yangkeduo.com", "pinduoduo.com"],
        "official_markers": ["官方旗舰店", "旗舰店", "品牌店"],
    },
    {
        "name": "唯品会",
        "domains": ["vip.com"],
        "official_markers": ["官方", "旗舰店", "品牌"],
    },
    {
        "name": "抖音商城",
        "domains": ["douyin.com"],
        "official_markers": ["官方旗舰店", "旗舰店", "官方店"],
    },
]

COUPON_KEYWORDS = [
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

# ============================================================
# 工具
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u200b", "")
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def to_float(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        number = float(value)
        return number if number > 0 else None

    text = str(value)
    text = (
        text.replace(",", "")
        .replace("¥", "")
        .replace("￥", "")
        .replace("元", "")
        .strip()
    )

    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None

    try:
        number = float(match.group(0))
    except ValueError:
        return None

    return number if number > 0 else None


def money(value):
    number = to_float(value)
    return round(number, 2) if number is not None else None


def unique_list(values):
    result = []
    for value in values:
        value = clean_text(value)
        if value and value not in result:
            result.append(value)
    return result


def first_value(item, *keys):
    if not isinstance(item, dict):
        return None

    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value.strip()
        else:
            return value

    return None


def safe_json_load(path):
    if not path.exists():
        return {}

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        print("读取旧数据失败：", exc)
        return {}


# ============================================================
# 平台 / 店铺 / 链接
# ============================================================

def detect_platform(url):
    if not url:
        return None

    host = urlparse(str(url)).netloc.lower()

    for rule in PLATFORM_RULES:
        for domain in rule["domains"]:
            if host == domain or host.endswith("." + domain):
                return rule["name"]

    return None


def detect_store_type(text):
    text = clean_text(text)

    if not text:
        return None

    if any(
        marker in text
        for marker in (
            "京东自营",
            "官方直营",
            "官方直营店",
            "品牌直营",
            "自营旗舰店",
        )
    ):
        return "官方直营/自营"

    if "官方旗舰店" in text or "品牌旗舰店" in text:
        return "官方旗舰店"

    if "旗舰店" in text:
        return "旗舰店"

    return None


def is_product_url(url):
    if not url:
        return False

    lower = str(url).lower()

    if "shihuo.cn" not in lower:
        return False

    return any(
        marker in lower
        for marker in (
            "goods",
            "product",
            "detail",
            "item",
            "pcgoodsdetail",
        )
    )


def collect_external_links(page):
    results = []

    try:
        anchors = page.locator("a")
        count = min(anchors.count(), 600)
    except Exception:
        return results

    for index in range(count):
        try:
            anchor = anchors.nth(index)
            href = anchor.get_attribute(
                "href",
                timeout=1000,
            )

            if not href:
                continue

            href = urljoin(page.url, href)
            text = clean_text(
                anchor.inner_text(timeout=1000)
            )

            platform = detect_platform(href)
            if not platform:
                continue

            results.append(
                {
                    "platform": platform,
                    "url": href,
                    "anchor_text": text[:200],
                    "store_type": detect_store_type(text),
                    "is_coupon": any(
                        word in text
                        for word in COUPON_KEYWORDS
                    ),
                }
            )
        except Exception:
            continue

    unique = []
    seen = set()

    for item in results:
        key = (item["platform"], item["url"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique


# ============================================================
# 文本字段提取
# ============================================================

def extract_product_code(text):
    text = clean_text(text)
    if not text:
        return None

    patterns = [
        r"(?:货号|商品货号|产品货号|款号|款式号|款式编号)"
        r"\s*(?:为|是|[:：])?\s*"
        r"([A-Za-z0-9][A-Za-z0-9._\-/]{3,40})",
        r"([A-Z]{1,8}\d{2,}[A-Z0-9._\-/]*)\s*货号",
    ]

    blacklist = {
        "adidas", "nike", "newbalance", "asics",
        "puma", "jordan", "apple", "coach",
        "originals", "superstar",
    }

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue

        value = clean_text(match.group(1))
        if value and value.lower() not in blacklist:
            return value

    return None


def extract_color(text):
    text = clean_text(text)
    if not text:
        return None

    patterns = [
        r"(?:当前配色|当前颜色|已选配色|已选颜色)"
        r"\s*[:：]?\s*([^，,。；;\n]{1,80})",
        r"(?:商品配色|商品颜色)"
        r"\s*[:：]\s*([^，,。；;\n]{1,80})",
    ]

    blacklist = {
        "可选配色", "可选尺码", "颜色", "尺码",
        "货号", "品牌", "商品名称", "价格信息",
    }

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue

        value = clean_text(match.group(1))
        value = value.strip("：:，,。；; ")
        if value and value not in blacklist and len(value) <= 80:
            return value

    return None


def extract_current_size(text):
    text = clean_text(text)
    if not text:
        return None

    patterns = [
        r"(?:当前尺码|已选尺码|选中尺码|当前鞋码)"
        r"\s*[:：]?\s*([A-Za-z0-9./\-½⅓⅔]{1,12})",
        r"(?:当前规格|已选规格|选中规格)"
        r"\s*[:：]?\s*[^，,；;]{0,30}?"
        r"(?:尺码|鞋码)"
        r"\s*[:：]?\s*([A-Za-z0-9./\-½⅓⅔]{1,12})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue

        value = clean_text(match.group(1))
        if value and value not in {"请选择", "未选择"}:
            return value

    return None


def extract_size_price_map(text):
    result = {}
    if not text:
        return result

    patterns = [
        r"([0-9A-Za-z./\-½⅓⅔]+)\s*[¥￥]\s*"
        r"([0-9]+(?:\.[0-9]+)?)",
        r"([0-9A-Za-z./\-½⅓⅔]+)\s+"
        r"([0-9]+(?:\.[0-9]+)?)\s*元",
    ]

    for pattern in patterns:
        for size, price in re.findall(pattern, text, re.I):
            number = to_float(price)
            size = clean_text(size)

            if number is None or not size or len(size) > 12:
                continue

            result[size] = money(number)

    return result


def extract_price_after_keywords(text, keywords):
    if not text:
        return None

    joined = "|".join(
        re.escape(keyword)
        for keyword in keywords
    )

    pattern = (
        rf"(?:{joined})"
        r"\s*[:：]?\s*[¥￥]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
    )

    match = re.search(pattern, text, re.I)
    return money(match.group(1)) if match else None


def extract_effective_price(text):
    return extract_price_after_keywords(
        text,
        (
            "券后价",
            "券后价格",
            "优惠后价格",
            "活动后价格",
            "最终到手价",
            "预计到手价",
            "到手价",
            "实付价",
            "最终价",
        ),
    )


def extract_base_price(text):
    return extract_price_after_keywords(
        text,
        (
            "原价",
            "吊牌价",
            "商品价",
            "售价",
            "价格",
        ),
    )


def extract_dewu_channel_price(text):
    return extract_price_after_keywords(
        text,
        (
            "得物渠道售价",
            "得物售价",
            "得物渠道价格",
        ),
    )


def extract_current_price(text):
    return extract_price_after_keywords(
        text,
        (
            "当前同款同规格",
            "当前价格",
            "当前价",
            "当前到手价",
        ),
    )


def extract_7d_low(text):
    if not text:
        return None

    patterns = [
        r"(?:近7天|过去7天|最近7天|7日|7天)"
        r".{0,150}?(?:最低价|最低)"
        r"\s*[:：]?\s*[¥￥]?\s*"
        r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
        r"(?:7天最低价|近7日最低价)"
        r"\s*[:：]?\s*[¥￥]?\s*"
        r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.I | re.S,
        )
        if match:
            value = money(match.group(1))
            if value is not None:
                return value

    return None


def extract_7d_high(text):
    if not text:
        return None

    patterns = [
        r"(?:近7天|过去7天|最近7天|7日|7天)"
        r".{0,150}?(?:最高价|最高)"
        r"\s*[:：]?\s*[¥￥]?\s*"
        r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
        r"(?:7天最高价|近7日最高价)"
        r"\s*[:：]?\s*[¥￥]?\s*"
        r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.I | re.S,
        )
        if match:
            value = money(match.group(1))
            if value is not None:
                return value

    return None


def extract_sales(text):
    result = {
        "sales_7d": None,
        "sales_30d": None,
        "sales_total": None,
        "sales_velocity_7d": None,
        "turnover_evidence": None,
        "turnover_confidence": "unknown",
    }

    if not text:
        return result

    patterns = {
        "sales_7d": [
            r"(?:近7天|近7日|7天销量|7日销量)"
            r"\s*[:：]?\s*"
            r"([0-9]+(?:\.[0-9]+)?)\s*(万)?",
        ],
        "sales_30d": [
            r"(?:月销|月销量|近30天销量|近30日销量)"
            r"\s*[:：]?\s*"
            r"([0-9]+(?:\.[0-9]+)?)\s*(万)?",
        ],
        "sales_total": [
            r"(?:全网销量|总销|总销量|累计销量)"
            r"\s*[:：]?\s*"
            r"([0-9]+(?:\.[0-9]+)?)\s*(万)?",
        ],
    }

    for field, field_patterns in patterns.items():
        for pattern in field_patterns:
            match = re.search(pattern, text, re.I)
            if not match:
                continue

            value = to_float(match.group(1))
            if value is None:
                continue

            if match.group(2) == "万":
                value *= 10000

            result[field] = money(value)
            break

    if result["sales_7d"]:
        velocity = round(result["sales_7d"] / 7, 2)
        result["sales_velocity_7d"] = velocity
        result["turnover_confidence"] = "high"
        result["turnover_evidence"] = (
            f"近7日销量 {result['sales_7d']:g}，"
            f"日均约 {velocity:.2f}"
        )
    elif result["sales_30d"]:
        velocity = round(result["sales_30d"] / 30, 2)
        result["sales_velocity_7d"] = velocity
        result["turnover_confidence"] = "medium"
        result["turnover_evidence"] = (
            f"月销 {result['sales_30d']:g}，"
            f"日均约 {velocity:.2f}"
        )
    elif result["sales_total"]:
        result["turnover_confidence"] = "low"
        result["turnover_evidence"] = (
            f"累计/全网销量 {result['sales_total']:g}，"
            "不能直接证明7日周转"
        )

    return result


def extract_coupon_evidence(text):
    if not text:
        return []

    results = []

    for keyword in COUPON_KEYWORDS:
        for match in list(
            re.finditer(
                re.escape(keyword),
                text,
                re.I,
            )
        )[:5]:
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 180)
            evidence = clean_text(text[start:end])

            if evidence and evidence not in results:
                results.append(evidence)

    return results[:30]


def extract_coupon_offers(text, links):
    offers = []

    if not text:
        text = ""

    # 1. 明确“满 X 减 Y”
    full_reduce_patterns = [
        r"满\s*([0-9]+(?:\.[0-9]+)?)\s*元?"
        r"[^。；;\n]{0,20}?"
        r"减\s*([0-9]+(?:\.[0-9]+)?)\s*元",
    ]

    for pattern in full_reduce_patterns:
        for match in re.finditer(pattern, text, re.I):
            threshold = money(match.group(1))
            amount = money(match.group(2))

            if amount is None:
                continue

            offers.append(
                {
                    "type": "满减",
                    "platform": "",
                    "amount": amount,
                    "threshold": threshold,
                    "url": None,
                    "stackable": False,
                    "evidence": clean_text(match.group(0)),
                }
            )

    # 2. 明确优惠券金额
    coupon_patterns = [
        r"(?:优惠券|店铺券|品牌券|平台券|领券)"
        r"[^。；;\n]{0,50}?"
        r"(?:减\s*)?([0-9]+(?:\.[0-9]+)?)\s*元",
        r"([0-9]+(?:\.[0-9]+)?)\s*元优惠券",
    ]

    amounts = []

    for pattern in coupon_patterns:
        for match in re.finditer(pattern, text, re.I):
            amount = money(match.group(1))
            if amount is not None and amount not in amounts:
                amounts.append(amount)

    coupon_links = [
        link
        for link in links
        if link.get("is_coupon")
    ]

    for amount in amounts:
        selected_link = (
            coupon_links[0]["url"]
            if coupon_links
            else None
        )

        offers.append(
            {
                "type": "优惠券",
                "platform": (
                    coupon_links[0]["platform"]
                    if coupon_links
                    else ""
                ),
                "amount": amount,
                "threshold": None,
                "url": selected_link,
                "stackable": False,
                "evidence": f"检测到优惠券约减 {amount:g} 元",
            }
        )

    # 3. 补贴 / 直降
    subsidy_patterns = [
        r"(?:平台补贴|补贴|直降|立减)"
        r"[^0-9]{0,20}"
        r"([0-9]+(?:\.[0-9]+)?)\s*元",
    ]

    for pattern in subsidy_patterns:
        for match in re.finditer(pattern, text, re.I):
            amount = money(match.group(1))
            if amount is None:
                continue

            offers.append(
                {
                    "type": "平台补贴/直降",
                    "platform": "",
                    "amount": amount,
                    "threshold": None,
                    "url": (
                        coupon_links[0]["url"]
                        if coupon_links
                        else None
                    ),
                    "stackable": False,
                    "evidence": clean_text(match.group(0)),
                }
            )

    return offers


# ============================================================
# 风险 / 证据
# ============================================================

def calculate_price_risk(current, low, high):
    downside = None
    position = None

    if (
        current is not None
        and low is not None
        and current > 0
        and low <= current
    ):
        downside = round(
            max(0, (current - low) / current * 100),
            2,
        )

    if (
        current is not None
        and low is not None
        and high is not None
        and high > low
    ):
        position = round(
            max(
                0,
                min(
                    100,
                    (current - low) / (high - low) * 100,
                ),
            ),
            2,
        )

    return downside, position


# ============================================================
# 商品详情页
# ============================================================

def get_page_text(page):
    try:
        return clean_text(
            page.locator("body").inner_text(timeout=8000)
        )
    except Exception:
        return ""


def extract_product_name(text, fallback=""):
    text = clean_text(text)

    if text:
        for line in re.split(r"[\n|]", text):
            line = clean_text(line)
            if (
                len(line) >= 6
                and "识货" not in line
                and "价格" not in line
                and "下载" not in line
            ):
                return line[:200]

    return clean_text(fallback)[:200] or "未知商品"


def build_platform_search_urls(product_code, product_name):
    keyword = clean_text(product_code or product_name)
    if not keyword:
        return {}

    encoded = quote(keyword)

    return {
        "淘宝": f"https://s.taobao.com/search?q={encoded}",
        "天猫": (
            "https://list.tmall.com/search_product.htm"
            f"?q={encoded}"
        ),
        "京东": (
            "https://search.jd.com/Search"
            f"?keyword={encoded}"
        ),
        "拼多多": (
            "https://mobile.yangkeduo.com/"
            f"search_result.html?search_key={encoded}"
        ),
        "唯品会": (
            "https://category.vip.com/"
            f"suggest.php?keyword={encoded}"
        ),
    }


def collect_product_links(page, keyword, page_number):
    search_url = SEARCH_URL.format(
        keyword=quote(keyword),
        page=page_number,
    )

    print(f"正在浏览：{keyword} / 第 {page_number} 页")

    try:
        page.goto(
            search_url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT,
        )
    except PlaywrightTimeoutError:
        print("搜索页加载超时，继续读取当前页面")
    except Exception as exc:
        print("打开搜索页失败：", exc)
        return []

    time.sleep(SEARCH_WAIT_SECONDS)

    links = []

    try:
        anchors = page.locator("a")
        count = min(anchors.count(), 800)

        for index in range(count):
            try:
                anchor = anchors.nth(index)
                href = anchor.get_attribute(
                    "href",
                    timeout=1000,
                )
                if not href:
                    continue

                href = urljoin(page.url, href)

                if not is_product_url(href):
                    continue

                text = clean_text(
                    anchor.inner_text(timeout=1000)
                )

                links.append(
                    {
                        "url": href,
                        "text": text,
                    }
                )
            except Exception:
                continue

    except Exception as exc:
        print("读取搜索结果链接失败：", exc)

    unique = []
    seen = set()

    for item in links:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)

    return unique


def build_product_from_detail(page, url, fallback_name):
    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=DETAIL_TIMEOUT,
        )
    except PlaywrightTimeoutError:
        print("详情页加载超时：", url)
    except Exception as exc:
        print("详情页打开失败：", exc)
        return None

    time.sleep(DETAIL_WAIT_SECONDS)

    text = get_page_text(page)
    if not text:
        return None

    links = collect_external_links(page)

    name = extract_product_name(
        text,
        fallback=fallback_name,
    )

    product_code = extract_product_code(text)
    color = extract_color(text)
    current_size = extract_current_size(text)
    size_price_map = extract_size_price_map(text)

    effective_buy_price = extract_effective_price(text)
    base_price = extract_base_price(text)

    if base_price is None:
        prices = list(size_price_map.values())
        if len(prices) == 1:
            base_price = prices[0]

    dewu_channel_price = extract_dewu_channel_price(text)
    trend_current_price = extract_current_price(text)
    low_7d = extract_7d_low(text)
    high_7d = extract_7d_high(text)

    sales = extract_sales(text)
    coupon_evidence = extract_coupon_evidence(text)
    promotion_offers = extract_coupon_offers(text, links)

    # 外部平台链接
    official_store_links = [
        item
        for item in links
        if item.get("store_type")
    ]

    coupon_urls = [
        item["url"]
        for item in links
        if item.get("is_coupon")
    ]

    # 计算活动后的最低可信买入价。
    promotion_result = calculate_best_price(
        base_price=base_price,
        offers=promotion_offers,
        explicit_effective_price=effective_buy_price,
    )

    best_effective_buy_price = (
        promotion_result.get("effective_price")
    )

    # 当前尺码明确价格优先。
    sku_buy_price = None
    if current_size and current_size in size_price_map:
        sku_buy_price = size_price_map[current_size]
    elif len(size_price_map) == 1:
        sku_buy_price = next(
            iter(size_price_map.values())
        )

    if best_effective_buy_price is not None:
        final_buy_price = best_effective_buy_price
        final_buy_source = "活动优惠计算后的最低到手价"
        final_buy_status = (
            "explicit_effective_price"
            if promotion_result.get("verified")
            else "calculated_promotion_price"
        )
    elif effective_buy_price is not None:
        final_buy_price = effective_buy_price
        final_buy_source = "活动后明确到手价"
        final_buy_status = "estimated_after_discount"
    elif sku_buy_price is not None:
        final_buy_price = sku_buy_price
        final_buy_source = "识货当前尺码价格"
        final_buy_status = "confirmed_sku_price"
    elif base_price is not None:
        final_buy_price = base_price
        final_buy_source = "识货商品价格"
        final_buy_status = "product_level_price"
    else:
        final_buy_price = None
        final_buy_source = None
        final_buy_status = "no_buy_price"

    current_dewu_price = (
        dewu_channel_price
        or trend_current_price
    )

    downside, position = calculate_price_risk(
        current_dewu_price,
        low_7d,
        high_7d,
    )

    product = {
        "name": name,
        "product_code": product_code,
        "color": color,
        "current_size": current_size,
        "selected_variant": None,
        "size_price_map": size_price_map,
        "sku_buy_price": sku_buy_price,
        "sku_price_status": (
            "confirmed_current_size"
            if current_size and sku_buy_price is not None
            else (
                "confirmed_single_sku_price"
                if len(size_price_map) == 1
                else "no_sku_price"
            )
        ),
        "buy_price_before_discount": base_price,
        "effective_buy_price": effective_buy_price,
        "best_effective_buy_price": best_effective_buy_price,
        "buy_price": final_buy_price,
        "buy_price_source": final_buy_source,
        "buy_price_status": final_buy_status,
        "discount_total": (
            money(
                base_price - final_buy_price
            )
            if base_price is not None
            and final_buy_price is not None
            and final_buy_price <= base_price
            else promotion_result.get("discount_total")
        ),
        "promotion_calculation": promotion_result,
        "promotion_offers": promotion_result.get(
            "offers", []
        ),
        "promotion_discount_total": promotion_result.get(
            "discount_total"
        ),
        "promotion_verified": promotion_result.get(
            "verified",
            False,
        ),
        "promotion_status": promotion_result.get(
            "calculation_status"
        ),
        "buy_platform": (
            links[0]["platform"]
            if links
            else None
        ),
        "store_type": (
            official_store_links[0].get("store_type")
            if official_store_links
            else None
        ),
        "buy_url": (
            official_store_links[0]["url"]
            if official_store_links
            else (
                links[0]["url"]
                if links
                else None
            )
        ),
        "official_store_links": official_store_links,
        "coupon_urls": unique_list(
            coupon_urls
            + promotion_result.get("coupon_urls", [])
        ),
        "coupon_evidence": coupon_evidence,
        "platform_search_urls": build_platform_search_urls(
            product_code,
            name,
        ),
        "dewu_channel_price": dewu_channel_price,
        "trend_current_price": trend_current_price,
        "dewu_price": current_dewu_price,
        "dewu_price_source": (
            "识货：得物渠道售价"
            if dewu_channel_price is not None
            else (
                "识货：当前同款同规格价格"
                if trend_current_price is not None
                else None
            )
        ),
        "dewu_price_status": (
            "channel_price"
            if dewu_channel_price is not None
            else (
                "current_price"
                if trend_current_price is not None
                else "no_dewu_price"
            )
        ),
        "price_7d_low": low_7d,
        "price_7d_high": high_7d,
        "price_current": current_dewu_price,
        "downside_to_7d_low": downside,
        "price_position_7d": position,
        "price_evidence_status": (
            "confirmed"
            if current_dewu_price is not None
            else "missing"
        ),
        **sales,
        "authenticity_verified": bool(
            "正品" in text or "鉴别" in text
        ),
        "authenticity_evidence": (
            "详情页包含正品/鉴别相关证据"
            if ("正品" in text or "鉴别" in text)
            else None
        ),
        "new_condition_verified": (
            True
            if any(
                marker in text
                for marker in ("全新", "新品", "未穿")
            )
            else None
        ),
        "dewu_check_compatible": (
            current_dewu_price is not None
        ),
        "source_note": "浏览器实际打开识货公开页面采集",
        "data_source": "shihuo_browser_public_web",
        "shihuo_source": True,
        "shihuo_url": url,
        "source_url": url,
        "data_time": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    # 证据完整度
    evidence = {
        "product_code": bool(product_code),
        "color": bool(color),
        "size_price_map": bool(size_price_map),
        "current_size": bool(current_size),
        "buy_price": final_buy_price is not None,
        "dewu_price": current_dewu_price is not None,
        "price_7d_low": low_7d is not None,
        "price_7d_high": high_7d is not None,
        "turnover": sales["turnover_confidence"] != "unknown",
        "official_store": bool(official_store_links),
        "coupon": bool(
            product["coupon_urls"]
            or coupon_evidence
        ),
    }

    product["evidence"] = evidence
    product["evidence_count"] = sum(
        1
        for value in evidence.values()
        if value
    )

    return product


# ============================================================
# 搜索结果兜底
# ============================================================

def build_fallback_product(url, anchor_text):
    name = clean_text(anchor_text) or "未知商品"
    price = extract_effective_price(name) or extract_base_price(name)

    return {
        "name": name[:200],
        "product_code": extract_product_code(name),
        "color": extract_color(name),
        "current_size": extract_current_size(name),
        "selected_variant": None,
        "size_price_map": {},
        "sku_buy_price": None,
        "sku_price_status": "no_sku_price",
        "buy_price_before_discount": price,
        "effective_buy_price": (
            extract_effective_price(name)
        ),
        "best_effective_buy_price": price,
        "buy_price": price,
        "buy_price_source": "搜索结果文字",
        "buy_price_status": (
            "product_level_price"
            if price is not None
            else "no_buy_price"
        ),
        "promotion_calculation": {
            "base_price": price,
            "effective_price": price,
            "discount_total": None,
            "offers": [],
            "coupon_urls": [],
            "verified": False,
            "calculation_status": "fallback_search_result",
        },
        "promotion_offers": [],
        "promotion_discount_total": None,
        "promotion_verified": False,
        "promotion_status": "fallback_search_result",
        "buy_platform": None,
        "store_type": None,
        "buy_url": None,
        "official_store_links": [],
        "coupon_urls": [],
        "coupon_evidence": [],
        "platform_search_urls": build_platform_search_urls(
            extract_product_code(name),
            name,
        ),
        "dewu_channel_price": None,
        "trend_current_price": None,
        "dewu_price": None,
        "dewu_price_source": None,
        "dewu_price_status": "no_dewu_price",
        "price_7d_low": None,
        "price_7d_high": None,
        "price_current": None,
        "downside_to_7d_low": None,
        "price_position_7d": None,
        "price_evidence_status": "missing",
        "sales_7d": None,
        "sales_30d": None,
        "sales_total": None,
        "sales_velocity_7d": None,
        "turnover_evidence": None,
        "turnover_confidence": "unknown",
        "authenticity_verified": False,
        "authenticity_evidence": None,
        "new_condition_verified": None,
        "dewu_check_compatible": False,
        "source_note": "识货搜索结果页",
        "data_source": "shihuo_browser_public_web",
        "shihuo_source": True,
        "shihuo_url": url,
        "source_url": url,
        "data_time": datetime.now(
            timezone.utc
        ).isoformat(),
        "evidence": {
            "product_code": bool(
                extract_product_code(name)
            ),
            "color": bool(extract_color(name)),
            "size_price_map": False,
            "current_size": False,
            "buy_price": price is not None,
            "dewu_price": False,
            "price_7d_low": False,
            "price_7d_high": False,
            "turnover": False,
            "official_store": False,
            "coupon": False,
        },
        "evidence_count": 1 if price is not None else 0,
    }


# ============================================================
# 合并
# ============================================================

def merge_products(existing, new_products):
    merged = {}

    for product in existing:
        if not isinstance(product, dict):
            continue

        name = clean_text(product.get("name"))
        if name:
            merged[name.lower()] = product

    for product in new_products:
        if not isinstance(product, dict):
            continue

        name = clean_text(product.get("name"))
        if not name:
            continue

        key = name.lower()

        if key not in merged:
            merged[key] = product
            continue

        old = merged[key]

        # 新采集值优先，但不覆盖有效旧值为 None。
        for field, value in product.items():
            if value is not None:
                old[field] = value

        old_urls = unique_list(
            old.get("coupon_urls", [])
            + product.get("coupon_urls", [])
        )
        old["coupon_urls"] = old_urls

        old_links = (
            old.get("official_store_links", [])
            + product.get("official_store_links", [])
        )
        old["official_store_links"] = old_links

        old["evidence_count"] = sum(
            1
            for value in old.get(
                "evidence", {}
            ).values()
            if value
        )

    return list(merged.values())


# ============================================================
# 主程序
# ============================================================

def main():
    print("")
    print("=" * 70)
    print("真实浏览器公开商品采集器")
    print("=" * 70)

    existing_data = safe_json_load(OUTPUT_FILE)
    existing_products = (
        existing_data.get("products", [])
        if isinstance(existing_data, dict)
        else []
    )

    if not isinstance(existing_products, list):
        existing_products = []

    collected = []
    product_links = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
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

        search_page = context.new_page()

        for keyword in KEYWORDS[:MAX_KEYWORDS]:
            links = collect_product_links(
                search_page,
                keyword,
                1,
            )

            for link in links:
                if link["url"] not in {
                    item["url"]
                    for item in product_links
                }:
                    product_links.append(link)

                if len(product_links) >= MAX_DETAIL_LINKS:
                    break

            if len(product_links) >= MAX_DETAIL_LINKS:
                break

        detail_page = context.new_page()

        for index, link in enumerate(
            product_links[:MAX_DETAIL_LINKS],
            start=1,
        ):
            print(
                f"[{index}/{min(len(product_links), MAX_DETAIL_LINKS)}] "
                f"读取详情：{link['url']}"
            )

            product = build_product_from_detail(
                detail_page,
                link["url"],
                link.get("text", ""),
            )

            if product is None:
                product = build_fallback_product(
                    link["url"],
                    link.get("text", ""),
                )

            collected.append(product)

        browser.close()

    print("")
    print("本次详情商品：", len(collected))

    if not collected:
        print("本次没有取得新的真实商品数据，保留旧数据。")
        products = existing_products
    else:
        products = merge_products(
            existing_products,
            collected,
        )

    output = {
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "count": len(products),
        "source": "识货",
        "products": products,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("最终商品数量：", len(products))
    print("有买入价：", sum(
        item.get("buy_price") is not None
        for item in products
    ))
    print("有识货链接：", sum(
        bool(item.get("shihuo_url"))
        for item in products
    ))
    print("有优惠证据：", sum(
        bool(
            item.get("coupon_urls")
            or item.get("coupon_evidence")
            or item.get("promotion_offers")
        )
        for item in products
    ))
    print("=" * 70)


if __name__ == "__main__":
    main()
