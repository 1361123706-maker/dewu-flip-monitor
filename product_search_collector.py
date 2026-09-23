import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs

from playwright.sync_api import sync_playwright


HOME_URL = "https://www.shihuo.cn/page/pcHome"
OUTPUT_FILE = "discovery_data.json"
MAX_DETAIL_PAGES = 10

VIEWPORT = {
    "width": 1440,
    "height": 1000,
}


# ============================================================
# 品类
# ============================================================

EXCLUDED_KEYWORDS = [
    "黄金", "足金", "金饰", "贵金属", "铂金", "白金",
    "18k", "钻石", "珠宝", "翡翠", "玉石",

    "点券", "充值", "虚拟商品", "游戏币", "游戏道具",
    "账号", "激活码", "兑换码", "cdkey", "代充",
    "会员充值", "话费充值", "流量充值",

    "白酒", "啤酒", "红酒", "葡萄酒", "洋酒", "威士忌",
    "伏特加", "香槟", "酒水",

    "食品", "零食", "饼干", "糖果", "巧克力", "饮料",
    "牛奶", "咖啡", "茶叶", "方便面", "火锅底料",

    "猫粮", "狗粮", "宠物粮", "宠物食品",

    "药品", "处方药", "非处方药", "保健品", "维生素",
    "钙片", "鱼油", "蛋白粉",

    "洗衣液", "洗衣粉", "洗洁精", "纸巾", "卫生纸",
    "垃圾袋", "拖把", "扫把",

    "洗发水", "护发素", "沐浴露", "牙膏", "牙刷",
    "洁面", "护肤", "面霜", "乳液", "化妆品",
    "口红", "粉底", "眼影", "香水",

    "床单", "被套", "枕头", "被子", "锅", "炒锅",
    "水杯", "保温杯", "餐具", "垃圾桶",
]

TARGET_KEYWORDS = [
    "鞋", "球鞋", "运动鞋", "跑鞋", "篮球鞋", "足球鞋",
    "训练鞋", "板鞋", "休闲鞋", "靴",

    "卫衣", "外套", "夹克", "羽绒服", "冲锋衣", "风衣",
    "棉服", "大衣", "T恤", "短袖", "长袖", "衬衫",
    "裤", "牛仔裤", "运动裤", "短裤", "裙", "服装",

    "包", "背包", "双肩包", "斜挎包", "腰包", "托特包",
    "手提包", "旅行包",

    "手表", "腕表", "电子表", "机械表",

    "帽", "棒球帽", "渔夫帽", "围巾", "手套", "腰带",
    "皮带", "墨镜", "太阳镜", "眼镜",

    "篮球", "足球", "网球拍", "羽毛球拍", "运动装备",
    "运动器材", "瑜伽垫", "滑板", "护具",

    "潮玩", "盲盒", "手办", "积木", "玩具",

    "耳机", "蓝牙耳机", "头戴式耳机", "耳塞",
    "游戏机", "掌机", "相机", "镜头", "数码相机",
]


# ============================================================
# 基础
# ============================================================

def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def clean_line(text):
    if not text:
        return None
    text = clean_text(text)
    text = re.sub(r"^[：:、\-\s]+", "", text)
    text = re.sub(r"[：:、\-\s]+$", "", text)
    return text or None


def normalize_price(value, unit=None):
    try:
        value = str(value).replace(",", "")
        value = value.replace("¥", "").replace("￥", "")
        value = value.replace("元", "").strip()
        number = float(value)

        if unit == "万":
            number *= 10000

        if number <= 0 or number > 1000000:
            return None

        return round(number, 2)
    except Exception:
        return None


def valid_name(name):
    if not name:
        return False

    name = clean_text(name)

    return (
        len(name) >= 4
        and name not in {
            "商品", "详情", "价格", "购买",
            "立即购买", "加入购物车", "未知商品"
        }
    )


def classify_product(name):
    text = clean_text(name).lower()

    if not text:
        return "unknown", "商品名称为空"

    for word in EXCLUDED_KEYWORDS:
        if word.lower() in text:
            return "excluded", f"命中排除关键词：{word}"

    for word in TARGET_KEYWORDS:
        if word.lower() in text:
            return "target", f"命中目标关键词：{word}"

    return "unknown", "未命中明确目标品类"


# ============================================================
# 商品名称
# ============================================================

def extract_product_name(text):
    patterns = [
        r"商品名称[:：]\s*(.+?)(?:。品牌[:：])",
        r"商品名称[:：]\s*(.+?)(?:\s+品牌[:：])",
        r"商品名称[:：]\s*(.+?)(?:\s+货号[:：])",
    ]

    for pattern in patterns:
        m = re.search(pattern, text)

        if m:
            name = clean_text(m.group(1))

            if valid_name(name):
                return name

    return None


# ============================================================
# 货号
# ============================================================

def extract_product_code(text):
    if not text:
        return None

    patterns = [
        r"(?:货号|商品货号|产品货号)\s*(?:为|是|[:：])?\s*([A-Za-z0-9][A-Za-z0-9._\-/]{3,40})",
        r"(?:款号|款式号|款式编号)\s*(?:为|是|[:：])?\s*([A-Za-z0-9][A-Za-z0-9._\-/]{3,40})",
        r"([A-Z]{1,8}\d{2,}[A-Z0-9._\-/]*)\s*货号",
    ]

    blacklist = {
        "adidas", "nike", "newbalance", "asics", "puma",
        "jordan", "apple", "coach", "originals", "superstar",
    }

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if not m:
            continue

        value = clean_line(m.group(1))

        if not value:
            continue

        if value.lower() in blacklist:
            continue

        return value

    return None
# ============================================================
# 当前配色
# ============================================================

def extract_color(text):
    if not text:
        return None

    # 识货页面当前选中规格：
    # 黑色/白色, 36
    # clean_text 会把换行合并，所以这里不能依赖 \n。
    patterns = [
        r"([^\s,，]{1,30}(?:/[^\s,，]{1,30})+)\s*,\s*[0-9A-Za-z./\-½⅓⅔]+",
        r"(?:当前配色|当前颜色|已选配色|已选颜色)\s*[:：]?\s*([^，,。；;]{1,60})",
        r"(?:商品配色|商品颜色)\s*[:：]\s*([^，,。；;]{1,60})",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)

        if not m:
            continue

        value = clean_line(m.group(1))

        if not value:
            continue

        if value in {
            "可选配色", "可选尺码", "颜色", "尺码",
            "货号", "品牌", "商品名称", "价格信息",
        }:
            continue

        return value

    return None
# ============================================================
# 尺码
# ============================================================

def extract_current_size(text):
    if not text:
        return None

    # 识货页面当前选中规格：
    # 黑色/白色, 36
    patterns = [
        r"[^\s,，]{1,30}(?:/[^\s,，]{1,30})+\s*,\s*([0-9A-Za-z./\-½⅓⅔]+)",
        r"(?:当前尺码|已选尺码|选中尺码|当前鞋码)\s*[:：]?\s*([A-Za-z0-9./\-½⅓⅔]{1,12})",
        r"(?:当前规格|已选规格|选中规格)\s*[:：]?\s*"
        r"[^，,；;]{0,30}?(?:尺码|鞋码)\s*[:：]?\s*"
        r"([A-Za-z0-9./\-½⅓⅔]{1,12})",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)

        if not m:
            continue

        value = clean_line(m.group(1))

        if not value:
            continue

        if value in {"请选择", "未选择", "信息"}:
            continue

        return value

    return None
# ============================================================
# 尺码 -> 识货价格
# ============================================================

def extract_size_price_map(text):
    """
    核心新增。

    识货页面如果出现：

    36 ¥340
    37 ¥350
    38 ¥380
    39 ¥420

    或：

    45⅓ ¥440
    46 ¥500
    46⅔ ¥500

    就建立：

    {
        "36": 340,
        "37": 350,
        "38": 380,
        ...
    }

    不把年份、销量、货号等普通数字当尺码。
    """

    result = {}

    if not text:
        return result

    # 常见鞋码格式
    size_pattern = (
        r"(?<![A-Za-z0-9])"
        r"("
        r"\d{2}(?:⅓|⅔)?"
        r"|"
        r"\d{1,2}(?:\.\d+)?"
        r"|"
        r"\d{2}/\d{2}"
        r")"
        r"\s*"
        r"[：:]*"
        r"\s*"
        r"[¥￥]"
        r"\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)"
    )

    for m in re.finditer(
        size_pattern,
        text,
    ):
        size = clean_line(m.group(1))
        price = normalize_price(m.group(2))

        if not size or price is None:
            continue

        # 排除明显不是鞋码的数字
        try:
            numeric = float(
                size.replace("⅓", ".33")
                    .replace("⅔", ".67")
            )
        except Exception:
            continue

        if numeric < 20 or numeric > 60:
            continue

        result[size] = price

    # 另一种常见形式：
    # 38 ￥320 / 39 ￥350
    if not result:
        pattern = (
            r"(?<![A-Za-z0-9])"
            r"(\d{2}(?:⅓|⅔)?)"
            r"\s+"
            r"[¥￥]"
            r"\s*"
            r"(\d+(?:,\d{3})*(?:\.\d+)?)"
        )

        for m in re.finditer(
            pattern,
            text,
        ):
            size = clean_line(m.group(1))
            price = normalize_price(m.group(2))

            if not size or price is None:
                continue

            try:
                numeric = float(
                    size.replace("⅓", ".33")
                        .replace("⅔", ".67")
                )
            except Exception:
                continue

            if 20 <= numeric <= 60:
                result[size] = price

    return result


def extract_size_price_evidence(text):
    size_prices = extract_size_price_map(text)

    if not size_prices:
        return None

    return "; ".join(
        f"{size}码 ¥{price:g}"
        for size, price in size_prices.items()
    )


# ============================================================
# 得物价格
# ============================================================

def extract_dewu_price(text):
    patterns = [
        r"得物渠道售价\s*[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",

        r"得物渠道售价为\s*[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",
    ]

    for pattern in patterns:
        m = re.search(pattern, text)

        if m:
            return normalize_price(
                m.group(1),
                m.group(2),
            )

    return None


def extract_trend_current_price(text):
    patterns = [
        r"当前同款同规格到手价为\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)",

        r"当前同款同规格到手价为\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*元",

        r"当前(?:同款同规格)?到手价为\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text)

        if m:
            return normalize_price(m.group(1))

    return None


# ============================================================
# 7日价格
# ============================================================

def extract_7d_extreme_status(text):
    if not text:
        return None

    if re.search(
        r"(?:过去|近|最近)\s*7\s*天.*?(?:最高价|最高)",
        text,
        re.S,
    ):
        return "current_is_7d_high"

    if re.search(
        r"(?:过去|近|最近)\s*7\s*天.*?(?:最低价|最低)",
        text,
        re.S,
    ):
        return "current_is_7d_low"

    return None


def extract_7d_prices(text):
    high = None
    low = None

    patterns_high = [
        r"(?:7天|7日|过去7天|近7天)"
        r".{0,100}?(?:最高价|最高)"
        r".{0,20}?[¥￥]\s*"
        r"(\d+(?:\.\d+)?)",

    ]

    patterns_low = [
        r"(?:7天|7日|过去7天|近7天)"
        r".{0,100}?(?:最低价|最低)"
        r".{0,20}?[¥￥]\s*"
        r"(\d+(?:\.\d+)?)",
    ]

    for pattern in patterns_high:
        m = re.search(pattern, text, re.S)

        if m:
            high = normalize_price(m.group(1))
            break

    for pattern in patterns_low:
        m = re.search(pattern, text, re.S)

        if m:
            low = normalize_price(m.group(1))
            break

    return high, low


# ============================================================
# 销量
# ============================================================

def extract_month_sales(text):
    patterns = [
        r"(?:月销|月销量)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?",

        r"(?:近30天销量|近30日销量)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?",
    ]

    for pattern in patterns:
        m = re.search(pattern, text)

        if not m:
            continue

        value = float(m.group(1))

        if m.group(2) == "万":
            value *= 10000

        return value

    return None


def extract_total_sales(text):
    pattern = (
        r"(?:全网销量|总销|总销量|累计销量)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?"
    )

    m = re.search(pattern, text)

    if not m:
        return None

    value = float(m.group(1))

    if m.group(2) == "万":
        value *= 10000

    return value


# ============================================================
# URL
# ============================================================

def extract_url_params(url):
    result = {
        "goods_id": None,
        "sku_id": None,
        "style_id": None,
    }

    try:
        params = parse_qs(
            urlparse(url).query
        )

        for key in result:
            values = params.get(key)

            if values:
                result[key] = values[0]

    except Exception:
        pass

    return result


# ============================================================
# 详情页
# ============================================================

def extract_detail(page, url):
    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=10000,
    )

    page.wait_for_timeout(1000)

    raw_text = page.locator(
        "body"
    ).inner_text()

    detail_text = clean_text(
        raw_text
    )

    name = extract_product_name(
        detail_text
    )

    if not name:
        title = clean_text(
            page.title()
        )

        if valid_name(title):
            name = title

    product_code = extract_product_code(
        detail_text
    )

    color = extract_color(
        detail_text
    )

    current_size = extract_current_size(
        detail_text
    )

    # ========================================================
    # 核心：完整尺码价格表
    # ========================================================

    size_price_map = extract_size_price_map(
        detail_text
    )

    size_price_evidence = (
        extract_size_price_evidence(
            detail_text
        )
    )

    # 如果当前尺码明确存在价格表中，
    # 当前买入价必须使用该尺码价格，
    # 不能再使用商品最低价/第一价格。
    sku_buy_price = None

    if (
        current_size
        and current_size in size_price_map
    ):
        sku_buy_price = size_price_map[
            current_size
        ]

    # ========================================================
    # 价格
    # ========================================================

    dewu_channel_price = extract_dewu_price(
        detail_text
    )

    trend_current_price = extract_trend_current_price(
        detail_text
    )

    price_7d_high, price_7d_low = extract_7d_prices(
        detail_text
    )

    extreme_status = extract_7d_extreme_status(
        detail_text
    )

    if (
        trend_current_price is not None
        and extreme_status == "current_is_7d_high"
    ):
        price_7d_high = trend_current_price

    if (
        trend_current_price is not None
        and extreme_status == "current_is_7d_low"
    ):
        price_7d_low = trend_current_price

    # ========================================================
    # 买入价
    # ========================================================

    buy_price = sku_buy_price

    if buy_price is None:
        # 没有明确当前尺码价格时，
        # 保留商品级价格，但明确标记为非 SKU 精确价格。
        m = re.search(
            r"全网价格区间[:：]\s*"
            r"[¥￥]?\s*(\d+(?:\.\d+)?)",
            detail_text,
        )

        if m:
            buy_price = normalize_price(
                m.group(1)
            )

    # ========================================================
    # 销量
    # ========================================================

    sales_30d = extract_month_sales(
        detail_text
    )

    sales_total = extract_total_sales(
        detail_text
    )

    # ========================================================
    # 周转
    # ========================================================

    if sales_30d:
        turnover_evidence = (
            f"月销 {sales_30d:g}，"
            f"日均约 {sales_30d / 30:.2f}"
        )
        turnover_confidence = "medium"
        sales_velocity_7d = round(
            sales_30d / 30,
            2,
        )
    elif sales_total:
        turnover_evidence = (
            f"累计/全网销量 {sales_total:g}，"
            f"不能直接换算周转速度"
        )
        turnover_confidence = "low"
        sales_velocity_7d = None
    else:
        turnover_evidence = None
        turnover_confidence = "unknown"
        sales_velocity_7d = None

    # ========================================================
    # 下跌风险
    # ========================================================

    downside_to_7d_low = None

    if (
        trend_current_price is not None
        and price_7d_low is not None
        and trend_current_price > 0
    ):
        downside_to_7d_low = round(
            (
                trend_current_price
                - price_7d_low
            )
            / trend_current_price
            * 100,
            2,
        )

    # ========================================================
    # SKU 定位
    # ========================================================

    if color and current_size:
        selected_variant = (
            f"{color} | {current_size}"
        )
    elif color:
        selected_variant = color
    elif current_size:
        selected_variant = current_size
    else:
        selected_variant = None

    search_key = " | ".join(
        [
            str(name or ""),
            f"货号 {product_code}"
            if product_code
            else "货号 未明确",
            f"配色 {color}"
            if color
            else "配色 未明确",
            f"尺码 {current_size}"
            if current_size
            else "尺码 未明确",
        ]
    )

    category, category_reason = classify_product(
        name
    )

    params = extract_url_params(
        url
    )

    # ========================================================
    # 数据状态
    # ========================================================

    if size_price_map:
        size_price_status = "available"
    elif re.search(
        r"(?:尺码|鞋码).{0,100}[¥￥]",
        detail_text,
    ):
        size_price_status = (
            "page_has_but_not_parsed"
        )
    else:
        size_price_status = "not_available"

    if (
        current_size
        and current_size in size_price_map
    ):
        sku_price_status = "confirmed"
    elif size_price_map:
        sku_price_status = (
            "size_prices_available_but_current_size_unknown"
        )
    else:
        sku_price_status = "unconfirmed"

    # ========================================================
    # 输出
    # ========================================================

    return {
        "name": name,

        "product_code": product_code,

        "color": color,

        "size": current_size,

        "selected_variant": selected_variant,

        "search_key": search_key,

        "shihuo_url": url,

        "goods_id": params["goods_id"],

        "sku_id": params["sku_id"],

        "style_id": params["style_id"],

        "category": category,

        "category_reason": category_reason,

        # SKU 对应买入价
        "buy_price": buy_price,

        "buy_price_type": (
            "sku_size_price"
            if sku_buy_price is not None
            else "product_level_price"
        ),

        # 完整尺码价格表
        "size_price_map": size_price_map,

        "size_price_evidence":
            size_price_evidence,

        "size_price_status":
            size_price_status,

        "sku_price_status":
            sku_price_status,

        # 得物价格
        "dewu_channel_price":
            dewu_channel_price,

        "dewu_display_price":
            dewu_channel_price,

        "trend_current_price":
            trend_current_price,

        "price_current":
            trend_current_price,

        # 7日
        "price_7d_high":
            price_7d_high,

        "price_7d_low":
            price_7d_low,

        "lowest_price":
            price_7d_low,

        "price_7d_extreme_status":
            extreme_status,

        "downside_to_7d_low":
            downside_to_7d_low,

        # 销量
        "sales_30d":
            sales_30d,

        "sales_total":
            sales_total,

        "sales":
            sales_total,

        "sales_velocity_7d":
            sales_velocity_7d,

        "turnover_evidence":
            turnover_evidence,

        "turnover_confidence":
            turnover_confidence,

        # 证据
        "evidence_status": {
            "product_code":
                "available"
                if product_code
                else "not_available",

            "color":
                "available"
                if color
                else "not_available",

            "current_size":
                "available"
                if current_size
                else "not_available",

            "size_price_map":
                size_price_status,

            "sku_price":
                sku_price_status,

            "dewu_channel_price":
                "available"
                if dewu_channel_price
                else "not_available",

            "trend_current_price":
                "available"
                if trend_current_price
                else "not_available",

            "sales_30d":
                "available"
                if sales_30d
                else "not_available",

            "sales_total":
                "available"
                if sales_total
                else "not_available",
        },

        "detail_text":
            raw_text[:30000],

        "observed_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
    }


# ============================================================
# URL
# ============================================================

def collect_urls(page):
    page.goto(
        HOME_URL,
        wait_until="domcontentloaded",
        timeout=10000,
    )

    page.wait_for_timeout(2000)

    links = page.locator(
        "a[href*='pcGoodsDetail']"
    )

    urls = []

    try:
        count = links.count()
    except Exception:
        count = 0

    for i in range(
        min(count, MAX_DETAIL_PAGES)
    ):
        try:
            href = links.nth(i).get_attribute(
                "href"
            )

            if not href:
                continue

            full_url = urljoin(
                HOME_URL,
                href,
            )

            if (
                "pcGoodsDetail" in full_url
                and full_url not in urls
            ):
                urls.append(full_url)

        except Exception:
            continue

    return urls


# ============================================================
# 合并
# ============================================================

def product_key(item):
    # SKU 级别优先
    code = item.get("product_code")
    color = item.get("color")
    size = item.get("size")

    if code and color and size:
        return (
            f"sku|{code}|{color}|{size}"
        )

    if code and color:
        return f"style|{code}|{color}"

    url = item.get("shihuo_url")

    if url:
        return f"url|{url}"

    return f"name|{item.get('name')}"


def merge_products(items):
    result = {}

    for item in items:
        if not valid_name(
            item.get("name")
        ):
            continue

        if item.get("category") == "excluded":
            continue

        if item.get("buy_price") is None:
            continue

        key = product_key(item)

        if key not in result:
            result[key] = item
            continue

        old = result[key]

        # 信息越完整越优先
        fields = [
            "product_code",
            "color",
            "size",
            "size_price_map",
            "dewu_channel_price",
            "trend_current_price",
            "price_7d_low",
            "price_7d_high",
            "sales_30d",
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
# 输出
# ============================================================

def print_item(item):
    print("")
    print("=" * 70)

    print("商品：", item.get("name"))
    print("货号：", item.get("product_code"))
    print("配色：", item.get("color"))
    print("尺码：", item.get("size"))
    print(
        "当前规格：",
        item.get("selected_variant"),
    )

    print(
        "检索键：",
        item.get("search_key"),
    )

    print(
        "识货买入价：",
        item.get("buy_price"),
    )

    print(
        "买入价类型：",
        item.get("buy_price_type"),
    )

    print(
        "尺码价格表：",
        item.get("size_price_map"),
    )

    print(
        "得物渠道售价：",
        item.get("dewu_channel_price"),
    )

    print(
        "当前同款同规格到手价：",
        item.get("trend_current_price"),
    )

    print(
        "7日最高：",
        item.get("price_7d_high"),
    )

    print(
        "7日最低：",
        item.get("price_7d_low"),
    )

    print(
        "月销：",
        item.get("sales_30d"),
    )

    print(
        "周转证据：",
        item.get("turnover_evidence"),
    )

    print(
        "SKU价格状态：",
        item.get("sku_price_status"),
    )

    print(
        "识货链接：",
        item.get("shihuo_url"),
    )


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

        detail_page = browser.new_page(
            viewport=VIEWPORT
        )

        urls = collect_urls(page)

        print(
            f"发现详情页：{len(urls)}"
        )

        for index, url in enumerate(
            urls,
            1,
        ):
            try:
                print(
                    f"\n[{index}/{len(urls)}]"
                )

                item = extract_detail(
                    detail_page,
                    url,
                )

                if not valid_name(
                    item.get("name")
                ):
                    continue

                if item.get("buy_price") is None:
                    print(
                        "跳过：没有价格"
                    )
                    continue

                if item.get("category") == "excluded":
                    print(
                        "过滤：",
                        item.get("name"),
                    )
                    continue

                items.append(item)

                print_item(item)

            except Exception as e:
                print(
                    "采集失败：",
                    repr(e),
                )

            time.sleep(1)

        browser.close()

    products = merge_products(
        items
    )

    output = {
        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "count":
            len(products),

        "products":
            products,
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

    print("")
    print("=" * 70)
    print(
        f"最终商品数：{len(products)}"
    )
    print("=" * 70)

    for item in products[:20]:
        print_item(item)


if __name__ == "__main__":
    main()
