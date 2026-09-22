import json
from pathlib import Path


# ==========================================
# 快进快出监控系统
# 风控引擎
# ==========================================

CAPITAL = 330
MAX_BUY = 120
MAX_DAYS = 7

MIN_PROFIT = 15
MIN_PROFIT_RATE = 12

MAX_DOWNSIDE_LOSS = 25

# 买入端额外成本。
# 如果以后数据源能提供真实采购运费，会优先使用真实数据。
DEFAULT_BUY_SHIPPING_COST = 6


def is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    )


def money(value):
    if not is_number(value):
        return None

    return float(value)


def calculate_expected_income(item):
    """
    优先使用得物页面/合法接口提供的预计收入。

    如果没有 expected_income，
    只有在所有必要费用都明确存在时才自行计算。

    公式：

    预计收入 =
    出售价格
    - 技术服务费
    - 操作服务费
    - 消费者邮费补贴
    - 转账手续费
    - 售后无忧服务费
    + 卖家券可抵扣金额
    """

    expected_income = money(
        item.get("expected_income")
    )

    if expected_income is not None:
        return {
            "value": expected_income,
            "confirmed": True,
            "method": "得物预计收入"
        }


    sale = money(
        item.get("dewu_price")
    )

    technical_service_fee = money(
        item.get("technical_service_fee")
    )

    operation_service_fee = money(
        item.get("operation_service_fee")
    )

    consumer_shipping_subsidy = money(
        item.get("consumer_shipping_subsidy")
    )

    transfer_fee = money(
        item.get("transfer_fee")
    )

    after_sales_service_fee = money(
        item.get("after_sales_service_fee")
    )

    seller_coupon_offset = money(
        item.get("seller_coupon_offset")
    )


    required_fields = [
        sale,
        technical_service_fee,
        operation_service_fee,
        consumer_shipping_subsidy,
        transfer_fee,
        after_sales_service_fee,
        seller_coupon_offset,
    ]


    if not all(
        value is not None
        for value in required_fields
    ):
        return {
            "value": None,
            "confirmed": False,
            "method": "费用数据不完整"
        }


    calculated = (
        sale
        - technical_service_fee
        - operation_service_fee
        - consumer_shipping_subsidy
        - transfer_fee
        - after_sales_service_fee
        + seller_coupon_offset
    )


    return {
        "value": calculated,
        "confirmed": True,
        "method": "按得物费用明细计算"
    }


def get_buy_shipping_cost(item):
    """
    买入端运费。

    如果数据源以后提供 buy_shipping_cost，
    使用真实数据。

    否则当前使用保守的默认值。
    """

    value = money(
        item.get("buy_shipping_cost")
    )

    if value is not None:
        return value

    return DEFAULT_BUY_SHIPPING_COST


def evaluate(item):

    reasons = []


    # ==========================================
    # 1. 买入价格
    # ==========================================

    buy_prices = item.get(
        "buy_prices",
        {}
    )

    valid_prices = [
        price
        for price in buy_prices.values()
        if is_number(price) and price > 0
    ]


    if not valid_prices:

        return {
            "name":
                item.get(
                    "name",
                    "未知商品"
                ),

            "status":
                "过滤",

            "reasons":
                ["没有有效买入价格"],
        }


    buy = min(valid_prices)


    if buy > MAX_BUY:

        reasons.append(
            f"买入价 ¥{buy:.2f} "
            f"超过单笔上限 ¥{MAX_BUY}"
        )


    if buy > CAPITAL:

        reasons.append(
            "超过当前本金"
        )


    # ==========================================
    # 2. 周转时间
    # ==========================================

    days = item.get(
        "days"
    )

    days_confirmed = (
        is_number(days)
        and days >= 0
    )


    if not days_confirmed:

        reasons.append(
            "周转时间：未确认"
        )

        days_display = "未确认"

    else:

        days_display = (
            f"{days:g}天"
        )

        if days > MAX_DAYS:

            reasons.append(
                f"预计周转 {days:g} 天，"
                f"超过 {MAX_DAYS} 天"
            )


    # ==========================================
    # 3. 流动性
    # ==========================================

    liquidity = item.get(
        "liquidity",
        "未知"
    )


    if liquidity != "高":

        reasons.append(
            f"流动性不是高"
            f"（当前：{liquidity}）"
        )


    # ==========================================
    # 4. 得物售价
    # ==========================================

    sale = money(
        item.get("dewu_price")
    )

    sale_confirmed = (
        sale is not None
        and sale > 0
    )


    if not sale_confirmed:

        reasons.append(
            "得物售价：未确认"
        )


    # ==========================================
    # 5. 得物预计收入
    # ==========================================

    income_result = (
        calculate_expected_income(item)
    )

    expected_income = (
        income_result["value"]
    )


    if not income_result["confirmed"]:

        reasons.append(
            "得物预计收入/费用数据不完整"
        )


    # ==========================================
    # 6. 买入端成本
    # ==========================================

    buy_shipping = (
        get_buy_shipping_cost(item)
    )

    total_buy_cost = (
        buy
        + buy_shipping
    )


    # ==========================================
    # 7. 真实净利润
    # ==========================================

    if expected_income is not None:

        profit = (
            expected_income
            - total_buy_cost
        )

    else:

        profit = None


    if (
        profit is not None
        and buy > 0
    ):

        profit_rate = (
            profit
            / buy
            * 100
        )

    else:

        profit_rate = None


    # ==========================================
    # 8. 最低利润
    # ==========================================

    if profit is None:

        reasons.append(
            "净利润无法确认"
        )

    else:

        if profit < MIN_PROFIT:

            reasons.append(
                f"净利润 ¥{profit:.2f}，"
                f"低于最低要求 ¥{MIN_PROFIT}"
            )


        if profit_rate < MIN_PROFIT_RATE:

            reasons.append(
                f"利润率 {profit_rate:.1f}%，"
                f"低于最低要求 "
                f"{MIN_PROFIT_RATE}%"
            )


    # ==========================================
    # 9. 下跌风险
    # ==========================================

    downside_loss = item.get(
        "downside_loss"
    )

    downside_confirmed = (
        is_number(downside_loss)
        and downside_loss >= 0
    )


    if not downside_confirmed:

        reasons.append(
            "下跌风险：未确认"
        )

        downside_display = "未确认"

    else:

        downside_display = (
            f"¥{downside_loss:.0f}"
        )


        if downside_loss > MAX_DOWNSIDE_LOSS:

            reasons.append(
                f"最大预估亏损 "
                f"¥{downside_loss:.0f}，"
                f"超过 "
                f"¥{MAX_DOWNSIDE_LOSS}"
            )


    # ==========================================
    # 10. 正品
    # ==========================================

    if item.get(
        "authenticity_verified"
    ) is not True:

        reasons.append(
            "正品无法确认"
        )


    # ==========================================
    # 11. 全新 / 成色
    # ==========================================

    if item.get(
        "new_condition_verified"
    ) is not True:

        reasons.append(
            "全新/成色无法确认"
        )


    # ==========================================
    # 12. 得物查验
    # ==========================================

    if item.get(
        "dewu_check_compatible"
    ) is not True:

        reasons.append(
            "无法确认符合得物查验要求"
        )


    # ==========================================
    # 13. 关键行情完整度
    # ==========================================

    market_fields = {

        "dewu_price":
            sale_confirmed,

        "expected_income":
            income_result["confirmed"],

        "days":
            days_confirmed,

        "downside_loss":
            downside_confirmed,

    }


    missing_market = [

        name

        for name, confirmed
        in market_fields.items()

        if not confirmed

    ]


    if missing_market:

        reasons.append(
            "关键行情数据不完整，"
            "禁止提醒购买"
        )


    # ==========================================
    # 14. 最终结果
    # ==========================================

    status = (
        "候选"
        if len(reasons) == 0
        else "过滤"
    )


    return {

        "name":
            item.get(
                "name",
                "未知商品"
            ),

        "buy_price":
            round(
                buy,
                2
            ),

        "dewu_price":
            round(
                sale,
                2
            )
            if sale is not None
            else None,

        "expected_income":
            round(
                expected_income,
                2
            )
            if expected_income is not None
            else None,

        "income_method":
            income_result["method"],

        "technical_service_fee":
            item.get(
                "technical_service_fee"
            ),

        "operation_service_fee":
            item.get(
                "operation_service_fee"
            ),

        "consumer_shipping_subsidy":
            item.get(
                "consumer_shipping_subsidy"
            ),

        "transfer_fee":
            item.get(
                "transfer_fee"
            ),

        "after_sales_service_fee":
            item.get(
                "after_sales_service_fee"
            ),

        "seller_coupon_offset":
            item.get(
                "seller_coupon_offset"
            ),

        "buy_shipping_cost":
            round(
                buy_shipping,
                2
            ),

        "total_buy_cost":
            round(
                total_buy_cost,
                2
            ),

        "net_profit":
            round(
                profit,
                2
            )
            if profit is not None
            else None,

        "profit_rate":
            round(
                profit_rate,
                1
            )
            if profit_rate is not None
            else None,

        "days":
            days
            if days_confirmed
            else None,

        "days_display":
            days_display,

        "liquidity":
            liquidity,

        "downside_loss":
            downside_loss
            if downside_confirmed
            else None,

        "downside_display":
            downside_display,

        "status":
            status,

        "reasons":
            reasons,

    }


def main():

    # ==========================================
    # 读取商品数据
    # ==========================================

    file_path = Path(
        "products.json"
    )


    if not file_path.exists():

        print(
            "❌ 找不到 products.json"
        )

        return


    try:

        data = json.loads(
            file_path.read_text(
                encoding="utf-8"
            )
        )

    except Exception as e:

        print(
            "❌ products.json 格式错误"
        )

        print(e)

        return


    products = data.get(
        "products",
        []
    )


    if not products:

        print(
            "❌ 当前没有商品数据"
        )

        return


    # ==========================================
    # 分析
    # ==========================================

    results = [

        evaluate(item)

        for item in products

    ]


    candidates = [

        item

        for item in results

        if item["status"] == "候选"

    ]


    # ==========================================
    # 报告
    # ==========================================

    print()

    print("=" * 60)

    print(
        "        快进快出监控系统"
    )

    print("=" * 60)

    print(
        f"本金：¥{CAPITAL}"
    )

    print(
        f"单笔最高买入：¥{MAX_BUY}"
    )

    print(
        f"最长周转：{MAX_DAYS} 天"
    )

    print(
        f"最低净利润：¥{MIN_PROFIT}"
    )

    print(
        f"最低利润率：{MIN_PROFIT_RATE}%"
    )

    print(
        f"最大允许下跌风险："
        f"¥{MAX_DOWNSIDE_LOSS}"
    )

    print(
        "得物费用："
        "优先使用实际预计收入/费用数据"
    )

    print("-" * 60)

    print(
        f"监控商品：{len(results)}"
    )

    print(
        f"符合条件：{len(candidates)}"
    )

    print("-" * 60)


    # ==========================================
    # 商品结果
    # ==========================================

    for item in results:

        print()

        print(
            f'{item["status"]} | '
            f'{item["name"]}'
        )


        print(
            f'  买入：'
            f'¥{item["buy_price"]:.2f}'
        )


        if item["dewu_price"] is not None:

            print(
                f'  得物售价：'
                f'¥{item["dewu_price"]:.2f}'
            )

        else:

            print(
                "  得物售价：未确认"
            )


        if item["expected_income"] is not None:

            print(
                f'  得物预计收入：'
                f'¥{item["expected_income"]:.2f}'
            )

        else:

            print(
                "  得物预计收入：未确认"
            )


        print(
            f'  收入数据来源：'
            f'{item["income_method"]}'
        )


        print(
            f'  技术服务费：'
            f'{item["technical_service_fee"]}'
        )


        print(
            f'  操作服务费：'
            f'{item["operation_service_fee"]}'
        )


        print(
            f'  消费者邮费补贴：'
            f'{item["consumer_shipping_subsidy"]}'
        )


        print(
            f'  转账手续费：'
            f'{item["transfer_fee"]}'
        )


        print(
            f'  售后无忧服务费：'
            f'{item["after_sales_service_fee"]}'
        )


        print(
            f'  卖家券抵扣：'
            f'{item["seller_coupon_offset"]}'
        )


        print(
            f'  买入端运费：'
            f'¥{item["buy_shipping_cost"]:.2f}'
        )


        print(
            f'  买入总成本：'
            f'¥{item["total_buy_cost"]:.2f}'
        )


        if item["net_profit"] is not None:

            print(
                f'  真实净利润：'
                f'¥{item["net_profit"]:.2f}'
            )

        else:

            print(
                "  真实净利润：未确认"
            )


        if item["profit_rate"] is not None:

            print(
                f'  利润率：'
                f'{item["profit_rate"]:.1f}%'
            )

        else:

            print(
                "  利润率：未确认"
            )


        print(
            f'  周转：'
            f'{item["days_display"]}'
        )


        print(
            f'  流动性：'
            f'{item["liquidity"]}'
        )


        print(
            f'  下跌风险：'
            f'{item["downside_display"]}'
        )


        if item["status"] == "候选":

            print(
                "  ★ 候选机会"
            )

            print(
                f'  资金占用：'
                f'¥{item["buy_price"]:.2f}'
            )

        else:

            print(
                "  过滤原因："
                + "；".join(
                    item["reasons"]
                )
            )


    print()

    print("-" * 60)


    if candidates:

        print(
            "★ 当前存在符合全部"
            "风控条件的候选商品"
        )

    else:

        print(
            "当前没有符合全部条件的商品"
        )

        print(
            "系统不会因为看起来有价差"
            "就提醒购买"
        )


    print("=" * 60)


if __name__ == "__main__":

    main()
