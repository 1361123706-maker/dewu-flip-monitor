import json
from pathlib import Path

# ==========================================
# 快进快出监控系统
# 当前阶段：风控引擎
# ==========================================

CAPITAL = 330
MAX_BUY = 120
MAX_DAYS = 7

MIN_PROFIT = 15
MIN_PROFIT_RATE = 12

MAX_DOWNSIDE_LOSS = 25
SHIPPING_COST = 6


def estimate_dewu_fee(sale_price):
    """
    前期保守估算。
    注意：不是得物官方固定收费标准。
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


def is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    )


def evaluate(item):

    reasons = []

    # ==========================================
    # 1. 买入价格
    # ==========================================

    buy_prices = item.get("buy_prices", {})

    valid_prices = [
        price
        for price in buy_prices.values()
        if is_number(price) and price > 0
    ]

    if not valid_prices:

        return {
            "name": item.get("name", "未知商品"),
            "status": "过滤",
            "reasons": ["没有有效买入价格"],
        }

    buy = min(valid_prices)

    if buy > MAX_BUY:
        reasons.append(
            f"买入价 ¥{buy:.0f} 超过单笔上限 ¥{MAX_BUY}"
        )

    if buy > CAPITAL:
        reasons.append("超过当前本金")

    # ==========================================
    # 2. 周转时间
    # ==========================================

    days = item.get("days")

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

        days_display = f"{days:g}天"

        if days > MAX_DAYS:

            reasons.append(
                f"预计周转 {days:g} 天，超过 {MAX_DAYS} 天"
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
            f"流动性不是高（当前：{liquidity}）"
        )

    # ==========================================
    # 4. 得物售价
    # ==========================================

    sale = item.get("dewu_price")

    sale_confirmed = (
        is_number(sale)
        and sale > 0
    )

    if not sale_confirmed:

        reasons.append(
            "得物售价：未确认"
        )

        sale = 0

    # ==========================================
    # 5. 得物费用
    # ==========================================

    dewu_fee = estimate_dewu_fee(
        sale
    )

    # ==========================================
    # 6. 成本
    # ==========================================

    cost = (
        buy
        + dewu_fee
        + SHIPPING_COST
    )

    # ==========================================
    # 7. 利润
    # ==========================================

    profit = (
        sale
        - cost
    )

    if buy > 0:

        profit_rate = (
            profit
            / buy
            * 100
        )

    else:

        profit_rate = 0

    # ==========================================
    # 8. 最低利润
    # ==========================================

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
                f"超过 ¥{MAX_DOWNSIDE_LOSS}"
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
            "关键行情数据不完整，禁止提醒购买"
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
            ),

        "dewu_fee":
            round(
                dewu_fee,
                2
            ),

        "shipping_cost":
            round(
                SHIPPING_COST,
                2
            ),

        "cost":
            round(
                cost,
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
                1
            ),

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
        "得物手续费："
        "按售价 ¥50～¥150 保守估算"
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
            f'¥{item["buy_price"]:.0f}'
        )

        print(
            f'  得物售价：'
            f'¥{item["dewu_price"]:.0f}'
        )

        print(
            f'  估算得物手续费：'
            f'¥{item["dewu_fee"]:.0f}'
        )

        print(
            f'  运费：'
            f'¥{item["shipping_cost"]:.0f}'
        )

        print(
            f'  总成本：'
            f'¥{item["cost"]:.0f}'
        )

        print(
            f'  净利润：'
            f'¥{item["net_profit"]:.0f}'
        )

        print(
            f'  利润率：'
            f'{item["profit_rate"]:.1f}%'
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
                f'¥{item["buy_price"]:.0f}'
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
    
