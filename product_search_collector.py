import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


HOME_URL = "https://www.shihuo.cn/page/pcHome"
OUTPUT_FILE = "discovery_data.json"
MAX_DETAIL_PAGES = 40

VIEWPORT = {
    "width": 1440,
    "height": 1000,
}


# ============================================================
# 商品范围控制
# ============================================================

# 明确排除：这些商品不进入后续利润分析
EXCLUDED_KEYWORDS = [
    # 贵金属 / 黄金 / 珠宝
    "黄金",
    "足金",
    "金饰",
    "金首饰",
    "金戒指",
    "金手镯",
    "金项链",
    "金耳环",
    "贵金属",
    "铂金",
    "白金",
    "18k金",
    "18k",
    "钻石",
    "珠宝",
    "翡翠",
    "玉石",

    # 虚拟商品 / 充值 / 游戏
    "点券",
    "充值",
    "虚拟商品",
    "虚拟物品",
    "游戏币",
    "游戏道具",
    "账号",
    "帐号",
    "激活码",
    "兑换码",
    "cdkey",
    "代充",
    "会员充值",
    "话费充值",
    "流量充值",

    # 酒类
    "白酒",
    "啤酒",
    "红酒",
    "葡萄酒",
    "洋酒",
    "威士忌",
    "伏特加",
    "香槟",
    "酒水",

    # 食品 / 饮料
    "食品",
    "零食",
    "饼干",
    "糖果",
    "巧克力",
    "饮料",
    "牛奶",
    "咖啡",
    "茶叶",
    "茶",
    "方便面",
    "火锅底料",
    "调味料",

    # 宠物食品
    "猫粮",
    "狗粮",
    "宠物粮",
    "宠物食品",
    "猫罐头",
    "狗罐头",

    # 药品 / 保健品
    "药品",
    "处方药",
    "非处方药",
    "otc",
    "保健品",
    "保健食品",
    "维生素",
    "钙片",
    "鱼油",
    "蛋白粉",

    # 普通日用品 / 清洁用品
    "洗衣液",
    "洗衣粉",
    "洗洁精",
    "清洁剂",
    "纸巾",
    "抽纸",
    "卫生纸",
    "垃圾袋",
    "拖把",
    "扫把",
    "清洁用品",

    # 普通个护 / 护肤 / 化妆
    "洗发水",
    "护发素",
    "沐浴露",
    "牙膏",
    "牙刷",
    "洁面",
    "洁面乳",
    "洁面啫喱",
    "护肤",
    "面霜",
    "乳液",
    "化妆品",
    "口红",
    "粉底",
    "眼影",
    "香水",

    # 家居 / 普通生活用品
    "床单",
    "被套",
    "枕头",
    "被子",
    "锅",
    "炒锅",
    "水杯",
    "保温杯",
    "餐具",
    "垃圾桶",
]


# 允许进入监控的主要商品方向。
# 注意：这不是最终“得物可售”判断，只是第一层商品范围控制。
TARGET_KEYWORDS = [
    # 鞋
    "鞋",
    "球鞋",
    "运动鞋",
    "跑鞋",
    "篮球鞋",
    "足球鞋",
    "训练鞋",
    "板鞋",
    "休闲鞋",
    "靴",

    # 服装
    "卫衣",
    "外套",
    "夹克",
    "羽绒服",
    "冲锋衣",
    "风衣",
    "棉服",
    "大衣",
    "T恤",
    "短袖",
    "长袖",
    "衬衫",
    "裤",
    "牛仔裤",
    "运动裤",
    "短裤",
    "裙",
    "服装",
    "衣",

    # 包
    "包",
    "背包",
    "双肩包",
    "斜挎包",
    "腰包",
    "托特包",
    "手提包",
    "旅行包",

    # 手表
    "手表",
    "腕表",
    "电子表",
    "机械表",

    # 潮流配饰
    "帽",
    "棒球帽",
    "渔夫帽",
    "围巾",
    "手套",
    "腰带",
    "皮带",
    "墨镜",
    "太阳镜",
    "眼镜",

    # 运动相关
    "篮球",
    "足球",
    "网球拍",
    "羽毛球拍",
    "运动装备",
    "运动器材",
    "瑜伽垫",
    "滑板",
    "护具",

    # 潮玩 / 收藏类
    "潮玩",
    "盲盒",
    "手办",
    "积木",
    "玩具",

    # 耳机 / 数码穿戴等得物常见商品
    "耳机",
    "蓝牙耳机",
    "头戴式耳机",
    "耳塞",
    "游戏机",
    "掌机",
    "相机",
    "镜头",
    "数码相机",
]


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def normalize_price(value, unit=None):
    if value is None:
        return None

    try:
        text = str(value).strip()
        text = text.replace(",", "")
        text = text.replace("¥", "")
        text = text.replace("￥", "")
        text = text.replace("元", "")
        text = text.strip()

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
    unit = None

    try:
        unit = match.group(2)
    except Exception:
        pass

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


def extract_product_name(text):
    if not text:
        return None

    patterns = [
        r"商品名称[:：]\s*(.+?)(?:。品牌[:：])",
        r"商品名称[:：]\s*(.+?)(?:\s+品牌[:：])",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            name = clean_text(match.group(1))

            if len(name) >= 4:
                return name

    return None


# ============================================================
# 商品资格判断
# ============================================================

def classify_product(name):
    """
    第一层商品资格控制：

    excluded:
        明确不做的商品，直接过滤。

    target:
        属于我们重点监控范围，进入后续分析。

    unknown:
        当前无法确认类别，不直接假装能卖。
        保留到 discovery_data，但标记为 unknown，
        后续 monitor.py 再做第二层硬过滤。
    """

    name = clean_text(name).lower()

    if not name:
        return "unknown", "商品名称为空"

    # 先排除明确禁止/不做的品类
    for keyword in EXCLUDED_KEYWORDS:
        if keyword.lower() in name:
            return (
                "excluded",
                f"命中排除品类关键词：{keyword}",
            )

    # 再判断目标商品
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
# 价格
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


def extract_7d_prices(text):
    if not text:
        return None, None

    high = None
    low = None

    high_patterns = [
        r"(?:过去|近|最近)\s*7\s*(?:天|日)"
        r"[^。；\n]{0,80}"
        r"(?:最高价|最高)"
        r"[^¥￥0-9]{0,20}"
        r"[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",

        r"(?:7日|7天)"
        r"[^。；\n]{0,60}"
        r"(?:最高价|最高)"
        r"[^¥￥0-9]{0,20}"
        r"[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",
    ]

    low_patterns = [
        r"(?:过去|近|最近)\s*7\s*(?:天|日)"
        r"[^。；\n]{0,80}"
        r"(?:最低价|最低)"
        r"[^¥￥0-9]{0,20}"
        r"[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",

        r"(?:7日|7天)"
        r"[^。；\n]{0,60}"
        r"(?:最低价|最低)"
        r"[^¥￥0-9]{0,20}"
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


def extract_price_position(current, high, low):
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


def extract_downside_to_low(current, low):
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

    pattern = (
        r"(?:总销|累计销量|总销量)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(万)?\+?"
    )

    match = re.search(pattern, text)

    if not match:
        return None

    try:
        value = float(match.group(1))
    except Exception:
        return None

    if match.group(2) == "万":
        value *= 10000

    return value if value > 0 else None


def calculate_turnover(sales_30d, sales):
    if sales_30d is not None and sales_30d > 0:
        return {
            "sales_velocity_7d": round(
                sales_30d / 30,
                2,
            ),
            "turnover_evidence": (
                f"近30日/月销 {sales_30d:g}，"
                f"折算日均约 "
                f"{sales_30d / 30:.2f}"
            ),
            "turnover_confidence": "medium",
        }

    if sales is not None and sales > 0:
        return {
            "sales_velocity_7d": None,
            "turnover_evidence": f"累计销量 {sales:g}",
            "turnover_confidence": "low",
        }

    return {
        "sales_velocity_7d": None,
        "turnover_evidence": None,
        "turnover_confidence": "unknown",
    }


# ============================================================
# 得物价格
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
# 价格走势
# ============================================================

def extract_price_trend(text):
    if not text:
        return None

    if re.search(r"价格.{0,20}下跌", text):
        return "下跌"

    if re.search(r"价格.{0,20}上涨", text):
        return "上涨"

    if re.search(r"价格.{0,20}(稳定|平稳)", text):
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
            rf"[^。；\n]{{0,40}}"
            rf"(上涨|下跌)\s*"
            rf"([0-9]+(?:\.[0-9]+)?)\s*%"
        )

        match = re.search(pattern, text)

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
# 商品详情
# ============================================================

def product_key(item):
    url = item.get("shihuo_url")

    if url:
        return f"url:{url}"

    product_code = item.get("product_code")
    name = item.get("name")

    if product_code and name:
        return f"code:{product_code}|name:{name}"

    return f"name:{name}"


def extract_detail(page, url):
    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(2500)

    detail_text = clean_text(
        page.locator("body").inner_text()
    )

    name = extract_product_name(detail_text)

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
        buy_price = extract_price(detail_text)

    dewu_price = extract_dewu_price(detail_text)

    trend_current_price = extract_trend_current_price(
        detail_text
    )

    price_7d_high, price_7d_low = extract_7d_prices(
        detail_text
    )

    sales_30d = extract_month_sales(detail_text)
    sales = extract_total_sales(detail_text)

    turnover = calculate_turnover(
        sales_30d,
        sales,
    )

    price_position_7d = extract_price_position(
        trend_current_price,
        price_7d_high,
        price_7d_low,
    )

    downside_to_7d_low = extract_downside_to_low(
        trend_current_price,
        price_7d_low,
    )

    changes = extract_price_changes(detail_text)
    price_trend = extract_price_trend(detail_text)

    category, category_reason = classify_product(name)

    return {
        "name": name,
        "buy_price": buy_price,
        "shihuo_url": url,
        "product_code": None,

        "category": category,
        "category_reason": category_reason,

        "dewu_display_price": dewu_price,

        "trend_current_price": trend_current_price,
        "price_current": trend_current_price,

        "lowest_price": price_7d_low,

        "sales": sales,
        "sales_7d": None,
        "sales_30d": sales_30d,

        "sales_velocity_7d": turnover[
            "sales_velocity_7d"
        ],

        "turnover_evidence": turnover[
            "turnover_evidence"
        ],

        "turnover_confidence": turnover[
            "turnover_confidence"
        ],

        "price_7d_high": price_7d_high,
        "price_7d_low": price_7d_low,

        "price_position_7d": price_position_7d,
        "downside_to_7d_low": downside_to_7d_low,

        "price_change_1d": changes[
            "price_change_1d"
        ],

        "price_change_7d": changes[
            "price_change_7d"
        ],

        "price_change_30d": changes[
            "price_change_30d"
        ],

        "price_trend": price_trend,

        "detail_text": detail_text[:12000],

        "observed_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


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


def merge_products(items):
    result = {}

    for item in items:

        if not valid_name(item.get("name")):
            continue

        if item.get("buy_price") is None:
            continue

        # ====================================================
        # 第一层硬过滤
        # ====================================================

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

    return list(result.values())


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

                # 明确排除品类
                if item.get("category") == "excluded":
                    print(
                        "过滤：",
                        item.get("name"),
                        "|",
                        item.get("category_reason"),
                    )
                    continue

                items.append(item)

                print(
                    f"商品：{item['name']}"
                )

                print(
                    f"类别：{item['category']}"
                )

                print(
                    f"买入价：{item['buy_price']}"
                )

                print(
                    f"得物渠道价："
                    f"{item['dewu_display_price']}"
                )

                print(
                    f"当前同款同规格到手价："
                    f"{item['trend_current_price']}"
                )

                print(
                    f"7日最高："
                    f"{item['price_7d_high']}"
                )

                print(
                    f"7日最低："
                    f"{item['price_7d_low']}"
                )

                print(
                    f"月销："
                    f"{item['sales_30d']}"
                )

            except Exception as e:

                print(
                    f"采集失败：{e}"
                )

            time.sleep(1)

        browser.close()

    products = merge_products(items)

    output = {
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "count": len(products),

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

    print(
        "\n=============================="
    )

    print(
        f"最终有效商品数：{len(products)}"
    )

    print(
        "=============================="
    )

    for item in products[:20]:

        print(
            f"\n商品：{item.get('name')}"
        )

        print(
            f"类别：{item.get('category')}"
        )

        print(
            f"类别依据："
            f"{item.get('category_reason')}"
        )

        print(
            f"买入价："
            f"{item.get('buy_price')}"
        )

        print(
            f"得物渠道价："
            f"{item.get('dewu_display_price')}"
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
            f"月销："
            f"{item.get('sales_30d')}"
        )


if __name__ == "__main__":
    main()
