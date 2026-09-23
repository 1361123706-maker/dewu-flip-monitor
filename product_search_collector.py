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

    text = str(text)

    text = text.replace(
        "\u00a0",
        " ",
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def clean_line(text):
    if not text:
        return None

    text = clean_text(text)

    text = re.sub(
        r"^[：:、\-\s]+",
        "",
        text,
    )

    text = re.sub(
        r"[：:、\-\s]+$",
        "",
        text,
    )

    return text or None


def normalize_price(
    value,
    unit=None,
):
    try:
        value = str(
            value
        )

        value = value.replace(
            ",",
            "",
        )

        value = value.replace(
            "¥",
            "",
        )

        value = value.replace(
            "￥",
            "",
        )

        value = value.replace(
            "元",
            "",
        )

        value = value.strip()

        number = float(
            value
        )

        if unit == "万":
            number *= 10000

        if (
            number <= 0
            or number > 1000000
        ):
            return None

        return round(
            number,
            2,
        )

    except Exception:
        return None


def valid_name(name):

    if not name:
        return False

    name = clean_text(
        name
    )

    return (
        len(name) >= 4
        and name not in {
            "商品",
            "详情",
            "价格",
            "购买",
            "立即购买",
            "加入购物车",
            "未知商品",
        }
    )


def classify_product(name):

    text = clean_text(
        name
    ).lower()

    if not text:
        return (
            "unknown",
            "商品名称为空",
        )

    for word in EXCLUDED_KEYWORDS:

        if word.lower() in text:

            return (
                "excluded",
                f"命中排除关键词：{word}",
            )

    for word in TARGET_KEYWORDS:

        if word.lower() in text:

            return (
                "target",
                f"命中目标关键词：{word}",
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

        match = re.search(
            pattern,
            text,
        )

        if not match:
            continue

        name = clean_text(
            match.group(1)
        )

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


# ============================================================
# 配色
# ============================================================

def extract_color(text):

    if not text:
        return None

    patterns = [

        # 例如：
        # 黑色/白色, 36
        r"([^\s,，]{1,30}"
        r"(?:/[^\s,，]{1,30})+)"
        r"\s*,\s*"
        r"[0-9A-Za-z./\-½⅓⅔]+",

        r"(?:当前配色|当前颜色|已选配色|已选颜色)"
        r"\s*[:：]?\s*"
        r"([^，,。；;]{1,60})",

        r"(?:商品配色|商品颜色)"
        r"\s*[:：]\s*"
        r"([^，,。；;]{1,60})",
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
            "可选配色",
            "可选尺码",
            "颜色",
            "尺码",
            "货号",
            "品牌",
            "商品名称",
            "价格信息",
        }:
            continue

        return value

    return None


# ============================================================
# 当前尺码
# ============================================================

def extract_current_size(text):

    if not text:
        return None

    patterns = [

        # 黑色/白色, 36
        r"[^\s,，]{1,30}"
        r"(?:/[^\s,，]{1,30})+"
        r"\s*,\s*"
        r"([0-9A-Za-z./\-½⅓⅔]+)",

        r"(?:当前尺码|已选尺码|选中尺码|当前鞋码)"
        r"\s*[:：]?\s*"
        r"([A-Za-z0-9./\-½⅓⅔]{1,12})",

        r"(?:当前规格|已选规格|选中规格)"
        r"\s*[:：]?"
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
# 尺码标准化
# ============================================================

def normalize_size_key(size):

    if size is None:
        return None

    text = str(
        size
    ).strip()

    text = text.replace(
        " ",
        "",
    )

    return text


# ============================================================
# 尺码 -> 识货价格
# ============================================================

def extract_size_price_map(text):

    result = {}

    if not text:
        return result

    # 支持：
    # 35½ ¥460
    # 36 ¥460
    # 36⅔ ¥430
    # 37⅓ ¥460
    # 38 ¥470
    # 38.5 ¥400
    #
    # 同时允许：
    # 36: ¥460
    # 36 ￥460

    patterns = [

        r"(?<![A-Za-z0-9])"
        r"("
        r"\d{2}(?:½|⅓|⅔)?"
        r"|"
        r"\d{1,2}(?:\.\d+)?"
        r")"
        r"\s*"
        r"[：:]?"
        r"\s*"
        r"[¥￥]"
        r"\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)",

        r"(?<![A-Za-z0-9])"
        r"("
        r"\d{2}(?:½|⅓|⅔)?"
        r")"
        r"\s+"
        r"[¥￥]"
        r"\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            text,
        ):

            size = normalize_size_key(
                match.group(1)
            )

            price = normalize_price(
                match.group(2)
            )

            if (
                not size
                or price is None
            ):
                continue

            # 判断是否像鞋码
            numeric_text = (
                size
                .replace(
                    "½",
                    ".5",
                )
                .replace(
                    "⅓",
                    ".33",
                )
                .replace(
                    "⅔",
                    ".67",
                )
            )

            try:
                numeric = float(
                    numeric_text
                )
            except Exception:
                continue

            if (
                numeric < 20
                or numeric > 60
            ):
                continue

            result[size] = price

    return result


def extract_size_price_evidence(text):

    size_prices = (
        extract_size_price_map(
            text
        )
    )

    if not size_prices:
        return None

    return "; ".join(
        f"{size}码 ¥{price:g}"
        for size, price
        in size_prices.items()
    )


# ============================================================
# 得物渠道售价
# ============================================================

def extract_dewu_price(text):

    if not text:
        return None

    patterns = [

        r"得物渠道售价"
        r"\s*[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"\s*(万)?",

        r"得物渠道售价为"
        r"\s*[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"\s*(万)?",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
        )

        if not match:
            continue

        return normalize_price(
            match.group(1),
            match.group(2),
        )

    return None


# ============================================================
# 当前同款同规格到手价
# ============================================================

def extract_trend_current_price(text):

    if not text:
        return None

    patterns = [

        r"当前同款同规格到手价为"
        r"\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)",

        r"当前同款同规格到手价为"
        r"\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"\s*元",

        r"当前(?:同款同规格)?到手价为"
        r"\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
        )

        if not match:
            continue

        return normalize_price(
            match.group(1)
        )

    return None


# ============================================================
# 7日价格
# ============================================================

def extract_7d_extreme_status(text):

    if not text:
        return None

    if re.search(
        r"(?:过去|近|最近)\s*7\s*天"
        r".*?"
        r"(?:最高价|最高)",
        text,
        re.S,
    ):
        return (
            "current_is_7d_high"
        )

    if re.search(
        r"(?:过去|近|最近)\s*7\s*天"
        r".*?"
        r"(?:最低价|最低)",
        text,
        re.S,
    ):
        return (
            "current_is_7d_low"
        )

    return None


def extract_7d_prices(text):

    high = None
    low = None

    patterns_high = [
        r"(?:7天|7日|过去7天|近7天)"
        r".{0,100}?"
        r"(?:最高价|最高)"
        r".{0,20}?"
        r"[¥￥]\s*"
        r"(\d+(?:\.\d+)?)",
    ]

    patterns_low = [
        r"(?:7天|7日|过去7天|近7天)"
        r".{0,100}?"
        r"(?:最低价|最低)"
        r".{0,20}?"
        r"[¥￥]\s*"
        r"(\d+(?:\.\d+)?)",
    ]

    for pattern in patterns_high:

        match = re.search(
            pattern,
            text,
            re.S,
        )

        if match:

            high = normalize_price(
                match.group(1)
            )

            break

    for pattern in patterns_low:

        match = re.search(
            pattern,
            text,
            re.S,
        )

        if match:

            low = normalize_price(
                match.group(1)
            )

            break

    return (
        high,
        low,
    )


# ============================================================
# 价格走势周期
# ============================================================

def extract_trend_periods(text):

    periods = []

    if not text:
        return periods

    for period in (
        "7天",
        "30天",
        "60天",
        "180天",
    ):

        if period in text:

            periods.append(
                period
            )

    return periods


# ============================================================
# 销量
# ============================================================

def extract_month_sales(text):

    if not text:
        return None

    patterns = [

        r"(?:月销|月销量)\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*(万)?",

        r"(?:近30天销量|近30日销量)\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*(万)?",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
        )

        if not match:
            continue

        value = float(
            match.group(1)
        )

        if match.group(2) == "万":
            value *= 10000

        return value

    return None


def extract_total_sales(text):

    if not text:
        return None

    pattern = (
        r"(?:全网销量|总销|总销量|累计销量)"
        r"\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*(万)?"
    )

    match = re.search(
        pattern,
        text,
    )

    if not match:
        return None

    value = float(
        match.group(1)
    )

    if match.group(2) == "万":
        value *= 10000

    return value


# ============================================================
# URL 参数
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

            values = params.get(
                key
            )

            if values:
                result[key] = (
                    values[0]
                )

    except Exception:
        pass

    return result


# ============================================================
# 详情页
# ============================================================

def extract_detail(
    page,
    url,
):

    try:

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=10000,
        )

    except Exception as e:

        print(
            "详情页打开失败：",
            repr(e),
            flush=True,
        )

        return None

    try:

        page.wait_for_timeout(
            1000
        )

    except Exception:
        pass

    try:

        raw_text = (
            page.locator(
                "body"
            ).inner_text(
                timeout=5000
            )
        )

    except Exception as e:

        print(
            "读取详情页正文失败：",
            repr(e),
            flush=True,
        )

        return None

    detail_text = clean_text(
        raw_text
    )

    name = extract_product_name(
        detail_text
    )

    if not name:

        try:

            title = clean_text(
                page.title()
            )

        except Exception:

            title = None

        if valid_name(title):
            name = title

    product_code = (
        extract_product_code(
            detail_text
        )
    )

    color = extract_color(
        detail_text
    )

    current_size = (
        extract_current_size(
            detail_text
        )
    )

    # ========================================================
    # SKU 尺码价格
    # ========================================================

    size_price_map = (
        extract_size_price_map(
            detail_text
        )
    )

    size_price_evidence = (
        extract_size_price_evidence(
            detail_text
        )
    )

    current_size_key = (
        normalize_size_key(
            current_size
        )
    )

    sku_buy_price = None

    if (
        current_size_key
        and current_size_key
        in size_price_map
    ):

        sku_buy_price = (
            size_price_map[
                current_size_key
            ]
        )

    # ========================================================
    # 得物价格
    # ========================================================

    dewu_channel_price = (
        extract_dewu_price(
            detail_text
        )
    )

    trend_current_price = (
        extract_trend_current_price(
            detail_text
        )
    )

    price_7d_high, price_7d_low = (
        extract_7d_prices(
            detail_text
        )
    )

    extreme_status = (
        extract_7d_extreme_status(
            detail_text
        )
    )

    if (
        trend_current_price
        is not None
        and extreme_status
        == "current_is_7d_high"
    ):

        price_7d_high = (
            trend_current_price
        )

    if (
        trend_current_price
        is not None
        and extreme_status
        == "current_is_7d_low"
    ):

        price_7d_low = (
            trend_current_price
        )

    trend_periods = (
        extract_trend_periods(
            detail_text
        )
    )

    # ========================================================
    # 商品级买入价
    # ========================================================

    buy_price = sku_buy_price

    buy_price_type = (
        "sku_size_price"
        if sku_buy_price
        is not None
        else None
    )

    # 如果没有当前尺码价格，
    # 不用其他尺码价格冒充当前尺码。
    #
    # 但保留商品级价格作为桥接层兜底，
    # 后面的 monitor 会因为存在 size_price_map
    # 而要求具体尺码，不会拿这个价格冒充 SKU。

    if buy_price is None:

        generic_patterns = [

            r"全网价格区间[:：]"
            r"\s*[¥￥]?\s*"
            r"(\d+(?:\.\d+)?)",

            r"到手价[:：]"
            r"\s*[¥￥]?\s*"
            r"(\d+(?:\.\d+)?)",
        ]

        for pattern in generic_patterns:

            match = re.search(
                pattern,
                detail_text,
            )

            if not match:
                continue

            candidate = (
                normalize_price(
                    match.group(1)
                )
            )

            if candidate is not None:

                buy_price = candidate

                buy_price_type = (
                    "product_level_price"
                )

                break

    # ========================================================
    # 销量
    # ========================================================

    sales_30d = (
        extract_month_sales(
            detail_text
        )
    )

    sales_total = (
        extract_total_sales(
            detail_text
        )
    )

    # ========================================================
    # 周转
    # ========================================================

    if (
        sales_30d is not None
        and sales_30d > 0
    ):

        turnover_evidence = (
            f"月销 {sales_30d:g}，"
            f"日均约 "
            f"{sales_30d / 30:.2f}"
        )

        turnover_confidence = (
            "medium"
        )

        sales_velocity_7d = round(
            sales_30d / 30,
            2,
        )

    elif (
        sales_total is not None
        and sales_total > 0
    ):

        turnover_evidence = (
            f"累计/全网销量 "
            f"{sales_total:g}，"
            f"不能直接换算周转速度"
        )

        turnover_confidence = (
            "low"
        )

        sales_velocity_7d = None

    else:

        turnover_evidence = None

        turnover_confidence = (
            "unknown"
        )

        sales_velocity_7d = None

    # ========================================================
    # 下跌风险
    # ========================================================

    downside_to_7d_low = None

    if (
        trend_current_price
        is not None
        and price_7d_low
        is not None
        and trend_current_price > 0
        and price_7d_low
        <= trend_current_price
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
    # 当前规格
    # ========================================================

    if color and current_size:

        selected_variant = (
            f"{color}, {current_size}"
        )

    elif color:

        selected_variant = color

    elif current_size:

        selected_variant = (
            current_size
        )

    else:

        selected_variant = None

    # ========================================================
    # 商品分类
    # ========================================================

    category, category_reason = (
        classify_product(
            name
        )
    )

    params = extract_url_params(
        url
    )

    # ========================================================
    # SKU 状态
    # ========================================================

    if size_price_map:

        size_price_status = (
            "available"
        )

    elif re.search(
        r"(?:尺码|鞋码)"
        r".{0,100}"
        r"[¥￥]",
        detail_text,
        re.S,
    ):

        size_price_status = (
            "page_has_but_not_parsed"
        )

    else:

        size_price_status = (
            "not_available"
        )

    if (
        current_size_key
        and current_size_key
        in size_price_map
    ):

        sku_price_status = (
            "current_size_confirmed"
        )

    elif size_price_map:

        sku_price_status = (
            "size_prices_available_but_current_size_unknown"
        )

    else:

        sku_price_status = (
            "unconfirmed"
        )

    # ========================================================
    # 数据状态
    # ========================================================

    evidence_status = {

        "product_code":
            (
                "available"
                if product_code
                else "not_available"
            ),

        "color":
            (
                "available"
                if color
                else "not_available"
            ),

        "current_size":
            (
                "available"
                if current_size
                else "not_available"
            ),

        "size_price_map":
            size_price_status,

        "sku_price":
            sku_price_status,

        "dewu_channel_price":
            (
                "available"
                if dewu_channel_price
                is not None
                else "not_available"
            ),

        "trend_current_price":
            (
                "available"
                if trend_current_price
                is not None
                else "not_available"
            ),

        "sales_30d":
            (
                "available"
                if sales_30d
                is not None
                else "not_available"
            ),

        "sales_total":
            (
                "available"
                if sales_total
                is not None
                else "not_available"
            ),
    }

    # ========================================================
    # 检索键
    # ========================================================

    search_parts = [
        str(
            name or ""
        ),
    ]

    if product_code:

        search_parts.append(
            f"货号 {product_code}"
        )

    if color:

        search_parts.append(
            f"配色 {color}"
        )

    if current_size:

        search_parts.append(
            f"尺码 {current_size}"
        )

    search_key = " | ".join(
        search_parts
    )

    # ========================================================
    # 输出
    # ========================================================

    return {

        "name":
            name,

        "product_code":
            product_code,

        "color":
            color,

        "size":
            current_size,

        "current_size":
            current_size,

        "selected_variant":
            selected_variant,

        "search_key":
            search_key,

        "shihuo_url":
            url,

        "goods_id":
            params[
                "goods_id"
            ],

        "sku_id":
            params[
                "sku_id"
            ],

        "style_id":
            params[
                "style_id"
            ],

        "category":
            category,

        "category_reason":
            category_reason,

        # ------------------------------
        # 买入价格
        # ------------------------------

        "buy_price":
            buy_price,

        "buy_price_type":
            buy_price_type,

        # ------------------------------
        # SKU 价格
        # ------------------------------

        "size_price_map":
            size_price_map,

        "size_price_evidence":
            size_price_evidence,

        "size_price_status":
            size_price_status,

        "sku_price_status":
            sku_price_status,

        # ------------------------------
        # 得物
        # ------------------------------

        "dewu_channel_price":
            dewu_channel_price,

        "dewu_display_price":
            dewu_channel_price,

        "trend_current_price":
            trend_current_price,

        "price_current":
            trend_current_price,

        # ------------------------------
        # 7日
        # ------------------------------

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

        # ------------------------------
        # 走势周期
        # ------------------------------

        "trend_periods":
            trend_periods,

        # ------------------------------
        # 销量
        # ------------------------------

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

        # ------------------------------
        # 证据
        # ------------------------------

        "evidence_status":
            evidence_status,

        # ------------------------------
        # 原始页面
        # ------------------------------

        "detail_text":
            raw_text[
                :30000
            ],

        "observed_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
    }


# ============================================================
# 首页 URL
# ============================================================

def collect_urls(page):

    print(
        "开始打开识货首页",
        flush=True,
    )

    try:

        page.goto(
            HOME_URL,
            wait_until="domcontentloaded",
            timeout=15000,
        )

        print(
            "识货首页打开完成",
            flush=True,
        )

    except Exception as e:

        print(
            "识货首页打开超时/失败：",
            repr(e),
            flush=True,
        )

    try:

        page.wait_for_timeout(
            2000
        )

    except Exception:
        pass

    print(
        "开始读取商品链接",
        flush=True,
    )

    urls = []

    try:

        links = page.locator(
            "a[href*='pcGoodsDetail']"
        )

        count = links.count()

    except Exception as e:

        print(
            "读取商品链接失败：",
            repr(e),
            flush=True,
        )

        return []

    print(
        f"发现页面链接：{count}",
        flush=True,
    )

    for i in range(
        min(
            count,
            MAX_DETAIL_PAGES,
        )
    ):

        try:

            href = (
                links.nth(i)
                .get_attribute(
                    "href",
                    timeout=3000,
                )
            )

            if not href:
                continue

            full_url = urljoin(
                HOME_URL,
                href,
            )

            if (
                "pcGoodsDetail"
                not in full_url
            ):
                continue

            if full_url not in urls:

                urls.append(
                    full_url
                )

        except Exception:

            continue

    return urls


# ============================================================
# 合并
# ============================================================

def product_key(item):

    code = item.get(
        "product_code"
    )

    color = item.get(
        "color"
    )

    size = item.get(
        "size"
    )

    if (
        code
        and color
        and size
    ):

        return (
            f"sku|{code}|"
            f"{color}|{size}"
        )

    if (
        code
        and color
    ):

        return (
            f"style|{code}|{color}"
        )

    url = item.get(
        "shihuo_url"
    )

    if url:

        return (
            f"url|{url}"
        )

    return (
        f"name|{item.get('name')}"
    )


def merge_products(items):

    result = {}

    for item in items:

        if not valid_name(
            item.get("name")
        ):
            continue

        if (
            item.get(
                "category"
            )
            == "excluded"
        ):
            continue

        # 注意：
        # 这里不能要求 buy_price 必须存在。
        #
        # 因为：
        # 有完整 size_price_map
        # 但当前尺码没有确认时，
        # 也必须把商品保留下来，
        # 后面的 monitor 会负责过滤。
        #
        # 否则会直接丢掉最重要的 SKU 数据。

        key = product_key(
            item
        )

        if key not in result:

            result[key] = item

            continue

        old = result[key]

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
            "sales_total",
        ]

        old_score = sum(
            bool(
                old.get(field)
            )
            for field in fields
        )

        new_score = sum(
            bool(
                item.get(field)
            )
            for field in fields
        )

        if new_score > old_score:

            result[key] = item

    return list(
        result.values()
    )


# ============================================================
# 打印
# ============================================================

def print_item(item):

    print("")
    print(
        "=" * 70
    )

    print(
        "商品：",
        item.get("name"),
    )

    print(
        "货号：",
        item.get(
            "product_code"
        ),
    )

    print(
        "配色：",
        item.get(
            "color"
        ),
    )

    print(
        "尺码：",
        item.get(
            "size"
        ),
    )

    print(
        "当前规格：",
        item.get(
            "selected_variant"
        ),
    )

    print(
        "识货买入价：",
        item.get(
            "buy_price"
        ),
    )

    print(
        "买入价类型：",
        item.get(
            "buy_price_type"
        ),
    )

    print(
        "尺码价格表：",
        item.get(
            "size_price_map"
        ),
    )

    print(
        "得物渠道售价：",
        item.get(
            "dewu_channel_price"
        ),
    )

    print(
        "当前同款同规格到手价：",
        item.get(
            "trend_current_price"
        ),
    )

    print(
        "7日最高：",
        item.get(
            "price_7d_high"
        ),
    )

    print(
        "7日最低：",
        item.get(
            "price_7d_low"
        ),
    )

    print(
        "价格走势周期：",
        item.get(
            "trend_periods"
        ),
    )

    print(
        "月销：",
        item.get(
            "sales_30d"
        ),
    )

    print(
        "总销量：",
        item.get(
            "sales_total"
        ),
    )

    print(
        "周转证据：",
        item.get(
            "turnover_evidence"
        ),
    )

    print(
        "SKU价格状态：",
        item.get(
            "sku_price_status"
        ),
    )

    print(
        "识货链接：",
        item.get(
            "shihuo_url"
        ),
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

        # 防止普通 locator 操作无限等待
        page.set_default_timeout(
            5000
        )

        detail_page.set_default_timeout(
            5000
        )

        urls = collect_urls(
            page
        )

        print(
            f"发现详情页：{len(urls)}",
            flush=True,
        )

        for index, url in enumerate(
            urls,
            1,
        ):

            try:

                print(
                    f"\n[{index}/{len(urls)}]",
                    flush=True,
                )

                item = extract_detail(
                    detail_page,
                    url,
                )

                if item is None:
                    continue

                if not valid_name(
                    item.get("name")
                ):

                    print(
                        "跳过：商品名称无法确认",
                        flush=True,
                    )

                    continue

                if (
                    item.get(
                        "category"
                    )
                    == "excluded"
                ):

                    print(
                        "过滤：",
                        item.get(
                            "name"
                        ),
                        flush=True,
                    )

                    continue

                # 有商品级价格，
                # 或者有完整 SKU 价格表，
                # 至少满足一个就保留。
                if (
                    item.get(
                        "buy_price"
                    )
                    is None
                    and not item.get(
                        "size_price_map"
                    )
                ):

                    print(
                        "跳过：没有任何有效买入价格证据",
                        flush=True,
                    )

                    continue

                items.append(
                    item
                )

                print_item(
                    item
                )

            except Exception as e:

                print(
                    "采集失败：",
                    repr(e),
                    flush=True,
                )

            time.sleep(
                0.5
            )

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

        "source":
            "识货",

        "products":
            products,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )

    # ========================================================
    # 汇总
    # ========================================================

    print("")
    print(
        "=" * 70
    )

    print(
        f"最终商品数：{len(products)}"
    )

    print(
        "有尺码价格表：",
        sum(
            1
            for item in products
            if item.get(
                "size_price_map"
            )
        ),
    )

    print(
        "货号已确认：",
        sum(
            1
            for item in products
            if item.get(
                "product_code"
            )
        ),
    )

    print(
        "配色已确认：",
        sum(
            1
            for item in products
            if item.get(
                "color"
            )
        ),
    )

    print(
        "当前尺码已确认：",
        sum(
            1
            for item in products
            if item.get(
                "size"
            )
        ),
    )

    print(
        "得物渠道售价：",
        sum(
            1
            for item in products
            if item.get(
                "dewu_channel_price"
            )
            is not None
        ),
    )

    print(
        "7日最低价：",
        sum(
            1
            for item in products
            if item.get(
                "price_7d_low"
            )
            is not None
        ),
    )

    print(
        "月销量：",
        sum(
            1
            for item in products
            if item.get(
                "sales_30d"
            )
            is not None
        ),
    )

    print(
        "=" * 70
    )


if __name__ == "__main__":
    main()
