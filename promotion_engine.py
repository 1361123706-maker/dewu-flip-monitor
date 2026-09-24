"""
活动优惠计算引擎

作用：
1. 统一处理商品原价
2. 处理直降
3. 处理店铺券
4. 处理品牌券
5. 处理平台券
6. 处理满减
7. 处理平台补贴
8. 在证据允许的情况下计算最低到手价
9. 输出购买链接和优惠领取链接

注意：
没有明确证据证明可以叠加的优惠，不自动强行叠加。
"""

from itertools import combinations


def to_float(value):
    if value is None:
        return None

    try:
        text = str(value).strip()
        text = text.replace("¥", "")
        text = text.replace("￥", "")
        text = text.replace(",", "")
        text = text.replace("元", "")

        number = float(text)

        if number <= 0:
            return None

        return number

    except Exception:
        return None


def money(value):
    number = to_float(value)

    if number is None:
        return None

    return round(number, 2)


def normalize_offer(offer):
    if not isinstance(offer, dict):
        return None

    amount = to_float(
        offer.get("amount")
    )

    if amount is None or amount <= 0:
        return None

    threshold = to_float(
        offer.get("threshold")
    )

    offer_type = str(
        offer.get(
            "type",
            "unknown"
        )
    ).strip()

    platform = str(
        offer.get(
            "platform",
            ""
        )
    ).strip()

    url = str(
        offer.get(
            "url",
            ""
        )
    ).strip()

    stackable = offer.get(
        "stackable"
    )

    if stackable is None:
        stackable = False

    return {
        "type": offer_type,
        "platform": platform,
        "amount": money(amount),
        "threshold": money(threshold),
        "url": url or None,
        "stackable": bool(stackable),
        "evidence": offer.get(
            "evidence"
        ),
    }


def offer_can_apply(
    price,
    offer,
):
    threshold = offer.get(
        "threshold"
    )

    if threshold is None:
        return True

    return price >= threshold


def apply_offer(
    price,
    offer,
):
    if not offer_can_apply(
        price,
        offer
    ):
        return None

    result = price - offer["amount"]

    if result <= 0:
        return None

    return round(
        result,
        2
    )


def calculate_best_price(
    base_price,
    offers=None,
    explicit_effective_price=None,
):
    """
    返回：
    {
        "base_price": 原价,
        "effective_price": 最低可信到手价,
        "discount_total": 总优惠,
        "offers": 实际采用的优惠,
        "coupon_urls": 可领取链接,
        "verified": 是否有明确到手价证据,
        "calculation_status": 状态
    }
    """

    base_price = to_float(
        base_price
    )

    if (
        base_price is None
        or base_price <= 0
    ):
        return {
            "base_price": None,
            "effective_price": None,
            "discount_total": None,
            "offers": [],
            "coupon_urls": [],
            "verified": False,
            "calculation_status":
                "missing_base_price",
        }

    normalized = []

    for offer in offers or []:
        item = normalize_offer(
            offer
        )

        if item is not None:
            normalized.append(
                item
            )

    # --------------------------------------------------
    # 如果采集器已经拿到明确“最终到手价”
    # 优先相信明确证据
    # --------------------------------------------------

    explicit = to_float(
        explicit_effective_price
    )

    if (
        explicit is not None
        and explicit < base_price
    ):
        urls = []

        for offer in normalized:
            url = offer.get("url")

            if url and url not in urls:
                urls.append(url)

        return {
            "base_price": money(base_price),
            "effective_price": money(explicit),
            "discount_total": money(
                base_price - explicit
            ),
            "offers": normalized,
            "coupon_urls": urls,
            "verified": True,
            "calculation_status":
                "explicit_effective_price",
        }

    # --------------------------------------------------
    # 没有明确到手价：
    # 只计算明确允许叠加的优惠
    # --------------------------------------------------

    stackable = [
        x
        for x in normalized
        if x.get("stackable") is True
    ]

    best_price = base_price
    best_offers = []

    # 不叠加任何优惠
    candidates = [
        []
    ]

    # 枚举可叠加优惠组合
    for r in range(
        1,
        min(
            len(stackable),
            5
        ) + 1
    ):
        candidates.extend(
            combinations(
                stackable,
                r
            )
        )

    for combination in candidates:

        price = base_price
        selected = []
        valid = True

        for offer in combination:

            new_price = apply_offer(
                price,
                offer
            )

            if new_price is None:
                valid = False
                break

            selected.append(
                offer
            )

            price = new_price

        if not valid:
            continue

        if price < best_price:
            best_price = price
            best_offers = list(
                selected
            )

    # --------------------------------------------------
    # 如果没有明确“可叠加”，
    # 分别计算单个优惠，不能擅自全部相加
    # --------------------------------------------------

    if not best_offers:

        for offer in normalized:

            new_price = apply_offer(
                base_price,
                offer
            )

            if new_price is None:
                continue

            if new_price < best_price:
                best_price = new_price
                best_offers = [
                    offer
                ]

    coupon_urls = []

    for offer in best_offers:

        url = offer.get(
            "url"
        )

        if (
            url
            and url not in coupon_urls
        ):
            coupon_urls.append(
                url
            )

    return {
        "base_price": money(
            base_price
        ),

        "effective_price": money(
            best_price
        ),

        "discount_total": money(
            base_price - best_price
        ),

        "offers": best_offers,

        "coupon_urls":
            coupon_urls,

        "verified": False,

        "calculation_status":
            (
                "calculated_from_offers"
                if best_offers
                else "no_verified_discount"
            ),
    }