import json
from pathlib import Path
from datetime import datetime, timezone


INPUT_FILE = "discovery_data.json"
OUTPUT_FILE = "products.json"


# ============================================================
# 基础
# ============================================================

def to_float(value):
    if value is None:
        return None

    try:
        if isinstance(value, str):
            value = value.replace(",", "")
            value = value.replace("¥", "")
            value = value.replace("￥", "")
            value = value.replace("元", "")
            value = value.strip()

        number = float(value)

        if number <= 0:
            return None

        return number

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

        if value is None:
            continue

        if isinstance(value, str):
            if value.strip():
                return value.strip()
        else:
            return value

    return None


# ============================================================
# 读取
# ============================================================

def load_json(path):
    file = Path(path)

    if not file.exists():
        print(f"找不到文件：{path}")
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
            e
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

        if isinstance(value, list):
            return value

    return []


# ============================================================
# 商品身份
# ============================================================

def get_product_code(item):
    value = first_value(
        item,
        "product_code",
        "goods_code",
        "style_code",
        "sku_code",
    )

    if value is None:
        return None

    return str(value).strip()


def get_color(item):
    value = first_value(
        item,
        "color",
        "current_color",
        "selected_color",
    )

    if value is None:
        return None

    return str(value).strip()


def get_size(item):
    value = first_value(
        item,
        "current_size",
        "size",
    )

    if value is not None:
        return str(value).strip()

    variant = item.get(
        "selected_variant"
    )

    if variant:
        text = str(variant).strip()

        for separator in (
            ",",
            "，",
        ):
            if separator in text:
                parts = text.split(separator)

                if len(parts) >= 2:
                    return parts[-1].strip()

    return None


def get_variant(item):
    value = item.get(
        "selected_variant"
    )

    if value is None:
        return None

    value = str(value).strip()

    return value if value else None


# ============================================================
# 尺码价格表
# ============================================================

def get_size_price_map(item):
    raw = item.get(
        "size_price_map"
    )

    if not isinstance(raw, dict):
        return {}

    result = {}

    for size, price in raw.items():
        number = to_float(price)

        if number is None or number <= 0:
            continue

        size_text = str(size).strip()

        if not size_text:
            continue

        result[size_text] = money(number)

    return result


def get_current_size_buy_price(
    item,
    size_price_map,
):
    size = get_size(item)

    if not size:
        return None

    return size_price_map.get(size)


def get_lowest_size_price(
    size_price_map,
):
    values = [
        price
        for price in size_price_map.values()
        if to_float(price) is not None
    ]

    if not values:
        return None

    return min(values)


# ============================================================
# 买入价
# ============================================================

def get_base_buy_price(item):

    candidates = [
        item.get(
            "best_effective_buy_price"
        ),

        item.get(
            "final_buy_price"
        ),

        item.get(
            "effective_buy_price"
        ),

        item.get(
            "estimated_final_price"
        ),

        item.get(
            "buy_price"
        ),

        item.get(
            "sku_buy_price"
        ),

        item.get(
            "market_low_price"
        ),

        item.get(
            "price"
        ),
    ]
    for value in candidates:
        number = to_float(value)

        if number is not None:
            return number

    return None


def get_buy_price_info(item):

    size_price_map = get_size_price_map(item)

    current_size = get_size(item)

    # 当前尺码有明确价格
    if current_size:
        size_price = size_price_map.get(
            current_size
        )

        if size_price is not None:
            return (
                money(size_price),
                "识货当前尺码价格",
                "confirmed_sku_price",
            )

    # 只有一个尺码
    if len(size_price_map) == 1:
        only_price = next(
            iter(size_price_map.values())
        )

        return (
            money(only_price),
            "识货唯一尺码价格",
            "confirmed_single_sku_price",
        )

    # 不把其他尺码最低价冒充当前尺码
    base_price = get_base_buy_price(item)

    if base_price is not None:
        return (
            money(base_price),
            "商品/活动价格，尺码未确认",
            "product_level_price",
        )

    return (
        None,
        None,
        "no_buy_price",
    )


# ============================================================
# 得物价格
# ============================================================

def get_dewu_channel_price(item):

    candidates = [
        item.get("dewu_channel_price"),
        item.get("dewu_display_price"),
    ]

    for value in candidates:
        number = to_float(value)

        if number is not None:
            return money(number)

    return None


def get_trend_current_price(item):

    candidates = [
        item.get("trend_current_price"),
        item.get("price_current"),
    ]

    for value in candidates:
        number = to_float(value)

        if number is not None:
            return money(number)

    return None


def build_dewu_price(item):

    channel_price = get_dewu_channel_price(item)

    trend_price = get_trend_current_price(item)

    # 得物渠道售价优先
    if channel_price is not None:
        return (
            channel_price,
            "识货：得物渠道售价",
            "channel_price",
        )

    # 没有渠道售价才使用当前同款同规格价格
    if trend_price is not None:
        return (
            trend_price,
            "识货：当前同款同规格到手价",
            "current_price",
        )

    return (
        None,
        None,
        "no_dewu_price",
    )


# ============================================================
# 7日价格
# ============================================================

def get_7d_low(item):

    for key in (
        "price_7d_low",
        "trend_7d_low",
        "lowest_price",
    ):
        number = to_float(
            item.get(key)
        )

        if number is not None:
            return money(number)

    return None


def get_7d_high(item):

    for key in (
        "price_7d_high",
        "trend_7d_high",
    ):
        number = to_float(
            item.get(key)
        )

        if number is not None:
            return money(number)

    return None


def calculate_price_risk(
    current_price,
    low_7d,
    high_7d,
):

    downside = None
    position = None

    if (
        current_price is not None
        and low_7d is not None
        and current_price > 0
        and low_7d <= current_price
    ):
        downside = (
            (
                current_price - low_7d
            )
            / current_price
            * 100
        )

        downside = round(
            max(0, downside),
            2,
        )

    if (
        current_price is not None
        and low_7d is not None
        and high_7d is not None
        and high_7d > low_7d
    ):
        position = (
            (
                current_price - low_7d
            )
            / (
                high_7d - low_7d
            )
            * 100
        )

        position = round(
            max(
                0,
                min(100, position),
            ),
            2,
        )

    return (
        downside,
        position,
    )


# ============================================================
# 销量 / 周转
# ============================================================

def get_sales(item):

    sales_7d = to_float(
        first_value(
            item,
            "sales_7d",
            "sales_7days",
        )
    )

    sales_30d = to_float(
        first_value(
            item,
            "sales_30d",
            "monthly_sales",
            "month_sales",
        )
    )

    sales_total = to_float(
        first_value(
            item,
            "sales_total",
            "total_sales",
        )
    )

    velocity = None
    evidence = None
    confidence = "unknown"

    if (
        sales_7d is not None
        and sales_7d > 0
    ):
        velocity = round(
            sales_7d / 7,
            2,
        )

        evidence = (
            f"近7日销量 {sales_7d:g}，"
            f"日均约 {velocity:.2f}"
        )

        confidence = "high"

    elif (
        sales_30d is not None
        and sales_30d > 0
    ):
        velocity = round(
            sales_30d / 30,
            2,
        )

        evidence = (
            f"月销 {sales_30d:g}，"
            f"日均约 {velocity:.2f}"
        )

        confidence = "medium"

    elif (
        sales_total is not None
        and sales_total > 0
    ):
        evidence = (
            f"累计/全网销量 {sales_total:g}，"
            "不能直接作为7日周转速度"
        )

        confidence = "low"

    return {
        "sales_7d": (
            money(sales_7d)
            if sales_7d is not None
            else None
        ),
        "sales_30d": (
            money(sales_30d)
            if sales_30d is not None
            else None
        ),
        "sales_total": (
            money(sales_total)
            if sales_total is not None
            else None
        ),
        "sales_velocity_7d": velocity,
        "turnover_evidence": evidence,
        "turnover_confidence": confidence,
    }


# ============================================================
# 活动 / 优惠券
# ============================================================

def get_effective_buy_price(item):

    candidates = [
        item.get("effective_buy_price"),
        item.get("estimated_final_price"),
        item.get("final_buy_price"),
    ]

    for value in candidates:
        number = to_float(value)

        if number is not None:
            return money(number)

    return None


def get_coupon_urls(item):

    value = item.get("coupon_urls")

    if not isinstance(value, list):
        return []

    result = []

    for url in value:
        if not url:
            continue

        text = str(url).strip()

        if text and text not in result:
            result.append(text)

    return result


def get_official_store_links(item):

    value = item.get(
        "official_store_links"
    )

    if not isinstance(value, list):
        return []

    return value


# ============================================================
# 正品 / 全新 / 得物兼容
# ============================================================

def get_authenticity_status(item):

    evidence = item.get(
        "authenticity_evidence"
    )

    if evidence:
        return (
            True,
            str(evidence),
        )

    if item.get("shihuo_source"):
        return (
            True,
            "商品来源为识货，按识货正品保障处理",
        )

    return (
        False,
        "没有识货来源证据",
    )


def get_new_condition(item):

    value = item.get(
        "new_condition_verified"
    )

    if value is True:
        return True

    if value is False:
        return False

    return None


def get_dewu_compatible(item):

    value = item.get(
        "dewu_check_compatible"
    )

    if value is True:
        return True

    if value is False:
        return False

    return None


# ============================================================
# 构建最终商品
# ============================================================

def build_product(item):

    product = dict(item)

    product["name"] = first_value(
        item,
        "name",
        "title",
        "product_name",
    )

    product["product_code"] = get_product_code(
        item
    )

    product["color"] = get_color(
        item
    )

    product["current_size"] = get_size(
        item
    )

    product["selected_variant"] = get_variant(
        item
    )

    # --------------------------------------------------------
    # SKU
    # --------------------------------------------------------

    size_price_map = get_size_price_map(
        item
    )

    product["size_price_map"] = (
        size_price_map
    )

    sku_buy_price = (
        get_current_size_buy_price(
            item,
            size_price_map,
        )
    )

    if sku_buy_price is not None:

        product["sku_buy_price"] = money(
            sku_buy_price
        )

        product["sku_price_status"] = (
            "confirmed_current_size"
        )

    elif (
        size_price_map
        and product["current_size"] is None
    ):

        product["sku_buy_price"] = None

        product["sku_price_status"] = (
            "size_prices_available_but_current_size_unknown"
        )

    else:

        product["sku_buy_price"] = None

        product["sku_price_status"] = (
            "no_sku_price"
        )

    # --------------------------------------------------------
    # 活动后价格
    # --------------------------------------------------------

    effective_buy_price = (
        get_effective_buy_price(item)
    )

    product["effective_buy_price"] = (
        effective_buy_price
    )

    product["buy_price_before_discount"] = (
        money(
            item.get(
                "buy_price_before_discount"
            )
        )
    )

    product["discount_total"] = (
        money(
            item.get("discount_total")
        )
    )

    product["coupon_urls"] = (
        get_coupon_urls(item)
    )

    product["official_store_links"] = (
        get_official_store_links(item)
    )

    # --------------------------------------------------------
    # 最终买入价
    # --------------------------------------------------------

    (
        buy_price,
        buy_source,
        buy_status,
    ) = get_buy_price_info(item)

    if effective_buy_price is not None:

        final_buy_price = (
            effective_buy_price
        )

        final_buy_source = (
            "活动后明确到手价"
        )

        final_buy_status = (
            "estimated_after_discount"
        )

    elif buy_price is not None:

        final_buy_price = buy_price
        final_buy_source = buy_source
        final_buy_status = buy_status

    else:

        final_buy_price = None
        final_buy_source = None
        final_buy_status = (
            "no_buy_price"
        )

    product["buy_price"] = (
        final_buy_price
    )

    product["buy_price_source"] = (
        final_buy_source
    )

    product["buy_price_status"] = (
        final_buy_status
    )

    # --------------------------------------------------------
    # 得物价格
    # --------------------------------------------------------

    (
        dewu_price,
        dewu_source,
        dewu_status,
    ) = build_dewu_price(item)

    product["dewu_channel_price"] = (
        get_dewu_channel_price(item)
    )

    product["trend_current_price"] = (
        get_trend_current_price(item)
    )

    product["dewu_price"] = dewu_price

    product["dewu_price_source"] = (
        dewu_source
    )

    product["dewu_price_status"] = (
        dewu_status
    )

    # --------------------------------------------------------
    # 7日趋势
    # --------------------------------------------------------

    low_7d = get_7d_low(item)

    high_7d = get_7d_high(item)

    current_price = (
        product["trend_current_price"]
        or product["dewu_channel_price"]
    )

    (
        downside,
        position,
    ) = calculate_price_risk(
        current_price,
        low_7d,
        high_7d,
    )

    product["price_7d_low"] = low_7d

    product["price_7d_high"] = high_7d

    product["price_current"] = (
        money(current_price)
        if current_price is not None
        else None
    )

    product["downside_to_7d_low"] = (
        downside
    )

    product["price_position_7d"] = (
        position
    )

    product["price_evidence_status"] = (
        "confirmed"
        if current_price is not None
        else "missing"
    )

    # --------------------------------------------------------
    # 周转
    # --------------------------------------------------------

    sales = get_sales(item)

    product.update(sales)

    # --------------------------------------------------------
    # 正品
    # --------------------------------------------------------

    (
        authenticity_ok,
        authenticity_reason,
    ) = get_authenticity_status(item)

    product["authenticity_verified"] = (
        authenticity_ok
    )

    product["authenticity_evidence"] = (
        authenticity_reason
    )

    # --------------------------------------------------------
    # 全新 / 得物兼容
    # --------------------------------------------------------

    product["new_condition_verified"] = (
        get_new_condition(item)
    )

    product["dewu_check_compatible"] = (
        get_dewu_compatible(item)
    )

    # --------------------------------------------------------
    # 活动信息
    # --------------------------------------------------------

    product["buy_platform"] = item.get(
        "buy_platform"
    )

    product["store_type"] = item.get(
        "store_type"
    )

    product["buy_url"] = item.get(
        "buy_url"
    )

    product["coupon_evidence"] = item.get(
        "coupon_evidence",
        [],
    )

    # --------------------------------------------------------
    # 估算利润状态
    # --------------------------------------------------------

    if (
        dewu_price is not None
        and final_buy_price is not None
    ):

        product[
            "estimated_profit_status"
        ] = "estimated_ready"

        product[
            "estimated_profit_confirmation"
        ] = (
            "已具备买入价和得物售价，"
            "可以按统一估算公式计算"
        )

    elif dewu_price is not None:

        product[
            "estimated_profit_status"
        ] = "missing_buy_price"

        product[
            "estimated_profit_confirmation"
        ] = (
            "已有得物售价，但缺少有效买入价"
        )

    elif final_buy_price is not None:

        product[
            "estimated_profit_status"
        ] = "missing_dewu_price"

        product[
            "estimated_profit_confirmation"
        ] = (
            "已有买入价，但缺少有效得物售价"
        )

    else:

        product[
            "estimated_profit_status"
        ] = "not_ready"

        product[
            "estimated_profit_confirmation"
        ] = (
            "买入价和得物售价均不足"
        )

    # 兼容旧代码
    product["income_confirmed"] = (
        product[
            "estimated_profit_status"
        ] == "estimated_ready"
    )

    product[
        "income_confirmation_reason"
    ] = product[
        "estimated_profit_confirmation"
    ]

    # --------------------------------------------------------
    # 证据完整度
    # --------------------------------------------------------

    evidence = {
        "product_code": bool(
            product.get(
                "product_code"
            )
        ),

        "color": bool(
            product.get(
                "color"
            )
        ),

        "size_price_map": bool(
            product.get(
                "size_price_map"
            )
        ),

        "current_size": bool(
            product.get(
                "current_size"
            )
        ),

        "buy_price": (
            final_buy_price is not None
        ),

        "dewu_price": (
            dewu_price is not None
        ),

        "price_7d_low": (
            low_7d is not None
        ),

        "price_7d_high": (
            high_7d is not None
        ),

        "turnover": (
            sales[
                "turnover_confidence"
            ] != "unknown"
        ),

        "official_store": bool(
            product.get(
                "official_store_links"
            )
        ),

        "coupon": bool(
            product.get(
                "coupon_urls"
            )
            or product.get(
                "coupon_evidence"
            )
        ),
    }

    product["evidence"] = evidence

    product["evidence_count"] = sum(
        1
        for value in evidence.values()
        if value
    )

    product["bridge_updated_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

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
        "货号：",
        sum(
            bool(
                x.get("product_code")
            )
            for x in products
        )
    )

    print(
        "配色：",
        sum(
            bool(
                x.get("color")
            )
            for x in products
        )
    )

    print(
        "SKU尺码价格表：",
        sum(
            bool(
                x.get("size_price_map")
            )
            for x in products
        )
    )

    print(
        "得物渠道售价：",
        sum(
            x.get(
                "dewu_channel_price"
            ) is not None
            for x in products
        )
    )

    print(
        "7日最低价：",
        sum(
            x.get(
                "price_7d_low"
            ) is not None
            for x in products
        )
    )

    print(
        "周转证据：",
        sum(
            x.get(
                "turnover_confidence"
            ) != "unknown"
            for x in products
        )
    )

    print(
        "活动后价格：",
        sum(
            x.get(
                "effective_buy_price"
            ) is not None
            for x in products
        )
    )

    print(
        "=============================="
    )


if __name__ == "__main__":
    main()