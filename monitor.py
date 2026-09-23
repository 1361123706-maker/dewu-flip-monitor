import json
from pathlib import Path
from datetime import datetime, timezone


INPUT_FILE = "products.json"
OUTPUT_FILE = "monitor_results.json"


# ============================================================
# 核心规则
# ============================================================

CAPITAL = 330

MAX_DAYS = 7

MIN_PROFIT = 15

MIN_PROFIT_RATE = 12

MAX_DOWNSIDE_LOSS = 25

# 得物售价按 92% 计算估算到账
DEWU_NET_RATE = 0.92

# 买入运费固定按 6 元估算
DEFAULT_BUY_SHIPPING = 6


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
    if value is None:
        return None

    return round(float(value), 2)


def normalize_trend(value):
    if value is None:
        return None

    text = str(value).strip().lower()

    mapping = {
        "rising": "上涨",
        "rise": "上涨",
        "up": "上涨",
        "上涨": "上涨",

        "falling": "下跌",
        "fall": "下跌",
        "down": "下跌",
        "下跌": "下跌",

        "stable": "稳定",
        "flat": "稳定",
        "稳定": "稳定",
        "平稳": "稳定",
    }

    return mapping.get(
        text,
        text if text in {
            "上涨",
            "下跌",
            "稳定",
        } else None,
    )


# ============================================================
# 读取 products.json
# ============================================================

def load_products():
    path = Path(INPUT_FILE)

    if not path.exists():
        print(
            f"找不到 {INPUT_FILE}"
        )
        return []

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception as e:
        print(
            f"读取 {INPUT_FILE} 失败：",
            e,
        )
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        products = data.get(
            "products"
        )

        if isinstance(products, list):
            return products

        results = data.get(
            "results"
        )

        if isinstance(results, list):
            return results

    return []


# ============================================================
# 买入价格
# ============================================================

def get_buy_price(item):

    value = to_float(
        item.get("buy_price")
    )

    if value is None or value <= 0:
        return None

    return value


# ============================================================
# SKU 尺码价格
# ============================================================

def get_size_price_map(item):

    size_prices = item.get(
        "size_price_map"
    )

    if not isinstance(
        size_prices,
        dict,
    ):
        return {}

    result = {}

    for size, price in size_prices.items():

        number = to_float(price)

        if (
            number is None
            or number <= 0
        ):
            continue

        result[str(size).strip()] = number

    return result


def get_current_size(item):

    # 采集器直接提供的当前尺码
    candidates = [
        item.get("current_size"),
        item.get("size"),
        item.get("sku_size"),
    ]

    for value in candidates:

        if value is None:
            continue

        text = str(value).strip()

        if text:
            return text

    # selected_variant 例如：
    # 黑色/白色, 36
    selected_variant = item.get(
        "selected_variant"
    )

    if selected_variant:

        text = str(
            selected_variant
        ).strip()

        if "," in text:
            parts = text.split(",")

            if len(parts) >= 2:

                size = parts[-1].strip()

                if size:
                    return size

        if "，" in text:
            parts = text.split("，")

            if len(parts) >= 2:

                size = parts[-1].strip()

                if size:
                    return size

    return None


def get_sku_buy_price(
    item,
    sku_size,
):
    """
    SKU 买入价必须对应具体尺码。

    如果存在 size_price_map：
        优先读取该尺码价格。

    如果没有：
        才退回商品级 buy_price。
    """

    size_prices = get_size_price_map(
        item
    )

    if size_prices:

        if sku_size is None:
            return None

        sku_size = str(
            sku_size
        ).strip()

        if sku_size in size_prices:
            return size_prices[
                sku_size
            ]

        # 尝试忽略空格
        normalized = (
            sku_size.replace(
                " ",
                ""
            )
        )

        for size, price in size_prices.items():

            if (
                size.replace(
                    " ",
                    ""
                )
                == normalized
            ):
                return price

        return None

    return get_buy_price(item)


def get_sku_context(item):

    size_prices = get_size_price_map(
        item
    )

    current_size = get_current_size(
        item
    )

    # 有尺码价格表时，
    # 必须明确当前尺码才能把利润归属于具体 SKU。
    if size_prices:

        if current_size is None:
            return []

        buy_price = get_sku_buy_price(
            item,
            current_size,
        )

        if buy_price is None:
            return []

        return [
            (
                current_size,
                buy_price,
            )
        ]

    # 没有尺码价格表，
    # 允许使用商品级价格作为最后兜底。
    buy_price = get_buy_price(
        item
    )

    if buy_price is None:
        return []

    return [
        (
            None,
            buy_price,
        )
    ]


# ============================================================
# 得物售价
# ============================================================

def get_dewu_price(item):
    """
    得物售价优先级：

    1. 得物渠道售价
    2. 当前同款同规格到手价
    3. 其他得物售价
    """

    channel_price = to_float(
        item.get(
            "dewu_channel_price"
        )
    )

    if (
        channel_price is not None
        and channel_price > 0
    ):
        return (
            channel_price,
            "识货：得物渠道售价",
            "channel_price",
        )

    trend_price = to_float(
        item.get(
            "trend_current_price"
        )
    )

    if (
        trend_price is not None
        and trend_price > 0
    ):
        return (
            trend_price,
            "识货：当前同款同规格到手价",
            "current_price",
        )

    dewu_price = to_float(
        item.get(
            "dewu_price"
        )
    )

    if (
        dewu_price is not None
        and dewu_price > 0
    ):
        return (
            dewu_price,
            "识货：得物售价",
            "dewu_price",
        )

    return (
        None,
        None,
        None,
    )


# ============================================================
# 买入运费
# ============================================================

def get_buy_shipping_cost(item):

    # 按用户确定的统一规则：
    # 固定估算 6 元。
    return (
        DEFAULT_BUY_SHIPPING,
        False,
    )


# ============================================================
# 估算利润
# ============================================================

def calculate_estimated_profit(
    dewu_price,
    buy_price,
    buy_shipping,
):
    """
    统一公式：

    估算利润
    =
    得物售价 × 92%
    − 买入价
    − 6元买入运费
    """

    if (
        dewu_price is None
        or buy_price is None
    ):
        return (
            None,
            None,
            None,
        )

    estimated_income = (
        dewu_price
        * DEWU_NET_RATE
    )

    total_cost = (
        buy_price
        + buy_shipping
    )

    estimated_profit = (
        estimated_income
        - total_cost
    )

    return (
        estimated_income,
        total_cost,
        estimated_profit,
    )


# ============================================================
# 价格证据
# ============================================================

def calculate_price_evidence(item):

    trend_price = to_float(
        item.get(
            "trend_current_price"
        )
    )

    channel_price = to_float(
        item.get(
            "dewu_channel_price"
        )
    )

    fallback_price = to_float(
        item.get(
            "dewu_price"
        )
    )

    if (
        trend_price is not None
        and trend_price > 0
    ):
        current_price = trend_price

    elif (
        channel_price is not None
        and channel_price > 0
    ):
        current_price = channel_price

    elif (
        fallback_price is not None
        and fallback_price > 0
    ):
        current_price = fallback_price

    else:
        current_price = None

    low = to_float(
        item.get(
            "price_7d_low"
        )
    )

    high = to_float(
        item.get(
            "price_7d_high"
        )
    )

    position = None
    downside = None

    if (
        current_price is not None
        and low is not None
        and high is not None
        and high > low
    ):

        position = (
            (
                current_price
                - low
            )
            / (
                high
                - low
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
        and low is not None
        and current_price > 0
        and 0 <= low <= current_price
    ):

        downside = (
            (
                current_price
                - low
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

    if (
        trend_price is not None
        and trend_price > 0
    ):

        status = (
            "confirmed_current_price"
        )

    elif (
        channel_price is not None
        and channel_price > 0
    ):

        status = (
            "channel_price_only"
        )

    elif (
        fallback_price is not None
        and fallback_price > 0
    ):

        status = (
            "dewu_price_only"
        )

    else:

        status = (
            "no_dewu_price"
        )

    return {
        "current": current_price,
        "low": low,
        "high": high,
        "position": position,
        "downside": downside,
        "status": status,
        "channel_price": channel_price,
    }


# ============================================================
# 销量 / 流动性
# ============================================================

def calculate_turnover(item):

    sales_7d = to_float(
        item.get(
            "sales_7d"
        )
    )

    sales_30d = to_float(
        item.get(
            "sales_30d"
        )
    )

    velocity = to_float(
        item.get(
            "sales_velocity_7d"
        )
    )

    evidence = item.get(
        "turnover_evidence"
    )

    confidence = item.get(
        "turnover_confidence"
    )

    if (
        sales_7d is not None
        and sales_7d > 0
    ):

        velocity = (
            sales_7d / 7
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

        velocity = (
            sales_30d / 30
        )

        evidence = (
            f"月销 {sales_30d:g}，"
            f"日均约 {velocity:.2f}"
        )

        confidence = "medium"

    elif evidence:

        confidence = (
            confidence or "low"
        )

    else:

        confidence = "unknown"

    return {
        "sales_7d": sales_7d,
        "sales_30d": sales_30d,
        "velocity": velocity,
        "evidence": evidence,
        "confidence": confidence,
        "days": None,
    }


def calculate_sales_score(
    turnover
):

    sales_7d = turnover[
        "sales_7d"
    ]

    sales_30d = turnover[
        "sales_30d"
    ]

    velocity = turnover[
        "velocity"
    ]

    if (
        sales_7d is not None
        and sales_7d >= 20
    ):
        return 3

    if (
        sales_7d is not None
        and sales_7d >= 7
    ):
        return 2

    if (
        sales_7d is not None
        and sales_7d > 0
    ):
        return 1

    if (
        sales_30d is not None
        and sales_30d >= 1000
    ):
        return 3

    if (
        sales_30d is not None
        and sales_30d >= 300
    ):
        return 2

    if (
        sales_30d is not None
        and sales_30d > 0
    ):
        return 1

    if (
        velocity is not None
        and velocity >= 30
    ):
        return 2

    if (
        velocity is not None
        and velocity > 0
    ):
        return 1

    return 0


# ============================================================
# 价格趋势
# ============================================================

def calculate_trend_score(item):

    trend = normalize_trend(
        item.get(
            "price_trend"
        )
    )

    change_7d = to_float(
        item.get(
            "price_change_7d"
        )
    )

    score = 0

    if trend == "上涨":
        score += 2

    elif trend == "稳定":
        score += 1

    elif trend == "下跌":
        score -= 1

    if change_7d is not None:

        if change_7d > 3:
            score += 1

        elif change_7d < -5:
            score -= 1

    return max(
        -2,
        min(
            3,
            score,
        ),
    )


# ============================================================
# 证据评分
# ============================================================

def calculate_evidence_score(
    price_evidence,
    turnover,
):

    score = 0

    if (
        price_evidence[
            "status"
        ]
        == "confirmed_current_price"
    ):
        score += 2

    elif (
        price_evidence[
            "current"
        ]
        is not None
    ):
        score += 1

    if (
        price_evidence[
            "low"
        ]
        is not None
    ):
        score += 1

    if (
        price_evidence[
            "high"
        ]
        is not None
    ):
        score += 1

    if (
        turnover[
            "confidence"
        ]
        == "high"
    ):
        score += 2

    elif (
        turnover[
            "confidence"
        ]
        == "medium"
    ):
        score += 1

    return score


# ============================================================
# 安全评分
# ============================================================

def calculate_safety(
    profit,
    downside,
    price_evidence_status,
):

    safety = 0

    if (
        profit is not None
        and profit >= MIN_PROFIT
    ):
        safety += 4

    if downside is None:

        safety -= 1

    elif downside <= 10:

        safety += 5

    elif downside <= 20:

        safety += 3

    elif downside <= MAX_DOWNSIDE_LOSS:

        safety += 1

    else:

        safety -= 5

    if (
        price_evidence_status
        != "confirmed_current_price"
    ):
        safety -= 1

    return safety


# ============================================================
# 硬风险
# ============================================================

def check_hard_risks(
    item,
    buy_price,
    dewu_price,
    total_cost,
    profit,
    downside,
    turnover,
    sku_size,
):

    reasons = []

    category = item.get(
        "category"
    )

    if category == "excluded":

        reasons.append(
            "属于明确排除品类"
        )

    if buy_price is None:

        reasons.append(
            "没有有效买入价"
        )

    if dewu_price is None:

        reasons.append(
            "没有有效得物价格"
        )

    if (
        total_cost is not None
        and total_cost > CAPITAL
    ):

        reasons.append(
            f"总资金占用 ¥{total_cost:.2f}"
            f"超过当前资金 ¥{CAPITAL:.2f}"
        )

    if (
        profit is not None
        and profit < -MAX_DOWNSIDE_LOSS
    ):

        reasons.append(
            "预计亏损超过容忍范围"
        )

    if (
        downside is not None
        and downside > MAX_DOWNSIDE_LOSS
    ):

        reasons.append(
            "当前价格距离7日低点过高，"
            "下行风险超过阈值"
        )

    days = turnover[
        "days"
    ]

    if (
        days is not None
        and days > MAX_DAYS
    ):

        reasons.append(
            f"明确周转时间超过"
            f"{MAX_DAYS}天"
        )

    new_verified = item.get(
        "new_condition_verified"
    )

    if new_verified is False:

        reasons.append(
            "明确不是全新状态"
        )

    check_compatible = item.get(
        "dewu_check_compatible"
    )

    if check_compatible is False:

        reasons.append(
            "得物查验/上架兼容性不满足"
        )

    # 有尺码价格表，但当前尺码无法确定
    # 不把其他尺码的价格冒充当前 SKU。
    size_prices = get_size_price_map(
        item
    )

    if (
        size_prices
        and sku_size is None
    ):

        reasons.append(
            "存在尺码价格，但当前尺码无法确认"
        )

    return reasons


# ============================================================
# A / B / C / D
# ============================================================

def calculate_grade(
    profit,
    profit_rate,
    safety,
    sales_score,
    trend_score,
    evidence_score,
    capital_score,
    hard_risks,
):

    if hard_risks:
        return "D"

    if (
        profit is None
        or profit_rate is None
    ):
        return "C"

    # A
    if (
        profit >= 30
        and profit_rate >= 20
        and safety >= 12
        and sales_score >= 2
        and trend_score >= 2
        and capital_score >= 1
        and evidence_score >= 4
    ):
        return "A"

    # B
    if (
        profit >= MIN_PROFIT
        and profit_rate >= MIN_PROFIT_RATE
        and safety > 0
    ):
        return "B"

    return "C"


# ============================================================
# 原因
# ============================================================

def build_reason(
    grade,
    profit,
    profit_rate,
    turnover,
    price_evidence,
    trend,
    income_reason,
    sku_size,
):

    reasons = []

    if grade == "A":

        reasons.append(
            "利润、价格、销量和风险证据较完整"
        )

    elif grade == "B":

        reasons.append(
            "达到推荐候选的最低利润与风险门槛"
        )

    elif grade == "C":

        reasons.append(
            "当前不能作为推荐候选"
        )

    else:

        reasons.append(
            "触发硬风险，直接过滤"
        )

    if sku_size:

        reasons.append(
            f"尺码 {sku_size}"
        )

    if profit is not None:

        reasons.append(
            f"估算利润 ¥{profit:.2f}"
        )

    if profit_rate is not None:

        reasons.append(
            f"利润率 {profit_rate:.2f}%"
        )

    reasons.append(
        "估算公式：得物售价×92%-买入价-6元"
    )

    if income_reason:

        reasons.append(
            income_reason
        )

    evidence = turnover[
        "evidence"
    ]

    if evidence:

        reasons.append(
            evidence
        )

    if (
        price_evidence[
            "low"
        ]
        is not None
    ):

        reasons.append(
            f"7日最低 ¥"
            f"{price_evidence['low']:.2f}"
        )

    if (
        price_evidence[
            "downside"
        ]
        is not None
    ):

        reasons.append(
            f"距离7日低点 "
            f"{price_evidence['downside']:.2f}%"
        )

    if trend:

        reasons.append(
            f"价格趋势：{trend}"
        )

    reasons.append(
        "买入运费按 ¥6 估算"
    )

    return "；".join(
        reasons
    )


# ============================================================
# 单个 SKU 分析
# ============================================================

def analyze(
    item,
    sku_size=None,
    sku_buy_price=None,
):

    name = item.get(
        "name"
    )

    if sku_buy_price is not None:

        buy_price = to_float(
            sku_buy_price
        )

    else:

        buy_price = get_buy_price(
            item
        )

    if (
        not name
        or buy_price is None
        or buy_price <= 0
    ):
        return None

    category = item.get(
        "category"
    )

    product_code = item.get(
        "product_code"
    )

    color = item.get(
        "color"
    )

    # --------------------------------------------------------
    # 明确排除品类
    # --------------------------------------------------------

    if category == "excluded":

        return {
            "name": name,
            "product_code": product_code,
            "color": color,
            "sku_size": sku_size,
            "sku_buy_price": money(
                buy_price
            ),
            "grade": "D",
            "category": category,
            "buy_price": money(
                buy_price
            ),
            "hard_risks": [
                "属于明确排除品类"
            ],
            "reason": (
                "属于明确排除品类"
            ),
            "capital": CAPITAL,
            "profit_type": "estimated",
        }

    # --------------------------------------------------------
    # 得物售价
    # --------------------------------------------------------

    (
        dewu_price,
        price_source,
        price_type,
    ) = get_dewu_price(item)

    if (
        dewu_price is None
        or dewu_price <= 0
    ):

        return {
            "name": name,
            "product_code": product_code,
            "color": color,
            "sku_size": sku_size,
            "sku_buy_price": money(
                buy_price
            ),
            "grade": "D",
            "category": category,
            "buy_price": money(
                buy_price
            ),
            "dewu_price": None,
            "hard_risks": [
                "没有有效得物价格"
            ],
            "reason": (
                "没有有效得物价格"
            ),
            "capital": CAPITAL,
            "profit_type": "estimated",
        }

    # --------------------------------------------------------
    # 买入成本
    # --------------------------------------------------------

    (
        buy_shipping,
        shipping_confirmed,
    ) = get_buy_shipping_cost(
        item
    )

    (
        estimated_income,
        total_cost,
        estimated_profit,
    ) = calculate_estimated_profit(
        dewu_price,
        buy_price,
        buy_shipping,
    )

    profit = estimated_profit

    profit_rate = None

    if (
        profit is not None
        and total_cost > 0
    ):

        profit_rate = (
            profit
            / total_cost
            * 100
        )

    # --------------------------------------------------------
    # 价格证据
    # --------------------------------------------------------

    price_evidence = (
        calculate_price_evidence(
            item
        )
    )

    # --------------------------------------------------------
    # 销量
    # --------------------------------------------------------

    turnover = (
        calculate_turnover(
            item
        )
    )

    sales_score = (
        calculate_sales_score(
            turnover
        )
    )

    trend_score = (
        calculate_trend_score(
            item
        )
    )

    evidence_score = (
        calculate_evidence_score(
            price_evidence,
            turnover,
        )
    )

    # --------------------------------------------------------
    # 资金
    # --------------------------------------------------------

    if total_cost <= CAPITAL:

        capital_score = 2

    else:

        capital_score = 0

    capital_ratio = (
        total_cost
        / CAPITAL
        * 100
        if CAPITAL > 0
        else None
    )

    # --------------------------------------------------------
    # 安全
    # --------------------------------------------------------

    safety = calculate_safety(
        profit,
        price_evidence[
            "downside"
        ],
        price_evidence[
            "status"
        ],
    )

    # --------------------------------------------------------
    # 硬风险
    # --------------------------------------------------------

    hard_risks = check_hard_risks(
        item,
        buy_price,
        dewu_price,
        total_cost,
        profit,
        price_evidence[
            "downside"
        ],
        turnover,
        sku_size,
    )

    # --------------------------------------------------------
    # 等级
    # --------------------------------------------------------

    grade = calculate_grade(
        profit,
        profit_rate,
        safety,
        sales_score,
        trend_score,
        evidence_score,
        capital_score,
        hard_risks,
    )

    trend = normalize_trend(
        item.get(
            "price_trend"
        )
    )

    # --------------------------------------------------------
    # 说明
    # --------------------------------------------------------

    income_reason = (
        f"得物售价 ¥{dewu_price:.2f}"
        f" × 92% = ¥{estimated_income:.2f}"
    )

    reason = build_reason(
        grade,
        profit,
        profit_rate,
        turnover,
        price_evidence,
        trend,
        income_reason,
        sku_size,
    )

    return {

        "name": name,

        "product_code": product_code,

        "color": color,

        "sku_size": sku_size,

        "sku_buy_price": money(
            buy_price
        ),

        "selected_variant": item.get(
            "selected_variant"
        ),

        "grade": grade,

        "category": category,

        "category_reason": item.get(
            "category_reason"
        ),

        "buy_price": money(
            buy_price
        ),

        "dewu_price": money(
            dewu_price
        ),

        "dewu_price_source": (
            price_source
        ),

        "dewu_price_type": (
            price_type
        ),

        "dewu_channel_price": money(
            to_float(
                item.get(
                    "dewu_channel_price"
                )
            )
        ),

        "estimated_income": money(
            estimated_income
        ),

        "expected_income": money(
            estimated_income
        ),

        "total_cost": money(
            total_cost
        ),

        "buy_shipping_cost": money(
            buy_shipping
        ),

        "buy_shipping_confirmed": (
            shipping_confirmed
        ),

        "profit_type": "estimated",

        "profit": money(
            profit
        ),

        "estimated_profit": money(
            profit
        ),

        "profit_rate": (
            round(
                profit_rate,
                2,
            )
            if profit_rate is not None
            else None
        ),

        "capital": CAPITAL,

        "capital_ratio": (
            round(
                capital_ratio,
                2,
            )
            if capital_ratio is not None
            else None
        ),

        "sales_7d": turnover[
            "sales_7d"
        ],

        "sales_30d": turnover[
            "sales_30d"
        ],

        "sales_velocity_7d": turnover[
            "velocity"
        ],

        "turnover_evidence": turnover[
            "evidence"
        ],

        "turnover_confidence": turnover[
            "confidence"
        ],

        "days": turnover[
            "days"
        ],

        "price_current": money(
            price_evidence[
                "current"
            ]
        ),

        "price_7d_low": money(
            price_evidence[
                "low"
            ]
        ),

        "price_7d_high": money(
            price_evidence[
                "high"
            ]
        ),

        "price_position_7d": (
            price_evidence[
                "position"
            ]
        ),

        "downside_to_7d_low": (
            price_evidence[
                "downside"
            ]
        ),

        "price_evidence_status": (
            price_evidence[
                "status"
            ]
        ),

        "price_trend": trend,

        "sales_score": sales_score,

        "trend_score": trend_score,

        "evidence_score": evidence_score,

        "safety_score": safety,

        "capital_score": capital_score,

        "hard_risks": hard_risks,

        "reason": reason,

        "shihuo_source": item.get(
            "shihuo_source",
            True,
        ),

        "authenticity_evidence": item.get(
            "authenticity_evidence"
        ),

        "new_condition_verified": item.get(
            "new_condition_verified"
        ),

        "dewu_check_compatible": item.get(
            "dewu_check_compatible"
        ),

        "source_note": item.get(
            "source_note"
        ),
    }


# ============================================================
# 主程序
# ============================================================

def main():

    products = load_products()

    results = []

    for item in products:

        try:

            sku_contexts = (
                get_sku_context(
                    item
                )
            )

            # 有尺码价格但当前尺码无法确认
            # 不拿其他尺码价格冒充。
            if not sku_contexts:

                continue

            for (
                sku_size,
                sku_buy_price,
            ) in sku_contexts:

                result = analyze(
                    item,
                    sku_size=sku_size,
                    sku_buy_price=sku_buy_price,
                )

                if result is not None:

                    results.append(
                        result
                    )

        except Exception as e:

            print(
                "分析商品失败：",
                item.get("name"),
                e,
            )

    # ========================================================
    # 推荐候选
    # ========================================================

    candidates = [
        item
        for item in results
        if item.get(
            "grade"
        )
        in {
            "A",
            "B",
        }
    ]

    candidates.sort(
        key=lambda x: (
            0
            if x.get(
                "grade"
            ) == "A"
            else 1,

            -(
                x.get(
                    "estimated_profit"
                )
                or 0
            ),

            -(
                x.get(
                    "profit_rate"
                )
                or 0
            ),
        )
    )

    output = {

        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "capital":
            CAPITAL,

        "rules": {

            "max_days":
                MAX_DAYS,

            "min_profit":
                MIN_PROFIT,

            "min_profit_rate":
                MIN_PROFIT_RATE,

            "max_downside_loss":
                MAX_DOWNSIDE_LOSS,

            "dewu_net_rate":
                DEWU_NET_RATE,

            "default_buy_shipping":
                DEFAULT_BUY_SHIPPING,

            "profit_type":
                "estimated",

            "profit_formula":
                "得物售价×92%-买入价-6元",

            "sku_level":
                True,
        },

        "summary": {

            "total":
                len(results),

            "A":
                sum(
                    1
                    for x in results
                    if x.get(
                        "grade"
                    ) == "A"
                ),

            "B":
                sum(
                    1
                    for x in results
                    if x.get(
                        "grade"
                    ) == "B"
                ),

            "C":
                sum(
                    1
                    for x in results
                    if x.get(
                        "grade"
                    ) == "C"
                ),

            "D":
                sum(
                    1
                    for x in results
                    if x.get(
                        "grade"
                    ) == "D"
                ),

            "estimated_profit_count":
                sum(
                    1
                    for x in results
                    if x.get(
                        "profit_type"
                    ) == "estimated"
                ),
        },

        "candidates":
            candidates,

        "results":
            results,
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
        f"SKU分析总数："
        f"{len(results)}"
    )

    print(
        f"A级："
        f"{output['summary']['A']}"
    )

    print(
        f"B级："
        f"{output['summary']['B']}"
    )

    print(
        f"C级："
        f"{output['summary']['C']}"
    )

    print(
        f"D级："
        f"{output['summary']['D']}"
    )

    print(
        "利润类型：估算利润"
    )

    print(
        "估算公式："
        "得物售价×92%-买入价-6元"
    )

    print(
        "=============================="
    )

    print(
        "\n推荐候选："
    )

    for item in candidates:

        print(
            f"{item.get('grade')} | "
            f"{item.get('product_code')} | "
            f"{item.get('color')} | "
            f"尺码 {item.get('sku_size')} | "
            f"买入 ¥{item.get('sku_buy_price')} | "
            f"得物 ¥{item.get('dewu_price')} | "
            f"估算利润 ¥{item.get('estimated_profit')} | "
            f"利润率 "
            f"{item.get('profit_rate')}%"
        )


if __name__ == "__main__":
    main()
