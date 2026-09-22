import json
from pathlib import Path

# ==========================================
# 快进快出监控系统
# 当前阶段：风控引擎
# 注意：products.json 里的价格必须是真实、可核验的数据
# ==========================================


# ===== 你的资金规则 =====
CAPITAL = 330
MAX_BUY = 120
MAX_DAYS = 7


# ===== 你的利润规则 =====
MIN_PROFIT = 15
MIN_PROFIT_RATE = 12


# ===== 你的最大风险 =====
MAX_DOWNSIDE_LOSS = 25


# ===== 其他交易成本 =====
SHIPPING_COST = 6


def estimate_dewu_fee(sale_price):
    """
    得物手续费前期采用保守估算。
    注意：这不是得物官方固定收费标准。
    后续接入真实费用数据后再替换。

    售价越高，暂时按照更高的费用估算。
    """

    if sale_price < 300:
        return 50

    elif sale_price < 600:
        return 70

    elif sale_price < 1000:
        return 90

    elif sale_price < 2000:
        return 120

    else:
        return 150


def evaluate(item):

    reasons = []

    # ------------------------------------------
    # 1. 检查四个平台价格
    # ------------------------------------------

    buy_prices = item.get("buy_prices", {})

    valid_prices = [
        price
        for price in buy_prices.values()
        if isinstance(price, (int, float)) and price > 0
    ]

    if not valid_prices:

        return {
            "name": item.get("name", "未知商品"),
            "status": "过滤",
            "reasons": ["没有有效买入价格"],
        }

    # 找四个平台中的最低真实买入价
    buy = min(valid_prices)


    # ------------------------------------------
    # 2. 检查资金占用
    # ------------------------------------------

    if buy > MAX_BUY:

        reasons.append(
            f"买入价 ¥{buy:.0f} 超过单笔上限 ¥{MAX_BUY}"
        )

    if buy > CAPITAL:

        reasons.append(
            "超过当前本金"
        )


    # ------------------------------------------
    # 3. 检查周转时间
    # ------------------------------------------

    days = item.get("days")

    if not isinstance(days, (int, float)):

        reasons.append(
            "无法确认预计周转时间"
        )

        days = 999

    elif days > MAX_DAYS:

        reasons.append(
            f"预计周转 {days} 天，超过 {MAX_DAYS} 天"
        )


    # ------------------------------------------
    # 4. 检查流动性
    # ------------------------------------------

    liquidity = item.get(
        "liquidity",
        "未知"
    )

    if liquidity != "高":

        reasons.append(
            f"流动性不是高（当前：{liquidity}）"
        )


    # ------------------------------------------
    # 5. 检查得物卖出价格
    # ------------------------------------------

    sale = item.get("dewu_price")

    if not isinstance(sale, (int, float)) or sale <= 0:

        reasons.append(
            "没有有效得物卖出价格"
        )

        sale = 0


    # ------------------------------------------
    # 6. 计算得物手续费
    # ------------------------------------------

    dewu_fee = estimate_dewu_fee(sale)


    # ------------------------------------------
    # 7. 计算真实成本
    # ------------------------------------------

    cost = (
        buy
        + dewu_fee
        + SHIPPING_COST
    )


    # ------------------------------------------
    # 8. 计算净利润
    # ------------------------------------------

    profit = sale - cost

    if buy > 0:

        profit_rate = (
            profit / buy * 100
        )

    else:

        profit_rate = 0


    # ------------------------------------------
    # 9. 检查最低利润
    # ------------------------------------------

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


    # ------------------------------------------
    # 10. 检查下跌风险
    # ------------------------------------------

    downside_loss = item.get(
        "downside_loss"
    )

    if not isinstance(
        downside_loss,
        (int, float)
    ):

        reasons.append(
            "无法确认下跌风险"
        )

        downside_loss = 999

    elif downside_loss > MAX_DOWNSIDE_LOSS:

        reasons.append(
            f"最大预估亏损 ¥{downside_loss:.0f}，"
            f"超过 ¥{MAX_DOWNSIDE_LOSS}"
        )


    # ------------------------------------------
    # 11. 正品检查
    # ------------------------------------------

    if item.get(
        "authenticity_verified"
    ) is not True:

        reasons.append(
            "正品无法确认"
        )


    # ------------------------------------------
    # 12. 全新/成色检查
    # ------------------------------------------

    if item.get(
        "new_condition_verified"
    ) is not True:

        reasons.append(
            "全新/成色无法确认"
        )


    # ------------------------------------------
    # 13. 得物查验检查
    # ------------------------------------------

    if item.get(
        "dewu_check_compatible"
    ) is not True:

        reasons.append(
            "无法确认符合得物查验要求"
        )


    # ------------------------------------------
    # 14. 最终结果
    # ------------------------------------------

    status = (
        "候选"
        if len(reasons) == 0
        else "过滤"
    )


    return {

        "name": item.get(
            "name",
            "未知商品"
        ),

        "buy_price": round(
            buy,
            2
        ),

        "dewu_price": round(
            sale,
            2
        ),

        "dewu_fee": round(
            dewu_fee,
            2
        ),

        "shipping_cost": round(
            SHIPPING_COST,
            2
        ),

        "cost": round(
            cost,
            2
        ),

        "net_profit": round(
            profit,
            2
        ),

        "profit_rate": round(
            profit_rate,
            1
        ),

        "days": days,

        "liquidity": liquidity,

        "downside_loss": downside_loss,

        "status": status,

        "reasons": reasons,
    }


def main():

    # ------------------------------------------
    # 读取商品数据
    # ------------------------------------------

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


    # ------------------------------------------
    # 开始分析
    # ------------------------------------------

    results = [
        evaluate(item)
        for item in products
    ]


    candidates = [
        item
        for item in results
        if item["status"] == "候选"
    ]


    # ------------------------------------------
    # 输出报告
    # ------------------------------------------

    print()

    print(
        "=" * 60
    )

    print(
        "        快进快出监控系统"
    )

    print(
        "=" * 60
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
        "得物手续费：按售价 ¥50～¥150 保守估算"
    )

    print(
        "-" * 60
    )


    print(
        f"监控商品：{len(results)}"
    )

    print(
        f"符合条件：{len(candidates)}"
    )


    print(
        "-" * 60
    )


    # ------------------------------------------
    # 输出每个商品
    # ------------------------------------------

    for item in results:

        print()

        print(
            f'{item["status"]} | '
            f'{item["name"]}'
        )

        print(
            f'  买入：¥{item["buy_price"]:.0f}'
        )

        print(
            f'  得物售价：¥{item["dewu_price"]:.0f}'
        )

        print(
            f'  估算得物手续费：¥{item["dewu_fee"]:.0f}'
        )

        print(
            f'  运费：¥{item["shipping_cost"]:.0f}'
        )

        print(
            f'  总成本：¥{item["cost"]:.0f}'
        )

        print(
            f'  净利润：¥{item["net_profit"]:.0f}'
        )

        print(
            f'  利润率：{item["profit_rate"]:.1f}%'
        )

        print(
            f'  周转：{item["days"]}天'
        )

        print(
            f'  流动性：{item["liquidity"]}'
        )


        if item["status"] == "候选":

            print(
                "  ★ 候选机会"
            )

            print(
                f'  资金占用：¥{item["buy_price"]:.0f}'
            )

            print(
                f'  最大预估亏损：'
                f'¥{item["downside_loss"]:.0f}'
            )

        else:

            print(
                "  过滤原因："
                + "；".join(
                    item["reasons"]
                )
            )


    print()

    print(
        "-" * 60
    )


    if candidates:

        print(
            "★ 当前存在符合全部风控条件的候选商品"
        )

    else:

        print(
            "当前没有符合全部条件的商品"
        )

        print(
            "系统不会因为看起来有价差就提醒购买"
        )


    print(
        "=" * 60
    )


if __name__ == "__main__":

    main()
