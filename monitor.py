import json
from pathlib import Path
from datetime import datetime, timezone


# ============================================================
# 资金
# ============================================================

CAPITAL = 330

MAX_DAYS = 7

MIN_PROFIT = 15

MIN_PROFIT_RATE = 12

MAX_DOWNSIDE_LOSS = 25


# ============================================================
# 得物费用模型
#
# 当前按 8% 费用估算
#
# 预计到账 = 得物售价 × 92%
#
# 这是估算模型，不冒充实时官方结算账单。
# ============================================================

DEWU_FEE_RATE = 0.08

DEWU_NET_RATE = 0.92


# ============================================================
# 买入运费
# ============================================================

DEFAULT_BUY_SHIPPING_COST = 6


# ============================================================
# 工具
# ============================================================

def is_number(value):

    return (
        isinstance(
            value,
            (int, float)
        )
        and not isinstance(
            value,
            bool
        )
    )


def money(value):

    if is_number(value):
        return float(value)

    return None


def positive_number(value):

    value = money(
        value
    )

    if value is None:
        return None

    if value <= 0:
        return None

    return value


# ============================================================
# 得物预计到账
# ============================================================

def calculate_expected_income(
    item
):

    explicit_income = positive_number(
        item.get(
            "expected_income"
        )
    )

    if explicit_income is not None:

        return {
            "value":
                explicit_income,

            "confirmed":
                True,

            "method":
                "数据源明确预计到账",
        }

    sale = positive_number(
        item.get(
            "dewu_price"
        )
    )

    if sale is None:

        return {
            "value":
                None,

            "confirmed":
                False,

            "method":
                "没有得物有效售价",
        }

    income = (
        sale
        * DEWU_NET_RATE
    )

    if income <= 0:

        return {
            "value":
                None,

            "confirmed":
                False,

            "method":
                "费用模型计算异常",
        }

    return {
        "value":
            income,

        "confirmed":
            True,

        "method":
            "得物售价按8%费用估算到账",
    }


# ============================================================
# 买入运费
# ============================================================

def get_buy_shipping_cost(
    item
):

    value = money(
        item.get(
            "buy_shipping_cost"
        )
    )

    if value is not None:

        return {
            "value":
                value,

            "confirmed":
                True,

            "method":
                "商品买入运费",
        }

    return {
        "value":
            DEFAULT_BUY_SHIPPING_COST,

        "confirmed":
            False,

        "method":
            "默认买入运费估算",
    }


# ============================================================
# 安全垫
#
# 当前得物价格下降多少以后才会不赚钱？
#
# 盈亏平衡售价：
#
# total_buy_cost / 0.92
#
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
            "break_even_sale":
                None,

            "amount":
                None,

            "rate":
                None,
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
        "break_even_sale":
            round(
                break_even_sale,
                2
            ),

        "amount":
            round(
                amount,
                2
            ),

        "rate":
            round(
                rate,
                2
            ),
    }


# ============================================================
# 品类判断
# ============================================================

def category_status(
    item
):

    category = str(
        item.get(
            "category",
            "unknown"
        )
    ).lower()

    if category == "excluded":

        return "excluded"

    if category == "target":

        return "target"

    return "unknown"


# ============================================================
# 销量评分
# ============================================================

def sales_score(
    item
):

    sales_7d = positive_number(
        item.get(
            "sales_7d"
        )
    )

    sales_30d = positive_number(
        item.get(
            "sales_30d"
        )
    )

    velocity = positive_number(
        item.get(
            "sales_velocity_7d"
        )
    )

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
        velocity is not None
        and velocity >= 1
    ):

        return 2

    if (
        sales_30d is not None
        and sales_30d >= 30
    ):

        return 1

    if (
        sales_7d is not None
        or sales_30d is not None
    ):

        return 1

    return 0


# ============================================================
# 价格趋势评分
# ============================================================

def trend_score(
    item
):

    trend = item.get(
        "price_trend"
    )

    change = money(
        item.get(
            "price_change_7d"
        )
    )

    if trend == "rising":

        return 3

    if trend == "stable":

        return 2

    if trend == "falling":

        if (
            change is not None
            and change <= -10
        ):

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

    return 0


# ============================================================
# 证据评分
# ============================================================

def evidence_score(
    item
):

    score = 0

    if item.get(
        "authenticity_evidence"
    ):

        score += 1

    if item.get(
        "new_condition_evidence"
    ):

        score += 1

    if item.get(
        "dewu_check_evidence"
    ):

        score += 1

    return score


# ============================================================
# 空过滤结果
# ============================================================

def filtered_result(
    item,
    reason,
    grade="D"
):

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

        "profit_safety_margin_amount":
            None,

        "profit_safety_margin_rate":
            None,

        "break_even_sale":
            None,

        "sales_7d":
            item.get(
                "sales_7d"
            ),

        "sales_30d":
            item.get(
                "sales_30d"
            ),

        "sales_velocity_7d":
            item.get(
                "sales_velocity_7d"
            ),

        "price_change_7d":
            item.get(
                "price_change_7d"
            ),

        "price_trend":
            item.get(
                "price_trend"
            ),

        "category":
            item.get(
                "category",
                "unknown"
            ),

        "risk_flags":
            [
                reason
            ],

        "reasons":
            [
                reason
            ],
    }


# ============================================================
# 核心评估
# ============================================================

def evaluate(
    item
):

    reasons = []

    risk_flags = []


    # ========================================================
    # 1. 品类
    # ========================================================

    category = category_status(
        item
    )

    if category == "excluded":

        return filtered_result(
            item,
            "非目标商品品类",
            "D"
        )


    # ========================================================
    # 2. 买入价格
    # ========================================================

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

    for source, price in buy_prices.items():

        if (
            is_number(price)
            and price > 0
        ):

            valid_prices.append(
                float(price)
            )

    if not valid_prices:

        return filtered_result(
            item,
            "没有有效买入价格",
            "D"
        )

    buy = min(
        valid_prices
    )


    # ========================================================
    # 3. 得物售价
    # ========================================================

    sale = positive_number(
        item.get(
            "dewu_price"
        )
    )

    if sale is None:

        return filtered_result(
            item,
            "没有有效得物公开售价",
            "D"
        )


    # ========================================================
    # 4. 预计到账
    # ========================================================

    income_result = calculate_expected_income(
        item
    )

    expected_income = (
        income_result[
            "value"
        ]
    )

    income_method = (
        income_result[
            "method"
        ]
    )

    if expected_income is None:

        return filtered_result(
            item,
            "无法计算预计到账",
            "D"
        )


    # ========================================================
    # 5. 买入运费
    # ========================================================

    shipping_result = get_buy_shipping_cost(
        item
    )

    buy_shipping = (
        shipping_result[
            "value"
        ]
    )

    shipping_confirmed = (
        shipping_result[
            "confirmed"
        ]
    )

    if not shipping_confirmed:

        risk_flags.append(
            "买入运费未明确"
        )


    # ========================================================
    # 6. 总成本
    # ========================================================

    total_buy_cost = (
        buy
        + buy_shipping
    )


    # ========================================================
    # 7. 资金限制
    #
    # 注意：
    # 不再有 MAX_BUY=120
    #
    # 单笔可以买超过120。
    #
    # 但是不能超过当前本金330。
    # ========================================================

    if total_buy_cost > CAPITAL:

        return filtered_result(
            item,
            f"总资金占用 ¥{total_buy_cost:.2f} 超过当前本金 ¥{CAPITAL}",
            "D"
        )


    # ========================================================
    # 8. 净利润
    # ========================================================

    profit = (
        expected_income
        - total_buy_cost
    )

    profit_rate = (
        profit
        / total_buy_cost
        * 100
    )


    # ========================================================
    # 9. 利润安全垫
    # ========================================================

    safety = calculate_profit_safety_margin(
        sale,
        total_buy_cost
    )

    safety_amount = safety[
        "amount"
    ]

    safety_rate = safety[
        "rate"
    ]

    break_even_sale = safety[
        "break_even_sale"
    ]


    # ========================================================
    # 10. 直接亏损
    # ========================================================

    if profit <= 0:

        return filtered_result(
            item,
            f"预计净利润为 ¥{profit:.2f}，没有实际盈利空间",
            "D"
        )


    # ========================================================
    # 11. 周转
    # ========================================================

    days = item.get(
        "days"
    )

    days_confirmed = (
        is_number(days)
        and days >= 0
    )

    if not days_confirmed:

        risk_flags.append(
            "周转天数未确认"
        )

    elif days > MAX_DAYS:

        risk_flags.append(
            f"预计周转 {days:g} 天，超过 {MAX_DAYS} 天"
        )


    # ========================================================
    # 12. 流动性
    # ========================================================

    liquidity = str(
        item.get(
            "liquidity",
            "未知"
        )
    )

    if liquidity not in (
        "高",
        "中",
    ):

        risk_flags.append(
            f"流动性：{liquidity}"
        )


    # ========================================================
    # 13. 销量
    # ========================================================

    sales_7d = positive_number(
        item.get(
            "sales_7d"
        )
    )

    sales_30d = positive_number(
        item.get(
            "sales_30d"
        )
    )

    sales_velocity = positive_number(
        item.get(
            "sales_velocity_7d"
        )
    )

    s_score = sales_score(
        item
    )

    if sales_7d is None:

        risk_flags.append(
            "近7日销量未公开或未获取"
        )


    # ========================================================
    # 14. 价格趋势
    # ========================================================

    price_change_7d = money(
        item.get(
            "price_change_7d"
        )
    )

    price_trend = item.get(
        "price_trend"
    )

    t_score = trend_score(
        item
    )

    if price_trend is None:

        risk_flags.append(
            "价格走势未确认"
        )

    elif price_trend == "falling":

        risk_flags.append(
            "近期价格走势偏弱"
        )


    # ========================================================
    # 15. 证据
    # ========================================================

    e_score = evidence_score(
        item
    )

    if e_score == 0:

        risk_flags.append(
            "缺少正品/全新/得物查验公开证据"
        )

    elif e_score == 1:

        risk_flags.append(
            "商品状态证据较少"
        )


    # ========================================================
    # 16. 得物查验兼容
    # ========================================================

    dewu_check = item.get(
        "dewu_check_compatible"
    )

    if dewu_check is False:

        risk_flags.append(
            "得物查验兼容性未确认"
        )


    # ========================================================
    # 17. 利润等级
    # ========================================================

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


    # ========================================================
    # 18. 安全垫
    # ========================================================

    if (
        safety_rate is not None
        and safety_rate >= 20
    ):

        safety_score = 3

    elif (
        safety_rate is not None
        and safety_rate >= 12
    ):

        safety_score = 2

    elif (
        safety_rate is not None
        and safety_rate > 0
    ):

        safety_score = 1

    else:

        safety_score = 0


    # ========================================================
    # 19. 资金占用
    #
    # 越少越好，但不再直接因为>120过滤。
    # ========================================================

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


    # ========================================================
    # 20. 综合评分
    #
    # 不是简单“分数决定一切”。
    # 下面还会有硬性风险限制。
    # ========================================================

    total_score = (

        profit_score

        + rate_score

        + safety_score

        + capital_score

        + s_score

        + t_score

        + e_score
    )


    # ========================================================
    # 21. 硬风险
    # ========================================================

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
        price_trend == "falling"
        and price_change_7d is not None
        and price_change_7d <= -15
    ):

        hard_risk = True

        risk_flags.append(
            "7日价格明显下跌"
        )

    downside_loss = money(
        item.get(
            "downside_loss"
        )
    )

    if (
        downside_loss is not None
        and downside_loss > MAX_DOWNSIDE_LOSS
    ):

        risk_flags.append(
            f"预估下行损失 ¥{downside_loss:.2f} 超过 ¥{MAX_DOWNSIDE_LOSS}"
        )


    # ========================================================
    # 22. ABCD
    #
    # A：
    # 高利润 + 安全垫 + 销量/趋势 + 资金合理
    #
    # B：
    # 基本盈利，风险可控，但证据不够完美
    #
    # C：
    # 有利润，但不够稳定/风险较高
    #
    # D：
    # 不适合进入实际候选
    # ========================================================

    if hard_risk:

        grade = "D"

        grade_reason = (
            "存在明显硬风险"
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
        and not (
            price_trend == "falling"
            and price_change_7d is not None
            and price_change_7d < -10
        )
    ):

        grade = "A"

        grade_reason = (
            "利润较高、利润率较高、"
            "利润安全垫充足，"
            "销量/价格趋势证据较好，"
            "资金占用可控"
        )

    elif (
        profit >= MIN_PROFIT
        and profit_rate >= MIN_PROFIT_RATE
        and safety_rate is not None
        and safety_rate > 0
        and capital_score >= 0
    ):

        grade = "B"

        grade_reason = (
            "存在明确盈利空间，"
            "但销量、走势、证据或资金占用中"
            "至少有一项不够强"
        )

    else:

        grade = "C"

        grade_reason = (
            "虽然存在价差/盈利，"
            "但利润、利润率或稳定性不足，"
            "暂不推荐"
        )


    # ========================================================
    # 23. C/D具体原因
    # ========================================================

    if profit < MIN_PROFIT:

        reasons.append(
            f"净利润 ¥{profit:.2f} 低于 ¥{MIN_PROFIT}"
        )

    if profit_rate < MIN_PROFIT_RATE:

        reasons.append(
            f"利润率 {profit_rate:.1f}% 低于 {MIN_PROFIT_RATE}%"
        )

    if (
        safety_rate is not None
        and safety_rate < 10
    ):

        reasons.append(
            f"利润安全垫只有 {safety_rate:.1f}%"
        )

    if (
        sales_7d is not None
        and sales_7d < 7
    ):

        reasons.append(
            f"近7日销量仅 {sales_7d:g}"
        )

    if price_trend == "falling":

        reasons.append(
            "价格走势偏下行"
        )


    # ========================================================
    # 24. 最终结果
    # ========================================================

    status = (
        "候选"
        if grade in (
            "A",
            "B",
        )
        else "不推荐"
    )

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
            round(
                buy,
                2
            ),

        "dewu_price":
            round(
                sale,
                2
            ),

        "expected_income":
            round(
                expected_income,
                2
            ),

        "income_method":
            income_method,

        "dewu_fee_rate":
            DEWU_FEE_RATE * 100,

        "buy_shipping_cost":
            round(
                buy_shipping,
                2
            ),

        "buy_shipping_confirmed":
            shipping_confirmed,

        "total_buy_cost":
            round(
                total_buy_cost,
                2
            ),

        "capital_usage_rate":
            round(
                capital_ratio * 100,
                2
            ),

        "net_profit":
            round(
                profit,
                2
            ),

        "profit_rate":
            round(
                profit_rate,
                2
            ),

        "break_even_sale":
            break_even_sale,

        "profit_safety_margin_amount":
            safety_amount,

        "profit_safety_margin_rate":
            safety_rate,

        "days":
            days,

        "days_display":
            (
                f"{days:g}天"
                if days_confirmed
                else "未确认"
            ),

        "liquidity":
            liquidity,

        "downside_loss":
            downside_loss,

        "sales":
            item.get(
                "sales"
            ),

        "sales_7d":
            sales_7d,

        "sales_30d":
            sales_30d,

        "sales_velocity_7d":
            sales_velocity,

        "price_current":
            item.get(
                "price_current"
            ),

        "price_change_1d":
            item.get(
                "price_change_1d"
            ),

        "price_change_7d":
            price_change_7d,

        "price_change_30d":
            item.get(
                "price_change_30d"
            ),

        "price_trend":
            price_trend,

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
            total_score,
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

            result = evaluate(
                item
            )

            results.append(
                result
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
                    [
                        str(e)
                    ],

                "reasons":
                    [
                        str(e)
                    ],
            })


    # ========================================================
    # 统计
    # ========================================================

    a_results = [
        x
        for x in results
        if x.get(
            "grade"
        ) == "A"
    ]

    b_results = [
        x
        for x in results
        if x.get(
            "grade"
        ) == "B"
    ]

    c_results = [
        x
        for x in results
        if x.get(
            "grade"
        ) == "C"
    ]

    d_results = [
        x
        for x in results
        if x.get(
            "grade"
        ) == "D"
    ]


    # A+B 才是真正候选
    candidates = (
        a_results
        + b_results
    )


    # ========================================================
    # A优先、B其次、利润最高优先
    # ========================================================

    def candidate_sort_key(
        item
    ):

        grade_order = {
            "A": 0,
            "B": 1,
            "C": 2,
            "D": 3,
        }

        return (
            grade_order.get(
                item.get(
                    "grade"
                ),
                9
            ),

            -float(
                item.get(
                    "net_profit"
                )
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
    # Actions日志
    # ========================================================

    print("=" * 70)

    print(
        "得物低买高卖监控完成"
    )

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


    # --------------------------------------------------------
    # 打印 A/B
    # --------------------------------------------------------

    for item in candidates:

        print()

        print(
            "【"
            + str(
                item.get(
                    "grade"
                )
            )
            + "】"
            + str(
                item.get(
                    "name"
                )
            )
        )

        print(
            "买入：¥"
            + str(
                item.get(
                    "buy_price"
                )
            )
        )

        print(
            "得物：¥"
            + str(
                item.get(
                    "dewu_price"
                )
            )
        )

        print(
            "净利润：¥"
            + str(
                item.get(
                    "net_profit"
                )
            )
        )

        print(
            "利润率："
            + str(
                item.get(
                    "profit_rate"
                )
            )
            + "%"
        )

        print(
            "利润安全垫："
            + str(
                item.get(
                    "profit_safety_margin_rate"
                )
            )
            + "%"
        )

        print(
            "近7日销量："
            + str(
                item.get(
                    "sales_7d"
                )
            )
        )

        print(
            "7日价格变化："
            + str(
                item.get(
                    "price_change_7d"
                )
            )
            + "%"
        )

        print(
            "价格趋势："
            + str(
                item.get(
                    "price_trend"
                )
            )
        )

        print(
            "原因："
            + str(
                item.get(
                    "grade_reason"
                )
            )
        )


if __name__ == "__main__":

    main()
