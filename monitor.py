import json
import math
from pathlib import Path


INPUT_FILE = "products.json"
OUTPUT_FILE = "monitor_results.json"


CAPITAL = 330

MAX_DAYS = 7

MIN_PROFIT = 15

MIN_PROFIT_RATE = 12

MAX_DOWNSIDE_LOSS = 25

DEWU_FEE_RATE = 0.08
DEWU_NET_RATE = 1 - DEWU_FEE_RATE

DEFAULT_BUY_SHIPPING = 6


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
        value if value in {
            "上涨",
            "下跌",
            "稳定",
        } else None,
    )


def load_products():
    path = Path(INPUT_FILE)

    if not path.exists():
        return []

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return []

    return (
        data.get("products")
        or []
    )


def get_buy_price(item):
    value = to_float(
        item.get("buy_price")
    )

    if value is None or value <= 0:
        return None

    return value


def get_dewu_price(item):
    """
    优先使用明确的：
    当前同款同规格到手价。

    没有时才使用：
    得物渠道售价。

    同时返回价格来源。
    """

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
            "当前同款同规格到手价",
            True,
        )

    channel_price = to_float(
        item.get(
            "dewu_channel_price"
        )
    )

    if (
        channel_price is None
        or channel_price <= 0
    ):
        channel_price = to_float(
            item.get(
                "dewu_price"
            )
        )

    if (
        channel_price is not None
        and channel_price > 0
    ):
        return (
            channel_price,
            "得物渠道售价",
            False,
        )

    return (
        None,
        None,
        False,
    )


def get_buy_shipping_cost(item):
    """
    如果识货明确给出买入运费，就使用明确值。
    否则使用保守的 ¥6，并标记为估算。
    """

    candidates = [
        item.get(
            "buy_shipping_cost"
        ),
        item.get(
            "shipping_cost"
        ),
        item.get(
            "consumer_shipping_fee"
        ),
    ]

    for value in candidates:

        number = to_float(
            value
        )

        if (
            number is not None
            and number >= 0
        ):
            return (
                number,
                True,
            )

    return (
        DEFAULT_BUY_SHIPPING,
        False,
    )


def get_platform_cost(item):
    """
    得物侧费用。

    如果存在明确费用，优先使用。
    否则按照 8% 技术服务费估算。
    """

    expected_income = to_float(
        item.get(
            "expected_income"
        )
    )

    if (
        expected_income is not None
        and expected_income > 0
    ):
        return (
            expected_income,
            True,
        )

    dewu_price, _, _ = get_dewu_price(
        item
    )

    if (
        dewu_price is None
        or dewu_price <= 0
    ):
        return (
            None,
            False,
        )

    income = (
        dewu_price
        * DEWU_NET_RATE
    )

    return (
        income,
        False,
    )


def calculate_price_evidence(item):
    current_price = to_float(
        item.get(
            "trend_current_price"
        )
    )

    if (
        current_price is None
        or current_price <= 0
    ):
        current_price = to_float(
            item.get(
                "price_current"
            )
        )

    if (
        current_price is None
        or current_price <= 0
    ):
        channel_price = to_float(
            item.get(
                "dewu_channel_price"
            )
        )

        if (
            channel_price is not None
            and channel_price > 0
        ):
            current_price = (
                channel_price
            )

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
                current_price - low
            )
            / (
                high - low
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
        and low >= 0
        and low <= current_price
    ):
        downside = (
            (
                current_price - low
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
        "current": current_price,
        "low": low,
        "high": high,
        "position": position,
        "downside": downside,
    }


def calculate_turnover(item):
    """
    销量和周转分开。

    有 7 日销量：
        可以得到销量速度。

    有月销：
        只能得到月销/日均销量证据，
        不能假装成“7天周转天数”。

    没有库存：
        days = None
    """

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
            f"近7日销量 "
            f"{sales_7d:g}，"
            f"日均约 "
            f"{velocity:.2f}"
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
            f"月销 "
            f"{sales_30d:g}，"
            f"日均约 "
            f"{velocity:.2f}"
        )

        confidence = "medium"

    elif evidence:
        confidence = (
            confidence
            or "low"
        )

    else:
        confidence = (
            confidence
            or "unknown"
        )

    return {
        "sales_7d": sales_7d,
        "sales_30d": sales_30d,
        "velocity": velocity,
        "evidence": evidence,
        "confidence": confidence,
        "days": None,
    }


def calculate_sales_score(turnover):
    sales_7d = turnover[
        "sales_7d"
    ]

    sales_30d = turnover[
        "sales_30d"
    ]

    velocity = turnover[
        "velocity"
    ]

    score = 0

    if (
        sales_7d is not None
        and sales_7d >= 20
    ):
        score = 3

    elif (
        sales_7d is not None
        and sales_7d >= 7
    ):
        score = 2

    elif (
        sales_7d is not None
        and sales_7d > 0
    ):
        score = 1

    elif (
        sales_30d is not None
        and sales_30d >= 1000
    ):
        score = 3

    elif (
        sales_30d is not None
        and sales_30d >= 300
    ):
        score = 2

    elif (
        sales_30d is not None
        and sales_30d > 0
    ):
        score = 1

    elif (
        velocity is not None
        and velocity >= 30
    ):
        score = 2

    elif (
        velocity is not None
        and velocity > 0
    ):
        score = 1

    return score


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


def calculate_evidence_score(
    item,
    price_evidence,
    turnover,
):
    score = 0

    # 当前价格明确
    if (
        price_evidence[
            "current"
        ]
        is not None
    ):
        score += 1

    # 7日低点明确
    if (
        price_evidence[
            "low"
        ]
        is not None
    ):
        score += 1

    # 7日高点明确
    if (
        price_evidence[
            "high"
        ]
        is not None
    ):
        score += 1

    # 销量证据
    if (
        turnover[
            "confidence"
        ] == "high"
    ):
        score += 2

    elif (
        turnover[
            "confidence"
        ] == "medium"
    ):
        score += 1

    return score


def calculate_safety(
    profit,
    downside,
    buy_shipping_confirmed,
    price_evidence,
):
    safety = 0

    if profit >= MIN_PROFIT:
        safety += 4

    if (
        downside is None
    ):
        safety -= 1

    elif downside <= 10:
        safety += 5

    elif downside <= 20:
        safety += 3

    elif downside <= MAX_DOWNSIDE_LOSS:
        safety += 1

    else:
        safety -= 5

    if not buy_shipping_confirmed:
        safety -= 1

    if (
        price_evidence[
            "current"
        ]
        is None
    ):
        safety -= 3

    return safety


def check_hard_risks(
    item,
    buy_price,
    dewu_price,
    profit,
    downside,
    turnover,
):
    reasons = []

    if buy_price is None:
        reasons.append(
            "没有有效买入价"
        )

    if dewu_price is None:
        reasons.append(
            "没有有效得物价格"
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

    # 全新状态
    new_verified = item.get(
        "new_condition_verified"
    )

    if new_verified is False:
        reasons.append(
            "不是明确全新状态"
        )

    # 得物查验兼容性
    check_compatible = item.get(
        "dewu_check_compatible"
    )

    if check_compatible is False:
        reasons.append(
            "得物查验/上架兼容性不满足"
        )

    return reasons


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

    # A：证据充分 + 利润高 + 风险可控
    if (
        profit >= 30
        and profit_rate >= 20
        and safety >= 12
        and sales_score >= 2
        and trend_score >= 2
        and capital_score >= 1
        and evidence_score >= 2
    ):
        return "A"

    # B：利润和资金风险达到最低要求
    # B 同样属于推荐候选
    if (
        profit >= MIN_PROFIT
        and profit_rate >= MIN_PROFIT_RATE
        and safety > 0
    ):
        return "B"

    return "C"


def build_reason(
    grade,
    profit,
    profit_rate,
    turnover,
    price_evidence,
    trend,
    buy_shipping_confirmed,
):
    reasons = []

    if grade == "A":
        reasons.append(
            "利润、资金占用、"
            "价格和销量证据较完整"
        )

    elif grade == "B":
        reasons.append(
            "利润和资金条件达到"
            "推荐候选门槛"
        )

    else:
        reasons.append(
            "当前证据或风险条件"
            "不足以进入推荐候选"
        )

    if profit is not None:
        reasons.append(
            f"预计净利润 ¥{profit:.2f}"
        )

    if profit_rate is not None:
        reasons.append(
            f"利润率 {profit_rate:.2f}%"
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

    if not buy_shipping_confirmed:
        reasons.append(
            "买入运费为估算值"
        )

    return "；".join(
        reasons
    )


def analyze(item):
    name = item.get(
        "name"
    )

    buy_price = get_buy_price(
        item
    )

    if (
        not name
        or buy_price is None
    ):
        return None

    dewu_price, price_source, explicit_current = (
        get_dewu_price(
            item
        )
    )

    if (
        dewu_price is None
        or dewu_price <= 0
    ):
        return None

    buy_shipping, shipping_confirmed = (
        get_buy_shipping_cost(
            item
        )
    )

    expected_income, income_confirmed = (
        get_platform_cost(
            item
        )
    )

    if (
        expected_income is None
        or expected_income <= 0
    ):
        return None

    total_cost = (
        buy_price
        + buy_shipping
    )

    profit = (
        expected_income
        - total_cost
    )

    profit_rate = (
        profit
        / total_cost
        * 100
        if total_cost > 0
        else None
    )

    price_evidence = (
        calculate_price_evidence(
            item
        )
    )

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
            item,
            price_evidence,
            turnover,
        )
    )

    capital_ratio = (
        total_cost
        / CAPITAL
        * 100
        if CAPITAL > 0
        else None
    )

    if total_cost <= CAPITAL:
        capital_score = 2

    elif total_cost <= CAPITAL * 1.2:
        capital_score = 1

    else:
        capital_score = 0

    safety = calculate_safety(
        profit,
        price_evidence[
            "downside"
        ],
        shipping_confirmed,
        price_evidence,
    )

    hard_risks = check_hard_risks(
        item,
        buy_price,
        dewu_price,
        profit,
        price_evidence[
            "downside"
        ],
        turnover,
    )

    # --------------------------------------------------
    # 价格口径一致性检查
    #
    # 如果同时存在：
    #   得物渠道售价
    #   当前同款同规格到手价
    #
    # 且两者差距明显，
    # 不允许系统假装它们是同一个价格。
    # --------------------------------------------------

    channel_price = to_float(
        item.get(
            "dewu_channel_price"
        )
    )

    trend_price = to_float(
        item.get(
            "trend_current_price"
        )
    )

    price_conflict = False

    if (
        channel_price is not None
        and trend_price is not None
        and channel_price > 0
        and trend_price > 0
    ):
        difference = abs(
            channel_price
            - trend_price
        ) / trend_price * 100

        if difference > 20:
            price_conflict = True

            hard_risks.append(
                "得物渠道售价与"
                "当前同款同规格到手价"
                "差异超过20%，"
                "价格口径不一致"
            )

    # 如果没有明确当前价格，
    # 但只有“得物渠道售价”，
    # 可以计算，但证据分降低。
    if (
        not explicit_current
        and channel_price is not None
    ):
        evidence_score = max(
            0,
            evidence_score - 1,
        )

        safety -= 1

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

    reason = build_reason(
        grade,
        profit,
        profit_rate,
        turnover,
        price_evidence,
        trend,
        shipping_confirmed,
    )

    return {
        "name": name,

        "grade": grade,

        "buy_price": money(
            buy_price
        ),

        "dewu_price": money(
            dewu_price
        ),

        "dewu_price_source": (
            price_source
        ),

        "expected_income": money(
            expected_income
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

        "income_confirmed": (
            income_confirmed
        ),

        "profit": money(
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

        "price_trend": trend,

        "sales_score": sales_score,

        "trend_score": trend_score,

        "evidence_score": evidence_score,

        "safety_score": safety,

        "capital_score": capital_score,

        "price_conflict": (
            price_conflict
        ),

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


def main():
    products = load_products()

    results = []

    for item in products:

        try:

            result = analyze(
                item
            )

            if result is not None:
                results.append(
                    result
                )

        except Exception as e:

            print(
                "分析商品失败：",
                item.get(
                    "name"
                ),
                e,
            )

    # --------------------------------------------------
    # A/B 都属于推荐候选
    # --------------------------------------------------

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
                    "profit"
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
        "updated_at": (
            __import__(
                "datetime"
            ).datetime.now(
                __import__(
                    "datetime"
                ).timezone.utc
            ).isoformat()
        ),

        "capital": CAPITAL,

        "rules": {
            "max_days": MAX_DAYS,
            "min_profit": MIN_PROFIT,
            "min_profit_rate": MIN_PROFIT_RATE,
            "max_downside_loss": MAX_DOWNSIDE_LOSS,
            "dewu_fee_rate": DEWU_FEE_RATE,
            "default_buy_shipping": DEFAULT_BUY_SHIPPING,
        },

        "summary": {
            "total": len(results),

            "A": sum(
                1
                for x in results
                if x.get(
                    "grade"
                ) == "A"
            ),

            "B": sum(
                1
                for x in results
                if x.get(
                    "grade"
                ) == "B"
            ),

            "C": sum(
                1
                for x in results
                if x.get(
                    "grade"
                ) == "C"
            ),

            "D": sum(
                1
                for x in results
                if x.get(
                    "grade"
                ) == "D"
            ),
        },

        "candidates": candidates,

        "results": results,
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
        f"商品总数：{len(results)}"
    )

    print(
        f"A级：{output['summary']['A']}"
    )

    print(
        f"B级：{output['summary']['B']}"
    )

    print(
        f"C级：{output['summary']['C']}"
    )

    print(
        f"D级：{output['summary']['D']}"
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
            f"{item.get('name')} | "
            f"买入 ¥{item.get('buy_price')} | "
            f"得物 ¥{item.get('dewu_price')} | "
            f"利润 ¥{item.get('profit')} | "
            f"利润率 "
            f"{item.get('profit_rate')}%"
        )


if __name__ == "__main__":
    main()
