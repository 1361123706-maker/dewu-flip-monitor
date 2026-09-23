import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent

INPUT_FILE = ROOT / "market_data_input.json"
DISCOVERY_FILE = ROOT / "discovery_data.json"
OUTPUT_FILE = ROOT / "products.json"


def load_json(path):
    if not path.exists():
        return {}

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def number(value):
    try:
        return float(value)
    except Exception:
        return None


def get_products(data):
    products = data.get("products", [])

    if not isinstance(products, list):
        return []

    return products


# ============================================================
# 价格标准化
# 支持：
# 1.08万       -> 10800
# 1 .08 万     -> 10800
# 1.16万       -> 11600
# 2万          -> 20000
# 820          -> 820
# ============================================================

def normalize_price(value, detail_text=""):

    text = clean_text(detail_text)

    # --------------------------------------------------------
    # 如果 value 本身就是字符串，优先直接解析
    # --------------------------------------------------------

    if isinstance(value, str):

        raw = value.strip()

        raw_clean = re.sub(
            r"\s+",
            "",
            raw
        )

        # 例如：¥1.08万
        m = re.search(
            r"(\d+(?:\.\d+)?)万",
            raw_clean,
            re.I
        )

        if m:
            return float(m.group(1)) * 10000

        # 例如：¥1.08
        m = re.search(
            r"\d+(?:\.\d+)?",
            raw_clean
        )

        if m:
            value = m.group(0)

    price = number(value)

    if price is None:
        return None

    # --------------------------------------------------------
    # 如果已经是正常的大金额，不再转换
    # --------------------------------------------------------

    if price >= 1000:
        return price

    # --------------------------------------------------------
    # 在详情文本中寻找对应的“X万”
    #
    # 支持：
    # 1.08万
    # 1 .08 万
    # 1.16万
    # 2万
    # --------------------------------------------------------

    if text:

        compact = re.sub(
            r"\s+",
            "",
            text
        )

        # 先处理带小数的万
        matches = re.findall(
            r"(\d+)\.(\d+)(?:万)",
            compact
        )

        for integer_part, decimal_part in matches:

            candidate_raw = (
                f"{integer_part}.{decimal_part}"
            )

            candidate = float(candidate_raw)

            # 如果和原始价格接近，
            # 说明这是同一个价格
            if abs(candidate - price) < 0.01:
                return candidate * 10000

        # 再处理整数万
        matches = re.findall(
            r"(\d+)万",
            compact
        )

        for match in matches:

            candidate = float(match) * 10000

            if candidate >= 1000:
                return candidate

    return price


# ============================================================
# 商品名称
# ============================================================

def valid_product_name(name):

    name = clean_text(name)

    if not name:
        return False

    if len(name) < 2:
        return False

    bad_names = {
        "未知商品",
        "商品",
        "详情",
        "价格",
        "购买",
        "立即购买",
        "加入购物车",
        "256GB",
        "512GB",
        "1TB",
        "2TB",
    }

    if name in bad_names:
        return False

    # 纯容量不要作为商品名称
    if re.fullmatch(
        r"\d+(?:GB|TB)",
        name,
        re.I
    ):
        return False

    return True


def extract_product_name(detail_text):

    text = clean_text(detail_text)

    if not text:
        return None

    # --------------------------------------------------------
    # 最高优先级：
    #
    # 商品名称：Apple/苹果 iPhone 17 Pro...
    # 品牌：
    # --------------------------------------------------------

    patterns = [
        r"商品名称\s*[:：]\s*(.+?)(?:。?\s*品牌\s*[:：])",
        r"商品名称\s*[:：]\s*(.+?)(?:\n|$)",
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            text,
            re.S
        )

        if m:

            name = clean_text(
                m.group(1)
            )

            name = re.sub(
                r"\s+",
                " ",
                name
            ).strip()

            if valid_product_name(name):
                return name

    # --------------------------------------------------------
    # 备用：商品名称后面到下一个字段
    # --------------------------------------------------------

    m = re.search(
        r"商品名称\s*[:：]\s*(.{2,120})",
        text,
        re.S
    )

    if m:

        name = clean_text(
            m.group(1)
        )

        name = re.split(
            r"品牌\s*[:：]|货号\s*[:：]|商品编号\s*[:：]",
            name
        )[0]

        name = clean_text(name)

        if valid_product_name(name):
            return name

    return None


# ============================================================
# 从“全网价格区间”取得最低价格
#
# 例如：
# 全网价格区间：
# 10000.00元 - 10685.17元
#
# 返回：
# 10000
# ============================================================

def extract_market_low_price(detail_text):

    text = clean_text(detail_text)

    if not text:
        return None

    patterns = [
        r"全网价格区间\s*[:：]\s*"
        r"[¥￥]?\s*([\d,]+(?:\.\d+)?)\s*元?\s*[-~～至]\s*"
        r"[¥￥]?\s*([\d,]+(?:\.\d+)?)",

        r"价格区间\s*[:：]\s*"
        r"[¥￥]?\s*([\d,]+(?:\.\d+)?)\s*元?\s*[-~～至]\s*"
        r"[¥￥]?\s*([\d,]+(?:\.\d+)?)",
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            text,
            re.I
        )

        if m:

            low = number(
                m.group(1).replace(",", "")
            )

            high = number(
                m.group(2).replace(",", "")
            )

            if (
                low is not None
                and high is not None
                and low > 0
                and high >= low
            ):
                return low

    return None


# ============================================================
# 得物渠道售价
#
# 例如：
# 得物渠道售价10685.17元
# 得物渠道售价为10685.17元
# ============================================================

def extract_dewu_channel_price(detail_text):

    text = clean_text(detail_text)

    if not text:
        return None

    patterns = [
        r"得物渠道售价\s*为?\s*[¥￥]?\s*"
        r"([\d,]+(?:\.\d+)?)\s*元?",

        r"得物渠道价格\s*为?\s*[¥￥]?\s*"
        r"([\d,]+(?:\.\d+)?)\s*元?",
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            text,
            re.I
        )

        if m:

            price = number(
                m.group(1).replace(",", "")
            )

            if price is not None and price > 0:
                return price

    return None


# ============================================================
# 价格走势当前价
#
# 例如：
# 当前同款同规格到手价为¥7510，
# 是过去7天内监测到的最低价
# ============================================================

def extract_trend_current_price(detail_text):

    text = clean_text(detail_text)

    if not text:
        return None

    patterns = [

        r"当前同款同规格到手价\s*为?\s*"
        r"[¥￥]?\s*([\d,]+(?:\.\d+)?)",

        r"当前价格\s*为?\s*"
        r"[¥￥]?\s*([\d,]+(?:\.\d+)?)",

        r"当前价\s*为?\s*"
        r"[¥￥]?\s*([\d,]+(?:\.\d+)?)",
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            text,
            re.I
        )

        if m:

            price = number(
                m.group(1).replace(",", "")
            )

            if price is not None and price > 0:
                return price

    return None


# ============================================================
# 7日最低价
# ============================================================

def extract_7d_low(detail_text):

    text = clean_text(detail_text)

    if not text:
        return None

    patterns = [
        r"过去7天.*?最低价.*?"
        r"[¥￥]?\s*([\d,]+(?:\.\d+)?)",

        r"近7天.*?最低价.*?"
        r"[¥￥]?\s*([\d,]+(?:\.\d+)?)",

        r"7天.*?最低价.*?"
        r"[¥￥]?\s*([\d,]+(?:\.\d+)?)",
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            text,
            re.I | re.S
        )

        if m:

            price = number(
                m.group(1).replace(",", "")
            )

            if price is not None and price > 0:
                return price

    return None


# ============================================================
# 商品唯一键
# ============================================================

def product_key(item):

    url = clean_text(
        item.get("shihuo_url")
    )

    if url:

        return (
            "url",
            url.lower()
        )

    code = clean_text(
        item.get("product_code")
    )

    name = clean_text(
        item.get("name")
    )

    if (
        code
        and valid_product_name(name)
    ):

        return (
            "code_name",
            code.lower(),
            name.lower()
        )

    if valid_product_name(name):

        return (
            "name",
            name.lower()
        )

    return (
        "unknown",
        ""
    )


# ============================================================
# 复制识货发现数据
# ============================================================

def copy_discovery_fields(
    result,
    discovery
):

    detail_text = clean_text(
        discovery.get("detail_text")
    )

    # ========================================================
    # 商品名称
    # ========================================================

    discovered_name = clean_text(
        discovery.get("name")
    )

    extracted_name = extract_product_name(
        detail_text
    )

    if extracted_name:

        result["name"] = extracted_name

    elif valid_product_name(
        discovered_name
    ):

        result["name"] = discovered_name

    # ========================================================
    # 买入价
    #
    # 优先：
    # 1. 全网价格区间最低价
    # 2. 采集器 buy_price
    # ========================================================

    market_low = extract_market_low_price(
        detail_text
    )

    raw_buy = discovery.get(
        "buy_price"
    )

    buy = normalize_price(
        raw_buy,
        detail_text
    )

    if (
        market_low is not None
        and market_low > 0
    ):

        buy = market_low

    if buy is not None and buy > 0:

        prices = result.get(
            "buy_prices"
        )

        if not isinstance(
            prices,
            dict
        ):
            prices = {}

        prices = dict(prices)

        prices["识货公开发现"] = buy

        result["buy_prices"] = prices
        result["buy_price"] = buy

    # ========================================================
    # 得物渠道售价
    #
    # 优先从 detail_text 中准确读取
    # ========================================================

    dewu_channel = (
        extract_dewu_channel_price(
            detail_text
        )
    )

    raw_dewu = discovery.get(
        "dewu_display_price"
    )

    dewu_fallback = normalize_price(
        raw_dewu,
        detail_text
    )

    dewu = (
        dewu_channel
        if dewu_channel is not None
        else dewu_fallback
    )

    if dewu is not None and dewu > 0:

        result["dewu_price"] = dewu

        result["dewu_display_price"] = dewu

        result["dewu_price_source"] = (
            "识货公开页面中的得物渠道售价"
            if dewu_channel is not None
            else "识货公开商品详情"
        )

        result["dewu_price_evidence"] = (
            "公开页面可见数据；"
            "不是得物内部出价接口"
        )

    # ========================================================
    # 价格走势当前价
    # ========================================================

    trend_current = (
        extract_trend_current_price(
            detail_text
        )
    )

    if trend_current is not None:

        result["trend_current_price"] = (
            trend_current
        )

    # ========================================================
    # 7日最低价
    # ========================================================

    trend_low = extract_7d_low(
        detail_text
    )

    if trend_low is not None:

        result["price_7d_low"] = (
            trend_low
        )

    # ========================================================
    # 原始字段完整传递
    # ========================================================

    fields = [

        "shihuo_url",
        "source_url",
        "product_code",

        # 价格
        "lowest_price",
        "price_current",
        "trend_current_price",

        # 7日价格
        "price_7d_high",
        "price_7d_low",
        "price_position_7d",
        "downside_to_7d_low",

        # 销量
        "sales",
        "sales_7d",
        "sales_30d",
        "sales_velocity_7d",

        # 周转证据
        "turnover_evidence",
        "turnover_confidence",

        # 历史价格
        "price_history",
        "price_1d",
        "price_7d",
        "price_30d",

        # 价格变化
        "price_change_1d",
        "price_change_7d",
        "price_change_30d",

        # 趋势
        "price_trend",

        # 风控
        "category",
        "authenticity_evidence",
        "new_condition_evidence",
        "dewu_check_evidence",
        "detail_status",

        # 原始证据
        "detail_text",
        "observed_at",
        "discovery_observed_at",
    ]

    for field in fields:

        value = discovery.get(
            field
        )

        if value in (
            None,
            "",
            [],
            {},
        ):
            continue

        # 如果已有更准确的解析结果，
        # 不用采集器可能错误的值覆盖
        if (
            field == "price_7d_low"
            and trend_low is not None
        ):
            continue

        if (
            field == "trend_current_price"
            and trend_current is not None
        ):
            continue

        result[field] = value

    # ========================================================
    # 再次确保走势当前价正确
    # ========================================================

    if trend_current is not None:

        result["trend_current_price"] = (
            trend_current
        )

        result["price_current"] = (
            trend_current
        )

    elif (
        result.get("price_current")
        is None
        and result.get(
            "trend_current_price"
        )
        is not None
    ):

        result["price_current"] = (
            result["trend_current_price"]
        )

    # ========================================================
    # 如果没有当前价，使用7日最低价
    # ========================================================

    if (
        result.get("price_current")
        is None
        and result.get(
            "price_7d_low"
        )
        is not None
    ):

        result["price_current"] = (
            result["price_7d_low"]
        )

    # ========================================================
    # 重新计算当前价到7日最低价的回落风险
    # ========================================================

    current = number(
        result.get(
            "price_current"
        )
    )

    low = number(
        result.get(
            "price_7d_low"
        )
    )

    if (
        current is not None
        and low is not None
        and current > 0
        and low >= 0
        and low <= current
    ):

        result[
            "downside_to_7d_low"
        ] = round(
            (
                current - low
            )
            / current
            * 100,
            2
        )

    # ========================================================
    # 如果有销量证据，补充周转证据
    # ========================================================

    sales_7d = number(
        result.get(
            "sales_7d"
        )
    )

    sales_30d = number(
        result.get(
            "sales_30d"
        )
    )

    velocity = number(
        result.get(
            "sales_velocity_7d"
        )
    )

    if velocity is None:

        if (
            sales_7d is not None
            and sales_7d > 0
        ):

            velocity = (
                sales_7d / 7
            )

            result[
                "sales_velocity_7d"
            ] = round(
                velocity,
                2
            )

        elif (
            sales_30d is not None
            and sales_30d > 0
        ):

            velocity = (
                sales_30d / 30
            )

            result[
                "sales_velocity_7d"
            ] = round(
                velocity,
                2
            )

    if (
        result.get(
            "turnover_evidence"
        )
        in (
            None,
            "",
        )
    ):

        if (
            sales_7d is not None
            and sales_7d > 0
        ):

            result[
                "turnover_evidence"
            ] = (
                f"近7天销量 {sales_7d:g}，"
                f"日均约 {sales_7d / 7:.2f}"
            )

            result[
                "turnover_confidence"
            ] = "high"

        elif (
            sales_30d is not None
            and sales_30d > 0
        ):

            result[
                "turnover_evidence"
            ] = (
                f"近30天销量 {sales_30d:g}，"
                f"日均约 {sales_30d / 30:.2f}"
            )

            result[
                "turnover_confidence"
            ] = "medium"

        elif (
            velocity is not None
            and velocity > 0
        ):

            result[
                "turnover_evidence"
            ] = (
                f"日均销量约 {velocity:.2f}"
            )

            result[
                "turnover_confidence"
            ] = "medium"

    # ========================================================
    # 数据来源
    # ========================================================

    result[
        "discovery_data_source"
    ] = "识货公开页面"

    return result


def merge_product(
    base,
    discovery
):

    result = dict(base)

    return copy_discovery_fields(
        result,
        discovery
    )


def clean_buy_prices(item):

    prices = item.get(
        "buy_prices"
    )

    if not isinstance(
        prices,
        dict
    ):
        return {}

    cleaned = {}

    for source, value in prices.items():

        price = number(value)

        if (
            price is not None
            and price > 0
        ):

            cleaned[source] = price

    return cleaned


# ============================================================
# 主程序
# ============================================================

def main():

    market_data = load_json(
        INPUT_FILE
    )

    discovery_data = load_json(
        DISCOVERY_FILE
    )

    market_products = get_products(
        market_data
    )

    discovery_products = get_products(
        discovery_data
    )

    merged = {}

    # ========================================================
    # 原市场数据
    # ========================================================

    for item in market_products:

        if not isinstance(
            item,
            dict
        ):
            continue

        key = product_key(
            item
        )

        merged[key] = dict(item)

    # ========================================================
    # 公开发现数据
    # ========================================================

    for discovery in discovery_products:

        if not isinstance(
            discovery,
            dict
        ):
            continue

        # 如果采集器名称错误，
        # 但 detail_text 里有真实商品名称，
        # 这里先允许进入 merge，
        # copy_discovery_fields 会修正名称。

        key = product_key(
            discovery
        )

        if key in merged:

            merged[key] = merge_product(
                merged[key],
                discovery
            )

        else:

            merged[key] = merge_product(
                {},
                discovery
            )

    # ========================================================
    # 最终清理
    # ========================================================

    products = []

    for item in merged.values():

        if not isinstance(
            item,
            dict
        ):
            continue

        if not valid_product_name(
            item.get("name")
        ):
            continue

        prices = clean_buy_prices(
            item
        )

        if not prices:
            continue

        item["buy_prices"] = prices

        products.append(
            item
        )

    output = {

        "updated_at":
            market_data.get(
                "updated_at"
            ),

        "discovery_updated_at":
            discovery_data.get(
                "updated_at"
            ),

        "source":
            "市场行情 + 识货公开商品发现",

        "products":
            products,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("=" * 70)
    print(
        "市场原有商品：",
        len(market_products)
    )
    print(
        "公开发现商品：",
        len(discovery_products)
    )
    print(
        "最终有效商品：",
        len(products)
    )
    print("=" * 70)

    for index, item in enumerate(
        products[:20],
        start=1
    ):

        print()
        print(
            f"#{index} "
            f"{item.get('name')}"
        )

        print(
            "买入：",
            item.get("buy_price")
        )

        print(
            "得物：",
            item.get("dewu_price")
        )

        print(
            "月销：",
            item.get("sales_30d")
        )

        print(
            "销量速度：",
            item.get(
                "sales_velocity_7d"
            )
        )

        print(
            "周转证据：",
            item.get(
                "turnover_evidence"
            )
        )

        print(
            "7日最高：",
            item.get(
                "price_7d_high"
            )
        )

        print(
            "7日最低：",
            item.get(
                "price_7d_low"
            )
        )

        print(
            "当前价：",
            item.get(
                "price_current"
            )
        )

        print(
            "7日回落风险：",
            item.get(
                "downside_to_7d_low"
            )
        )

        print(
            "价格趋势：",
            item.get(
                "price_trend"
            )
        )


if __name__ == "__main__":
    main()
