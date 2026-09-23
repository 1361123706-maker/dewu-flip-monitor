import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, quote

from playwright.sync_api import sync_playwright


HOME_URL = "https://www.shihuo.cn/page/pcHome"
OUTPUT_FILE = "discovery_data.json"

MAX_DETAIL_PAGES = 10
PAGE_TIMEOUT = 12000
DETAIL_TIMEOUT = 10000

VIEWPORT = {"width": 1440, "height": 1000}


# ============================================================
# 品类
# ============================================================

EXCLUDED = [
    "黄金", "足金", "金饰", "贵金属", "铂金", "白金",
    "钻石", "珠宝", "翡翠", "玉石",
    "点券", "充值", "虚拟商品", "游戏币", "账号",
    "激活码", "兑换码", "cdkey", "代充",
    "白酒", "啤酒", "红酒", "葡萄酒", "洋酒",
    "食品", "零食", "饮料", "牛奶", "咖啡",
    "猫粮", "狗粮", "宠物食品",
    "药品", "处方药", "保健品",
    "洗衣液", "洗衣粉", "洗洁精", "纸巾",
    "洗发水", "沐浴露", "牙膏",
    "护肤", "化妆品", "香水",
    "锅", "餐具", "垃圾桶",
]

TARGET = [
    "鞋", "球鞋", "运动鞋", "跑鞋", "篮球鞋",
    "足球鞋", "训练鞋", "板鞋", "休闲鞋", "靴",
    "卫衣", "外套", "夹克", "羽绒服", "冲锋衣",
    "风衣", "棉服", "大衣", "t恤", "短袖",
    "衬衫", "裤", "牛仔裤", "运动裤", "短裤",
    "裙", "服装", "包", "背包", "双肩包",
    "斜挎包", "腰包", "托特包", "手提包",
    "手表", "腕表", "帽", "棒球帽",
    "围巾", "手套", "腰带", "皮带",
    "墨镜", "眼镜", "篮球", "足球",
    "网球拍", "羽毛球拍", "手办", "积木",
    "玩具", "耳机", "游戏机", "掌机",
    "相机", "镜头",
]


# ============================================================
# 平台
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

OFFICIAL = [
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

COUPON = [
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

def clean(v):
    if v is None:
        return ""
    return re.sub(
        r"\s+",
        " ",
        str(v).replace("\xa0", " ")
    ).strip()


def money(v):
    try:
        v = re.sub(
            r"[¥￥元,]",
            "",
            str(v)
        ).strip()

        n = float(v)

        if n <= 0 or n > 1000000:
            return None

        return round(n, 2)

    except Exception:
        return None


def valid_name(v):
    v = clean(v)

    return (
        len(v) >= 4
        and v not in {
            "商品",
            "详情",
            "价格",
            "购买",
            "立即购买",
            "未知商品",
        }
    )


def classify(name):
    text = clean(name).lower()

    for x in EXCLUDED:
        if x.lower() in text:
            return "excluded", x

    for x in TARGET:
        if x.lower() in text:
            return "target", x

    return "unknown", "未命中目标关键词"


# ============================================================
# 商品身份
# ============================================================

def extract_name(text, title):
    patterns = [
        r"商品名称[:：]\s*(.+?)(?:。品牌[:：]|\s+品牌[:：]|\s+货号[:：])",
        r"商品名称[:：]\s*(.+)",
    ]

    for p in patterns:
        m = re.search(p, text, re.I)

        if m and valid_name(m.group(1)):
            return clean(m.group(1))

    return clean(title) if valid_name(title) else None


def extract_code(text):
    patterns = [
        r"(?:货号|商品货号|产品货号)\s*(?:为|是|[:：])?\s*([A-Za-z0-9][A-Za-z0-9._\-/]{3,40})",
        r"(?:款号|款式号|款式编号)\s*(?:为|是|[:：])?\s*([A-Za-z0-9][A-Za-z0-9._\-/]{3,40})",
        r"([A-Z]{1,8}\d{2,}[A-Z0-9._\-/]*)\s*货号",
    ]

    bad = {
        "adidas",
        "nike",
        "puma",
        "jordan",
        "apple",
        "coach",
        "originals",
        "superstar",
    }

    for p in patterns:
        m = re.search(p, text, re.I)

        if not m:
            continue

        v = clean(m.group(1))

        if v and v.lower() not in bad:
            return v

    return None


def extract_color(text):
    patterns = [
        r"([^\s,，]{1,30}(?:/[^\s,，]{1,30})+)\s*,\s*[0-9A-Za-z./\-½⅓⅔]+",
        r"(?:当前配色|当前颜色|已选配色|已选颜色)\s*[:：]?\s*([^，,。；;]{1,60})",
        r"(?:商品配色|商品颜色)\s*[:：]\s*([^，,。；;]{1,60})",
    ]

    bad = {
        "可选配色",
        "可选尺码",
        "颜色",
        "尺码",
        "货号",
        "品牌",
        "商品名称",
    }

    for p in patterns:
        m = re.search(p, text, re.I)

        if m:
            v = clean(m.group(1))

            if v and v not in bad:
                return v

    return None


def normalize_size(v):
    if v is None:
        return None

    return str(v).strip().replace(" ", "")


def extract_size(text):
    patterns = [
        r"[^\s,，]{1,30}(?:/[^\s,，]{1,30})+\s*,\s*([0-9A-Za-z./\-½⅓⅔]+)",
        r"(?:当前尺码|已选尺码|选中尺码|当前鞋码)\s*[:：]?\s*([A-Za-z0-9./\-½⅓⅔]{1,12})",
    ]

    for p in patterns:
        m = re.search(p, text, re.I)

        if m:
            v = normalize_size(m.group(1))

            if v and v not in {"请选择", "未选择"}:
                return v

    return None


# ============================================================
# SKU 尺码价格
# ============================================================

def extract_size_price_map(text):
    result = {}

    patterns = [
        r"(?<![A-Za-z0-9])(\d{2}(?:½|⅓|⅔)?|\d{1,2}(?:\.\d+)?)\s*[：:]?\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"(?<![A-Za-z0-9])(\d{2}(?:½|⅓|⅔)?)\s+[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]

    for p in patterns:

        for m in re.finditer(p, text):

            size = normalize_size(m.group(1))
            price = money(m.group(2))

            if not size or price is None:
                continue

            n = (
                size
                .replace("½", ".5")
                .replace("⅓", ".33")
                .replace("⅔", ".67")
            )

            try:
                n = float(n)
            except Exception:
                continue

            if 20 <= n <= 60:
                result[size] = price

    return result


# ============================================================
# 得物
# ============================================================

def extract_dewu_price(text):
    for p in [
        r"得物渠道售价\s*[¥￥]?\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"得物渠道售价为\s*[¥￥]?\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]:
        m = re.search(p, text, re.I)

        if m:
            return money(m.group(1))

    return None


def extract_current_price(text):
    for p in [
        r"当前同款同规格到手价为\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"当前同款同规格到手价为\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*元",
        r"当前(?:同款同规格)?到手价为\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]:
        m = re.search(p, text, re.I)

        if m:
            return money(m.group(1))

    return None


# ============================================================
# 7日价格趋势
# ============================================================

def extract_7d(text):
    low = None
    high = None

    for p in [
        r"(?:过去|近|最近)?7\s*天.{0,180}?(?:最低价|最低)\s*[：:]?\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"(?:过去|近|最近)?7\s*天.{0,180}?最低(?:为|是)?\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]:
        m = re.search(p, text, re.I | re.S)

        if m:
            low = money(m.group(1))
            break

    for p in [
        r"(?:过去|近|最近)?7\s*天.{0,180}?(?:最高价|最高)\s*[：:]?\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"(?:过去|近|最近)?7\s*天.{0,180}?最高(?:为|是)?\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]:
        m = re.search(p, text, re.I | re.S)

        if m:
            high = money(m.group(1))
            break

    return low, high


def extract_trend_periods(text):
    return [
        x
        for x in ["7天", "30天", "60天", "180天"]
        if x in text
    ]


# ============================================================
# 销量
# ============================================================

def sales_number(text, patterns):
    for p in patterns:

        m = re.search(p, text, re.I)

        if not m:
            continue

        try:
            n = float(m.group(1))

            if m.group(2) == "万":
                n *= 10000

            return n

        except Exception:
            pass

    return None


def extract_sales(text):

    s7 = sales_number(
        text,
        [
            r"(?:近7天|近7日|7天销量|7日销量)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(万)?",
        ],
    )

    s30 = sales_number(
        text,
        [
            r"(?:月销|月销量|近30天销量|近30日销量)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(万)?",
        ],
    )

    total = sales_number(
        text,
        [
            r"(?:全网销量|总销|总销量|累计销量)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(万)?",
        ],
    )

    if s7:
        velocity = round(s7 / 7, 2)
        confidence = "high"
        evidence = f"近7日销量 {s7:g}，日均约 {velocity}"

    elif s30:
        velocity = round(s30 / 30, 2)
        confidence = "medium"
        evidence = f"月销 {s30:g}，日均约 {velocity}"

    elif total:
        velocity = None
        confidence = "low"
        evidence = f"累计/全网销量 {total:g}，不能直接换算7日周转"

    else:
        velocity = None
        confidence = "unknown"
        evidence = None

    return {
        "sales_7d": s7,
        "sales_30d": s30,
        "sales_total": total,
        "sales_velocity_7d": velocity,
        "turnover_evidence": evidence,
        "turnover_confidence": confidence,
    }


# ============================================================
# 活动 / 优惠
# ============================================================

def extract_discount_price(text):
    for p in [
        r"(?:券后价|券后|优惠后|折后价|活动后价|最终价|实付价|预计到手价|到手价)\s*[:：]?\s*[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"(?:券后价|券后|优惠后|折后价|活动后价|最终价|实付价|预计到手价|到手价)\s*[:：]?\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*元",
    ]:
        m = re.search(p, text, re.I)

        if m:
            return money(m.group(1))

    return None


def coupon_evidence(text):
    result = []

    for marker in COUPON:
        for m in list(
            re.finditer(
                re.escape(marker),
                text
            )
        )[:3]:

            part = text[
                max(0, m.start() - 50):
                m.start() + 120
            ]

            if part not in result:
                result.append(part)

    return result[:15]


# ============================================================
# 外部平台链接
# ============================================================

def platform(url):
    host = urlparse(url).netloc.lower()

    for name, domains in PLATFORMS.items():

        if any(
            d in host
            for d in domains
        ):
            return name

    return None


def store_type(text):
    for x in OFFICIAL:

        if x in text:

            return (
                "官方直营/自营"
                if "自营" in x or "直营" in x
                else "官方旗舰店"
            )

    return None


def external_links(page):

    result = []

    try:
        links = page.locator("a")
        count = min(
            links.count(),
            400
        )
    except Exception:
        return []

    for i in range(count):

        try:
            a = links.nth(i)

            href = a.get_attribute(
                "href",
                timeout=1000
            )

            if not href:
                continue

            href = urljoin(
                page.url,
                href
            )

            p = platform(href)

            if not p:
                continue

            text = clean(
                a.inner_text(
                    timeout=1000
                )
            )

            result.append({
                "platform": p,
                "url": href,
                "anchor_text": text[:150],
                "store_type": store_type(text),
                "is_coupon": any(
                    x in text
                    for x in COUPON
                ),
            })

        except Exception:
            continue

    unique = []
    seen = set()

    for x in result:

        if x["url"] in seen:
            continue

        seen.add(x["url"])
        unique.append(x)

    return unique


def search_urls(code, name):

    q = quote(code or name or "")

    if not q:
        return {}

    return {
        "淘宝":
            f"https://s.taobao.com/search?q={q}",
        "天猫":
            f"https://list.tmall.com/search_product.htm?q={q}",
        "京东":
            f"https://search.jd.com/Search?keyword={q}",
        "拼多多":
            f"https://mobile.yangkeduo.com/search_result.html?search_key={q}",
        "唯品会":
            f"https://category.vip.com/suggest.php?keyword={q}",
    }


# ============================================================
# 详情
# ============================================================

def extract_detail(page, url):

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=DETAIL_TIMEOUT
        )
        page.wait_for_timeout(1000)

    except Exception as e:
        print(
            "详情页失败：",
            repr(e),
            flush=True
        )
        return None

    try:
        raw = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )
    except Exception:
        return None

    text = clean(raw)

    try:
        title = clean(page.title())
    except Exception:
        title = ""

    name = extract_name(
        text,
        title
    )

    if not valid_name(name):
        return None

    category, reason = classify(name)

    if category == "excluded":
        return None

    code = extract_code(text)
    color = extract_color(text)
    size = extract_size(text)

    size_map = extract_size_price_map(
        text
    )

    sku_price = (
        size_map.get(
            normalize_size(size)
        )
        if size
        else None
    )

    dewu = extract_dewu_price(text)
    current = extract_current_price(text)

    low7, high7 = extract_7d(text)

    trends = extract_trend_periods(
        text
    )

    sales = extract_sales(text)

    discount = extract_discount_price(
        text
    )

    coupons = coupon_evidence(
        text
    )

    try:
        links = external_links(page)
    except Exception:
        links = []

    official_links = [
        x for x in links
        if x["store_type"]
    ]

    coupon_links = [
        x for x in links
        if x["is_coupon"]
    ]

    buy_links = [
        x for x in links
        if not x["is_coupon"]
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

    store = (
        official_links[0]["store_type"]
        if official_links
        else None
    )

    # 只有页面明确出现“到手/券后/实付”
    # 才认定为活动后的实际价格。
    effective = (
        discount
        if discount
        else sku_price
    )

    if discount:
        price_type = "活动后明确到手价"
    elif sku_price:
        price_type = "识货当前尺码价格"
    else:
        price_type = "未确认"

    downside = None

    if (
        current
        and low7
        and current >= low7
    ):
        downside = round(
            (current - low7)
            / current
            * 100,
            2
        )

    selected = None

    if color and size:
        selected = f"{color}, {size}"
    elif color:
        selected = color
    elif size:
        selected = size

    return {
        "name": name,
        "product_code": code,
        "color": color,
        "size": size,
        "current_size": size,
        "selected_variant": selected,

        "category": category,
        "category_reason": reason,

        "shihuo_url": url,

        "size_price_map": size_map,
        "sku_buy_price": sku_price,

        "buy_price": effective,
        "buy_price_type": price_type,
        "effective_buy_price": effective,

        "buy_price_before_discount": sku_price,

        "discount_total": (
            round(
                sku_price - discount,
                2
            )
            if sku_price
            and discount
            and sku_price >= discount
            else None
        ),

        "buy_platform": buy_platform,
        "buy_url": buy_url,
        "store_type": store,

        "official_store_links": [
            {
                "platform": x["platform"],
                "url": x["url"],
                "anchor_text": x["anchor_text"],
                "store_type": x["store_type"],
            }
            for x in official_links
        ],

        "platform_search_urls":
            search_urls(
                code,
                name
            ),

        "coupon_urls": [
            x["url"]
            for x in coupon_links
        ],

        "coupon_evidence": coupons,

        "dewu_channel_price": dewu,
        "dewu_display_price": dewu,

        "trend_current_price": current,
        "price_current": current,

        "price_7d_low": low7,
        "price_7d_high": high7,
        "lowest_price": low7,

        "downside_to_7d_low":
            downside,

        "trend_periods": trends,

        **sales,

        "new_condition_verified":
            True
            if re.search(
                r"全新|全新未使用|未使用",
                text,
                re.I
            )
            else None,

        "dewu_check_compatible":
            True
            if re.search(
                r"支持鉴别|支持得物|得物可售|可在得物",
                text,
                re.I
            )
            else None,

        "authenticity_evidence":
            "识货正品保障/鉴别"
            if re.search(
                r"正品|鉴别|假一赔三",
                text,
                re.I
            )
            else None,

        "evidence_status": {
            "product_code": bool(code),
            "color": bool(color),
            "current_size": bool(size),
            "size_price_map": bool(size_map),
            "dewu_channel_price": bool(dewu),
            "trend_current_price": bool(current),
            "price_7d_low": bool(low7),
            "price_7d_high": bool(high7),
            "sales_7d": bool(sales["sales_7d"]),
            "sales_30d": bool(sales["sales_30d"]),
            "official_store":
                bool(official_links),
            "coupon":
                bool(coupons or coupon_links),
        },

        "search_key": " | ".join(
            x for x in [
                name,
                f"货号 {code}" if code else None,
                f"配色 {color}" if color else None,
                f"尺码 {size}" if size else None,
            ]
            if x
        ),

        "detail_text": raw[:30000],

        "observed_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
    }


# ============================================================
# 首页
# ============================================================

def collect_urls(page):

    print(
        "开始打开识货首页",
        flush=True
    )

    try:
        page.goto(
            HOME_URL,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT
        )

        print(
            "识货首页打开完成",
            flush=True
        )

    except Exception as e:
        print(
            "识货首页失败：",
            repr(e),
            flush=True
        )

    try:
        page.wait_for_timeout(
            1500
        )
    except Exception:
        pass

    try:
        links = page.locator(
            "a[href*='pcGoodsDetail']"
        )

        count = links.count()

    except Exception as e:
        print(
            "读取商品链接失败：",
            repr(e),
            flush=True
        )
        return []

    print(
        f"发现详情链接：{count}",
        flush=True
    )

    result = []

    for i in range(
        min(
            count,
            MAX_DETAIL_PAGES
        )
    ):

        try:
            href = links.nth(i).get_attribute(
                "href",
                timeout=2000
            )

            if not href:
                continue

            url = urljoin(
                HOME_URL,
                href
            )

            if (
                "pcGoodsDetail"
                in url
                and url not in result
            ):
                result.append(url)

        except Exception:
            continue

    return result


# ============================================================
# 合并
# ============================================================

def merge(items):

    result = {}

    for item in items:

        key = (
            f"{item.get('product_code')}|"
            f"{item.get('color')}|"
            f"{item.get('shihuo_url')}"
        )

        if key not in result:
            result[key] = item
            continue

        old = result[key]

        fields = [
            "product_code",
            "color",
            "current_size",
            "size_price_map",
            "dewu_channel_price",
            "price_7d_low",
            "sales_30d",
            "official_store_links",
            "coupon_evidence",
        ]

        old_score = sum(
            bool(old.get(x))
            for x in fields
        )

        new_score = sum(
            bool(item.get(x))
            for x in fields
        )

        if new_score > old_score:
            result[key] = item

    return list(result.values())


# ============================================================
# 主程序
# ============================================================

def main():

    items = []

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport=VIEWPORT
        )

        detail = browser.new_page(
            viewport=VIEWPORT
        )

        page.set_default_timeout(
            5000
        )

        detail.set_default_timeout(
            5000
        )

        urls = collect_urls(
            page
        )

        print(
            f"准备检查 {len(urls)} 个商品",
            flush=True
        )

        for i, url in enumerate(
            urls,
            1
        ):

            print(
                f"[{i}/{len(urls)}]",
                flush=True
            )

            try:

                item = extract_detail(
                    detail,
                    url
                )

                if not item:
                    print(
                        "跳过",
                        flush=True
                    )
                    continue

                items.append(item)

                print(
                    "商品：",
                    item.get("name"),
                    flush=True
                )

                print(
                    "货号：",
                    item.get("product_code"),
                    flush=True
                )

                print(
                    "配色：",
                    item.get("color"),
                    flush=True
                )

                print(
                    "尺码价格：",
                    item.get("size_price_map"),
                    flush=True
                )

                print(
                    "得物：",
                    item.get("dewu_channel_price"),
                    flush=True
                )

                print(
                    "7日最低：",
                    item.get("price_7d_low"),
                    flush=True
                )

            except Exception as e:

                print(
                    "采集失败：",
                    repr(e),
                    flush=True
                )

            time.sleep(0.3)

        browser.close()

    products = merge(items)

    output = {
        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "count":
            len(products),

        "source":
            "识货公开商品详情",

        "rules": {
            "sku_level": True,
            "dewu_channel_price_first": True,
            "estimated_profit_formula":
                "得物售价×92%-买入价-6元",
            "official_store_collection": True,
            "coupon_collection": True,
            "platforms":
                list(PLATFORMS.keys()),
        },

        "products":
            products,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        "=============================="
    )

    print(
        "最终商品数：",
        len(products)
    )

    for label, key in [
        ("货号", "product_code"),
        ("配色", "color"),
        ("尺码价格", "size_price_map"),
        ("得物渠道售价", "dewu_channel_price"),
        ("7日最低", "price_7d_low"),
        ("月销", "sales_30d"),
        ("官方店", "official_store_links"),
        ("优惠券", "coupon_evidence"),
    ]:

        print(
            f"{label}：",
            sum(
                bool(x.get(key))
                for x in products
            )
        )

    print(
        "=============================="
    )


if __name__ == "__main__":
    main()