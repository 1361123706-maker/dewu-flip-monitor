import json
from pathlib import Path
from datetime import datetime, timezone

INPUT_FILE = "discovery_data.json"
OUTPUT_FILE = "products.json"


def to_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        text = str(value).strip().replace(",", "").replace("¥", "").replace("￥", "").replace("元", "")
        number = float(text)
        return number if number > 0 else None
    except Exception:
        return None


def money(value):
    number = to_float(value)
    return round(number, 2) if number is not None else None


def first_value(item, *keys):
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
        else:
            return value
    return None


def load_json(path):
    file = Path(path)
    if not file.exists():
        print(f"找不到文件：{path}")
        return None
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"读取 {path} 失败：{e}")
        return None


def get_items(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("products", "items", "results", "data"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def get_product_code(item):
    value = first_value(item, "product_code", "goods_code", "style_code", "sku_code")
    return str(value).strip() if value is not None else None


def get_color(item):
    value = first_value(item, "color", "current_color", "selected_color")
    return str(value).strip() if value is not None else None


def get_size(item):
    value = first_value(item, "current_size", "size", "sku_size")
    if value is not None:
        return str(value).strip()
    variant = first_value(item, "selected_variant")
    if variant:
        text = str(variant).strip()
        for sep in (",", "，"):
            if sep in text:
                parts = text.split(sep)
                if len(parts) >= 2 and parts[-1].strip():
                    return parts[-1].strip()
    return None


def get_variant(item):
    value = item.get("selected_variant")
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def get_size_price_map(item):
    raw = item.get("size_price_map")
    if not isinstance(raw, dict):
        return {}
    result = {}
    for size, price in raw.items():
        number = to_float(price)
        text = str(size).strip()
        if number is not None and text:
            result[text] = money(number)
    return result


def get_effective_buy_price(item):
    # 只接受活动引擎已经产出的可信最终价；不自行把多个优惠相加。
    for key in ("best_effective_buy_price", "effective_buy_price", "final_buy_price", "estimated_final_price"):
        number = to_float(item.get(key))
        if number is not None:
            return money(number), key
    return None, None


def get_base_buy_price(item):
    for key in ("buy_price", "sku_buy_price", "market_low_price", "price"):
        number = to_float(item.get(key))
        if number is not None:
            return money(number), key
    return None, None


def get_buy_price_info(item):
    """活动后价格优先；有尺码表时，只有明确尺码原价才作为无优惠兜底。"""
    effective, effective_key = get_effective_buy_price(item)
    size_prices = get_size_price_map(item)
    current_size = get_size(item)

    if effective is not None:
        # 有尺码表时，只在活动引擎的 base_price 与当前尺码价格一致时
        # 才把商品级活动价映射到该 SKU；否则避免把一个尺码的优惠价
        # 错套到其他尺码。
        calculation = item.get("promotion_calculation")
        base_price = to_float(calculation.get("base_price")) if isinstance(calculation, dict) else None
        current_sku_price = size_prices.get(current_size) if current_size else None
        if not size_prices or current_sku_price is None or base_price is None or abs(base_price - current_sku_price) < 0.01:
            return effective, "活动优惠计算后的最低可信到手价", f"promotion_{effective_key}"

    if current_size and current_size in size_prices:
        return size_prices[current_size], "识货当前尺码价格", "confirmed_sku_price"

    if len(size_prices) == 1:
        only_price = next(iter(size_prices.values()))
        return money(only_price), "识货唯一尺码价格", "confirmed_single_sku_price"

    base, base_key = get_base_buy_price(item)
    if base is not None:
        return base, "商品/活动基础价格，尺码未确认", f"product_level_{base_key}"

    return None, None, "no_buy_price"


def get_dewu_channel_price(item):
    for key in ("dewu_channel_price", "dewu_display_price"):
        number = to_float(item.get(key))
        if number is not None:
            return money(number)
    return None


def get_trend_current_price(item):
    for key in ("trend_current_price", "price_current"):
        number = to_float(item.get(key))
        if number is not None:
            return money(number)
    return None


def build_dewu_price(item):
    channel = get_dewu_channel_price(item)
    trend = get_trend_current_price(item)
    fallback = to_float(item.get("dewu_price"))
    if channel is not None:
        return channel, "识货：得物渠道售价", "channel_price"
    if trend is not None:
        return trend, "识货：当前同款同规格价格", "current_price"
    if fallback is not None:
        return money(fallback), "识货：得物售价", "dewu_price"
    return None, None, "no_dewu_price"


def get_7d_low(item):
    for key in ("price_7d_low", "trend_7d_low", "lowest_price"):
        number = to_float(item.get(key))
        if number is not None:
            return money(number)
    return None


def get_7d_high(item):
    for key in ("price_7d_high", "trend_7d_high"):
        number = to_float(item.get(key))
        if number is not None:
            return money(number)
    return None


def calculate_price_risk(current, low, high):
    downside = None
    position = None
    if current is not None and low is not None and current > 0 and 0 <= low <= current:
        downside = round((current - low) / current * 100, 2)
    if current is not None and low is not None and high is not None and high > low:
        position = round(max(0, min(100, (current - low) / (high - low) * 100)), 2)
    return downside, position


def get_sales(item):
    sales_7d = to_float(first_value(item, "sales_7d", "sales_7days"))
    sales_30d = to_float(first_value(item, "sales_30d", "monthly_sales", "month_sales"))
    sales_total = to_float(first_value(item, "sales_total", "total_sales"))
    if sales_7d is not None:
        velocity = round(sales_7d / 7, 2)
        evidence = f"近7日销量 {sales_7d:g}，日均约 {velocity:.2f}"
        confidence = "high"
    elif sales_30d is not None:
        velocity = round(sales_30d / 30, 2)
        evidence = f"月销 {sales_30d:g}，日均约 {velocity:.2f}"
        confidence = "medium"
    elif sales_total is not None:
        velocity = None
        evidence = f"累计/全网销量 {sales_total:g}，不能直接作为7日周转速度"
        confidence = "low"
    else:
        velocity = None
        evidence = None
        confidence = "unknown"
    return {"sales_7d": money(sales_7d), "sales_30d": money(sales_30d), "sales_total": money(sales_total), "sales_velocity_7d": velocity, "turnover_evidence": evidence, "turnover_confidence": confidence}


def get_coupon_urls(item):
    value = item.get("coupon_urls")
    if not isinstance(value, list):
        return []
    result = []
    for url in value:
        text = str(url).strip() if url else ""
        if text and text not in result:
            result.append(text)
    return result


def get_official_store_links(item):
    value = item.get("official_store_links")
    return value if isinstance(value, list) else []


def build_product(item):
    product = dict(item)
    product["name"] = first_value(item, "name", "title", "product_name")
    product["product_code"] = get_product_code(item)
    product["color"] = get_color(item)
    product["current_size"] = get_size(item)
    product["selected_variant"] = get_variant(item)

    size_price_map = get_size_price_map(item)
    product["size_price_map"] = size_price_map
    if product["current_size"] in size_price_map:
        product["sku_buy_price"] = size_price_map[product["current_size"]]
        product["sku_price_status"] = "confirmed_current_size"
    elif len(size_price_map) == 1:
        product["sku_buy_price"] = next(iter(size_price_map.values()))
        product["sku_price_status"] = "confirmed_single_sku_price"
    else:
        product["sku_buy_price"] = None
        product["sku_price_status"] = "size_unconfirmed" if size_price_map else "no_sku_price"

    effective, effective_key = get_effective_buy_price(item)
    product["best_effective_buy_price"] = effective
    product["effective_buy_price"] = effective
    product["effective_buy_price_source"] = effective_key
    product["buy_price_before_discount"] = money(item.get("buy_price_before_discount"))
    product["discount_total"] = money(item.get("discount_total"))
    product["coupon_urls"] = get_coupon_urls(item)
    product["all_coupon_urls"] = get_coupon_urls(item) + [u for u in item.get("all_coupon_urls", []) if u not in get_coupon_urls(item)] if isinstance(item.get("all_coupon_urls"), list) else get_coupon_urls(item)
    product["official_store_links"] = get_official_store_links(item)
    product["promotion_offers"] = item.get("promotion_offers", []) if isinstance(item.get("promotion_offers", []), list) else []
    product["promotion_calculation"] = item.get("promotion_calculation")
    product["promotion_verified"] = bool(item.get("promotion_verified", False))
    product["promotion_status"] = item.get("promotion_status")
    product["promotion_discount_total"] = money(item.get("promotion_discount_total"))

    buy_price, buy_source, buy_status = get_buy_price_info(product)
    product["buy_price"] = buy_price
    product["buy_price_source"] = buy_source
    product["buy_price_status"] = buy_status

    dewu_price, dewu_source, dewu_status = build_dewu_price(item)
    product["dewu_channel_price"] = get_dewu_channel_price(item)
    product["trend_current_price"] = get_trend_current_price(item)
    product["dewu_price"] = dewu_price
    product["dewu_price_source"] = dewu_source
    product["dewu_price_status"] = dewu_status

    low_7d = get_7d_low(item)
    high_7d = get_7d_high(item)
    current = product["trend_current_price"] or product["dewu_channel_price"] or dewu_price
    downside, position = calculate_price_risk(current, low_7d, high_7d)
    product["price_7d_low"] = low_7d
    product["price_7d_high"] = high_7d
    product["price_current"] = money(current)
    product["downside_to_7d_low"] = downside
    product["price_position_7d"] = position
    product["price_evidence_status"] = "confirmed" if current is not None else "missing"

    sales = get_sales(item)
    product.update(sales)
    product["authenticity_verified"] = bool(item.get("authenticity_evidence") or item.get("shihuo_source"))
    product["authenticity_evidence"] = item.get("authenticity_evidence") or ("商品来源为识货" if item.get("shihuo_source") else None)
    product["new_condition_verified"] = item.get("new_condition_verified")
    product["dewu_check_compatible"] = item.get("dewu_check_compatible")
    product["buy_platform"] = item.get("buy_platform", item.get("platform"))
    product["store_type"] = item.get("store_type")
    product["buy_url"] = item.get("buy_url", item.get("source_url"))
    product["coupon_evidence"] = item.get("coupon_evidence", [])

    if dewu_price is not None and buy_price is not None:
        product["estimated_profit_status"] = "estimated_ready"
        product["estimated_profit_confirmation"] = "已具备买入价和得物售价"
    elif dewu_price is not None:
        product["estimated_profit_status"] = "missing_buy_price"
        product["estimated_profit_confirmation"] = "已有得物售价，但缺少有效买入价"
    elif buy_price is not None:
        product["estimated_profit_status"] = "missing_dewu_price"
        product["estimated_profit_confirmation"] = "已有买入价，但缺少有效得物售价"
    else:
        product["estimated_profit_status"] = "not_ready"
        product["estimated_profit_confirmation"] = "买入价和得物售价均不足"
    product["income_confirmed"] = product["estimated_profit_status"] == "estimated_ready"
    product["income_confirmation_reason"] = product["estimated_profit_confirmation"]

    evidence = {
        "product_code": bool(product.get("product_code")),
        "color": bool(product.get("color")),
        "size_price_map": bool(product.get("size_price_map")),
        "current_size": bool(product.get("current_size")),
        "buy_price": buy_price is not None,
        "dewu_price": dewu_price is not None,
        "price_7d_low": low_7d is not None,
        "price_7d_high": high_7d is not None,
        "turnover": sales["turnover_confidence"] != "unknown",
        "official_store": bool(product.get("official_store_links")),
        "coupon": bool(product.get("coupon_urls") or product.get("coupon_evidence")),
        "promotion_calculation": bool(product.get("promotion_calculation")),
    }
    product["evidence"] = evidence
    product["evidence_count"] = sum(bool(v) for v in evidence.values())
    product["bridge_updated_at"] = datetime.now(timezone.utc).isoformat()
    return product


def main():
    data = load_json(INPUT_FILE)
    items = get_items(data)
    products = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            products.append(build_product(item))
        except Exception as e:
            print("整理商品失败：", item.get("name"), e)
    output = {"updated_at": datetime.now(timezone.utc).isoformat(), "count": len(products), "source": "识货", "products": products}
    Path(OUTPUT_FILE).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("输入商品数：", len(items))
    print("输出商品数：", len(products))
    print("活动后价格：", sum(x.get("best_effective_buy_price") is not None for x in products))
    print("得物价格：", sum(x.get("dewu_price") is not None for x in products))
    print("7日最低价：", sum(x.get("price_7d_low") is not None for x in products))
    print("周转证据：", sum(x.get("turnover_confidence") != "unknown" for x in products))


if __name__ == "__main__":
    main()
