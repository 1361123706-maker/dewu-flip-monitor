import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs

from playwright.sync_api import sync_playwright


HOME_URL = "https://www.shihuo.cn/page/pcHome"
OUTPUT_FILE = "discovery_data.json"
MAX_DETAIL_PAGES = 40

VIEWPORT = {
    "width": 1440,
    "height": 1000,
}


# ============================================================
# 商品范围
# ============================================================

EXCLUDED_KEYWORDS = [
    "黄金", "足金", "金饰", "金首饰", "金戒指", "金手镯",
    "金项链", "金耳环", "贵金属", "铂金", "白金", "18k金",
    "18k", "钻石", "珠宝", "翡翠", "玉石",

    "点券", "充值", "虚拟商品", "虚拟物品", "游戏币",
    "游戏道具", "账号", "帐号", "激活码", "兑换码",
    "cdkey", "代充", "会员充值", "话费充值", "流量充值",

    "白酒", "啤酒", "红酒", "葡萄酒", "洋酒", "威士忌",
    "伏特加", "香槟", "酒水",

    "食品", "零食", "饼干", "糖果", "巧克力", "饮料",
    "牛奶", "咖啡", "茶叶", "茶", "方便面", "火锅底料",
    "调味料",

    "猫粮", "狗粮", "宠物粮", "宠物食品", "猫罐头",
    "狗罐头",

    "药品", "处方药", "非处方药", "otc", "保健品",
    "保健食品", "维生素", "钙片", "鱼油", "蛋白粉",

    "洗衣液", "洗衣粉", "洗洁精", "清洁剂", "纸巾",
    "抽纸", "卫生纸", "垃圾袋", "拖把", "扫把",
    "清洁用品",

    "洗发水", "护发素", "沐浴露", "牙膏", "牙刷", "洁面",
    "洁面乳", "洁面啫喱", "护肤", "面霜", "乳液",
    "化妆品", "口红", "粉底", "眼影", "香水",

    "床单", "被套", "枕头", "被子", "锅", "炒锅", "水杯",
    "保温杯", "餐具", "垃圾桶",
]


TARGET_KEYWORDS = [
    "鞋", "球鞋", "运动鞋", "跑鞋", "篮球鞋", "足球鞋",
    "训练鞋", "板鞋", "休闲鞋", "靴",

    "卫衣", "外套", "夹克", "羽绒服", "冲锋衣", "风衣",
    "棉服", "大衣", "T恤", "短袖", "长袖", "衬衫", "裤",
    "牛仔裤", "运动裤", "短裤", "裙", "服装", "衣",

    "包", "背包", "双肩包", "斜挎包", "腰包", "托特包",
    "手提包", "旅行包",

    "手表", "腕表", "电子表", "机械表",

    "帽", "棒球帽", "渔夫帽", "围巾", "手套", "腰带",
    "皮带", "墨镜", "太阳镜", "眼镜",

    "篮球", "足球", "网球拍", "羽毛球拍", "运动装备",
    "运动器材", "瑜伽垫", "滑板", "护具",

    "潮玩", "盲盒", "手办", "积木", "玩具",

    "耳机", "蓝牙耳机", "头戴式耳机", "耳塞", "游戏机",
    "掌机", "相机", "镜头", "数码相机",
]


# ============================================================
# 基础工具
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

    return text.strip() or None


def normalize_price(value, unit=None):
    if value is None:
        return None

    try:
        text = str(value).strip()
        text = text.replace(",", "")
        text = text.replace("¥", "")
        text = text.replace("￥", "")
        text = text.replace("元", "")

        number = float(text)

        if unit == "万":
            number *= 10000

        if number <= 0 or number > 1000000:
            return None

        return round(number, 2)

    except Exception:
        return None


def price_from_match(match):
    if not match:
        return None

    value = match.group(1)

    try:
        unit = match.group(2)
    except Exception:
        unit = None

    return normalize_price(value, unit)


def extract_price(text):
    if not text:
        return None

    patterns = [
        r"[¥￥]\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)\s*元",
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*元",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            price = price_from_match(match)

            if price is not None:
                return price

    return None


def valid_name(name):
    if not name:
        return False

    name = clean_text(name)

    if len(name) < 4:
        return False

    bad_names = {
        "商品",
        "详情",
        "价格",
        "购买",
        "立即购买",
        "加入购物车",
        "未知商品",
    }

    return name not in bad_names


# ============================================================
# 商品分类
# ============================================================

def classify_product(name):
    name = clean_text(name).lower()

    if not name:
        return "unknown", "商品名称为空"

    for keyword in EXCLUDED_KEYWORDS:
        if keyword.lower() in name:
            return (
                "excluded",
                f"命中排除品类关键词：{keyword}",
            )

    for keyword in TARGET_KEYWORDS:
        if keyword.lower() in name:
            return (
                "target",
                f"命中目标商品关键词：{keyword}",
            )

    return (
        "unknown",
        "未命中明确目标品类",
    )


# ============================================================
# 商品名称
# ============================================================

def extract_product_name(text):
    if not text:
        return None

    patterns = [
        r"商品名称[:：]\s*(.+?)(?:。品牌[:：])",
        r"商品名称[:：]\s*(.+?)(?:\s+品牌[:：])",
        r"商品名称[:：]\s*(.+?)(?:\s+货号[:：])",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            name = clean_text(match.group(1))

            if valid_name(name):
                return name

    # 页面没有明确“商品名称”标签时，尝试从 title 获取
    return None


# ============================================================
# 货号
# ============================================================

def extract_product_code(text):
    if not text:
        return None

    patterns = [
        r"(?:商品货号|产品货号|货号|款号|款式号|型号)"
        r"\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_/.]{2,40})",

        r"(?:Style\s*Code|Style\s*ID|Item\s*Code)"
        r"\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_/.]{2,40})",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if not match:
            continue

        value = clean_line(match.group(1))

        if value:
            return value

    return None


# ============================================================
# 配色
# ============================================================

def extract_color(text):
    if not text:
        return None

    patterns = [
        r"(?:商品配色|商品颜色|配色|颜色分类|颜色)"
        r"\s*[:：]\s*([^，,。；;\n]{1,80})",

        r"(?:可选配色|可选颜色)"
        r"\s*[:：]?\s*([^，,。；;\n]{1,80})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if not match:
            continue

        value = clean_line(match.group(1))

        if value:
            return value

    return None


# ============================================================
# 尺码
# ============================================================

def extract_size(text):
    """
    只提取明确出现的尺码信息。

    重要：
    不根据标题里的孤立数字猜尺码。
    不把年份、货号、价格、销量等数字误判为尺码。

    优先识别：
    当前尺码 / 已选尺码 / 选择尺码 / 尺码 / 鞋码 / 当前规格
    """

    if not text:
        return None

    patterns = [
        r"(?:当前尺码|已选尺码|选择尺码|选中尺码|当前鞋码)"
        r"\s*[:：]?\s*([A-Za-z0-9./\-½]{1,12})",

        r"(?:鞋码|尺码|尺寸)"
        r"\s*[:：]\s*([A-Za-z0-9./\-½]{1,12})",

        r"(?:当前规格|已选规格|选择规格|选中规格)"
        r"\s*[:：]?\s*([^，,。；;\n]{1,30})",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if not match:
            continue

        value = clean_line(match.group(1))

        if not value:
            continue

        # 防止把明显不是尺码的文字当尺码
        bad_values = {
            "信息",
            "商品",
            "价格",
            "详情",
            "颜色",
            "配色",
            "请选择",
            "未选择",
        }

        if value in bad_values:
            continue

        return value

    return None


# ============================================================
# 当前 SKU / 规格
# ============================================================

def extract_selected_variant(text):
    """
    尝试得到当前实际参与价格计算的规格。

    例如：
    乳白色/森林绿, 38
    黑色, 42
    """

    if not text:
        return None

    color = extract_color(text)
    size = extract_size(text)

    if color and size:
        return f"{color} | {size}"

    if color:
        return color

    if size:
        return size

    # 识货页面有时直接出现：
    # 当前同款同规格到手价
    # 这里不猜具体 SKU，只记录无法明确定位
    return None


# ============================================================
# 检索键
# ============================================================

def build_search_key(
    name,
    product_code,
    color,
    size,
):
    parts = []

    if name:
        parts.append(str(name))

    if product_code:
        parts.append(f"货号 {product_code}")

    if color:
        parts.append(f"配色 {color}")

    if size:
        parts.append(f"尺码 {size}")
    else:
        parts.append("尺码 未明确")

    return " | ".join(parts)


# ============================================================
# 当前同款同规格到手价
# ============================================================

def extract_trend_current_price(text):
    if not text:
        return None

    patterns = [
        r"当前同款同规格到手价为\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",

        r"当前同款同规格到手价为\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?\s*元",

        r"当前(?:同款同规格)?到手价为\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",

        r"当前(?:同款同规格)?到手价为\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?\s*元",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            price = price_from_match(match)

            if price is not None:
                return price

    return None


# ============================================================
# 得物渠道售价
# ============================================================

def extract_dewu_price(text):
    if not text:
        return None

    patterns = [
        r"得物渠道售价\s*[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?\s*元?",

        r"得物渠道售价为\s*[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?\s*元?",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            price = price_from_match(match)

            if price is not None:
                return price

    return None


# ============================================================
# 7日最高 / 最低
# ============================================================

def extract_7d_prices(text):
    if not text:
        return None, None

    high = None
    low = None

    high_patterns = [
        r"(?:过去|近|最近)\s*7\s*(?:天|日)"
        r"[^。；\n]{0,100}"
        r"(?:最高价|最高)"
        r"[^¥￥0-9]{0,30}"
        r"[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",

        r"(?:7日|7天)"
        r"[^。；\n]{0,80}"
        r"(?:最高价|最高)"
        r"[^¥￥0-9]{0,30}"
        r"[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",
    ]

    low_patterns = [
        r"(?:过去|近|最近)\s*7\s*(?:天|日)"
        r"[^。；\n]{0,100}"
        r"(?:最低价|最低)"
        r"[^¥￥0-9]{0,30}"
        r"[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",

        r"(?:7日|7天)"
        r"[^。；\n]{0,80}"
        r"(?:最低价|最低)"
        r"[^¥￥0-9]{0,30}"
        r"[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",
    ]

    for pattern in high_patterns:
        match = re.search(pattern, text)

        if match:
            high = price_from_match(match)

            if high is not None:
                break

    for pattern in low_patterns:
        match = re.search(pattern, text)

        if match:
            low = price_from_match(match)

            if low is not None:
                break

    if high is not None and low is not None:
        if high < low:
            return None, None

    return high, low


# ============================================================
# 识货 AI 摘要中的 7 日最高 / 最低
# ============================================================

def extract_7d_extreme_status(text):
    """
    识货常见表达：

    当前同款同规格到手价为¥530，
    是过去7天内监测到的最高价

    或：

    当前同款同规格到手价为¥530，
    是过去7天内监测到的最低价
    """

    if not text:
        return None

    if re.search(
        r"过去\s*7\s*天.*?(?:最高价|最高)",
        text,
        re.S,
    ):
        return "current_is_7d_high"

    if re.search(
        r"过去\s*7\s*天.*?(?:最低价|最低)",
        text,
        re.S,
    ):
        return "current_is_7d_low"

    if re.search(
        r"近\s*7\s*(?:天|日).*?(?:最高价|最高)",
        text,
        re.S,
    ):
        return "current_is_7d_high"

    if re.search(
        r"近\s*7\s*(?:天|日).*?(?:最低价|最低)",
        text,
        re.S,
    ):
        return "current_is_7d_low"

    return None


# ============================================================
# 价格位置
# ============================================================

def extract_price_position(
    current,
    high,
    low,
):
    if current is None or high is None or low is None:
        return None

    if high <= low:
        return None

    value = (
        (current - low)
        / (high - low)
        * 100
    )

    return round(
        max(0, min(100, value)),
        2,
    )


def extract_downside_to_low(
    current,
    low,
):
    if current is None or low is None:
        return None

    if current <= 0:
        return None

    value = (
        (current - low)
        / current
        * 100
    )

    return round(
        max(0, value),
        2,
    )


# ============================================================
# 销量
# ============================================================

def extract_month_sales(text):
    if not text:
        return None

    patterns = [
        r"(?:月销|月销量)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?\+?",

        r"(?:近30天销量|近30日销量)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?\+?",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if not match:
            continue

        try:
            value = float(match.group(1))
        except Exception:
            continue

        if match.group(2) == "万":
            value *= 10000

        if value > 0:
            return value

    return None


def extract_total_sales(text):
    if not text:
        return None

    patterns = [
        r"(?:全网销量|总销|总销量|累计销量)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?\+?",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if not match:
            continue

        try:
            value = float(match.group(1))
        except Exception:
            continue

        if match.group(2) == "万":
            value *= 10000

        if value > 0:
            return value

    return None


def calculate_turnover(
    sales_30d,
    sales_total,
):
    if sales_30d is not None and sales_30d > 0:
        return {
            "sales_velocity_7d": round(
                sales_30d / 30,
                2,
            ),
            "turnover_evidence": (
                f"近30日/月销 {sales_30d:g}，"
                f"折算日均约 {sales_30d / 30:.2f}"
            ),
            "turnover_confidence": "medium",
        }

    if sales_total is not None and sales_total > 0:
        return {
            "sales_velocity_7d": None,
            "turnover_evidence": (
                f"累计/全网销量 {sales_total:g}，"
                f"不能直接换算周转速度"
            ),
            "turnover_confidence": "low",
        }

    return {
        "sales_velocity_7d": None,
        "turnover_evidence": None,
        "turnover_confidence": "unknown",
    }


# ============================================================
# 价格趋势
# ============================================================

def extract_price_trend(text):
    if not text:
        return None

    if re.search(
        r"价格.{0,30}下跌",
        text,
    ):
        return "下跌"

    if re.search(
        r"价格.{0,30}上涨",
        text,
    ):
        return "上涨"

    if re.search(
        r"价格.{0,30}(稳定|平稳)",
        text,
    ):
        return "稳定"

    return None


def extract_price_changes(text):
    result = {
        "price_change_1d": None,
        "price_change_7d": None,
        "price_change_30d": None,
    }

    if not text:
        return result

    periods = [
        ("1d", 1),
        ("7d", 7),
        ("30d", 30),
    ]

    for key, days in periods:
        pattern = (
            rf"(?:近|过去|最近)\s*{days}\s*"
            rf"(?:天|日)"
            rf"[^。；\n]{{0,50}}"
            rf"(上涨|下跌)\s*"
            rf"([0-9]+(?:\.[0-9]+)?)\s*%"
        )

        match = re.search(
            pattern,
            text,
        )

        if not match:
            continue

        try:
            value = float(match.group(2))
        except Exception:
            continue

        if match.group(1) == "下跌":
            value = -value

        result[f"price_change_{key}"] = value

    return result


# ============================================================
# 商品 URL / SKU 参数
# ============================================================

def extract_url_params(url):
    result = {
        "goods_id": None,
        "sku_id": None,
        "style_id": None,
    }

    if not url:
        return result

    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        for key in result:
            values = params.get(key)

            if values:
                result[key] = values[0]

    except Exception:
        pass

    return result


# ============================================================
# 数据状态
# ============================================================

def field_status(
    value,
    detail_text,
    keywords=None,
):
    """
    区分：

    available:
        已经成功解析。

    page_has_but_not_parsed:
        页面文本里存在相关证据，但当前字段没有成功解析。

    not_available:
        当前页面没有发现对应证据。
    """

    if value is not None and value != "":
        return "available"

    if keywords and detail_text:
        for keyword in keywords:
            if keyword in detail_text:
                return "page_has_but_not_parsed"

    return "not_available"


# ============================================================
# 商品唯一键
# ============================================================

def product_key(item):
    url = item.get("shihuo_url")

    if url:
        return f"url:{url}"

    product_code = item.get("product_code")
    color = item.get("color")
    size = item.get("size")

    if product_code:
        return (
            f"sku:{product_code}|"
            f"{color}|"
            f"{size}"
        )

    return f"name:{item.get('name')}"


# ============================================================
# 商品详情
# ============================================================

def extract_detail(
    page,
    url,
):
    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(2500)

    detail_text = clean_text(
        page.locator("body").inner_text()
    )

    # --------------------------------------------------------
    # 基础字段
    # --------------------------------------------------------

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

    size = extract_size(
        detail_text
    )

    selected_variant = extract_selected_variant(
        detail_text
    )

    search_key = build_search_key(
        name,
        product_code,
        color,
        size,
    )

    # --------------------------------------------------------
    # URL 参数
    # --------------------------------------------------------

    url_params = extract_url_params(
        url
    )

    # --------------------------------------------------------
    # 买入价格
    # --------------------------------------------------------

    buy_price = None

    price_info_match = re.search(
        r"全网价格区间[:：]\s*"
        r"[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"\s*(万)?"
        r"\s*元?\s*-\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"\s*(万)?",

        detail_text,
    )

    if price_info_match:
        buy_price = normalize_price(
            price_info_match.group(1),
            price_info_match.group(2),
        )

    if buy_price is None:
        buy_price = extract_price(
            detail_text
        )

    # --------------------------------------------------------
    # 得物价格
    # --------------------------------------------------------

    dewu_channel_price = extract_dewu_price(
        detail_text
    )

    trend_current_price = extract_trend_current_price(
        detail_text
    )

    # --------------------------------------------------------
    # 7日价格
    # --------------------------------------------------------

    price_7d_high, price_7d_low = extract_7d_prices(
        detail_text
    )

    price_7d_extreme_status = (
        extract_7d_extreme_status(
            detail_text
        )
    )

    # 如果识货 AI 明确说：
    # 当前价格就是过去7天最低/最高
    # 那么当前价格本身就是对应极值。
    if (
        trend_current_price is not None
        and price_7d_extreme_status
        == "current_is_7d_low"
    ):
        price_7d_low = trend_current_price

    if (
        trend_current_price is not None
        and price_7d_extreme_status
        == "current_is_7d_high"
    ):
        price_7d_high = trend_current_price

    # --------------------------------------------------------
    # 销量
    # --------------------------------------------------------

    sales_30d = extract_month_sales(
        detail_text
    )

    sales_total = extract_total_sales(
        detail_text
    )

    turnover = calculate_turnover(
        sales_30d,
        sales_total,
    )

    # --------------------------------------------------------
    # 价格位置 / 下跌风险
    # --------------------------------------------------------

    price_position_7d = extract_price_position(
        trend_current_price,
        price_7d_high,
        price_7d_low,
    )

    downside_to_7d_low = extract_downside_to_low(
        trend_current_price,
        price_7d_low,
    )

    changes = extract_price_changes(
        detail_text
    )

    price_trend = extract_price_trend(
        detail_text
    )

    # --------------------------------------------------------
    # 分类
    # --------------------------------------------------------

    category, category_reason = classify_product(
        name
    )

    # --------------------------------------------------------
    # 数据状态
    # --------------------------------------------------------

    evidence_status = {
        "product_code": field_status(
            product_code,
            detail_text,
            [
                "货号",
                "款号",
                "商品货号",
                "产品货号",
            ],
        ),

        "color": field_status(
            color,
            detail_text,
            [
                "配色",
                "颜色",
                "商品配色",
                "颜色分类",
            ],
        ),

        "size": field_status(
            size,
            detail_text,
            [
                "尺码",
                "鞋码",
                "当前尺码",
                "当前规格",
            ],
        ),

        "trend_current_price": field_status(
            trend_current_price,
            detail_text,
            [
                "当前同款同规格到手价",
            ],
        ),

        "price_7d_high": field_status(
            price_7d_high,
            detail_text,
            [
                "7天",
                "7日",
                "最高价",
                "最高",
            ],
        ),

        "price_7d_low": field_status(
            price_7d_low,
            detail_text,
            [
                "7天",
                "7日",
                "最低价",
                "最低",
            ],
        ),

        "sales_30d": field_status(
            sales_30d,
            detail_text,
            [
                "月销",
                "月销量",
                "近30天销量",
                "近30日销量",
            ],
        ),

        "sales_total": field_status(
            sales_total,
            detail_text,
            [
                "总销",
                "总销量",
                "累计销量",
                "全网销量",
            ],
        ),
    }

    return {
        # ----------------------------------------------------
        # 商品定位
        # ----------------------------------------------------

        "name": name,

        "product_code": product_code,

        "color": color,

        "size": size,

        "selected_variant": selected_variant,

        "search_key": search_key,

        # ----------------------------------------------------
        # URL / SKU
        # ----------------------------------------------------

        "shihuo_url": url,

        "goods_id": url_params["goods_id"],

        "sku_id": url_params["sku_id"],

        "style_id": url_params["style_id"],

        # ----------------------------------------------------
        # 分类
        # ----------------------------------------------------

        "category": category,

        "category_reason": category_reason,

        # ----------------------------------------------------
        # 买入价格
        # ----------------------------------------------------

        "buy_price": buy_price,

        # ----------------------------------------------------
        # 得物价格
        # ----------------------------------------------------

        "dewu_display_price": dewu_channel_price,

        "dewu_channel_price": dewu_channel_price,

        "trend_current_price": trend_current_price,

        "price_current": trend_current_price,

        # ----------------------------------------------------
        # 7日价格
        # ----------------------------------------------------

        "price_7d_high": price_7d_high,

        "price_7d_low": price_7d_low,

        "lowest_price": price_7d_low,

        "price_7d_extreme_status":
            price_7d_extreme_status,

        "price_position_7d":
            price_position_7d,

        "downside_to_7d_low":
            downside_to_7d_low,

        # ----------------------------------------------------
        # 销量
        # ----------------------------------------------------

        "sales": sales_total,

        "sales_total": sales_total,

        "sales_7d": None,

        "sales_30d": sales_30d,

        "sales_velocity_7d":
            turnover["sales_velocity_7d"],

        "turnover_evidence":
            turnover["turnover_evidence"],

        "turnover_confidence":
            turnover["turnover_confidence"],

        # ----------------------------------------------------
        # 趋势
        # ----------------------------------------------------

        "price_change_1d":
            changes["price_change_1d"],

        "price_change_7d":
            changes["price_change_7d"],

        "price_change_30d":
            changes["price_change_30d"],

        "price_trend":
            price_trend,

        # ----------------------------------------------------
        # 数据状态
        # ----------------------------------------------------

        "evidence_status":
            evidence_status,

        # ----------------------------------------------------
        # 原始页面证据
        # ----------------------------------------------------

        "detail_text":
            detail_text[:20000],

        # ----------------------------------------------------
        # 时间
        # ----------------------------------------------------

        "observed_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
    }


# ============================================================
# 收集商品详情 URL
# ============================================================

def collect_urls(page):
    page.goto(
        HOME_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(4000)

    locator = page.locator(
        "a[href*='pcGoodsDetail']"
    )

    urls = []

    try:
        count = locator.count()
    except Exception:
        count = 0

    for i in range(
        min(count, MAX_DETAIL_PAGES)
    ):
        try:
            href = (
                locator
                .nth(i)
                .get_attribute("href")
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
            pass

    return urls


# ============================================================
# 合并商品
# ============================================================

def merge_products(items):
    result = {}

    for item in items:

        if not valid_name(
            item.get("name")
        ):
            continue

        if item.get("buy_price") is None:
            continue

        # 明确排除品类
        if item.get("category") == "excluded":
            print(
                "过滤商品：",
                item.get("name"),
                "|",
                item.get("category_reason"),
            )
            continue

        key = product_key(item)

        if key not in result:
            result[key] = item
            continue

        # 如果同一个商品出现多次，
        # 优先保留 SKU 定位信息更完整的一条。
        old = result[key]

        old_score = sum(
            1
            for field in [
                "product_code",
                "color",
                "size",
                "dewu_channel_price",
                "trend_current_price",
                "price_7d_low",
                "price_7d_high",
                "sales_30d",
            ]
            if old.get(field) is not None
        )

        new_score = sum(
            1
            for field in [
                "product_code",
                "color",
                "size",
                "dewu_channel_price",
                "trend_current_price",
                "price_7d_low",
                "price_7d_high",
                "sales_30d",
            ]
            if item.get(field) is not None
        )

        if new_score > old_score:
            result[key] = item

    return list(result.values())


# ============================================================
# 打印商品
# ============================================================

def print_item(item):
    print("")
    print("=" * 60)

    print(
        f"商品：{item.get('name')}"
    )

    print(
        f"货号：{item.get('product_code')}"
    )

    print(
        f"配色：{item.get('color')}"
    )

    print(
        f"尺码：{item.get('size')}"
    )

    print(
        f"当前规格：{item.get('selected_variant')}"
    )

    print(
        f"检索键：{item.get('search_key')}"
    )

    print(
        f"识货链接：{item.get('shihuo_url')}"
    )

    print(
        f"买入价：{item.get('buy_price')}"
    )

    print(
        f"得物渠道售价："
        f"{item.get('dewu_channel_price')}"
    )

    print(
        f"当前同款同规格到手价："
        f"{item.get('trend_current_price')}"
    )

    print(
        f"7日最高："
        f"{item.get('price_7d_high')}"
    )

    print(
        f"7日最低："
        f"{item.get('price_7d_low')}"
    )

    print(
        f"7日极值证据："
        f"{item.get('price_7d_extreme_status')}"
    )

    print(
        f"月销："
        f"{item.get('sales_30d')}"
    )

    print(
        f"累计/全网销量："
        f"{item.get('sales_total')}"
    )

    print(
        f"周转证据："
        f"{item.get('turnover_evidence')}"
    )

    print(
        f"价格趋势："
        f"{item.get('price_trend')}"
    )

    print(
        f"下跌至7日低点幅度："
        f"{item.get('downside_to_7d_low')}"
    )

    print(
        f"数据状态："
        f"{item.get('evidence_status')}"
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
                    print(
                        "跳过：没有有效商品名称"
                    )
                    continue

                if item.get("buy_price") is None:
                    print(
                        "跳过：没有有效买入价"
                    )
                    continue

                if item.get("category") == "excluded":
                    print(
                        "过滤：",
                        item.get("name"),
                        "|",
                        item.get(
                            "category_reason"
                        ),
                    )
                    continue

                items.append(item)

                print_item(item)

            except Exception as e:

                print(
                    f"采集失败：{e}"
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
    print("=" * 60)
    print(
        f"最终有效商品数：{len(products)}"
    )
    print("=" * 60)

    for item in products[:20]:
        print_item(item)


if __name__ == "__main__":
    main()
