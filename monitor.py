import json
from pathlib import Path

# ===== 你的风控规则 =====
CAPITAL = 330
MAX_BUY = 120
MAX_DAYS = 7
MIN_PROFIT = 15
MIN_PROFIT_RATE = 12
MAX_DOWNSIDE_LOSS = 25

# 演示阶段的固定成本
PLATFORM_COST = 8
SHIPPING_COST = 6


def evaluate(item):
    # 找到四个平台中的最低买入价
    buy = min(item["buy_prices"].values())

    # 计算总成本
    cost = buy + PLATFORM_COST + SHIPPING_COST

    # 得物预估卖出价
    sale = item["dewu_price"]

    # 净利润
    profit = sale - cost

    # 利润率
    rate = profit / buy * 100 if buy else 0

    reasons = []

    if buy > MAX_BUY:
        reasons.append("单笔资金占用过高")

    if buy > CAPITAL:
        reasons.append("超过本金")

    if item["days"] > MAX_DAYS:
        reasons.append("预计周转超过7天")

    if item["liquidity"] == "低":
        reasons.append("流动性低")

    if profit < MIN_PROFIT:
        reasons.append("净利润不足")

    if rate < MIN_PROFIT_RATE:
        reasons.append("利润率不足")

    if item["downside_loss"] > MAX_DOWNSIDE_LOSS:
        reasons.append("下跌风险过高")

    if not item["authenticity_verified"]:
        reasons.append("正品无法确认")

    if not item["new_condition_verified"]:
        reasons.append("全新/成色无法确认")

    if not item["dewu_check_compatible"]:
        reasons.append("得物查验适配无法确认")

    return {
        "name": item["name"],
        "buy_price": buy,
        "dewu_price": sale,
        "cost": round(cost, 2),
        "net_profit": round(profit, 2),
        "profit_rate": round(rate, 1),
        "days": item["days"],
        "liquidity": item["liquidity"],
        "downside_loss": item["downside_loss"],
        "status": "候选" if not reasons else "过滤",
        "reasons": reasons,
    }


def main():
    data = json.loads(
        Path("products.json").read_text(encoding="utf-8")
    )

    results = [evaluate(item) for item in data["products"]]

    candidates = [
        item for item in results
        if item["status"] == "候选"
    ]

    print("================================")
    print("       快进快出监控系统")
    print("================================")
    print(f"监控商品：{len(results)}")
    print(f"符合条件：{len(candidates)}")
    print()

    for item in results:
        print(
            f'{item["status"]} | '
            f'{item["name"]} | '
            f'买入 ¥{item["buy_price"]:.0f} | '
            f'得物 ¥{item["dewu_price"]:.0f} | '
            f'净利润 ¥{item["net_profit"]:.0f} | '
            f'{item["profit_rate"]:.1f}% | '
            f'{item["days"]}天 | '
            f'流动性{item["liquidity"]}'
        )

        if item["reasons"]:
            print(
                "  过滤原因："
                + "；".join(item["reasons"])
            )


if __name__ == "__main__":
    main()
