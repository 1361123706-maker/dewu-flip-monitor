# -*- coding: utf-8 -*-
"""活动优惠计算引擎（保守版）。

规则：
- 明确“券后/到手/实付”价格优先；
- 8.4折/85折等折扣直接换算；
- 满减/优惠券只有页面明确出现时才进入候选；
- 未明确“可叠加”时，不把多个优惠相加；
- 国家补贴/百亿补贴如果只有入口，没有明确金额，不虚构金额；
- 返回所有可点击的优惠入口，但只有有证据的优惠才影响价格。
"""

from itertools import combinations


def to_float(value):
    if value is None:
        return None
    try:
        text = str(value).strip()
        text = text.replace("¥", "").replace("￥", "").replace(",", "").replace("元", "")
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
    rate = to_float(offer.get("rate"))
    threshold = to_float(offer.get("threshold"))

    # 8.4折 -> 0.84
    if rate is not None:
        if rate > 1:
            rate = rate / 10
        if not 0 < rate < 1:
            rate = None

    if amount is None and rate is None:
        return None

    return {
        "type": str(offer.get("type", "unknown")).strip(),
        "platform": str(offer.get("platform", "")).strip(),
        "amount": money(amount),
        "rate": round(rate, 4) if rate is not None else None,
        "threshold": money(threshold),
        "url": str(offer.get("url", "")).strip() or None,
        "stackable": offer.get("stackable") is True,
        "evidence": offer.get("evidence"),
        "source": offer.get("source"),
    }


def offer_can_apply(base_price, current_price, offer):
    threshold = offer.get("threshold")
    return threshold is None or base_price >= threshold


def apply_offer(base_price, current_price, offer):
    if not offer_can_apply(base_price, current_price, offer):
        return None

    rate = offer.get("rate")
    amount = offer.get("amount")

    if rate is not None:
        result = current_price * rate
    elif amount is not None:
        result = current_price - amount
    else:
        return None

    if result <= 0:
        return None
    return round(result, 2)


def urls(offers):
    result = []
    for offer in offers:
        url = offer.get("url")
        if url and url not in result:
            result.append(url)
    return result


def result(base, effective, detected, applied, verified, status):
    return {
        "base_price": money(base),
        "effective_price": money(effective),
        "discount_total": (
            money(base - effective) if effective is not None else None
        ),
        "offers": applied,
        "detected_offers": detected,
        "coupon_urls": urls(applied),
        "all_coupon_urls": urls(detected),
        "verified": bool(verified),
        "calculation_status": status,
    }


def calculate_best_price(
    base_price,
    offers=None,
    explicit_effective_price=None,
):
    base = to_float(base_price)

    normalized = []
    for offer in offers or []:
        item = normalize_offer(offer)
        if item:
            normalized.append(item)

    if base is None:
        return result(
            None, None, normalized, [], False, "missing_base_price"
        )

    # 页面直接给出券后/到手/实付，优先相信这个明确价格。
    explicit = to_float(explicit_effective_price)
    if explicit is not None and explicit < base:
        return result(
            base, explicit, normalized, normalized, True,
            "explicit_effective_price",
        )

    best_price = base
    best_offers = []

    # 有明确“可叠加”证据的优惠才允许组合。
    stackable = [x for x in normalized if x.get("stackable")]
    candidates = [()]
    for r in range(1, min(len(stackable), 5) + 1):
        candidates.extend(combinations(stackable, r))

    for combo in candidates:
        current = base
        selected = []
        valid = True

        for offer in combo:
            new_price = apply_offer(base, current, offer)
            if new_price is None:
                valid = False
                break
            current = new_price
            selected.append(offer)

        if valid and current < best_price:
            best_price = current
            best_offers = selected

    # 没有叠加证据：只允许单个优惠，不做“优惠券+补贴+折扣”强行相加。
    if not best_offers:
        for offer in normalized:
            new_price = apply_offer(base, base, offer)
            if new_price is not None and new_price < best_price:
                best_price = new_price
                best_offers = [offer]

    if best_offers:
        return result(
            base, best_price, normalized, best_offers,
            False, "calculated_from_evidenced_offers"
        )

    return result(
        base, base, normalized, [], False,
        "offers_detected_but_not_verified"
        if normalized else "no_verified_discount",
    )
