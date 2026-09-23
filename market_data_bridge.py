import json
import re
from pathlib import Path


INPUT_FILE = "market_data_input.json"
DISCOVERY_FILE = "discovery_data.json"
OUTPUT_FILE = "products.json"


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_price(value):
    """
    支持：
    820
    820.00
    1.08万
    1 .08 万
    ¥820
    820元
    """

    if value is None:
        return None

    text = clean_text(value)

    if not text:
        return None

    text = (
        text.replace(",", "")
        .replace("¥", "")
        .replace("￥", "")
        .replace("元", "")
        .strip()
    )

    text = re.sub(r"\s+", "", text)

    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)(万)?",
        text,
    )

    if not match:
        return None

    try:
        number = float(match.group(1))
    except Exception:
        return None

    if match.group(2) == "万":
        number *= 10000

    if number <= 0 or number > 1000000:
        return None

    return round(number, 2)


def extract_product_name(item):
    name = clean_text(
        item.get("name")
    )

    if name and len(name) >= 4:
        return name

    detail_text = clean_text(
        item.get("detail_text")
    )

    if not detail_text:
        return None

    patterns = [
        r"商品名称[:：]\s*(.+?)(?:。品牌[:：])",
        r"商品名称[:：]\s*(.+?)(?:\s+品牌[:：])",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            detail_text,
        )

        if match:
            result = clean_text(
                match.group(1)
            )

            if len(result) >= 4:
                return result

    return None


def extract_market_low_price(item):
    detail_text = clean_text(
        item.get("detail_text")
    )

    if not detail_text:
        return None

    pattern = (
        r"全网价格区间[:：]\s*"
        r"[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"\s*(万)?"
        r"\s*元?\s*-\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"\s*(万)?"
    )

    match = re.search(
        pattern,
        detail_text,
    )

    if not match:
        return None

    low = normalize_price(
        match.group(1)
        + (
            "万"
            if match.group(2)
            else ""
        )
    )

    return low


def extract_dewu_channel_price(item):
    detail_text = clean_text(
        item.get("detail_text")
    )

    if not detail_text:
        return None

    patterns = [
        r"得物渠道售价\s*[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"\s*(万)?\s*元?",

        r"得物渠道售价为\s*[¥￥]?\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)"
        r"\s*(万)?\s*元?",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            detail_text,
        )

        if not match:
            continue

        value = match.group(1)

        if match.group(2):
            value += "万"

        price = normalize_price(
            value
        )

        if price is not None:
            return price

    return None


def extract_trend_current_price(item):
    """
    只接受明确的：
    当前同款同规格到手价
    当前同款同规格到手价为 ¥xxx

    不从普通文本里的单独数字猜价格。
    """

    explicit = normalize_price(
        item.get(
            "trend_current_price"
        )
    )

    if explicit is not None:
        return explicit

    explicit = normalize_price(
        item.get(
            "price_current"
        )
    )

    if explicit is not None:
        return explicit

    detail_text = clean_text(
        item.get("detail_text")
    )

    if not detail_text:
        return None

    patterns = [
        r"当前同款同规格到手价为\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",

        r"当前同款同规格到手价为\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?\s*元",

        r"当前(?:同款同规格)?到手价为\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            detail_text,
        )

        if not match:
            continue

        value = match.group(1)

        if match.group(2):
            value += "万"

        price = normalize_price(
            value
        )

        if price is not None:
            return price

    return None


def extract_explicit_7d_low(item):
    """
    7日最低价必须来自明确的7日语义。

    禁止：
    ¥7
    ¥9
    尺码7
    日期7
    规格数字7

    被当成7日最低价。
    """

    explicit = normalize_price(
        item.get("price_7d_low")
    )

    if explicit is not None:
        return explicit

    detail_text = clean_text(
        item.get("detail_text")
    )

    if not detail_text:
        return None

    patterns = [
        r"当前同款同规格到手价为\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?"
        r"[^。；\n]{0,100}"
        r"(?:过去|近|最近)\s*7\s*(?:天|日)"
        r"[^。；\n]{0,50}"
        r"(?:最低价|最低)",

        r"(?:过去|近|最近)\s*7\s*(?:天|日)"
        r"[^。；\n]{0,80}"
        r"(?:最低价|最低)"
        r"[^¥￥0-9]{0,20}"
        r"[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            detail_text,
        )

        if not match:
            continue

        value = match.group(1)

        if match.group(2):
            value += "万"

        price = normalize_price(
            value
        )

        if price is not None:
            return price

    return None


def extract_explicit_7d_high(item):
    explicit = normalize_price(
        item.get("price_7d_high")
    )

    if explicit is not None:
        return explicit

    detail_text = clean_text(
        item.get("detail_text")
    )

    if not detail_text:
        return None

    patterns = [
        r"当前同款同规格到手价为\s*[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?"
        r"[^。；\n]{0,100}"
        r"(?:过去|近|最近)\s*7\s*(?:天|日)"
        r"[^。；\n]{0,50}"
        r"(?:最高价|最高)",

        r"(?:过去|近|最近)\s*7\s*(?:天|日)"
        r"[^。；\n]{0,80}"
        r"(?:最高价|最高)"
        r"[^¥￥0-9]{0,20}"
        r"[¥￥]\s*"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(万)?",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            detail_text,
        )

        if not match:
            continue

        value = match.group(1)

        if match.group(2):
            value += "万"

        price = normalize_price(
            value
        )

        if price is not None:
            return price

    return None


def calculate_price_evidence(item):
    """
    统一整理价格证据。

    重要：
    得物渠道售价 != 当前同款同规格到手价。

    两者都保存，不互相覆盖。
    """

    dewu_channel_price = (
        extract_dewu_channel_price(
            item
        )
    )

    if dewu_channel_price is None:
        dewu_channel_price = normalize_price(
            item.get(
                "dewu_display_price"
            )
        )

    trend_current_price = (
        extract_trend_current_price(
            item
        )
    )

    price_7d_low = (
        extract_explicit_7d_low(
            item
        )
    )

    price_7d_high = (
        extract_explicit_7d_high(
            item
        )
    )

    current_price = (
        trend_current_price
        if trend_current_price
        is not None
        else dewu_channel_price
    )

    position = None
    downside = None

    if (
        trend_current_price is not None
        and price_7d_low is not None
        and price_7d_high is not None
        and price_7d_high > price_7d_low
    ):
        position = round(
            (
                (
                    trend_current_price
                    - price_7d_low
                )
                / (
                    price_7d_high
                    - price_7d_low
                )
            )
            * 100,
            2,
        )

    if (
        trend_current_price is not None
        and price_7d_low is not None
        and trend_current_price > 0
    ):
        downside = round(
            (
                (
                    trend_current_price
                    - price_7d_low
                )
                / trend_current_price
            )
            * 100,
            2,
        )

    return {
        "dewu_channel_price": (
            dewu_channel_price
        ),

        "trend_current_price": (
            trend_current_price
        ),

        "price_current": (
            current_price
        ),

        "price_7d_low": (
            price_7d_low
        ),

        "price_7d_high": (
            price_7d_high
        ),

        "price_position_7d": (
            position
        ),

        "downside_to_7d_low": (
            downside
        ),

        "price_evidence_status": (
            "明确当前价"
            if trend_current_price
            is not None
            else (
                "仅有得物渠道价"
                if dewu_channel_price
                is not None
                else "无有效得物价格"
            )
        ),
    }


def product_key(item):
    url = item.get(
        "shihuo_url"
    )

    if url:
        return f"url:{url}"

    product_code = item.get(
        "product_code"
    )

    name = item.get(
        "name"
    )

    if product_code and name:
        return (
            f"code:{product_code}"
            f"|name:{name}"
        )

    return f"name:{name}"


def load_json(path):
    file = Path(path)

    if not file.exists():
        return {}

    try:
        return json.loads(
            file.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return {}


def main():

    market_data = load_json(
        INPUT_FILE
    )

    discovery_data = load_json(
        DISCOVERY_FILE
    )

    discovery_products = (
        discovery_data.get(
            "products"
        )
        or []
    )

    old_products = (
        market_data.get(
            "products"
        )
        or []
    )

    old_by_key = {}

    for item in old_products:

        key = product_key(
            item
        )

        old_by_key[key] = item

    products = []

    for raw in discovery_products:

        item = dict(raw)

        name = extract_product_name(
            item
        )

        if not name:
            continue

        buy_price = normalize_price(
            item.get(
                "buy_price"
            )
        )

        if buy_price is None:
            buy_price = extract_market_low_price(
                item
            )

        if buy_price is None:
            continue

        item["name"] = name
        item["buy_price"] = buy_price

        # 市场最低价证据
        market_low = (
            extract_market_low_price(
                item
            )
        )

        if market_low is not None:
            item[
                "market_low_price"
            ] = market_low

        # 价格证据
        price = calculate_price_evidence(
            item
        )

        item.update(
            {
                "dewu_channel_price":
                    price[
                        "dewu_channel_price"
                    ],

                "trend_current_price":
                    price[
                        "trend_current_price"
                    ],

                "price_current":
                    price[
                        "price_current"
                    ],

                "price_7d_low":
                    price[
                        "price_7d_low"
                    ],

                "price_7d_high":
                    price[
                        "price_7d_high"
                    ],

                "price_position_7d":
                    price[
                        "price_position_7d"
                    ],

                "downside_to_7d_low":
                    price[
                        "downside_to_7d_low"
                    ],

                "price_evidence_status":
                    price[
                        "price_evidence_status"
                    ],
            }
        )

        # --------------------------------------------------
        # 得物卖价：
        #
        # 只有明确“当前同款同规格到手价”时，
        # 才把它作为主要当前价格。
        #
        # 如果没有，则暂时保留得物渠道价，
        # 但同时记录价格证据状态。
        # --------------------------------------------------

        if (
            price[
                "trend_current_price"
            ]
            is not None
        ):
            item[
                "dewu_price"
            ] = price[
                "trend_current_price"
            ]

            item[
                "dewu_price_source"
            ] = (
                "识货公开页面："
                "当前同款同规格到手价"
            )

        elif (
            price[
                "dewu_channel_price"
            ]
            is not None
        ):
            item[
                "dewu_price"
            ] = price[
                "dewu_channel_price"
            ]

            item[
                "dewu_price_source"
            ] = (
                "识货公开页面："
                "得物渠道售价"
            )

        else:
            item[
                "dewu_price"
            ] = None

            item[
                "dewu_price_source"
            ] = None

        # --------------------------------------------------
        # 销量
        # --------------------------------------------------

        sales_30d = item.get(
            "sales_30d"
        )

        sales = item.get(
            "sales"
        )

        if (
            sales_30d is not None
            and sales_30d > 0
        ):
            item[
                "sales_velocity_7d"
            ] = round(
                float(sales_30d)
                / 30,
                2,
            )

            item[
                "turnover_evidence"
            ] = (
                f"月销{float(sales_30d):g}"
                f"，日均"
                f"{float(sales_30d) / 30:.2f}"
            )

            item[
                "turnover_confidence"
            ] = "medium"

        elif (
            sales is not None
            and sales > 0
        ):
            item[
                "turnover_evidence"
            ] = (
                f"累计销量"
                f"{float(sales):g}"
            )

            item[
                "turnover_confidence"
            ] = "low"

        else:
            item[
                "turnover_evidence"
            ] = None

            item[
                "turnover_confidence"
            ] = "unknown"

        # --------------------------------------------------
        # 识货来源
        # --------------------------------------------------

        item[
            "shihuo_source"
        ] = True

        item[
            "discovery_data_source"
        ] = (
            "识货公开页面"
        )

        # 正品规则：
        # 识货来源按用户规则默认通过，
        # 但不伪造 authenticity_verified=true。
        item[
            "authenticity_evidence"
        ] = (
            "识货公开页面来源，"
            "按规则默认正品风险通过"
        )

        # 保留原始字段
        item[
            "source_note"
        ] = (
            "数据来自识货公开页面；"
            "得物价格字段保持来源区分"
        )

        key = product_key(
            item
        )

        old = old_by_key.get(
            key
        )

        if old:
            # 只补缺失字段，
            # 不用旧数据覆盖新采集数据。
            for field, value in old.items():

                if (
                    item.get(field)
                    is None
                    and value is not None
                ):
                    item[field] = value

        products.append(
            item
        )

    output = {
        "updated_at": (
            discovery_data.get(
                "updated_at"
            )
        ),

        "count": len(products),

        "products": products,
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
        f"最终整理商品数："
        f"{len(products)}"
    )

    print(
        "=============================="
    )

    for item in products[:20]:

        print(
            f"\n商品："
            f"{item.get('name')}"
        )

        print(
            f"买入价："
            f"{item.get('buy_price')}"
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
            f"最终得物价格："
            f"{item.get('dewu_price')}"
        )

        print(
            f"价格来源："
            f"{item.get('dewu_price_source')}"
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
            f"价格证据："
            f"{item.get('price_evidence_status')}"
        )

        print(
            f"销量证据："
            f"{item.get('turnover_evidence')}"
        )


if __name__ == "__main__":
    main()
