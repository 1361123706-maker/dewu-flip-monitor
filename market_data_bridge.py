import json
from pathlib import Path
from datetime import datetime, timezone


INPUT_FILE = "discovery_data.json"
OUTPUT_FILE = "products.json"


# ============================================================
# 基础工具
# ============================================================

def to_float(value):
    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


def money(value):
    number = to_float(value)

    if number is None:
        return None

    return round(number, 2)


def first_value(item, *keys):
    for key in keys:
        value = item.get(key)

        if value is not None:
            if isinstance(value, str):
                if value.strip():
                    return value.strip()
            else:
                return value

    return None


# ============================================================
# 读取数据
# ============================================================

def load_json(path):
    file = Path(path)

    if not file.exists():
        print(
            f"找不到文件：{path}"
        )
        return None

    try:
        return json.loads(
            file.read_text(
                encoding="utf-8"
            )
        )
    except Exception as e:
        print(
            f"读取 {path} 失败：",
            e,
        )
        return None


def get_items(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in (
        "products",
        "items",
        "results",
        "data",
    ):

        value = data.get(key)

        if isinstance(
            value,
            list,
        ):
            return value

    return []


# ============================================================
# 价格
# ============================================================

def extract_dewu_channel_price(item):

    candidates = [
        item.get(
            "dewu_channel_price"
        ),
        item.get(
            "dewu_display_price"
        ),
    ]

    for value in candidates:

        number = to_float(value)

        if (
            number is not None
            and number > 0
        ):
            return number

    return None


def extract_trend_current_price(item):

    candidates = [
        item.get(
            "trend_current_price"
        ),
        item.get(
            "price_current"
        ),
    ]

    for value in candidates:

        number = to_float(value)

        if (
            number is not None
            and number > 0
        ):
            return number

    return None


def extract_explicit_7d_low(item):

    candidates = [
        item.get(
            "price_7d_low"
        ),
        item.get(
            "trend_7d_low"
        ),
    ]

    for value in candidates:

        number = to_float(value)

        if (
            number is not None
            and number > 0
        ):
            return number

    return None


def extract_explicit_7d_high(item):

    candidates = [
        item.get(
            "price_7d_high"
        ),
        item.get(
            "trend_7d_high"
        ),
    ]

    for value in candidates:

        number = to_float(value)

        if (
            number is not None
            and number > 0
        ):
            return number

    return None


def calculate_price_evidence(item):

    dewu_channel_price = (
        extract_dewu_channel_price(
            item
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

    # --------------------------------------------------------
    # 价格证据
    # --------------------------------------------------------

    if (
        trend_current_price is not None
        and trend_current_price > 0
    ):

        current_price = (
            trend_current_price
        )

        evidence_status = (
            "confirmed_current_price"
        )

    elif (
        dewu_channel_price is not None
        and dewu_channel_price > 0
    ):

        current_price = (
            dewu_channel_price
        )

        evidence_status = (
            "channel_price_only"
        )

    else:

        current_price = None

        evidence_status = (
            "no_dewu_price"
        )

    position = None
    downside = None

    if (
        current_price is not None
        and price_7d_low is not None
        and price_7d_high is not None
        and price_7d_high > price_7d_low
    ):

        position = (
            (
                current_price
                - price_7d_low
            )
            / (
                price_7d_high
                - price_7d_low
            )
            * 100
        )

        position = round(
            max(
                0,
                min(
                    100,
                    position,
                ),
            ),
            2,
        )

    if (
        current_price is not None
        and price_7d_low is not None
        and current_price > 0
        and price_7d_low <= current_price
    ):

        downside = (
            (
                current_price
                - price_7d_low
            )
            / current_price
            * 100
        )

        downside = round(
            max(
                0,
                downside,
            ),
            2,
        )

    return {

        "dewu_channel_price":
            money(
                dewu_channel_price
            ),

        "trend_current_price":
            money(
                trend_current_price
            ),

        "price_current":
            money(
                current_price
            ),

        "price_7d_low":
            money(
                price_7d_low
            ),

        "price_7d_high":
            money(
                price_7d_high
            ),

        "price_position_7d":
            position,

        "downside_to_7d_low":
            downside,

        "price_evidence_status":
            evidence_status,
    }


# ============================================================
# 买入价格
# ============================================================

def extract_buy_price(item):

    candidates = [
        item.get(
            "buy_price"
        ),
        item.get(
            "market_low_price"
        ),
        item.get(
            "lowest_price"
        ),
        item.get(
            "price"
        ),
    ]

    for value in candidates:

        number = to_float(value)

        if (
            number is not None
            and number > 0
        ):
            return number

    # 最后尝试 size_price_map
    size_prices = item.get(
        "size_price_map"
    )

    if isinstance(
        size_prices,
        dict,
    ):

        values = []

        for value in (
            size_prices.values()
        ):

            number = to_float(
                value
            )

            if (
                number is not None
                and number > 0
            ):
                values.append(
                    number
                )

        if values:
            return min(values)

    return None


# ============================================================
# SKU / 规格
# ============================================================

def extract_size_price_map(item):

    raw = item.get(
        "size_price_map"
    )

    if not isinstance(
        raw,
        dict,
    ):
        return {}

    result = {}

    for size, price in raw.items():

        number = to_float(
            price
        )

        if (
            number is None
            or number <= 0
        ):
            continue

        size_text = str(
            size
        ).strip()

        if not size_text:
            continue

        result[
            size_text
        ] = money(
            number
        )

    return result


def extract_current_size(item):

    candidates = [
        item.get(
            "current_size"
        ),
        item.get(
            "size"
        ),
    ]

    for value in candidates:

        if value is None:
            continue

        text = str(
            value
        ).strip()

        if text:
            return text

    selected_variant = item.get(
        "selected_variant"
    )

    if selected_variant:

        text = str(
            selected_variant
        ).strip()

        for separator in (
            ",",
            "，",
        ):

            if separator in text:

                parts = text.split(
                    separator
                )

                if len(parts) >= 2:

                    value = parts[-1].strip()

                    if value:
                        return value

    return None


def extract_selected_variant(item):

    value = item.get(
        "selected_variant"
    )

    if value is None:
        return None

    text = str(
        value
    ).strip()

    return (
        text
        if text
        else None
    )


# ============================================================
# 商品信息
# ============================================================

def extract_product_code(item):

    value = first_value(
        item,
        "product_code",
        "goods_code",
        "style_code",
        "sku_code",
    )

    if value is None:
        return None

    return str(
        value
    ).strip()


def extract_color(item):

    value = first_value(
        item,
        "color",
        "current_color",
        "selected_color",
    )

    if value is None:
        return None

    return str(
        value
    ).strip()


def extract_name(item):

    value = first_value(
        item,
        "name",
        "title",
        "product_name",
    )

    if value is None:
        return None

    return str(
        value
    ).strip()


# ============================================================
# 销量
# ============================================================

def extract_sales_7d(item):

    candidates = [
        item.get(
            "sales_7d"
        ),
        item.get(
            "sales_7days"
        ),
    ]

    for value in candidates:

        number = to_float(
            value
        )

        if (
            number is not None
            and number > 0
        ):
            return number

    return None


def extract_sales_30d(item):

    candidates = [
        item.get(
            "sales_30d"
        ),
        item.get(
            "monthly_sales"
        ),
        item.get(
            "month_sales"
        ),
    ]

    for value in candidates:

        number = to_float(
            value
        )

        if (
            number is not None
            and number > 0
        ):
            return number

    return None


def extract_sales_total(item):

    candidates = [
        item.get(
            "sales_total"
        ),
        item.get(
            "total_sales"
        ),
    ]

    for value in candidates:

        number = to_float(
            value
        )

        if (
            number is not None
            and number > 0
        ):
            return number

    return None


# ============================================================
# 周转证据
# ============================================================

def build_turnover_evidence(
    sales_7d,
    sales_30d,
):

    if (
        sales_7d is not None
        and sales_7d > 0
    ):

        velocity = (
            sales_7d / 7
        )

        return (
            f"近7日销量 {sales_7d:g}，"
            f"日均约 {velocity:.2f}",
            "high",
            velocity,
        )

    if (
        sales_30d is not None
        and sales_30d > 0
    ):

        velocity = (
            sales_30d / 30
        )

        return (
            f"月销 {sales_30d:g}，"
            f"日均约 {velocity:.2f}",
            "medium",
            velocity,
        )

    return (
        None,
        "unknown",
        None,
    )


# ============================================================
# 商品资格
# ============================================================

def build_product(item):

    price = calculate_price_evidence(
        item
    )

    buy_price = extract_buy_price(
        item
    )

    size_price_map = (
        extract_size_price_map(
            item
        )
    )

    current_size = (
        extract_current_size(
            item
        )
    )

    selected_variant = (
        extract_selected_variant(
            item
        )
    )

    sales_7d = extract_sales_7d(
        item
    )

    sales_30d = extract_sales_30d(
        item
    )

    sales_total = extract_sales_total(
        item
    )

    (
        turnover_evidence,
        turnover_confidence,
        sales_velocity_7d,
    ) = build_turnover_evidence(
        sales_7d,
        sales_30d,
    )

    product = dict(item)

    # --------------------------------------------------------
    # 商品基本信息
    # --------------------------------------------------------

    product["name"] = (
        extract_name(item)
    )

    product["product_code"] = (
        extract_product_code(item)
    )

    product["color"] = (
        extract_color(item)
    )

    product["current_size"] = (
        current_size
    )

    product["selected_variant"] = (
        selected_variant
    )

    # --------------------------------------------------------
    # SKU
    # --------------------------------------------------------

    product["size_price_map"] = (
        size_price_map
    )

    product["size_price_status"] = (
        "available"
        if size_price_map
        else "not_available"
    )

    if size_price_map:

        if current_size:

            current_size_price = (
                size_price_map.get(
                    current_size
                )
            )

            if (
                current_size_price
                is not None
            ):

                product[
                    "sku_price_status"
                ] = (
                    "current_size_confirmed"
                )

                product[
                    "buy_price"
                ] = money(
                    current_size_price
                )

            else:

                product[
                    "sku_price_status"
                ] = (
                    "size_prices_available_but_current_size_unknown"
                )

                # 不随便把其他尺码价格冒充当前尺码
                if buy_price is not None:
                    product[
                        "buy_price"
                    ] = money(
                        buy_price
                    )

        else:

            product[
                "sku_price_status"
            ] = (
                "size_prices_available_but_current_size_unknown"
            )

    else:

        product[
            "sku_price_status"
        ] = (
            "product_level_price"
        )

        if buy_price is not None:

            product[
                "buy_price"
            ] = money(
                buy_price
            )

    # --------------------------------------------------------
    # 价格
    # --------------------------------------------------------

    product[
        "dewu_channel_price"
    ] = price[
        "dewu_channel_price"
    ]

    product[
        "trend_current_price"
    ] = price[
        "trend_current_price"
    ]

    product[
        "price_current"
    ] = price[
        "price_current"
    ]

    product[
        "price_7d_low"
    ] = price[
        "price_7d_low"
    ]

    product[
        "price_7d_high"
    ] = price[
        "price_7d_high"
    ]

    product[
        "price_position_7d"
    ] = price[
        "price_position_7d"
    ]

    product[
        "downside_to_7d_low"
    ] = price[
        "downside_to_7d_low"
    ]

    product[
        "price_evidence_status"
    ] = price[
        "price_evidence_status"
    ]

    # --------------------------------------------------------
    # 得物售价
    #
    # 注意：
    # 利润计算优先使用得物渠道售价。
    # --------------------------------------------------------

    if (
        price[
            "dewu_channel_price"
        ]
        is not None
    ):

        product[
            "dewu_price"
        ] = price[
            "dewu_channel_price"
        ]

        product[
            "dewu_price_source"
        ] = (
            "识货：得物渠道售价"
        )

        product[
            "income_confirmed"
        ] = False

        product[
            "income_confirmation_reason"
        ] = (
            "使用识货采集到的得物渠道售价，"
            "利润按估算公式计算"
        )

    elif (
        price[
            "trend_current_price"
        ]
        is not None
    ):

        product[
            "dewu_price"
        ] = price[
            "trend_current_price"
        ]

        product[
            "dewu_price_source"
        ] = (
            "识货：当前同款同规格到手价"
        )

        product[
            "income_confirmed"
        ] = True

        product[
            "income_confirmation_reason"
        ] = (
            "识货采集到当前同款同规格到手价"
        )

    else:

        product[
            "dewu_price"
        ] = None

        product[
            "dewu_price_source"
        ] = None

        product[
            "income_confirmed"
        ] = False

        product[
            "income_confirmation_reason"
        ] = (
            "没有有效得物价格"
        )

    # --------------------------------------------------------
    # 销量
    # --------------------------------------------------------

    product[
        "sales_7d"
    ] = (
        money(sales_7d)
        if sales_7d is not None
        else None
    )

    product[
        "sales_30d"
    ] = (
        money(sales_30d)
        if sales_30d is not None
        else None
    )

    product[
        "sales_total"
    ] = (
        money(sales_total)
        if sales_total is not None
        else None
    )

    product[
        "sales_velocity_7d"
    ] = (
        round(
            sales_velocity_7d,
            2,
        )
        if sales_velocity_7d is not None
        else None
    )

    product[
        "turnover_evidence"
    ] = turnover_evidence

    product[
        "turnover_confidence"
    ] = turnover_confidence

    # --------------------------------------------------------
    # 来源
    # --------------------------------------------------------

    product[
        "shihuo_source"
    ] = True

    if not product.get(
        "source_note"
    ):

        product[
            "source_note"
        ] = (
            "市场商品数据来源：识货"
        )

    # 识货明确有正品保障时，
    # 默认正品风险通过。
    if (
        product.get(
            "authenticity_evidence"
        )
        is None
    ):

        product[
            "authenticity_evidence"
        ] = (
            "识货来源，正品风险按来源保障通过"
        )

    # --------------------------------------------------------
    # 保留全新 / 得物兼容状态
    # --------------------------------------------------------

    if (
        "new_condition_verified"
        not in product
    ):

        product[
            "new_condition_verified"
        ] = None

    if (
        "dewu_check_compatible"
        not in product
    ):

        product[
            "dewu_check_compatible"
        ] = None

    # --------------------------------------------------------
    # 最终状态
    # --------------------------------------------------------

    product[
        "bridge_updated_at"
    ] = datetime.now(
        timezone.utc
    ).isoformat()

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

            if product is None:
                continue

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
        "SKU价格表：",
        sum(
            1
            for x in products
            if x.get(
                "size_price_map"
            )
        )
    )

    print(
        "货号已确认：",
        sum(
            1
            for x in products
            if x.get(
                "product_code"
            )
        )
    )

    print(
        "配色已确认：",
        sum(
            1
            for x in products
            if x.get(
                "color"
            )
        )
    )

    print(
        "得物渠道售价：",
        sum(
            1
            for x in products
            if x.get(
                "dewu_channel_price"
            )
            is not None
        )
    )

    print(
        "7日最低价：",
        sum(
            1
            for x in products
            if x.get(
                "price_7d_low"
            )
            is not None
        )
    )

    print(
        "月销量：",
        sum(
            1
            for x in products
            if x.get(
                "sales_30d"
            )
            is not None
        )
    )

    print(
        "=============================="
    )


if __name__ == "__main__":
    main()
