import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, quote

from playwright.sync_api import sync_playwright


HOME_URL = "https://www.shihuo.cn/page/pcHome"
OUTPUT_FILE = "discovery_data.json"

MAX_DETAIL_PAGES = 10
PAGE_TIMEOUT = 15000
DETAIL_TIMEOUT = 12000

VIEWPORT = {"width": 1440, "height": 1000}


# ============================================================
# 品类
# ============================================================

EXCLUDED_KEYWORDS = [
    "黄金", "足金", "金饰", "贵金属", "铂金", "白金",
    "18k", "钻石", "珠宝", "翡翠", "玉石",
    "点券", "充值", "虚拟商品", "游戏币", "账号",
    "激活码", "兑换码", "cdkey", "代充",
    "白酒", "啤酒", "红酒", "葡萄酒", "洋酒",
    "食品", "零食", "饮料", "牛奶", "咖啡",
    "猫粮", "狗粮", "宠物食品",
    "药品", "处方药", "保健品", "维生素",
    "洗衣液", "洗衣粉", "洗洁精", "纸巾",
    "洗发水", "沐浴露", "牙膏", "护肤",
    "化妆品", "香水", "锅", "餐具", "垃圾桶",
]

TARGET_KEYWORDS = [
    "鞋", "球鞋", "运动鞋", "跑鞋", "篮球鞋",
    "足球鞋", "训练鞋", "板鞋", "休闲鞋", "靴",
    "卫衣", "外套", "夹克", "羽绒服", "冲锋衣",
    "风衣", "棉服", "大衣", "t恤", "短袖",
    "衬衫", "裤", "牛仔裤", "运动裤", "短裤",
    "裙", "服装", "包", "背包", "双肩包",
    "斜挎包", "腰包", "托特包", "手提包",
    "手表", "腕表", "帽", "棒球帽", "围巾",
    "手套", "腰带", "皮带", "墨镜", "眼镜",
    "篮球", "足球", "网球拍", "羽毛球拍",
    "运动装备", "手办", "积木", "玩具",
    "耳机", "游戏机", "掌机", "相机", "镜头",
]


# ============================================================
# 中国大陆主要平台
# ============================================================

PLATFORMS = {
    "淘宝": ["taobao.com"],
    "天猫": ["tmall.com"],
    "京东": ["jd.com"],
    "拼多多": ["yangkeduo.com", "pinduoduo.com"],
    "唯品会": ["vip.com"],
    "抖音商城": ["douyin.com"],
    "得物": ["dewu.com"],
}


OFFICIAL_MARKERS = [
    "官方旗舰店",
    "官方店",
    "品牌旗舰店",
    "旗舰店",
    "京东自营",
    "自营旗舰店",
    "官方直营",
    "品牌直营",
    "官方直营店",
]


COUPON_MARKERS = [
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
# 基础
# ============================================================

def clean(text):
    if text is None:
        return ""
    text = str(text).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def money(value):
    try:
        text = str(value).replace(",", "")
        text = re.sub(r"[¥￥元]", "", text).strip()
        number = float(text)
        if number <= 0 or number > 1000000:
            return None
        return round(number, 2)
    except Exception:
        return None


def valid_name(name):
    name = clean(name)
    return len(name) >= 4 and name not in {
        "商品", "详情", "价格", "购买",
        "立即购买", "未知商品",
    }


def classify(name):
    text = clean(name).lower()

    for word in EXCLUDED_KEYWORDS:
        if word.lower() in text:
            return "excluded", f"命中排除词：{word}"

    for word in TARGET_KEYWORDS:
        if word.lower() in text:
            return "target", f"命中目标词：{word}"

    return "unknown", "未命中明确目标关键词"


# ============================================================
# 商品基本信息
# ============================================================

def extract_name(text, title=None):
    patterns = [
        r"商品名称[:：]\s*(.+?)(?:。品牌[:：]|\s+品牌[:：]|\s+货号[:：])",
        r"商品名称[:：]\s*(.+)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            value = clean(m.group(1))
            if valid_name(value):
                return value

    if valid_name(title):
        return clean(title)

    return None


def extract_code(text):
    patterns = [
        r"(?:货号|商品货号|产品货号)\s*(?:为|是|[:：])?\s*([A-Za-z0-9][A-Za-z0-9._\-/]{3,40})",
        r"(?:款号|款式号|款式编号)\s*(?:为|是|[:：])?\s*([A-Za-z0-9][A-Za-z0-9._\-/]{3,40})",
        r"([A-Z]{1,8}\d{2,}[A-Z0-9._\-/]*)\s*货号",
    ]

    blacklist = {
        "adidas", "nike", "puma", "jordan",
        "apple", "coach", "originals", "superstar",
    }

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if not m:
            continue

        value = clean(m.group(1))

        if value and value.lower() not in blacklist:
            return value

    return None


def extract_color(text):
    patterns = [
        r"([^\s,，]{1,30}(?:/[^\s,，]{1,30})+)\s*,\s*[0-9A-Za-z./\-½⅓⅔]+",
        r"(?:当前配色|当前颜色|已选配色|已选颜色)\s*[:：]?\s*([^，,。；;]{1,60})",
        r"(?:商品配色|商品颜色)\s*[:：]\s*([^，,。；;]{1,60})",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if not m:
            continue

        value = clean(m.group(1))

        if value and value not in {
            "可选配色", "可选尺码", "颜色",
            "尺码", "货号", "品牌", "商品名称",
        }:
            return value

    return None


def extract_size(text):
    patterns = [
        r"[^\s,，]{1,30}(?:/[^\s,，]{1,30})+\s*,\s*([0-9A-Za-z./\-½⅓⅔]+)",
        r"(?:当前尺码|已选尺码|选中尺码|当前鞋码)\s*[:：]?\s*([A-Za-z0-9./\-½⅓⅔]{1,12})",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            value = clean(m.group(1))
            if value and value not in {"请选择", "未选择"}:
                return value

    return None


# ============================================================
# 每个尺码对应识货价格
# ============================================================

def normalize_size(size):
    if size is None:
        return None
    return str(size).strip().replace(" ", "")


def extract_size_price_map(text):
    result = {}

    patterns = [
        r"(?<![A-Za-z0-9])(\d{2}(?:½|⅓|⅔)?|\d{1,2}(?:\.\d+)?)\s*[：:]?\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"(?<![A-Za-z0-9])(\d{2}(?:½|⅓|⅔)?)\s+[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]

    for pattern in patterns:
        for m in re.finditer(pattern, text):
            size = normalize_size(m.group(1))
            price = money(m.group(2))

            if not size or price is None:
                continue

            numeric = (
                size.replace("½", ".5")
                .replace("⅓", ".33")
                .replace("⅔", ".67")
            )

            try:
                number = float(numeric)
            except Exception:
                continue

            if 20 <= number <= 60:
                result[size] = price

    return result


# ============================================================
# 得物价格
# ============================================================

def extract_dewu_price(text):
    patterns = [
        r"得物渠道售价\s*[¥￥]?\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"得物渠道售价为\s*[¥￥]?\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return money(m.group(1))

    return None


def extract_current_price(text):
    patterns = [
        r"当前同款同规格到手价为\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"当前同款同规格到手价为\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*元",
        r"当前(?:同款同规格)?到手价为\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return money(m.group(1))

    return None


# ============================================================
# 7日价格
# ============================================================

def extract_7d_low_high(text):
    low = None
    high = None

    low_patterns = [
        r"(?:过去|近|最近)?7\s*天.{0,150}?(?:最低价|最低)\s*[：:]?\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"(?:过去|近|最近)?7\s*天.{0,150}?最低(?:为|是)?\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]

    high_patterns = [
        r"(?:过去|近|最近)?7\s*天.{0,150}?(?:最高价|最高)\s*[：:]?\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"(?:过去|近|最近)?7\s*天.{0,150}?最高(?:为|是)?\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]

    for pattern in low_patterns:
        m = re.search(pattern, text, re.S | re.I)
        if m:
            low = money(m.group(1))
            break

    for pattern in high_patterns:
        m = re.search(pattern, text, re.S | re.I)
        if m:
            high = money(m.group(1))
            break

    return low, high


def extract_trend_periods(text):
    return [
        period for period in
        ("7天", "30天", "60天", "180天")
        if period in text
    ]


# ============================================================
# 销量 / 周转
# ============================================================

def extract_sales(text):
    sales_7d = None
    sales_30d = None
    sales_total = None

    patterns_7d = [
        r"(?:近7天|近7日|7天销量|7日销量)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(万)?",
    ]

    patterns_30d = [
        r"(?:月销|月销量|近30天销量|近30日销量)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(万)?",
    ]

    patterns_total = [
        r"(?:全网销量|总销|总销量|累计销量)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(万)?",
    ]

    for pattern in patterns_7d:
        m = re.search(pattern, text, re.I)
        if m:
            sales_7d = float(m.group(1))
            if m.group(2) == "万":
                sales_7d *= 10000
            break

    for pattern in patterns_30d:
        m = re.search(pattern, text, re.I)
        if m:
            sales_30d = float(m.group(1))
            if m.group(2) == "万":
                sales_30d *= 10000
            break

    for pattern in patterns_total:
        m = re.search(pattern, text, re.I)
        if m:
            sales_total = float(m.group(1))
            if m.group(2) == "万":
                sales_total *= 10000
            break

    if sales_7d:
        velocity = round(sales_7d / 7, 2)
        evidence = f"近7日销量 {sales_7d:g}，日均约 {velocity}"
        confidence = "high"
    elif sales_30d:
        velocity = round(sales_30d / 30, 2)
        evidence = f"月销 {sales_30d:g}，日均约 {velocity}"
        confidence = "medium"
    elif sales_total:
        velocity = None
        evidence = f"累计/全网销量 {sales_total:g}，不能直接换算周转"
        confidence = "low"
    else:
        velocity = None
        evidence = None
        confidence = "unknown"

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
    patterns = [
        r"(?:券后价|券后|优惠后|折后价|活动后价|最终价|实付价|预计到手价|到手价)\s*[:：]?\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"(?:券后价|券后|优惠后|折后价|活动后价|最终价|实付价|预计到手价|到手价)\s*[:：]?\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*元",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return money(m.group(1))

    return None


def extract_coupon_evidence(text):
    found = []

    for marker in COUPON_MARKERS:
        if marker in text:
            positions = [m.start() for m in re.finditer(re.escape(marker), text)]
            for pos in positions[:3]:
                part = text[max(0, pos - 50):pos + 100]
                if part not in found:
                    found.append(part)

    return found[:15]


def classify_store(text):
    for marker in OFFICIAL_MARKERS:
        if marker in text:
            if "自营" in marker or "直营" in marker:
                return "官方直营/自营"
            return "官方旗舰店"

    return None


def detect_platform(url):
    host = urlparse(url).netloc.lower()

    for platform, domains in PLATFORMS.items():
        if any(domain in host for domain in domains):
            return platform

    return None


def extract_external_links(page):
    results = []

    try:
        links = page.locator("a")
        count = min(links.count(), 500)
    except Exception:
        return results

    for i in range(count):
        try:
            href = links.nth(i).get_attribute("href", timeout=1500)
            text = clean(links.nth(i).inner_text(timeout=1500))

            if not href:
                continue

            href = urljoin(page.url, href)
            platform = detect_platform(href)

            if not platform:
                continue

            store_type = None
            if any(marker in text for marker in OFFICIAL_MARKERS):
                store_type = classify_store(text)

            is_coupon = any(marker in text for marker in COUPON_MARKERS)

            results.append({
                "platform": platform,
                "url": href,
                "anchor_text": text[:150],
                "store_type": store_type,
                "is_coupon": is_coupon,
            })

        except Exception:
            continue

    unique = []
    seen = set()

    for item in results:
        key = item["url"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique


def build_platform_search_urls(product_code, name):
    query = product_code or name
    if not query:
        return {}

    q = quote(query)

    return {
        "淘宝": f"https://s.taobao.com/search?q={q}",
        "天猫": f"https://list.tmall.com/search_product.htm?q={q}",
        "京东": f"https://search.jd.com/Search?keyword={q}",
        "拼多多": f"https://mobile.yangkeduo.com/search_result.html?search_key={q}",
        "唯品会": f"https://category.vip.com/suggest.php?keyword={q}",
    }


# ============================================================
# 详情页
# ============================================================

def extract_detail(page, url):
    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=DETAIL_TIMEOUT,
        )
    except Exception as e:
        print("详情页打开失败：", repr(e), flush=True)
        return None

    try:
        page.wait_for_timeout(1500)
        raw = page.locator("body").inner_text(timeout=6000)
    except Exception as e:
        print("读取详情页失败：", repr(e), flush=True)
        return None

    text = clean(raw)

    try:
        title = clean(page.title())
    except Exception:
        title = None

    name = extract_name(text, title)
    if not valid_name(name):
        return None

    category, category_reason = classify(name)
    if category == "excluded":
        return None

    product_code = extract_code(text)
    color = extract_color(text)
    current_size = extract_size(text)

    size_price_map = extract_size_price_map(text)

    sku_buy_price = None
    if current_size:
        sku_buy_price = size_price_map.get(
            normalize_size(current_size)
        )

    dewu_channel_price = extract_dewu_price(text)
    trend_current_price = extract_current_price(text)

    price_7d_low, price_7d_high = extract_7d_low_high(text)
    trend_periods = extract_trend_periods(text)

    sales = extract_sales(text)

    discount_price = extract_discount_price(text)
    coupon_evidence = extract_coupon_evidence(text)

    try:
        external_links = extract_external_links(page)
    except Exception:
        external_links = []

    official_links = [
        item for item in external_links
        if item.get("store_type")
    ]

    coupon_links = [
        item for item in external_links
        if item.get("is_coupon")
    ]

    buy_links = [
        item for item in external_links
        if not item.get("is_coupon")
    ]

    buy_url = (
        buy_links[0]["url"]
        if buy_links
        else None
    )

    buy_platform = (
        buy_links[0]["platform"]
        if buy_links
        else None
    )

    store_type = (
        official_links[0]["store_type"]
        if official_links
        else None
    )

    official_store_links = [
        {
            "platform": x["platform"],
            "url": x["url"],
            "anchor_text": x["anchor_text"],
            "store_type": x["store_type"],
        }
        for x in official_links
    ]

    coupon_urls = [
        x["url"] for x in coupon_links
    ]

    # 如果页面明确给出了券后/到手价，
    # 才把它作为活动后的预计买入价。
    if discount_price:
        effective_buy_price = discount_price
        buy_price_type = "活动后明确到手价"
    elif sku_buy_price:
        effective_buy_price = sku_buy_price
        buy_price_type = "识货当前尺码价格"
    else:
        effective_buy_price = None
        buy_price_type = "未确认"

    downside = None
    if (
        trend_current_price
        and price_7d_low
        and trend_current_price >= price_7d_low
    ):
        downside = round(
            (trend_current_price - price_7d_low)
            / trend_current_price
            * 100,
            2,
        )

    selected_variant = None

    if color and current_size:
        selected_variant = f"{color}, {current_size}"
    elif color:
        selected_variant = color
    elif current_size:
        selected_variant = current_size

    evidence_status = {
        "product_code": bool(product_code),
        "color": bool(color),
        "current_size": bool(current_size),
        "size_price_map": bool(size_price_map),
        "dewu_channel_price": bool(dewu_channel_price),
        "trend_current_price": bool(trend_current_price),
        "price_7d_low": bool(price_7d_low),
        "price_7d_high": bool(price_7d_high),
        "sales_7d": bool(sales["sales_7d"]),
        "sales_30d": bool(sales["sales_30d"]),
        "official_store": bool(official_store_links),
        "coupon": bool(coupon_evidence or coupon_urls),
    }

    return {
        "name": name,
        "product_code": product_code,
        "color": color,
        "size": current_size,
        "current_size": current_size,
        "selected_variant": selected_variant,

        "category": category,
        "category_reason": category_reason,

        "shihuo_url": url,

        "size_price_map": size_price_map,
        "size_price_evidence": "; ".join(
            f"{s}码 ¥{p:g}"
            for s, p in size_price_map.items()
        ) if size_price_map else None,

        "sku_buy_price": sku_buy_price,

        "buy_price": effective_buy_price,
        "buy_price_type": buy_price_type,

        "buy_platform": buy_platform,
        "buy_url": buy_url,
        "store_type": store_type,

        "official_store_links": official_store_links,

        "platform_search_urls": build_platform_search_urls(
            product_code,
            name,
        ),

        "coupon_urls": coupon_urls,
        "coupon_evidence": coupon_evidence,

        "buy_price_before_discount": sku_buy_price,
        "discount_total": (
            round(
                sku_buy_price - discount_price,
                2,
            )
            if sku_buy_price
            and discount_price
            and sku_buy_price >= discount_price
            else None
        ),

        "effective_buy_price": effective_buy_price,

        "dewu_channel_price": dewu_channel_price,
        "dewu_display_price": dewu_channel_price,

        "trend_current_price": trend_current_price,
        "price_current": trend_current_price,

        "price_7d_low": price_7d_low,
        "price_7d_high": price_7d_high,
        "lowest_price": price_7d_low,

        "downside_to_7d_low": downside,
        "trend_periods": trend_periods,

        "sales_7d": sales["sales_7d"],
        "sales_30d": sales["sales_30d"],
        "sales_total": sales["sales_total"],
        "sales_velocity_7d": sales["sales_velocity_7d"],
        "turnover_evidence": sales["turnover_evidence"],
        "turnover_confidence": sales["turnover_confidence"],

        "new_condition_verified": (
            True
            if re.search(
                r"全新|全新未使用|未使用",
                text,
                re.I,
            )
            else None
        ),

        "dewu_check_compatible": (
            True
            if re.search(
                r"支持鉴别|支持得物|得物可售|可在得物",
                text,
                re.I,
            )
            else None
        ),

        "authenticity_evidence": (
            "识货正品保障/鉴别"
            if re.search(
                r"正品|鉴别|假一赔三",
                text,
                re.I,
            )
            else None
        ),

        "evidence_status": evidence_status,

        "search_key": " | ".join(
            x for x in [
                name,
                f"货号 {product_code}" if product_code else None,
                f"配色 {color}" if color else None,
                f"尺码 {current_size}" if current_size else None,
            ]
            if x
        ),

        "detail_text": raw[:30000],

        "observed_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


# ============================================================
# 首页
# ============================================================

def collect_urls(page):
    print("开始打开识货首页", flush=True)

    try:
        page.goto(
            HOME_URL,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT,
        )
        print("识货首页打开完成", flush=True)
    except Exception as e:
        print("识货首页打开失败：", repr(e), flush=True)

    try:
        page.wait_for_timeout(2000)
    except Exception:
        pass

    urls = []

    try:
        links = page.locator("a[href*='pcGoodsDetail']")
        count = links.count()
    except Exception as e:
        print("读取商品链接失败：", repr(e), flush=True)
        return []

    print(f"发现详情链接：{count}", flush=True)

    for i in range(min(count, MAX_DETAIL_PAGES)):
        try:
            href = links.nth(i).get_attribute(
                "href",
                timeout=3000,
            )

            if not href:
                continue

            full = urljoin(HOME_URL, href)

            if "pcGoodsDetail" in full and full not in urls:
                urls.append(full)

        except Exception:
            continue

    return urls


# ============================================================
# 合并
# ============================================================

def product_key(item):
    code = item.get("product_code")
    color = item.get("color")

    if code and color:
        return f"{code}|{color}"

    url = item.get("shihuo_url")
    if url:
        return url

    return item.get("name")


def merge_items(items):
    merged = {}

    for item in items:
        key = product_key(item)

        if key not in merged:
            merged[key] = item
            continue

        old = merged[key]

        # 保留信息更多的一份
        old_score = sum(
            bool(old.get(k))
            for k in (
                "product_code",
                "color",
                "size_price_map",
                "dewu_channel_price",
                "price_7d_low",
                "sales_30d",
                "official_store_links",
                "coupon_evidence",
            )
        )

        new_score = sum(
            bool(item.get(k))
            for k in (
                "product_code",
                "color",
                "size_price_map",
                "dewu_channel_price",
                "price_7d_low",
                "sales_30d",
                "official_store_links",
                "coupon_evidence",
            )
        )

        if new_score > old_score:
            merged[key] = item

    return list(merged.values())


# ============================================================
# 主程序
# ============================================================

def main():
    items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport=VIEWPORT
        )

        detail_page = browser.new_page(
            viewport=VIEWPORT
        )

        page.set_default_timeout(5000)
        detail_page.set_default_timeout(6000)

        urls = collect_urls(page)

        print(
            f"准备检查 {len(urls)} 个商品",
            flush=True,
        )

        for index, url in enumerate(urls, 1):
            print(
                f"\n[{index}/{len(urls)}] {url}",
                flush=True,
            )

            try:
                item = extract_detail(
                    detail_page,
                    url,
                )

                if not item:
                    print("跳过：无法取得有效商品", flush=True)
                    continue

                items.append(item)

                print(
                    "商品：",
                    item.get("name"),
                    flush=True,
                )

                print(
                    "货号：",
                    item.get("product_code"),
                    flush=True,
                )

                print(
                    "配色：",
                    item.get("color"),
                    flush=True,
                )

                print(
                    "尺码价格：",
                    item.get("size_price_map"),
                    flush=True,
                )

                print(
                    "得物渠道售价：",
                    item.get("dewu_channel_price"),
                    flush=True,
                )

                print(
                    "7日最低：",
                    item.get("price_7d_low"),
                    flush=True,
                )

                print(
                    "月销：",
                    item.get("sales_30d"),
                    flush=True,
                )

                print(
                    "官方店数量：",
                    len(item.get("official_store_links", [])),
                    flush=True,
                )

                print(
                    "优惠券证据：",
                    len(item.get("coupon_evidence", [])),
                    flush=True,
                )

            except Exception as e:
                print(
                    "商品采集失败：",
                    repr(e),
                    flush=True,
                )

            time.sleep(0.5)

        browser.close()

    products = merge_items(items)

    output = {
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "count": len(products),

        "source": "识货公开商品详情",

        "rules": {
            "sku_level": True,
            "dewu_channel_price_first": True,
            "estimated_profit_formula":
                "得物售价×92%-买入价-6元",
            "official_store_collection": True,
            "coupon_collection": True,
            "platforms": list(PLATFORMS.keys()),
        },

        "products": products,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("\n==============================")
    print(f"最终商品数：{len(products)}")

    print(
        "货号已确认：",
        sum(
            bool(x.get("product_code"))
            for x in products
        ),
    )

    print(
        "配色已确认：",
        sum(
            bool(x.get("color"))
            for x in products
        ),
    )

    print(
        "尺码价格表：",
        sum(
            bool(x.get("size_price_map"))
            for x in products
        ),
    )

    print(
        "得物渠道售价：",
        sum(
            bool(x.get("dewu_channel_price"))
            for x in products
        ),
    )

    print(
        "7日最低：",
        sum(
            bool(x.get("price_7d_low"))
            for x in products
        ),
    )

    print(
        "月销量：",
        sum(
            bool(x.get("sales_30d"))
            for x in products
        ),
    )

    print(
        "官方店：",
        sum(
            bool(x.get("official_store_links"))
            for x in products
        ),
    )

    print(
        "优惠券证据：",
        sum(
            bool(x.get("coupon_evidence"))
            or bool(x.get("coupon_urls"))
            for x in products
        ),
    )

    print("==============================")


if __name__ == "__main__":
    main()