import json
from pathlib import Path
from datetime import datetime, timezone


# ============================================================
# 基础规则
# ============================================================

CAPITAL = 330

MAX_DAYS = 7

MIN_PROFIT = 15

MIN_PROFIT_RATE = 12

MAX_DOWNSIDE_LOSS = 25


# ============================================================
# 得物费用模型
# ============================================================

DEWU_FEE_RATE = 0.08
DEWU_NET_RATE = 0.92


# ============================================================
# 默认买入运费
# ============================================================

DEFAULT_BUY_SHIPPING_COST = 6


# ============================================================
# 工具
# ============================================================

def is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    )


def money(value):
    if is_number(value):
        return float(value)

    try:
        if value is None:
            return None

        text = str(value).strip()

        if not text:
            return None

        return float(text)

    except Exception:
        return None


def positive_number(value):
    value = money(value)

    if value is None:
        return None

    if value <= 0:
        return None

    return value


def first_number(item, *keys):
    for key in keys:
        value = positive_number(item.get(key))

        if value is not None:
            return value

    return None


# ============================================================
# 得物预计到账
# ============================================================

def calculate_expected_income(item):

    explicit_income = positive_number(
        item.get("expected_income")
    )

    if explicit_income is not None:
        return {
            "value": explicit_income,
            "confirmed": True,
            "method": "数据源明确预计到账",
        }

    sale = positive_number(
        item.get("dewu_price")
    )

    if sale is None:
        return {
            "value": None,
            "confirmed": False,
            "method": "没有得物有效售价",
        }

    income = sale * DEWU_NET_RATE

    return {
        "value": round(income, 2),
        "confirmed": True,
        "method": "得物售价按8%费用估算到账",
    }


# ============================================================
# 买入运费
# ============================================================

def get_buy_shipping_cost(item):

    value = money(
        item.get("buy_shipping_cost")
    )

    if value is not None and value >= 0:
        return {
            "value": value,
            "confirmed": True,
            "method": "商品买入运费",
        }

    return {
        "value": DEFAULT_BUY_SHIPPING_COST,
        "confirmed": False,
        "method": "默认买入运费估算",
    }


# ============================================================
# 品类
# ============================================================

def category_status(item):

    category = str(
        item.get("category", "unknown")
    ).lower()

    if category == "excluded":
        return "excluded"

    if category == "target":
        return "target"

    return "unknown"


# ============================================================
# 价格趋势标准化
#
# 兼容：
# rising / falling / stable
# 上涨 / 下跌 / 稳定
# 上升 / 下降
# ============================================================

def normalize_trend(value):

    if value is None:
        return None

    text = str(value).strip().lower()

    if not text:
        return None

    if any(x in text for x in [
        "falling",
        "下降",
        "下跌",
        "走低",
        "下行",
    ]):
        return "falling"

    if any(x in text for x in [
        "rising",
        "上涨",
        "上升",
        "走高",
        "上行",
    ]):
        return "rising"

    if any(x in text for x in [
        "stable",
        "稳定",
        "持平",
    ]):
        return "stable"

    return None


# ============================================================
# 销量 / 周转证据
#
# 注意：
# sales_velocity_7d 是“每天卖多少件”
# 不能直接变成周转天数。
#
# 没有库存量时：
# 不计算错误的“0天周转”
# 而显示：
# 月销1600，日均53.33（周转证据）
# ============================================================

def calculate_turnover(item):

    sales_7d = positive_number(
        item.get("sales_7d")
    )

    sales_30d = positive_number(
        item.get("sales_30d")
    )

    velocity = positive_number(
        item.get("sales_velocity_7d")
    )

    if velocity is None and sales_7d is not None:
        velocity = sales_7d / 7

    if velocity is None and sales_30d is not None:
        velocity = sales_30d / 30

    if sales_7d is not None:

        return {
            "confirmed": True,
            "source": "近7日销量",
            "sales_7d": sales_7d,
            "sales_30d": sales_30d,
            "velocity": round(velocity, 2) if velocity else None,
            "days": None,
            "display": (
                f"近7日销量{sales_7d:g}，"
                f"日均{velocity:.2f}"
                if velocity
                else f"近7日销量{sales_7d:g}"
            ),
        }

    if sales_30d is not None:

        return {
            "confirmed": True,
            "source": "近30日销量",
            "sales_7d": None,
            "sales_30d": sales_30d,
            "velocity": round(velocity, 2) if velocity else None,
            "days": None,
            "display": (
                f"月销{sales_30d:g}，"
                f"日均{velocity:.2f}"
                if velocity
                else f"月销{sales_30d:g}"
            ),
        }

    if velocity is not None:

        return {
            "confirmed": True,
            "source": "销量速度",
            "sales_7d": None,
            "sales_30d": None,
            "velocity": round(velocity, 2),
            "days": None,
            "display": f"日均销量{velocity:.2f}",
        }

    days = money(item.get("days"))

    if days is not None and days >= 0:

        return {
            "confirmed": True,
            "source": "周转天数",
            "sales_7d": None,
            "sales_30d": None,
            "velocity": None,
            "days": days,
            "display": f"周转约{days:g}天",
        }

    return {
        "confirmed": False,
        "source": None,
        "sales_7d": None,
        "sales_30d": None,
        "velocity": None,
        "days": None,
        "display": "未获取销量/周转证据",
    }


# ============================================================
# 价格走势 / 下跌风险
# ============================================================

def calculate_price_evidence(item):

    current = first_number(
        item,
        "trend_current_price",
        "price_current",
        "dewu_price"
    )

    low = first_number(
        item,
        "price_7d_low"
    )

    high = first_number(
        item,
        "price_7d_high"
    )

    downside_percent = money(
        item.get("downside_to_7d_low")
    )

    downside_amount = None

    if (
        current is not None
        and low is not None
        and current > 0
        and low > 0
        and current >= low
    ):
        downside_amount = current - low

        if downside_percent is None:
            downside_percent = (
                downside_amount
                / current
                * 100
            )

    trend = normalize_trend(
        item.get("price_trend")
    )

    if trend is None:
        trend = normalize_trend(
            item.get("trend")
        )

    price_change_7d = money(
        item.get("price_change_7d")
    )

    confirmed = (
        current is not None
        and (
            low is not None
            or trend is not None
            or price_change_7d is not None
        )
    )

    return {
        "confirmed": confirmed,
        "current": current,
        "low": low,
        "high": high,
        "downside_amount": (
            round(downside_amount, 2)
            if downside_amount is not None
            else None
        ),
        "downside_percent": (
            round(downside_percent, 2)
            if downside_percent is not None
            else None
        ),
        "trend": trend,
        "change_7d": price_change_7d,
    }


# ============================================================
# 利润安全垫
# ============================================================

def calculate_profit_safety_margin(
    sale,
    total_buy_cost
):

    if (
        sale is None
        or total_buy_cost is None
        or sale <= 0
        or total_buy_cost <= 0
    ):
        return {
            "break_even_sale": None,
            "amount": None,
            "rate": None,
        }

    break_even_sale = (
        total_buy_cost
        / DEWU_NET_RATE
    )

    amount = (
        sale
        - break_even_sale
    )

    rate = (
        amount
        / sale
        * 100
    )

    return {
        "break_even_sale": round(
            break_even_sale,
            2
        ),
        "amount": round(
            amount,
            2
        ),
        "rate": round(
            rate,
            2
        ),
    }


# ============================================================
# 销量评分
# ============================================================

def sales_score(turnover):

    if not turnover["confirmed"]:
        return 0

    velocity = turnover["velocity"]

    sales_7d = turnover["sales_7d"]

    sales_30d = turnover["sales_30d"]

    if sales_7d is not None:

        if sales_7d >= 20:
            return 3

        if sales_7d >= 7:
            return 2

        return 1

    if velocity is not None:

        if velocity >= 3:
            return 3

        if velocity >= 1:
            return 2

        return 1

    if sales_30d is not None:

        if sales_30d >= 120:
            return 3

        if sales_30d >= 30:
            return 2

        return 1

    return 0


# ============================================================
# 趋势评分
# ============================================================

def trend_score(price):

    trend = price["trend"]

    change = price["change_7d"]

    if trend == "rising":
        return 3

    if trend == "stable":
        return 2

    if trend == "falling":

        if change is not None and change <= -10:
            return 0

        return 1

    if change is not None:

        if change >= 5:
            return 3

        if change >= -3:
            return 2

        if change >= -10:
            return 1

        return 0

    if price["low"] is not None:
        return 2

    return 0


# ============================================================
# 商品状态证据
# ============================================================

def evidence_score(item):

    score = 0

    if item.get("authenticity_evidence"):
        score += 1

    if item.get("new_condition_evidence"):
        score += 1

    if item.get("dewu_check_evidence"):
        score += 1

    if item.get("authenticity_verified") is True:
        score += 1

    if item.get("new_condition_verified") is True:
        score += 1

    if item.get("dewu_check_compatible") is True:
        score += 1

    return min(score, 3)


# ============================================================
# 过滤结果
# ============================================================

def filtered_result(
    item,
    reason,
    grade="D"
):

    turnover = calculate_turnover(item)

    price = calculate_price_evidence(item)

    return {

        "name":
            item.get(
                "name",
                "未知商品"
            ),

        "grade":
            grade,

        "grade_reason":
            reason,

        "status":
            "过滤",

        "buy_price":
            None,

        "dewu_price":
            None,

        "expected_income":
            None,

        "income_method":
            "无法计算",

        "total_buy_cost":
            None,

        "net_profit":
            None,

        "profit_rate":
            None,

        "days":
            turnover["days"],

        "days_display":
            turnover["display"],

        "turnover_confirmed":
            turnover["confirmed"],

        "turnover_evidence":
            turnover["display"],

        "sales_7d":
            turnover["sales_7d"],

        "sales_30d":
            turnover["sales_30d"],

        "sales_velocity_7d":
            turnover["velocity"],

        "price_current":
            price["current"],

        "price_7d_low":
            price["low"],

        "price_7d_high":
            price["high"],

        "downside_to_7d_low":
            price["downside_percent"],

        "downside_loss":
            price["downside_amount"],

        "price_change_7d":
            price["change_7d"],

        "price_trend":
            price["trend"],

        "risk_flags":
            [reason],

        "reasons":
            [reason],
    }


# ============================================================
# 核心评估
# ============================================================

def evaluate(item):

    reasons = []

    risk_flags = []


    # --------------------------------------------------------
    # 1. 品类
    # --------------------------------------------------------

    if category_status(item) == "excluded":

        return filtered_result(
            item,
            "非目标商品品类",
            "D"
        )


    # --------------------------------------------------------
    # 2. 买入价格
    # --------------------------------------------------------

    buy_prices = item.get(
        "buy_prices",
        {}
    )

    if not isinstance(
        buy_prices,
        dict
    ):

        return filtered_result(
            item,
            "买入价格字段错误",
            "D"
        )

    valid_prices = []

    for price in buy_prices.values():

        value = positive_number(price)

        if value is not None:
            valid_prices.append(value)

    if not valid_prices:

        return filtered_result(
            item,
            "没有有效买入价格",
            "D"
        )

    buy = min(valid_prices)


    # --------------------------------------------------------
    # 3. 得物售价
    # --------------------------------------------------------

    sale = positive_number(
        item.get("dewu_price")
    )

    if sale is None:

        return filtered_result(
            item,
            "没有有效得物公开售价",
            "D"
        )


    # --------------------------------------------------------
    # 4. 得物预计到账
    # --------------------------------------------------------

    income_result = (
        calculate_expected_income(item)
    )

    expected_income = (
        income_result["value"]
    )

    income_method = (
        income_result["method"]
    )

    if expected_income is None:

        return filtered_result(
            item,
            "无法计算预计到账",
            "D"
        )


    # --------------------------------------------------------
    # 5. 买入运费
    # --------------------------------------------------------

    shipping = get_buy_shipping_cost(item)

    buy_shipping = shipping["value"]

    shipping_confirmed = shipping["confirmed"]

    if not shipping_confirmed:

        risk_flags.append(
            "买入运费未明确，暂按¥6估算"
        )


    # --------------------------------------------------------
    # 6. 总成本
    # --------------------------------------------------------

    total_buy_cost = (
        buy
        + buy_shipping
    )


    # --------------------------------------------------------
    # 7. 资金
    # --------------------------------------------------------

    if total_buy_cost > CAPITAL:

        return filtered_result(
            item,
            (
                f"总资金占用¥{total_buy_cost:.2f}"
                f"超过当前本金¥{CAPITAL}"
            ),
            "D"
        )


    # --------------------------------------------------------
    # 8. 利润
    # --------------------------------------------------------

    profit = (
        expected_income
        - total_buy_cost
    )

    profit_rate = (
        profit
        / total_buy_cost
        * 100
    )


    if profit <= 0:

        return filtered_result(
            item,
            f"预计净利润¥{profit:.2f}，没有实际盈利空间",
            "D"
        )


    # --------------------------------------------------------
    # 9. 安全垫
    # --------------------------------------------------------

    safety = (
        calculate_profit_safety_margin(
            sale,
            total_buy_cost
        )
    )

    safety_rate = safety["rate"]

    break_even_sale = safety["break_even_sale"]

    safety_amount = safety["amount"]


    # --------------------------------------------------------
    # 10. 周转证据
    # --------------------------------------------------------

    turnover = calculate_turnover(item)

    if not turnover["confirmed"]:

        risk_flags.append(
            "近期销量/周转证据未获取"
        )

    # 有真实销量证据时，不再标记“周转未确认”
    # 因为没有库存数据，所以不伪造周转天数。


    # --------------------------------------------------------
    # 11. 价格走势
    # --------------------------------------------------------

    price = calculate_price_evidence(item)

    trend = price["trend"]

    change_7d = price["change_7d"]

    downside_amount = price["downside_amount"]

    downside_percent = price["downside_percent"]

    if not price["confirmed"]:

        risk_flags.append(
            "价格走势证据未获取"
        )

    if trend == "falling":

        risk_flags.append(
            "近期价格走势偏弱"
        )


    # --------------------------------------------------------
    # 12. 下跌风险
    # --------------------------------------------------------

    # 优先使用7日最低价计算实际跌幅
    if downside_amount is not None:

        if downside_amount > MAX_DOWNSIDE_LOSS:

            risk_flags.append(
                (
                    f"当前价回落至7日低点的"
                    f"空间约¥{downside_amount:.2f}"
                    f"，超过容忍¥{MAX_DOWNSIDE_LOSS}"
                )
            )

    # 如果数据源直接提供 downside_loss，也读取
    source_downside_loss = money(
        item.get("downside_loss")
    )

    if (
        source_downside_loss is not None
        and source_downside_loss > MAX_DOWNSIDE_LOSS
    ):

        if (
            downside_amount is None
            or source_downside_loss > downside_amount
        ):
            downside_amount = source_downside_loss


    # --------------------------------------------------------
    # 13. 流动性
    # --------------------------------------------------------

    liquidity = str(
        item.get(
            "liquidity",
            "未知"
        )
    )

    if liquidity not in ("高", "中"):

        risk_flags.append(
            f"流动性：{liquidity}"
        )


    # --------------------------------------------------------
    # 14. 商品状态证据
    # --------------------------------------------------------

    e_score = evidence_score(item)

    if e_score == 0:

        risk_flags.append(
            "正品/全新/得物查验证据不足"
        )

    elif e_score == 1:

        risk_flags.append(
            "商品状态证据较少"
        )


    # --------------------------------------------------------
    # 15. 得物查验
    # --------------------------------------------------------

    dewu_check = item.get(
        "dewu_check_compatible"
    )

    if dewu_check is False:

        return filtered_result(
            item,
            "明确不兼容得物查验",
            "D"
        )


    # --------------------------------------------------------
    # 16. 利润评分
    # --------------------------------------------------------

    if profit >= 50:
        profit_score = 4

    elif profit >= 30:
        profit_score = 3

    elif profit >= MIN_PROFIT:
        profit_score = 2

    else:
        profit_score = 1


    if profit_rate >= 30:
        rate_score = 4

    elif profit_rate >= 20:
        rate_score = 3

    elif profit_rate >= MIN_PROFIT_RATE:
        rate_score = 2

    else:
        rate_score = 1


    # --------------------------------------------------------
    # 17. 安全垫评分
    # --------------------------------------------------------

    if safety_rate is not None and safety_rate >= 20:
        safety_score = 3

    elif safety_rate is not None and safety_rate >= 12:
        safety_score = 2

    elif safety_rate is not None and safety_rate > 0:
        safety_score = 1

    else:
        safety_score = 0


    # --------------------------------------------------------
    # 18. 资金占用评分
    # --------------------------------------------------------

    capital_ratio = (
        total_buy_cost
        / CAPITAL
    )

    if capital_ratio <= 0.35:
        capital_score = 3

    elif capital_ratio <= 0.60:
        capital_score = 2

    elif capital_ratio <= 0.85:
        capital_score = 1

    else:
        capital_score = 0


    # --------------------------------------------------------
    # 19. 销量 / 趋势评分
    # --------------------------------------------------------

    s_score = sales_score(
        turnover
    )

    t_score = trend_score(
        price
    )


    # --------------------------------------------------------
    # 20. 硬风险
    # --------------------------------------------------------

    hard_risk = False

    if profit <= 0:
        hard_risk = True

    if profit_rate <= 0:
        hard_risk = True

    if (
        safety_rate is not None
        and safety_rate <= 0
    ):
        hard_risk = True

    if (
        trend == "falling"
        and change_7d is not None
        and change_7d <= -15
    ):

        hard_risk = True

        risk_flags.append(
            "7日价格明显下跌"
        )

    if (
        downside_amount is not None
        and downside_amount > MAX_DOWNSIDE_LOSS
    ):

        # 下行风险超过¥25，不进入推荐
        hard_risk = True


    # --------------------------------------------------------
    # 21. ABCD
    # --------------------------------------------------------

    if hard_risk:

        grade = "D"

        grade_reason = (
            "存在明确的较大下行风险或其他硬风险"
        )

    elif (
        profit >= 30
        and profit_rate >= 20
        and safety_rate is not None
        and safety_rate >= 12
        and s_score >= 2
        and t_score >= 2
        and capital_score >= 1
        and e_score >= 2
    ):

        grade = "A"

        grade_reason = (
            "利润较高、利润率较高、"
            "利润安全垫较充足，"
            "近期销量/价格证据较好"
        )

    elif (
        profit >= MIN_PROFIT
        and profit_rate >= MIN_PROFIT_RATE
        and safety_rate is not None
        and safety_rate > 0
    ):

        grade = "B"

        grade_reason = (
            "存在明确盈利空间，"
            "近期销量或价格证据至少有一项，"
            "但部分证据仍不够完整"
        )

    else:

        grade = "C"

        grade_reason = (
            "存在一定价差，"
            "但利润、利润率或稳定性暂时不足"
        )


    # --------------------------------------------------------
    # 22. 原因
    # --------------------------------------------------------

    if profit < MIN_PROFIT:

        reasons.append(
            f"净利润¥{profit:.2f}低于¥{MIN_PROFIT}"
        )

    if profit_rate < MIN_PROFIT_RATE:

        reasons.append(
            (
                f"利润率{profit_rate:.1f}%"
                f"低于{MIN_PROFIT_RATE}%"
            )
        )

    if (
        downside_amount is not None
        and downside_amount > 0
    ):

        reasons.append(
            (
                f"距离7日低点约¥"
                f"{downside_amount:.2f}"
            )
        )

    if trend == "falling":

        reasons.append(
            "价格走势偏下行"
        )


    # --------------------------------------------------------
    # 23. 状态
    # --------------------------------------------------------

    status = (
        "候选"
        if grade in ("A", "B")
        else "不推荐"
    )


    # --------------------------------------------------------
    # 24. 最终结果
    # --------------------------------------------------------

    return {

        "name":
            item.get(
                "name",
                "未知商品"
            ),

        "grade":
            grade,

        "grade_reason":
            grade_reason,

        "status":
            status,

        "buy_price":
            round(buy, 2),

        "dewu_price":
            round(sale, 2),

        "expected_income":
            round(expected_income, 2),

        "income_method":
            income_method,

        "dewu_fee_rate":
            DEWU_FEE_RATE * 100,

        "buy_shipping_cost":
            round(buy_shipping, 2),

        "buy_shipping_confirmed":
            shipping_confirmed,

        "total_buy_cost":
            round(total_buy_cost, 2),

        "capital_usage_rate":
            round(
                capital_ratio * 100,
                2
            ),

        "net_profit":
            round(profit, 2),

        "profit_rate":
            round(profit_rate, 2),

        "break_even_sale":
            break_even_sale,

        "profit_safety_margin_amount":
            safety_amount,

        "profit_safety_margin_rate":
            safety_rate,

        # -------------------------
        # 周转
        # -------------------------

        "days":
            turnover["days"],

        "days_display":
            turnover["display"],

        "turnover_confirmed":
            turnover["confirmed"],

        "turnover_evidence":
            turnover["display"],

        "sales":
            item.get("sales"),

        "sales_7d":
            turnover["sales_7d"],

        "sales_30d":
            turnover["sales_30d"],

        "sales_velocity_7d":
            turnover["velocity"],

        # -------------------------
        # 价格走势
        # -------------------------

        "price_current":
            price["current"],

        "trend_current_price":
            price["current"],

        "price_7d_low":
            price["low"],

        "price_7d_high":
            price["high"],

        "downside_to_7d_low":
            downside_percent,

        "downside_loss":
            downside_amount,

        "price_change_1d":
            item.get("price_change_1d"),

        "price_change_7d":
            change_7d,

        "price_change_30d":
            item.get("price_change_30d"),

        "price_trend":
            trend,

        # -------------------------
        # 其他
        # -------------------------

        "liquidity":
            liquidity,

        "category":
            item.get(
                "category",
                "unknown"
            ),

        "authenticity_evidence":
            item.get(
                "authenticity_evidence"
            ),

        "new_condition_evidence":
            item.get(
                "new_condition_evidence"
            ),

        "dewu_check_evidence":
            item.get(
                "dewu_check_evidence"
            ),

        "dewu_price_source":
            item.get(
                "dewu_price_source"
            ),

        "risk_flags":
            risk_flags,

        "reasons":
            reasons,

        "score":
            (
                profit_score
                + rate_score
                + safety_score
                + capital_score
                + s_score
                + t_score
                + e_score
            ),
    }


# ============================================================
# 主程序
# ============================================================

def main():

    root = Path(
        __file__
    ).resolve().parent

    input_file = (
        root
        / "products.json"
    )

    output_file = (
        root
        / "monitor_results.json"
    )


    if not input_file.exists():

        output = {

            "updated_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "capital":
                CAPITAL,

            "candidate_count":
                0,

            "a_count":
                0,

            "b_count":
                0,

            "c_count":
                0,

            "d_count":
                0,

            "candidates":
                [],

            "all_results":
                [],

            "error":
                "products.json 不存在",
        }

        output_file.write_text(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        return


    try:

        data = json.loads(
            input_file.read_text(
                encoding="utf-8"
            )
        )

    except Exception as e:

        output = {

            "updated_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "candidate_count":
                0,

            "error":
                str(e),
        }

        output_file.write_text(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        return


    products = data.get(
        "products",
        []
    )

    if not isinstance(
        products,
        list
    ):
        products = []


    results = []


    for item in products:

        if not isinstance(
            item,
            dict
        ):
            continue

        try:

            results.append(
                evaluate(item)
            )

        except Exception as e:

            results.append({

                "name":
                    item.get(
                        "name",
                        "未知商品"
                    ),

                "grade":
                    "D",

                "grade_reason":
                    "程序评估异常",

                "status":
                    "过滤",

                "risk_flags":
                    [str(e)],

                "reasons":
                    [str(e)],
            })


    # ========================================================
    # 分类
    # ========================================================

    a_results = [
        x for x in results
        if x.get("grade") == "A"
    ]

    b_results = [
        x for x in results
        if x.get("grade") == "B"
    ]

    c_results = [
        x for x in results
        if x.get("grade") == "C"
    ]

    d_results = [
        x for x in results
        if x.get("grade") == "D"
    ]


    # A + B = 真正候选
    candidates = (
        a_results
        + b_results
    )


    # ========================================================
    # 排序
    # ========================================================

    def candidate_sort_key(item):

        grade_order = {
            "A": 0,
            "B": 1,
            "C": 2,
            "D": 3,
        }

        return (

            grade_order.get(
                item.get("grade"),
                9
            ),

            -float(
                item.get("net_profit")
                or 0
            ),

            -float(
                item.get(
                    "profit_safety_margin_rate"
                )
                or 0
            ),
        )


    candidates.sort(
        key=candidate_sort_key
    )


    # ========================================================
    # 输出
    # ========================================================

    output = {

        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "capital":
            CAPITAL,

        "max_days":
            MAX_DAYS,

        "min_profit":
            MIN_PROFIT,

        "min_profit_rate":
            MIN_PROFIT_RATE,

        "max_downside_loss":
            MAX_DOWNSIDE_LOSS,

        "dewu_fee_rate":
            DEWU_FEE_RATE,

        "dewu_net_rate":
            DEWU_NET_RATE,

        "monitored_count":
            len(products),

        "candidate_count":
            len(candidates),

        "a_count":
            len(a_results),

        "b_count":
            len(b_results),

        "c_count":
            len(c_results),

        "d_count":
            len(d_results),

        "candidates":
            candidates,

        "all_results":
            results,
    }


    output_file.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


    # ========================================================
    # Actions 日志
    # ========================================================

    print("=" * 70)

    print("得物低买高卖监控完成")

    print(
        f"监控商品：{len(products)}"
    )

    print(
        f"A 推荐：{len(a_results)}"
    )

    print(
        f"B 较推荐：{len(b_results)}"
    )

    print(
        f"C 不推荐：{len(c_results)}"
    )

    print(
        f"D 过滤：{len(d_results)}"
    )

    print(
        f"真正候选 A+B：{len(candidates)}"
    )

    print("=" * 70)


    for item in candidates:

        print()

        print(
            f"【{item.get('grade')}】"
            f"{item.get('name')}"
        )

        print(
            f"买入：¥{item.get('buy_price')}"
        )

        print(
            f"得物：¥{item.get('dewu_price')}"
        )

        print(
            f"净利润：¥{item.get('net_profit')}"
        )

        print(
            f"利润率：{item.get('profit_rate')}%"
        )

        print(
            f"周转证据："
            f"{item.get('turnover_evidence')}"
        )

        print(
            f"当前价：¥"
            f"{item.get('price_current')}"
        )

        print(
            f"7日最低：¥"
            f"{item.get('price_7d_low')}"
        )

        print(
            f"下跌风险："
            f"{item.get('downside_to_7d_low')}%"
        )

        print(
            f"价格趋势："
            f"{item.get('price_trend')}"
        )

        print(
            f"原因："
            f"{item.get('grade_reason')}"
        )


if __name__ == "__main__":
    main()
