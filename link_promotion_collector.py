import json
import re
from pathlib import Path
from urllib.parse import urlencode

FILE = Path("discovery_data.json")

PLATFORM_DOMAINS = {
    "淘宝": ("taobao.com",),
    "天猫": ("tmall.com",),
    "京东": ("jd.com",),
    "拼多多": ("yangkeduo.com", "pinduoduo.com"),
    "唯品会": ("vip.com",),
    "抖音商城": ("douyin.com",),
}

def valid_url(v):
    return isinstance(v, str) and v.startswith(("http://", "https://")) and v not in {"None", "null"}

def clean_urls(values):
    out = []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return out
    for v in values:
        if valid_url(v) and v not in out:
            out.append(v)
    return out

def domain_platform(url):
    if not valid_url(url):
        return None
    u = url.lower()
    for name, domains in PLATFORM_DOMAINS.items():
        if any(d in u for d in domains):
            return name
    return None

def extract_urls_from_text(text):
    if not isinstance(text, str):
        return []
    return clean_urls(re.findall(r'https?://[^\s<>"\']+', text))

def repair_item(item):
    if not isinstance(item, dict):
        return item

    goods_id = item.get("goods_id")
    sku_id = item.get("sku_id")
    style_id = item.get("style_id")

    # 只整理真实存在的商品/SKU入口，不伪造第三方优惠券。
    if goods_id and sku_id:
        params = {"goodsId": goods_id, "skuId": sku_id}
        if style_id:
            params["styleId"] = style_id
        item["shihuo_sku_url"] = (
            f"https://m.shihuo.cn/page/goodsDetail/{goods_id}?{urlencode(params)}"
        )
        item["sku_purchase_url"] = (
            f"https://m.shihuo.cn/page/supplierList/{sku_id}"
            f"?{urlencode({'id': goods_id, 'sku_id': sku_id})}"
        )

    buy_candidates = []
    for key in ("buy_url", "sku_purchase_url", "shihuo_sku_url", "shihuo_url", "source_url"):
        buy_candidates += clean_urls(item.get(key))

    official = item.get("official_store_links")
    if isinstance(official, list):
        for link in official:
            if isinstance(link, dict):
                buy_candidates += clean_urls(link.get("url"))

    item["buy_urls"] = list(dict.fromkeys(buy_candidates))
    item["buy_url"] = item["buy_urls"][0] if item["buy_urls"] else None

    coupon_urls = []
    for key in ("coupon_urls", "all_coupon_urls"):
        coupon_urls += clean_urls(item.get(key))

    calc = item.get("promotion_calculation")
    if isinstance(calc, dict):
        for key in ("coupon_urls", "all_coupon_urls"):
            coupon_urls += clean_urls(calc.get(key))

    offers = item.get("promotion_offers")
    if isinstance(offers, list):
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            urls = clean_urls(offer.get("url"))
            if urls:
                offer["url"] = urls[0]
                coupon_urls += urls
            elif "url" in offer:
                offer["url"] = None

    for key in ("coupon_evidence", "promotion_evidence", "source_note"):
        coupon_urls += extract_urls_from_text(item.get(key, ""))

    item["coupon_urls"] = list(dict.fromkeys(coupon_urls))
    item["all_coupon_urls"] = item["coupon_urls"][:]

    promotion_links = []
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict) and valid_url(offer.get("url")):
                promotion_links.append({
                    "type": offer.get("type") or "优惠活动",
                    "platform": offer.get("platform") or domain_platform(offer["url"]) or "",
                    "url": offer["url"],
                    "evidence": offer.get("evidence") or "",
                })

    item["promotion_links"] = promotion_links
    item["promotion_link_count"] = len(promotion_links)
    item["coupon_link_count"] = len(item["coupon_urls"])

    # 没有证据时不能凭空把优惠标记成已验证。
    item["promotion_verified"] = bool(item.get("promotion_verified")) and bool(
        item.get("promotion_calculation")
    )
    return item

def main():
    if not FILE.exists():
        raise SystemExit("discovery_data.json 不存在")

    data = json.loads(FILE.read_text(encoding="utf-8"))

    if isinstance(data, dict) and isinstance(data.get("products"), list):
        data["products"] = [repair_item(x) for x in data["products"]]
        products = data["products"]
    elif isinstance(data, list):
        data = [repair_item(x) for x in data]
        products = data
    else:
        raise SystemExit("discovery_data.json 格式异常")

    FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("链接/优惠字段整理完成：", len(products))
    print("有效购买链接：", sum(bool(x.get("buy_urls")) for x in products if isinstance(x, dict)))
    print("有效优惠链接：", sum(bool(x.get("coupon_urls")) for x in products if isinstance(x, dict)))

if __name__ == "__main__":
    main()
