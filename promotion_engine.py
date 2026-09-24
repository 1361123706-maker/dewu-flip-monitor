"""活动优惠计算引擎：保守计算可验证的最低到手价。"""

from itertools import combinations


def to_float(value):
    if value is None:
        return None
    try:
        text = str(value).strip()
        text = text.replace("¥", "").replace("￥", "")
        text = text.replace(",", "").replace("元", "")
        number = float(text)
        return number if number > 0 else None
    except Exception:
        return None


def money(value):
    number = to_float(value)
    return round(number, 2) if number is not None else None


def normalize_offer(offer):
    if not isinstance(offer, dict):
        return None

    amount = to_float(offer.get("amount"))
    if amount is None or amount <= 0:
        return None

    threshold = to_float(offer.get("threshold"))
    offer_type = str(offer.get("type", "unknown")).strip()
    platform = str(offer.get("platform", "")).strip()
    url = str(offer.get("url", "")).strip()

    return {
        "type": offer_type,
        "platform": platform,
        "amount": money(amount),
        "threshold": money(threshold),
        "url": url or None,
        "stackable": offer.get("stackable") is True,
        "evidence": offer.get("evidence"),
        "source": offer.get("source"),
    }


def offer_can_apply(base_price, current_price, offer):
    """满减门槛默认按原始订单金额判断，避免连续减价后错误失去/获得门槛。"""
    threshold = offer.get("threshold")
    if threshold is None:
        return True
    return base_price >= threshold


def apply_offer(base_price, current_price, offer):
    if not offer_can_apply(base_price, current_price, offer):
        return None
    result = current_price - offer["amount"]
    if result <= 0:
        return None
    return round(result, 2)


def _urls(offers):
    result = []
    for offer in offers:
        url = offer.get("url")
        if url and url not in result:
            result.append(url)
    return result


def _result(base_price, effective_price, detected, applied, verified, status):
    return {
        "base_price": money(base_price),
        "effective_price": money(effective_price),
        "discount_total": money(base_price - effective_price) if effective_price is not None else None,
        "offers": applied,
        "detected_offers": detected,
        "coupon_urls": _urls(applied),
        "all_coupon_urls": _urls(detected),
        "verified": bool(verified),
        "calculation_status": status,
    }


def calculate_best_price(base_price, offers=None, explicit_effective_price=None):
    """只把页面明确给出的到手价，或有明确叠加证据的优惠组合用于最终计算。"""
    base_price = to_float(base_price)
    normalized = []
    for offer in offers or []:
        item = normalize_offer(offer)
        if item is not None:
            normalized.append(item)

    if base_price is None:
        return {
            "base_price": None,
            "effective_price": None,
            "discount_total": None,
            "offers": [],
            "detected_offers": normalized,
            "coupon_urls": [],
            "all_coupon_urls": _urls(normalized),
            "verified": False,
            "calculation_status": "missing_base_price",
        }

    explicit = to_float(explicit_effective_price)
    if explicit is not None and explicit < base_price:
        return _result(
            base_price, explicit, normalized, normalized,
            True, "explicit_effective_price",
        )

    stackable = [x for x in normalized if x.get("stackable") is True]
    best_price = base_price
    best_offers = []

    candidates = [()]
    for r in range(1, min(len(stackable), 5) + 1):
        candidates.extend(combinations(stackable, r))

    for combination in candidates:
        price = base_price
        selected = []
        valid = True
        for offer in combination:
            new_price = apply_offer(base_price, price, offer)
            if new_price is None:
                valid = False
                break
            selected.append(offer)
            price = new_price
        if valid and price < best_price:
            best_price = price
            best_offers = selected

    # 没有叠加证据时，只选择单个优惠，绝不把多个优惠直接相加。
    if not best_offers:
        for offer in normalized:
            new_price = apply_offer(base_price, base_price, offer)
            if new_price is not None and new_price < best_price:
                best_price = new_price
                best_offers = [offer]

    if best_offers:
        return _result(
            base_price,
            best_price,
            normalized,
            best_offers,
            False,
            "calculated_from_offers",
        )

    status = "offers_detected_but_not_applied" if normalized else "no_verified_discount"
    return _result(
        base_price, base_price, normalized, [], False, status,
    )
