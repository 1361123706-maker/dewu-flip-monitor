import json
from pathlib import Path
from datetime import datetime, timezone

INPUT_FILE = "products.json"
OUTPUT_FILE = "monitor_results.json"

CONFIG_FILE = "config.json"
DEFAULT_CAPITAL = 330

def load_capital():
    path = Path(CONFIG_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = float(data.get("capital"))
        if value > 0:
            return value
    except Exception as e:
        print(f"读取 {CONFIG_FILE} 失败，使用默认本金 ¥{DEFAULT_CAPITAL:.2f}：{e}")
    return float(DEFAULT_CAPITAL)

CAPITAL = load_capital()
MAX_DAYS = 7
MIN_PROFIT = 15
MIN_PROFIT_RATE = 12
MAX_DOWNSIDE_LOSS = 25
DEWU_NET_RATE = 0.92
DEFAULT_BUY_SHIPPING = 6
REQUIRE_PROMOTION_EVIDENCE = False


def to_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        text = str(value).strip().replace("¥", "").replace("￥", "").replace(",", "")
        return float(text) if text else None
    except Exception:
        return None


def money(value):
    return round(float(value), 2) if value is not None else None


def normalize_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_trend(value):
    if value is None:
        return None
    mapping = {"rising":"上涨", "rise":"上涨", "up":"上涨", "上涨":"上涨",
               "falling":"下跌", "fall":"下跌", "down":"下跌", "下跌":"下跌",
               "stable":"稳定", "flat":"稳定", "稳定":"稳定", "平稳":"稳定"}
    return mapping.get(str(value).strip().lower())


def load_products():
    path = Path(INPUT_FILE)
    if not path.exists():
        print(f"找不到 {INPUT_FILE}")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"读取 {INPUT_FILE} 失败：{e}")
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("products", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def get_size_price_map(item):
    raw = item.get("size_price_map")
    if not isinstance(raw, dict):
        return {}
    result = {}
    for size, price in raw.items():
        number = to_float(price)
        if number is not None and number > 0:
            result[str(size).strip()] = number
    return result


def sku_identity_complete(item, sku_size=None):
    """利润计算的硬门槛：货号 + 配色 + 可定位 SKU。"""
    if item.get("hard_exclude") is True:
        return False

    product_code = normalize_text(item.get("product_code"))
    color = normalize_text(item.get("color"))
    sku_id = normalize_text(item.get("sku_id"))
    current_size = normalize_text(item.get("current_size"))
    chosen_size = normalize_text(sku_size)

    if not product_code or not color:
        return False

    # 有当前尺码或 sku_id 才认为可以定位具体 SKU。
    return bool(sku_id or current_size or chosen_size)


def get_buy_price(item):
    for key in (
        "best_effective_buy_price", "effective_buy_price",
        "final_buy_price", "estimated_final_price",
        "buy_price", "sku_buy_price"
    ):
        value = to_float(item.get(key))
        if value is not None and value > 0:
            return value
    return None


def get_sku_context(item):
    # 绝对禁止 hard_exclude / SKU 身份不完整的商品进入利润计算。
    if not sku_identity_complete(item):
        return []

    size_prices = get_size_price_map(item)
    effective = (
        to_float(item.get("best_effective_buy_price"))
        or to_float(item.get("effective_buy_price"))
    )
    calculation = item.get("promotion_calculation")
    base_price = (
        to_float(calculation.get("base_price"))
        if isinstance(calculation, dict) else None
    )
    current_size = normalize_text(item.get("current_size"))
    sku_id = normalize_text(item.get("sku_id"))

    if size_prices:
        # 有尺寸价格表时，只允许当前明确选择的尺码进入。
        # 不再把所有尺码批量当成已定位 SKU。
        if not current_size:
            return []

        price = size_prices.get(current_size)
        if price is None:
            return []

        if effective is not None and base_price is not None and abs(base_price - price) < 0.01:
            sku_price = effective
        elif effective is not None and sku_id and current_size:
            sku_price = effective
        else:
            sku_price = price

        return [(current_size, sku_price)]

    # 没有尺码表时，仍要求已定位 SKU。
    if not (current_size or sku_id):
        return []

    buy_price = effective or get_buy_price(item)
    return [(current_size, buy_price)] if buy_price is not None else []


def get_dewu_price(item):
    for key, label, kind in (
        ("dewu_channel_price", "识货：得物渠道售价", "channel_price"),
        ("trend_current_price", "识货：当前同款同规格价格", "current_price"),
        ("dewu_price", "识货：得物售价", "dewu_price")
    ):
        value = to_float(item.get(key))
        if value is not None and value > 0:
            return value, label, kind
    return None, None, None


def calculate_estimated_profit(dewu_price, buy_price):
    if dewu_price is None or buy_price is None:
        return None, None, None
    income = dewu_price * DEWU_NET_RATE
    total_cost = buy_price + DEFAULT_BUY_SHIPPING
    return income, total_cost, income - total_cost


def price_evidence(item):
    current = (
        to_float(item.get("trend_current_price"))
        or to_float(item.get("dewu_channel_price"))
        or to_float(item.get("dewu_price"))
    )
    status = (
        "confirmed_current_price" if to_float(item.get("trend_current_price"))
        else ("channel_price_only" if to_float(item.get("dewu_channel_price"))
              else ("dewu_price_only" if current else "no_dewu_price"))
    )
    low = to_float(item.get("price_7d_low"))
    high = to_float(item.get("price_7d_high"))
    position = None
    downside = None
    if current is not None and low is not None and high is not None and high > low:
        position = round(max(0, min(100, (current-low)/(high-low)*100)), 2)
    if current is not None and low is not None and current > 0 and 0 <= low <= current:
        downside = round((current-low)/current*100, 2)
    return {"current": current, "low": low, "high": high,
            "position": position, "downside": downside, "status": status}


def turnover(item):
    sales_7d = to_float(item.get("sales_7d"))
    sales_30d = to_float(item.get("sales_30d"))
    velocity = to_float(item.get("sales_velocity_7d"))
    evidence = item.get("turnover_evidence")
    confidence = item.get("turnover_confidence")
    if sales_7d is not None and sales_7d > 0:
        velocity = sales_7d / 7
        evidence = f"近7日销量 {sales_7d:g}，日均约 {velocity:.2f}"
        confidence = "high"
    elif sales_30d is not None and sales_30d > 0:
        velocity = sales_30d / 30
        evidence = f"月销 {sales_30d:g}，日均约 {velocity:.2f}"
        confidence = "medium"
    elif not evidence:
        confidence = "unknown"
    return {"sales_7d": sales_7d, "sales_30d": sales_30d,
            "velocity": velocity, "evidence": evidence,
            "confidence": confidence or "unknown", "days": None}


def sales_score(t):
    if t["sales_7d"] is not None:
        if t["sales_7d"] >= 20: return 3
        if t["sales_7d"] >= 7: return 2
        if t["sales_7d"] > 0: return 1
    if t["sales_30d"] is not None:
        if t["sales_30d"] >= 1000: return 3
        if t["sales_30d"] >= 300: return 2
        if t["sales_30d"] > 0: return 1
    if t["velocity"] is not None:
        return 2 if t["velocity"] >= 30 else (1 if t["velocity"] > 0 else 0)
    return 0


def trend_score(item):
    trend = normalize_trend(item.get("price_trend"))
    change = to_float(item.get("price_change_7d"))
    score = 2 if trend == "上涨" else (1 if trend == "稳定" else (-1 if trend == "下跌" else 0))
    if change is not None:
        if change > 3: score += 1
        elif change < -5: score -= 1
    return max(-2, min(3, score))


def evidence_score(pe, t):
    score = 2 if pe["status"] == "confirmed_current_price" else (1 if pe["current"] is not None else 0)
    score += 1 if pe["low"] is not None else 0
    score += 1 if pe["high"] is not None else 0
    score += 2 if t["confidence"] == "high" else (1 if t["confidence"] == "medium" else 0)
    return score


def safety_score(profit, downside, price_status):
    score = 4 if profit is not None and profit >= MIN_PROFIT else 0
    if downside is None: score -= 1
    elif downside <= 10: score += 5
    elif downside <= 20: score += 3
    elif downside <= MAX_DOWNSIDE_LOSS: score += 1
    else: score -= 5
    if price_status != "confirmed_current_price": score -= 1
    return score


def hard_risks(item, buy_price, dewu_price, total_cost, downside, t, sku_size):
    reasons = []
    if not sku_identity_complete(item, sku_size):
        reasons.append("SKU身份不完整，禁止计算利润")
    if item.get("promotion_status") == "missing_base_price":
        reasons.append("没有有效活动/买入价格")
    if REQUIRE_PROMOTION_EVIDENCE and not item.get("promotion_verified"):
        reasons.append("优惠价格缺少明确证据")
    if item.get("category") == "excluded":
        reasons.append("属于明确排除品类")
    if buy_price is None:
        reasons.append("没有有效买入价")
    if dewu_price is None:
        reasons.append("没有有效得物价格")
    if total_cost is not None and total_cost > CAPITAL:
        reasons.append(f"总资金占用 ¥{total_cost:.2f} 超过当前资金 ¥{CAPITAL:.2f}")
    if downside is not None and downside > MAX_DOWNSIDE_LOSS:
        reasons.append("当前价格距离7日低点过高，下行风险超过阈值")
    if t["days"] is not None and t["days"] > MAX_DAYS:
        reasons.append(f"明确周转时间超过{MAX_DAYS}天")
    if item.get("new_condition_verified") is False:
        reasons.append("明确不是全新状态")
    if item.get("dewu_check_compatible") is False:
        reasons.append("得物查验/上架兼容性不满足")
    if get_size_price_map(item) and sku_size is None:
        reasons.append("存在尺码价格，但无法确认具体尺码")
    return reasons


def grade(profit, profit_rate, safety, sales, trend, evidence, capital, risks):
    if risks: return "D"
    if profit is None or profit_rate is None: return "C"
    if profit >= 30 and profit_rate >= 20 and safety >= 12 and sales >= 2 and trend >= 2 and capital >= 1 and evidence >= 4:
        return "A"
    if profit >= MIN_PROFIT and profit_rate >= MIN_PROFIT_RATE and safety > 0:
        return "B"
    return "C"


def analyze(item, sku_size=None, sku_buy_price=None):
    # 第二道硬闸门：即使上游漏标，也不能让不完整 SKU 产生利润。
    if not sku_identity_complete(item, sku_size):
        return {
            "name": item.get("name"),
            "product_code": normalize_text(item.get("product_code")),
            "color": normalize_text(item.get("color")),
            "sku_size": normalize_text(sku_size or item.get("current_size")),
            "sku_buy_price": None,
            "grade": "D",
            "category": "excluded",
            "category_reason": "SKU身份不完整，禁止使用商品级最低价计算利润",
            "buy_price": None,
            "dewu_price": None,
            "hard_risks": ["SKU身份不完整，禁止计算利润"],
            "reason": "SKU身份不完整，禁止使用商品级最低价计算利润",
            "capital": CAPITAL,
            "profit_type": "not_ready",
            "profit_status": "sku_identity_incomplete",
            "profit_estimate_ready": False,
            "sku_identity_complete": False,
        }

    name = item.get("name")
    buy_price = to_float(sku_buy_price) if sku_buy_price is not None else get_buy_price(item)
    if not name or buy_price is None or buy_price <= 0:
        return None

    dewu_price, price_source, price_type = get_dewu_price(item)
    if dewu_price is None:
        return {
            "name": name,
            "product_code": normalize_text(item.get("product_code")),
            "color": normalize_text(item.get("color")),
            "sku_size": sku_size,
            "sku_buy_price": money(buy_price),
            "grade": "D",
            "category": item.get("category"),
            "buy_price": money(buy_price),
            "dewu_price": None,
            "hard_risks": ["没有有效得物价格"],
            "reason": "没有有效得物价格",
            "capital": CAPITAL,
            "profit_type": "estimated",
            "profit_status": "estimated_not_ready",
            "profit_estimate_ready": False,
            "sku_identity_complete": True,
        }

    income, total_cost, profit = calculate_estimated_profit(dewu_price, buy_price)
    profit_rate = profit / total_cost * 100 if profit is not None and total_cost > 0 else None
    pe = price_evidence(item)
    t = turnover(item)
    s_score = sales_score(t)
    tr_score = trend_score(item)
    e_score = evidence_score(pe, t)
    capital_score = 2 if total_cost <= CAPITAL else 0
    capital_ratio = total_cost / CAPITAL * 100 if CAPITAL > 0 else None
    safety = safety_score(profit, pe["downside"], pe["status"])
    risks = hard_risks(item, buy_price, dewu_price, total_cost, pe["downside"], t, sku_size)
    g = grade(profit, profit_rate, safety, s_score, tr_score, e_score, capital_score, risks)
    trend = normalize_trend(item.get("price_trend"))
    reasons = []
    reasons.append("利润、价格、销量和风险证据较完整" if g == "A" else ("达到候选最低利润与风险门槛" if g == "B" else ("当前不能作为推荐候选" if g == "C" else "触发硬风险，直接过滤")))
    if sku_size: reasons.append(f"尺码 {sku_size}")
    reasons.append(f"买入 ¥{buy_price:.2f}")
    reasons.append(f"得物售价 ¥{dewu_price:.2f} × 92% = ¥{income:.2f}")
    reasons.append(f"估算利润 ¥{profit:.2f}")
    if profit_rate is not None: reasons.append(f"利润率 {profit_rate:.2f}%")
    if t["evidence"]: reasons.append(t["evidence"])
    if pe["low"] is not None: reasons.append(f"7日最低 ¥{pe['low']:.2f}")
    if pe["high"] is not None: reasons.append(f"7日最高 ¥{pe['high']:.2f}")
    if pe["downside"] is not None: reasons.append(f"距离7日低点 {pe['downside']:.2f}%")
    if trend: reasons.append(f"价格趋势：{trend}")
    reasons.append("估算公式：得物售价×92%-买入价-6元运费")
    return {
        "name": name, "product_code": normalize_text(item.get("product_code")), "color": normalize_text(item.get("color")), "sku_size": sku_size, "sku_buy_price": money(buy_price),
        "sku_identity_complete": True,
        "selected_variant": item.get("selected_variant"), "grade": g, "category": item.get("category"), "category_reason": item.get("category_reason"),
        "buy_platform": item.get("buy_platform", item.get("platform")), "store_type": item.get("store_type"), "buy_url": item.get("buy_url", item.get("source_url")),
        "buy_price_before_discount": money(item.get("buy_price_before_discount")), "discount_total": money(item.get("discount_total")), "effective_buy_price": money(buy_price),
        "best_effective_buy_price": money(item.get("best_effective_buy_price")), "coupon_urls": item.get("coupon_urls", []), "all_coupon_urls": item.get("all_coupon_urls", item.get("coupon_urls", [])), "coupon_evidence": item.get("coupon_evidence"),
        "promotion_offers": item.get("promotion_offers", []), "promotion_calculation": item.get("promotion_calculation"), "promotion_verified": item.get("promotion_verified"), "promotion_status": item.get("promotion_status"), "promotion_discount_total": money(item.get("promotion_discount_total")),
        "buy_price": money(buy_price), "buy_price_source": item.get("buy_price_source"), "buy_price_status": item.get("buy_price_status"),
        "dewu_price": money(dewu_price), "dewu_price_source": price_source, "dewu_price_type": price_type, "dewu_channel_price": money(item.get("dewu_channel_price")), "trend_current_price": money(item.get("trend_current_price")),
        "estimated_income": money(income), "expected_income": money(income), "total_cost": money(total_cost), "buy_shipping_cost": DEFAULT_BUY_SHIPPING, "buy_shipping_confirmed": False,
        "profit_type": "estimated", "profit_status": "estimated_ready", "profit_estimate_ready": True, "profit_confirmation": "已按统一估算公式计算；最终平台结算费用以实际下单为准", "profit": money(profit), "estimated_profit": money(profit), "profit_rate": round(profit_rate, 2) if profit_rate is not None else None,
        "capital": CAPITAL, "capital_ratio": round(capital_ratio, 2) if capital_ratio is not None else None,
        "sales_7d": t["sales_7d"], "sales_30d": t["sales_30d"], "sales_velocity_7d": t["velocity"], "turnover_evidence": t["evidence"], "turnover_confidence": t["confidence"], "days": t["days"],
        "price_current": money(pe["current"]), "price_7d_low": money(pe["low"]), "price_7d_high": money(pe["high"]), "price_position_7d": pe["position"], "downside_to_7d_low": pe["downside"], "price_evidence_status": pe["status"], "price_trend": trend,
        "sales_score": s_score, "trend_score": tr_score, "evidence_score": e_score, "safety_score": safety, "capital_score": capital_score,
        "hard_risks": risks, "reason": "；".join(reasons), "shihuo_source": item.get("shihuo_source", True), "authenticity_evidence": item.get("authenticity_evidence"), "new_condition_verified": item.get("new_condition_verified"), "dewu_check_compatible": item.get("dewu_check_compatible"), "source_note": item.get("source_note")
    }


def main():
    products = load_products()
    results = []
    for item in products:
        try:
            for sku_size, sku_price in get_sku_context(item):
                result = analyze(item, sku_size=sku_size, sku_buy_price=sku_price)
                if result is not None:
                    results.append(result)
        except Exception as e:
            print("分析商品失败：", item.get("name"), e)

    candidates = [
        x for x in results
        if x.get("sku_identity_complete") is True
        and x.get("grade") in {"A", "B"}
        and (x.get("estimated_profit") or 0) >= MIN_PROFIT
        and (x.get("profit_rate") or 0) >= MIN_PROFIT_RATE
    ]
    candidates.sort(key=lambda x: (
        0 if x.get("grade") == "A" else 1,
        -(x.get("estimated_profit") or 0),
        -(x.get("profit_rate") or 0)
    ))

    summary = {
        "total": len(results),
        "A": sum(x.get("grade") == "A" for x in results),
        "B": sum(x.get("grade") == "B" for x in results),
        "C": sum(x.get("grade") == "C" for x in results),
        "D": sum(x.get("grade") == "D" for x in results),
        "estimated_profit_count": sum(
            x.get("profit_status") == "estimated_ready" for x in results
        ),
    }

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "capital": CAPITAL,
        "rules": {
            "max_days": MAX_DAYS,
            "min_profit": MIN_PROFIT,
            "min_profit_rate": MIN_PROFIT_RATE,
            "max_downside_loss": MAX_DOWNSIDE_LOSS,
            "dewu_net_rate": DEWU_NET_RATE,
            "default_buy_shipping": DEFAULT_BUY_SHIPPING,
            "profit_type": "estimated",
            "profit_status": "estimated_ready",
            "profit_formula": "得物售价×92%-买入价-6元",
            "sku_level": True,
            "strict_sku_identity": True,
            "coupon_aware": True,
            "multi_platform_buy_sources": True,
        },
        "summary": summary,
        "monitored_count": len(results),
        "candidate_count": len(candidates),
        "grade_a_count": summary["A"],
        "grade_b_count": summary["B"],
        "grade_c_count": summary["C"],
        "grade_d_count": summary["D"],
        "candidates": candidates,
        "results": results,
    }

    Path(OUTPUT_FILE).write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("==============================")
    print(f"SKU分析总数：{len(results)}")
    print(f"A级：{summary['A']}")
    print(f"B级：{summary['B']}")
    print(f"C级：{summary['C']}")
    print(f"D级：{summary['D']}")
    print(f"推荐候选：{len(candidates)}")
    print("==============================")


if __name__ == "__main__":
    main()
