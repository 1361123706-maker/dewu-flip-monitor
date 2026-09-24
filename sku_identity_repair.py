# -*- coding: utf-8 -*-
"""SKU 身份修复器（严格版）

规则：
- 货号 + 配色 + 可定位 SKU（当前尺码或 sku_id）才允许进入利润链；
- 只存在商品级最低价/尺码价格表、但无法定位具体 SKU 时，彻底清空买入价；
- 活动优惠只有在 SKU 已确认后才允许影响买入价；
- 精确 SKU 购买链接优先用于后续通知。
"""

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright
from promotion_engine import calculate_best_price


INPUT_FILE = Path("discovery_data.json")
BACKUP_FILE = Path("discovery_data.before_sku_fix.json")

PAGE_TIMEOUT = 25000
WAIT_MS = 1200


def clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def money(value):
    if value is None:
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return round(float(m.group(0)), 2) if m else None


def first(*values):
    for value in values:
        value = clean(value)
        if value:
            return value
    return None


def parse_ids(url, text=""):
    result = {"goods_id": None, "style_id": None, "sku_id": None}
    try:
        qs = parse_qs(urlparse(url).query)
    except Exception:
        qs = {}

    for key in ("goodsId", "goods_id", "goodsid"):
        if qs.get(key):
            result["goods_id"] = qs[key][0]
            break
    for key in ("styleId", "style_id", "styleid"):
        if qs.get(key):
            result["style_id"] = qs[key][0]
            break
    for key in ("skuId", "sku_id", "skuid"):
        if qs.get(key):
            result["sku_id"] = qs[key][0]
            break

    for field, names in {
        "goods_id": ("goodsId", "goods_id", "goodsid"),
        "style_id": ("styleId", "style_id", "styleid"),
        "sku_id": ("skuId", "sku_id", "skuid"),
    }.items():
        if result[field]:
            continue
        for name in names:
            m = re.search(rf"{re.escape(name)}\s*[=:]\s*[\"']?(\d+)", text, re.I)
            if m:
                result[field] = m.group(1)
                break
    return result


def extract_code(text):
    patterns = [
        r"(?:货号|商品货号|产品货号|款号|款式号|款式编号)\s*(?:为|是|[:：])?\s*([A-Za-z0-9][A-Za-z0-9._\-/]{3,40})",
        r"\b([A-Z]{1,8}\d{2,}[A-Z0-9._\-/]*)\b",
    ]
    blacklist = {"ADIDAS", "NIKE", "PUMA", "ASICS", "JORDAN", "NEWBALANCE", "ORIGINALS", "SUPERSTAR"}
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.I):
            value = clean(m.group(1))
            if value and value.upper() not in blacklist:
                return value
    return None


def normalize_size(value):
    value = clean(value)
    if not value:
        return None
    return value.replace("US ", "US").replace("EU ", "EU")


def looks_like_size(value):
    value = normalize_size(value)
    if not value:
        return False
    return bool(re.fullmatch(
        r"(?:EU|US|UK)?\s*\d{1,3}(?:[./]\d{1,2})?(?:⅓|⅔|½)?"
        r"|(?:XS|S|M|L|XL|XXL|XXXL)"
        r"|(?:均码|F|Free)",
        value, re.I
    ))


def extract_variant(text):
    text = clean(text)
    color = None
    size = None

    for pattern in (
        r"(?:当前配色|当前颜色|已选配色|已选颜色|商品配色|商品颜色)\s*[:：]?\s*([^，,；;。]{1,80})",
        r"(?:配色|颜色)\s*[:：]\s*([^，,；;。]{1,80})",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            candidate = clean(m.group(1)).strip("：:，,；; ")
            if candidate and candidate not in {"颜色", "配色", "未选择"}:
                color = candidate
                break

    for pattern in (
        r"(?:当前尺码|已选尺码|选中尺码|当前鞋码|尺码|鞋码)\s*[:：]?\s*([A-Za-z0-9./\-\u00bd⅓⅔ ]{1,15})",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            candidate = normalize_size(m.group(1))
            if looks_like_size(candidate):
                size = candidate
                break

    if not color or not size:
        for m in re.finditer(
            r"([^\n，,；;。]{1,50})\s*[,，]\s*([A-Za-z0-9./\-\u00bd⅓⅔ ]{1,15})",
            text, re.I
        ):
            c = clean(m.group(1))
            s = normalize_size(m.group(2))
            if looks_like_size(s) and 1 <= len(c) <= 50:
                if not any(x in c for x in ("价格", "销量", "优惠", "商品", "尺码", "货号")):
                    color = color or c
                    size = size or s
                    break

    if not color:
        color_words = (
            "黑色", "白色", "蓝色", "红色", "绿色", "灰色", "粉色", "紫色",
            "黄色", "米色", "棕色", "银色", "金色", "卡其", "藏青", "奶白",
            "象牙白", "纯白", "曜石黑", "幻影黑",
        )
        found = [x for x in color_words if x in text]
        if found:
            color = "/".join(dict.fromkeys(found[:3]))

    variant = f"{color}, {size}" if color and size else (color or size)
    return color, size, variant


def extract_size_price_map(text):
    result = {}
    patterns = [
        r"([0-9A-Za-z./\-\u00bd⅓⅔]+)\s*[¥￥]\s*([0-9]+(?:\.[0-9]+)?)",
        r"(?:尺码|鞋码)\s*([0-9A-Za-z./\-\u00bd⅓⅔]+)\s*[:：]?\s*[¥￥]?\s*([0-9]+(?:\.[0-9]+)?)",
    ]
    for pattern in patterns:
        for size, price in re.findall(pattern, text, re.I):
            if looks_like_size(size):
                p = money(price)
                if p is not None:
                    result[normalize_size(size)] = p
    return result


def extract_promotion_offers(text, links):
    offers = []
    text = clean(text)

    for m in re.finditer(r"(?<!\d)(\d+(?:\.\d+)?)\s*折", text, re.I):
        rate = float(m.group(1)) / 10
        if 0.1 < rate < 1:
            nearby = text[max(0, m.start()-80):min(len(text), m.end()+120)]
            offers.append({
                "type": "折扣", "platform": "", "amount": None, "rate": rate,
                "threshold": None, "url": None,
                "stackable": any(x in nearby for x in ("可叠加", "叠加使用", "可同时使用")),
                "evidence": nearby, "source": "shihuo_detail_text",
            })

    for m in re.finditer(
        r"满\s*(\d+(?:\.\d+)?)\s*元?\s*(?:减|立减|优惠)\s*(\d+(?:\.\d+)?)\s*元?",
        text, re.I
    ):
        nearby = text[max(0, m.start()-80):min(len(text), m.end()+120)]
        offers.append({
            "type": "满减", "platform": "", "amount": float(m.group(2)),
            "rate": None, "threshold": float(m.group(1)), "url": None,
            "stackable": any(x in nearby for x in ("可叠加", "叠加使用", "可同时使用")),
            "evidence": m.group(0), "source": "shihuo_detail_text",
        })

    for m in re.finditer(
        r"(国家补贴|百亿补贴|平台补贴|官方补贴)[^0-9]{0,30}(?:立减|减|补贴)?\s*(\d+(?:\.\d+)?)\s*元",
        text, re.I
    ):
        nearby = text[max(0, m.start()-80):min(len(text), m.end()+120)]
        offers.append({
            "type": m.group(1), "platform": "", "amount": float(m.group(2)),
            "rate": None, "threshold": None, "url": None,
            "stackable": any(x in nearby for x in ("可叠加", "叠加使用", "可同时使用")),
            "evidence": m.group(0), "source": "shihuo_detail_text",
        })

    for link in links or []:
        if link.get("url") and link.get("is_coupon"):
            offers.append({
                "type": "优惠领取入口", "platform": link.get("platform", ""),
                "amount": None, "rate": None, "threshold": None,
                "url": link.get("url"), "stackable": False,
                "evidence": link.get("anchor_text", ""),
                "source": "shihuo_external_link",
            })
    return offers


def build_urls(ids, original_url):
    goods_id = ids.get("goods_id")
    sku_id = ids.get("sku_id")
    style_id = ids.get("style_id")
    goods_url = original_url
    supplier_url = None

    if goods_id and sku_id:
        supplier_url = f"https://m.shihuo.cn/page/supplierList/{sku_id}?id={goods_id}&sku_id={sku_id}"
        goods_url = f"https://m.shihuo.cn/page/goodsDetail/{goods_id}?goodsId={goods_id}&skuId={sku_id}"
        if style_id:
            goods_url += f"&styleId={style_id}"
    return goods_url, supplier_url


def repair_item(page, item):
    url = item.get("shihuo_url") or item.get("source_url") or item.get("buy_url")
    if not url:
        item["hard_exclude"] = True
        item["hard_exclude_reason"] = "没有可重新验证的识货商品页面"
        item["sku_identity_complete"] = False
        return item

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        page.wait_for_timeout(WAIT_MS)
        text = clean(page.locator("body").inner_text(timeout=5000))
        html = page.content()
    except Exception as exc:
        item["sku_repair_error"] = str(exc)[:300]
        item["hard_exclude"] = True
        item["hard_exclude_reason"] = "SKU页面重新验证失败，禁止使用旧商品级价格"
        item["sku_identity_complete"] = False
        return item

    ids = parse_ids(page.url, html + "\n" + text)
    color, size, variant = extract_variant(text)
    size_map = extract_size_price_map(text)
    promotion_offers = extract_promotion_offers(text, item.get("official_store_links", []))

    explicit_effective = None
    m_effective = re.search(
        r"(?:券后价|优惠后价格|最终到手价|预计到手价|到手价|实付价|最终价)"
        r"\s*[:：]?\s*[¥￥]?\s*(\d+(?:\.\d+)?)",
        text, re.I
    )
    if m_effective:
        explicit_effective = float(m_effective.group(1))

    item["goods_id"] = first(item.get("goods_id"), ids["goods_id"])
    item["style_id"] = first(item.get("style_id"), ids["style_id"])
    item["sku_id"] = first(item.get("sku_id"), ids["sku_id"])
    item["product_code"] = first(item.get("product_code"), extract_code(text))
    item["color"] = first(color, item.get("color"))
    item["current_size"] = first(size, item.get("current_size"))
    item["selected_variant"] = first(variant, item.get("selected_variant"))

    if size_map:
        merged = dict(item.get("size_price_map") or {})
        merged.update(size_map)
        item["size_price_map"] = merged

    current_size = normalize_size(item.get("current_size"))
    if current_size and current_size in item.get("size_price_map", {}):
        item["sku_buy_price"] = item["size_price_map"][current_size]
        item["sku_price_status"] = "confirmed_current_size"
        item["buy_price"] = item["sku_buy_price"]
        item["buy_price_source"] = "识货当前颜色+当前尺码 SKU 价格"
        item["buy_price_status"] = "confirmed_sku_price"

    goods_url, supplier_url = build_urls(
        {"goods_id": item.get("goods_id"), "style_id": item.get("style_id"), "sku_id": item.get("sku_id")},
        page.url
    )
    item["shihuo_sku_url"] = goods_url
    item["sku_purchase_url"] = supplier_url

    # 严格身份：必须有货号、配色，并且有当前尺码或 sku_id。
    complete = bool(
        item.get("product_code")
        and item.get("color")
        and (item.get("current_size") or item.get("sku_id"))
    )
    item["sku_identity_complete"] = complete

    # 只有身份完整时，优惠才能进入最终买入价。
    if complete:
        base_for_promo = (
            item.get("sku_buy_price")
            or item.get("buy_price_before_discount")
            or item.get("buy_price")
        )
        promo = calculate_best_price(
            base_for_promo,
            offers=promotion_offers,
            explicit_effective_price=explicit_effective,
        )
    else:
        promo = calculate_best_price(None, offers=promotion_offers)

    item["promotion_calculation"] = promo
    item["promotion_offers"] = promo.get("offers", [])
    item["coupon_urls"] = list(dict.fromkeys(
        (item.get("coupon_urls") or []) + promo.get("coupon_urls", [])
    ))
    item["all_coupon_urls"] = list(dict.fromkeys(
        (item.get("all_coupon_urls") or []) + promo.get("all_coupon_urls", [])
    ))

    if complete and promo.get("effective_price") is not None:
        item["best_effective_buy_price"] = promo["effective_price"]
        item["effective_buy_price"] = promo["effective_price"]
        item["buy_price"] = promo["effective_price"]
        item["buy_price_source"] = "SKU价格 + 页面明确活动优惠"
        item["buy_price_status"] = (
            "explicit_effective_price" if promo.get("verified")
            else "calculated_promotion_price"
        )

    if not complete:
        item["hard_exclude"] = True
        item["hard_exclude_reason"] = "缺少货号/配色/可定位SKU，禁止使用商品级最低价计算利润"
        item["category"] = "excluded"
        item["category_reason"] = item["hard_exclude_reason"]

        # 无论之前有什么商品级价格，都彻底清空，防止下游误算。
        for key in (
            "buy_price", "sku_buy_price", "best_effective_buy_price",
            "effective_buy_price", "final_buy_price", "estimated_final_price"
        ):
            item[key] = None
        item["buy_price_status"] = "sku_identity_incomplete"
        item["buy_price_source"] = "禁止使用商品级最低价"

    else:
        item["hard_exclude"] = False
        item["hard_exclude_reason"] = None
        if item.get("category") == "excluded":
            item["category"] = None
            item["category_reason"] = None

    if supplier_url:
        item["buy_url"] = supplier_url

    item["sku_repair_status"] = "repaired"
    return item


def main():
    if not INPUT_FILE.exists():
        raise SystemExit("找不到 discovery_data.json")

    data = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    products = data.get("products") or []
    if not isinstance(products, list):
        raise SystemExit("discovery_data.json 的 products 不是列表")

    BACKUP_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = context.new_page()

        repaired = 0
        complete = 0
        excluded = 0

        for index, item in enumerate(products, 1):
            if not isinstance(item, dict):
                continue
            print(f"[SKU修复 {index}/{len(products)}] {item.get('name', '')[:80]}")
            new_item = repair_item(page, item)
            products[index - 1] = new_item
            if new_item.get("sku_repair_status") == "repaired":
                repaired += 1
            if new_item.get("sku_identity_complete"):
                complete += 1
            if new_item.get("hard_exclude"):
                excluded += 1

        browser.close()

    data["products"] = products
    data["sku_repair"] = {
        "enabled": True,
        "repaired": repaired,
        "sku_identity_complete": complete,
        "hard_excluded": excluded,
        "rule": "货号+配色+可定位SKU；禁止商品级最低价冒充SKU买入价",
    }

    INPUT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=" * 60)
    print("SKU 修复完成")
    print("商品总数：", len(products))
    print("重新读取：", repaired)
    print("SKU身份完整：", complete)
    print("硬排除：", excluded)
    print("原始备份：", BACKUP_FILE)
    print("=" * 60)


if __name__ == "__main__":
    main()
