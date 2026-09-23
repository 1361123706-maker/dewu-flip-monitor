import json
from pathlib import Path
from datetime import datetime, timezone


# ============================================================
# 核心资金与风控
# ============================================================

CAPITAL = 330

MAX_BUY = 120

MAX_DAYS = 7

MIN_PROFIT = 15

MIN_PROFIT_RATE = 12

MAX_DOWNSIDE_LOSS = 25


# ============================================================
# 注意：
# 如果没有明确的买入运费，就不能假装它是 0。
# 这里仍保留默认值，但会记录为估算成本。
# ============================================================

DEFAULT_BUY_SHIPPING_COST = 6


# ============================================================
# 基础工具
# ============================================================

def is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    )


def money(value):
    if is_number(value):
        return float(value)

    return None


def positive_number(value):
    value = money(value)

    if value is None:
        return None

    if value <= 0:
        return None

    return value


# ============================================================
# 计算得物实际预计到账
#
# 重要：
# 绝不使用：
#
#     得物展示价 = 实际到账
#
# 只有：
#
#     expected_income
#
# 或者：
#
#     得物售价 - 完整费用
#
# 才允许进入利润计算。
# ============================================================

def calculate_expected_income(item):

    expected_income = positive_number(
        item.get("expected_income")
    )

    if expected_income is not None:

        return {
            "value": expected_income,
            "confirmed": True,
            "method": "得物明确预计收入"
        }


    sale = positive_number(
        item.get("dewu_price")
    )

    if sale is None:

        return {
            "value": None,
            "confirmed": False,
            "method": "没有得物有效售价"
        }


    technical = money(
        item.get("technical_service_fee")
    )

    operation = money(
        item.get("operation_service_fee")
    )

    shipping = money(
        item.get("consumer_shipping_subsidy")
    )

    transfer = money(
        item.get("transfer_fee")
    )

    after_sales = money(
        item.get("after_sales_service_fee")
    )

    coupon = money(
        item.get("seller_coupon_offset")
    )


    # --------------------------------------------------------
    # 任何费用缺失，都不能自己猜。
    # --------------------------------------------------------

    required_fees = [
        technical,
        operation,
        shipping,
        transfer,
        after_sales,
        coupon,
    ]

    if not all(
        value is not None
        for value in required_fees
    ):

        return {
            "value": None,
            "confirmed": False,
            "method": "得物费用数据不完整"
        }


    calculated = (
        sale
        - technical
        - operation
        - shipping
        - transfer
        - after_sales
        + coupon
    )


    if calculated <= 0:

        return {
            "value": None,
            "confirmed": False,
            "method": "计算后的预计到账异常"
        }


    return {
        "value": calculated,
        "confirmed": True,
        "method": "按完整得物费用明细计算"
    }


# ============================================================
# 买入运费
# ============================================================

def get_buy_shipping_cost(item):

    value = money(
        item.get("buy_shipping_cost")
    )

    if value is not None:

        return {
            "value": value,
            "confirmed": True,
            "method": "商品买入运费"
        }


    # 没有明确买入运费时：
    # 仍然采用保守成本，但标记为估算。
    return {
        "value": DEFAULT_BUY_SHIPPING_COST,
        "confirmed": False,
        "method": "默认买入运费估算"
    }


# ============================================================
# 空过滤结果
# ============================================================

def empty_filtered_result(
    item,
    reason
):

    return {

        "name":
            item.get(
                "name",
                "未知商品"
            ),

        "buy_price":
            None,

        "dewu_price":
            None,

        "expected_income":
            None,

        "income_method":
            "无法计算",


        "technical_service_fee":
            item.get(
                "technical_service_fee"
            ),

        "technical_service_rate":
            item.get(
                "technical_service_rate"
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

        "transfer_fee_rate":
            item.get(
                "transfer_fee_rate"
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
            None,

        "buy_shipping_confirmed":
            False,

        "total_buy_cost":
            None,

        "net_profit":
            None,

        "profit_rate":
            None,


        "days":
            None,

        "days_display":
            "未确认",


        "liquidity":
            item.get(
                "liquidity",
                "未知"
            ),


        "downside_loss":
            None,

        "downside_display":
            "未确认",


        "authenticity_verified":
            False,

        "new_condition_verified":
            False,

        "dewu_check_compatible":
            False,


        "status":
            "过滤",

        "reasons":
            [reason],
    }


# ============================================================
# 核心评估
# ============================================================

def evaluate(item):

    reasons = []


    # ========================================================
    # 1. 买入价格
    # ========================================================

    buy_prices = item.get(
        "buy_prices",
        {}
    )

    if not isinstance(
        buy_prices,
        dict
    ):

        return empty_filtered_result(
            item,
            "买入价格字段格式错误"
        )


    valid_prices = []

    for source, price in buy_prices.items():

        if is_number(price) and price > 0:

            valid_prices.append(
                float(price)
            )


    if not valid_prices:

        return empty_filtered_result(
            item,
            "没有有效买入价格"
        )


    # 使用当前公开来源中的最低价格
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


    # ========================================================
    # 2. 周转时间
    # ========================================================

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


    # ========================================================
    # 3. 流动性
    # ========================================================

    liquidity = item.get(
        "liquidity",
        "未知"
    )


    if liquidity != "高":

        reasons.append(
            f"流动性不是高"
            f"（当前：{liquidity}）"
        )


    # ========================================================
    # 4. 得物售价
    # ========================================================

    sale = positive_number(
        item.get(
            "dewu_price"
        )
    )


    sale_confirmed = (
        sale is not None
    )


    if not sale_confirmed:

        reasons.append(
            "得物售价：未确认"
        )


    # ========================================================
    # 5. 得物预计实际到账
    # ========================================================

    income_result = (
        calculate_expected_income(
            item
        )
    )


    expected_income = (
        income_result["value"]
    )


    income_confirmed = (
        income_result["confirmed"]
    )


    if not income_confirmed:

        reasons.append(
            "得物实际预计到账无法确认"
        )


    # ========================================================
    # 6. 买入运费
    # ========================================================

    buy_shipping_result = (
        get_buy_shipping_cost(
            item
        )
    )


    buy_shipping = (
        buy_shipping_result["value"]
    )


    buy_shipping_confirmed = (
        buy_shipping_result["confirmed"]
    )


    # --------------------------------------------------------
    # 买入运费如果只是默认估算：
    #
    # 可以用于风险计算，
    # 但不能作为“实打实利益”的完全确认。
    # --------------------------------------------------------

    if not buy_shipping_confirmed:

        reasons.append(
            "买入运费未明确确认"
        )


    total_buy_cost = (
        buy
        + buy_shipping
    )


    # ========================================================
    # 7. 真实净利润
    # ========================================================

    if (
        expected_income is not None
        and income_confirmed
    ):

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


    if profit is None:

        reasons.append(
            "真实净利润无法确认"
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
                f"低于最低要求 {MIN_PROFIT_RATE}%"
            )


    # ========================================================
    # 8. 下行风险
    # ========================================================

    downside_loss = (
        item.get(
            "downside_loss"
        )
    )


    downside_confirmed = (
        is_number(downside_loss)
        and downside_loss >= 0
    )


    if not downside_confirmed:

        reasons.append(
            "下跌风险：未确认"
        )

        downside_display = (
            "未确认"
        )

    else:

        downside_display = (
            f"¥{downside_loss:.0f}"
        )


        if (
            downside_loss
            > MAX_DOWNSIDE_LOSS
        ):

            reasons.append(
                f"最大预估亏损 "
                f"¥{downside_loss:.0f}，"
                f"超过 ¥{MAX_DOWNSIDE_LOSS}"
            )


    # ========================================================
    # 9. 正品
    # ========================================================

    authenticity_verified = (
        item.get(
            "authenticity_verified"
        )
        is True
    )


    if not authenticity_verified:

        reasons.append(
            "正品无法确认"
        )


    # ========================================================
    # 10. 全新状态
    # ========================================================

    new_condition_verified = (
        item.get(
            "new_condition_verified"
        )
        is True
    )


    if not new_condition_verified:

        reasons.append(
            "全新/成色无法确认"
        )


    # ========================================================
    # 11. 得物查验兼容
    # ========================================================

    dewu_check_compatible = (
        item.get(
            "dewu_check_compatible"
        )
        is True
    )


    if not dewu_check_compatible:

        reasons.append(
            "无法确认符合得物查验要求"
        )


    # ========================================================
    # 12. 商品身份
    # ========================================================

    name = str(
        item.get(
            "name",
            ""
        )
    ).strip()


    if (
        not name
        or name == "未知商品"
    ):

        reasons.append(
            "商品身份无法确认"
        )


    # ========================================================
    # 13. 最终硬门槛
    # ========================================================

    critical_confirmations = {

        "得物售价":
            sale_confirmed,

        "得物实际到账":
            income_confirmed,

        "周转":
            days_confirmed,

        "下行风险":
            downside_confirmed,

        "正品":
            authenticity_verified,

        "全新":
            new_condition_verified,

        "得物查验":
            dewu_check_compatible,

        "买入运费":
            buy_shipping_confirmed,

    }


    for field, confirmed in (
        critical_confirmations.items()
    ):

        if not confirmed:

            reasons.append(
                f"{field}证据不足"
            )


    # ========================================================
    # 最终状态
    #
    # 必须所有条件同时成立。
    # ========================================================

    status = (
        "候选"
        if len(reasons) == 0
        else "过滤"
    )


    return {

        "name":
            name
            or "未知商品",


        "buy_price":
            round(
                buy,
                2
            ),


        "dewu_price":
            (
                round(
                    sale,
                    2
                )
                if sale is not None
                else None
            ),


        "expected_income":
            (
                round(
                    expected_income,
                    2
                )
                if expected_income is not None
                else None
            ),


        "income_method":
            income_result["method"],


        "technical_service_fee":
            item.get(
                "technical_service_fee"
            ),

        "technical_service_rate":
            item.get(
                "technical_service_rate"
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

        "transfer_fee_rate":
            item.get(
                "transfer_fee_rate"
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


        "buy_shipping_confirmed":
            buy_shipping_confirmed,


        "total_buy_cost":
            round(
                total_buy_cost,
                2
            ),


        "net_profit":
            (
                round(
                    profit,
                    2
                )
                if profit is not None
                else None
            ),


        "profit_rate":
            (
                round(
                    profit_rate,
                    1
                )
                if profit_rate is not None
                else None
            ),


        "days":
            (
                days
                if days_confirmed
                else None
            ),


        "days_display":
            days_display,


        "liquidity":
            liquidity,


        "downside_loss":
            (
                downside_loss
                if downside_confirmed
                else None
            ),


        "downside_display":
            downside_display,


        "authenticity_verified":
            authenticity_verified,


        "new_condition_verified":
            new_condition_verified,


        "dewu_check_compatible":
            dewu_check_compatible,


        "status":
            status,


        "reasons":
            reasons,
    }


# ============================================================
# 写入监控结果
# ============================================================

def write_monitor_results(
    results,
    candidates
):

    panel_data = {

        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "capital":
            CAPITAL,

        "max_buy":
            MAX_BUY,

        "max_days":
            MAX_DAYS,

        "min_profit":
            MIN_PROFIT,

        "min_profit_rate":
            MIN_PROFIT_RATE,

        "max_downside_loss":
            MAX_DOWNSIDE_LOSS,

        "monitored_count":
            len(results),

        "candidate_count":
            len(candidates),

        "candidates":
            candidates,

        "results":
            results,
    }


    Path(
        "monitor_results.json"
    ).write_text(

        json.dumps(
            panel_data,
            ensure_ascii=False,
            indent=2
        ),

        encoding="utf-8"
    )


    print(
        "✅ 已生成 monitor_results.json"
    )


# ============================================================
# 主程序
# ============================================================

def main():

    file_path = Path(
        "products.json"
    )


    if not file_path.exists():

        print(
            "❌ 找不到 products.json"
        )

        write_monitor_results(
            [],
            []
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

        write_monitor_results(
            [],
            []
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

        print(
            "❌ products.json 的 "
            "products 字段格式错误"
        )

        write_monitor_results(
            [],
            []
        )

        return


    if not products:

        print(
            "❌ 当前没有商品数据"
        )

        write_monitor_results(
            [],
            []
        )

        return


    results = []


    # ========================================================
    # 逐个商品评估
    # ========================================================

    for index, item in enumerate(
        products
    ):

        if not isinstance(
            item,
            dict
        ):

            print(
                f"⚠️ 第 {index + 1} 条商品"
                "不是对象，已过滤"
            )

            results.append(
                empty_filtered_result(
                    {},
                    "商品数据格式错误"
                )
            )

            continue


        try:

            result = evaluate(
                item
            )

            results.append(
                result
            )


        except Exception as e:

            print(
                f"⚠️ 第 {index + 1} 条商品"
                f"处理失败，已过滤：{e}"
            )

            results.append(
                empty_filtered_result(
                    item,
                    "商品数据处理异常"
                )
            )


    # ========================================================
    # 只允许完整通过的商品成为候选
    # ========================================================

    candidates = [

        item

        for item in results

        if item.get(
            "status"
        ) == "候选"

    ]


    write_monitor_results(
        results,
        candidates
    )


    # ========================================================
    # 控制台报告
    # ========================================================

    print()

    print(
        "=" * 70
    )

    print(
        "          得物真实利润监控系统"
    )

    print(
        "=" * 70
    )


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
        f"最大允许下跌风险：¥{MAX_DOWNSIDE_LOSS}"
    )


    print(
        "-" * 70
    )


    print(
        f"监控商品：{len(results)}"
    )

    print(
        f"符合全部条件：{len(candidates)}"
    )


    print(
        "-" * 70
    )


    # ========================================================
    # 输出每个商品
    # ========================================================

    for item in results:

        print()

        print(
            f'{item["status"]} | '
            f'{item["name"]}'
        )


        if item["buy_price"] is not None:

            print(
                f'  买入：'
                f'¥{item["buy_price"]:.2f}'
            )

        else:

            print(
                "  买入：未确认"
            )


        if item["dewu_price"] is not None:

            print(
                f'  得物展示价：'
                f'¥{item["dewu_price"]:.2f}'
            )

        else:

            print(
                "  得物展示价：未确认"
            )


        if item["expected_income"] is not None:

            print(
                f'  实际预计到账：'
                f'¥{item["expected_income"]:.2f}'
            )

        else:

            print(
                "  实际预计到账：未确认"
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
                "  ★★★ "
                "真实盈利候选 ★★★"
            )

            print(
                f'  资金占用：'
                f'¥{item["total_buy_cost"]:.2f}'
            )

        else:

            reasons = item.get(
                "reasons",
                []
            )

            print(
                "  过滤原因："
                + "；".join(
                    reasons
                )
            )


    # ========================================================
    # 最终结论
    # ========================================================

    print()

    print(
        "=" * 70
    )


    if candidates:

        print(
            "★★★ 发现满足全部盈利与风控条件的候选 ★★★"
        )

        print(
            f"数量：{len(candidates)}"
        )

        print(
            "这些商品才允许进入下一阶段通知。"
        )

    else:

        print(
            "当前没有满足全部条件的真实盈利机会。"
        )

        print(
            "系统没有用展示价差冒充利润。"
        )

        print(
            "继续采集，不强行制造候选。"
        )


    print(
        "=" * 70
    )


if __name__ == "__main__":

    main()
