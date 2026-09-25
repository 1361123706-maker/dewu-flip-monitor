import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

from promotion_engine import calculate_best_price
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

OUTPUT_FILE = Path("discovery_data.json")

HOME_URL = "https://www.shihuo.cn/page/pcHome"
SEARCH_URL = (
    "https://m.shihuo.cn/search/searchResult/goods"
    "?keywords={keyword}&page={page}&pagesize=30"
)

KEYWORDS = [
    "Nike", "adidas", "New Balance", "ASICS", "PUMA",
    "李宁", "安踏", "乔丹体育", "运动鞋", "球鞋",
    "潮鞋", "跑鞋", "服饰", "包袋",
]

MAX_KEYWORDS = 14
MAX_PRODUCTS = 30
MAX_DETAIL_LINKS = 30
PAGE_TIMEOUT = 30000
DETAIL_TIMEOUT = 20000
SEARCH_WAIT_SECONDS = 3
DETAIL_WAIT_SECONDS = 1.5

PLATFORM_RULES = [
    {"name": "天猫", "domains": ["tmall.com"], "official_markers": ["官方旗舰店", "旗舰店", "官方店"]},
    {"name": "淘宝", "domains": ["taobao.com"], "official_markers": ["官方旗舰店", "旗舰店", "官方店"]},
    {"name": "京东", "domains": ["jd.com"], "official_markers": ["京东自营", "自营旗舰店", "官方旗舰店", "旗舰店"]},
    {"name": "拼多多", "domains": ["yangkeduo.com", "pinduoduo.com"], "official_markers": ["官方旗舰店", "旗舰店", "品牌店"]},
    {"name": "唯品会", "domains": ["vip.com"], "official_markers": ["官方", "旗舰店", "品牌"]},
    {"name": "抖音商城", "domains": ["douyin.com"], "official_markers": ["官方旗舰店", "旗舰店", "官方店"]},
]

COUPON_KEYWORDS = [
    "优惠券", "领券", "券后", "店铺券", "品牌券", "平台券",
    "满减", "补贴", "立减", "直降", "到手价", "实付",
]

INVALID_URL_VALUES = {"none", "null", "undefined", "nan", "-"}

def clean_text(value):
    if value is None:
        return ""
    text = str(value).replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()

def to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number > 0 else None
    text = str(value).replace(",", "").replace("¥", "").replace("￥", "").replace("元", "").strip()
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    return number if number > 0 else None

def money(value):
    number = to_float(value)
    return round(number, 2) if number is not None else None

def valid_url(value):
    if not isinstance(value, str):
        return False
    value = value.strip()
    return bool(value) and value.lower() not in INVALID_URL_VALUES and value.startswith(("http://", "https://"))

def clean_url(value):
    value = clean_text(value)
    return value if valid_url(value) else None

def unique_list(values):
    result = []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return result
    for value in values:
        value = clean_text(value)
        if value and value.lower() not in INVALID_URL_VALUES and value not in result:
            result.append(value)
    return result

def clean_url_list(values):
    result = []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return result
    for value in values:
        value = clean_url(value)
        if value and value not in result:
            result.append(value)
    return result

def clean_offer_list(values):
    if not isinstance(values, list):
        return []
    result = []
    for offer in values:
        if not isinstance(offer, dict):
            continue
        offer = dict(offer)
        if "url" in offer:
            offer["url"] = clean_url(offer.get("url"))
        result.append(offer)
    return result

def clean_product_links(product):
    if not isinstance(product, dict):
        return product
    for key in ("coupon_urls", "all_coupon_urls", "buy_urls"):
        product[key] = clean_url_list(product.get(key))
    for key in ("buy_url", "shihuo_url", "shihuo_sku_url", "sku_purchase_url", "source_url"):
        if key in product:
            product[key] = clean_url(product.get(key))
    product["promotion_offers"] = clean_offer_list(product.get("promotion_offers"))
    product["promotion_links"] = clean_offer_list(product.get("promotion_links"))
    if isinstance(product.get("official_store_links"), list):
        cleaned = []
        for link in product["official_store_links"]:
            if not isinstance(link, dict):
                continue
            item = dict(link)
            item["url"] = clean_url(item.get("url"))
            if item.get("url"):
                cleaned.append(item)
        product["official_store_links"] = cleaned
    return product

def clean_existing_data(data):
    if isinstance(data, dict) and isinstance(data.get("products"), list):
        data["products"] = [clean_product_links(x) for x in data["products"] if isinstance(x, dict)]
        data["count"] = len(data["products"])
        return data
    if isinstance(data, list):
        return [clean_product_links(x) for x in data if isinstance(x, dict)]
    return data

def first_value(item, *keys):
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value.strip()
        else:
            return value
    return None

def safe_json_load(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print("读取旧数据失败：", exc)
        return {}

def detect_platform(url):
    if not valid_url(url):
        return None
    host = urlparse(url).netloc.lower()
    for rule in PLATFORM_RULES:
        for domain in rule["domains"]:
            if host == domain or host.endswith("." + domain):
                return rule["name"]
    return None

def detect_store_type(text):
    text = clean_text(text)
    if not text:
        return None
    if any(x in text for x in ("京东自营", "官方直营", "官方直营店", "品牌直营", "自营旗舰店")):
        return "官方直营/自营"
    if "官方旗舰店" in text or "品牌旗舰店" in text:
        return "官方旗舰店"
    if "旗舰店" in text:
        return "旗舰店"
    return None

def is_product_url(url):
    if not valid_url(url):
        return False
    lower = url.lower()
    if "shihuo.cn" not in lower:
        return False
    return any(marker in lower for marker in ("goods", "product", "detail", "item", "pcgoodsdetail"))

def collect_external_links(page):
    results = []
    try:
        anchors = page.locator("a")
        count = min(anchors.count(), 600)
    except Exception:
        return results
    for index in range(count):
        try:
            anchor = anchors.nth(index)
            href = anchor.get_attribute("href", timeout=1000)
            if not href:
                continue
            href = urljoin(page.url, href)
            text = clean_text(anchor.inner_text(timeout=1000))
            platform = detect_platform(href)
            if not platform:
                continue
            results.append({
                "platform": platform,
                "url": href,
                "anchor_text": text[:200],
                "store_type": detect_store_type(text),
                "is_coupon": any(word in text for word in COUPON_KEYWORDS),
            })
        except Exception:
            continue
    unique = []
    seen = set()
    for item in results:
        key = (item["platform"], item["url"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique

def extract_product_code(text):
    text = clean_text(text)
    if not text:
        return None
    patterns = [
        r"(?:货号|商品货号|产品货号|款号|款式号|款式编号)\s*(?:为|是|[:：])?\s*([A-Za-z0-9][A-Za-z0-9._\-/]{3,40})",
        r"([A-Z]{1,8}\d{2,}[A-Z0-9._\-/]*)\s*货号",
    ]
    blacklist = {"adidas", "nike", "newbalance", "asics", "puma", "jordan", "apple", "coach", "originals", "superstar"}
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = clean_text(match.group(1))
            if value and value.lower() not in blacklist:
                return value
    return None

def extract_color(text):
    text = clean_text(text)
    if not text:
        return None
    patterns = [
        r"(?:当前配色|当前颜色|已选配色|已选颜色)\s*[:：]?\s*([^，,。；;\n]{1,80})",
        r"(?:商品配色|商品颜色)\s*[:：]\s*([^，,。；;\n]{1,80})",
    ]
    blacklist = {"可选配色", "可选尺码", "颜色", "尺码", "货号", "品牌", "商品名称", "价格信息"}
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = clean_text(match.group(1)).strip("：:，,。；; ")
            if value and value not in blacklist and len(value) <= 80:
                return value
    return None

def extract_current_size(text):
    text = clean_text(text)
    if not text:
        return None
    patterns = [
        r"(?:当前尺码|已选尺码|选中尺码|当前鞋码)\s*[:：]?\s*([A-Za-z0-9./\-½⅓⅔]{1,12})",
        r"(?:当前规格|已选规格|选中规格)\s*[:：]?\s*[^，,；;]{0,30}?(?:尺码|鞋码)\s*[:：]?\s*([A-Za-z0-9./\-½⅓⅔]{1,12})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = clean_text(match.group(1))
            if value and value not in {"请选择", "未选择"}:
                return value
    return None

def extract_size_price_map(text):
    result = {}
    if not text:
        return result
    patterns = [
        r"([0-9A-Za-z./\-/½⅓⅔]+)\s*[¥￥]\s*([0-9]+(?:\.[0-9]+)?)",
        r"([0-9A-Za-z./\-/½⅓⅔]+)\s+([0-9]+(?:\.[0-9]+)?)\s*元",
    ]
    for pattern in patterns:
        for size, price in re.findall(pattern, text, re.I):
            number = to_float(price)
            size = clean_text(size)
            if number is not None and size and len(size) <= 12:
                result[size] = money(number)
    return result

def extract_price_after_keywords(text, keywords):
    if not text:
        return None
    joined = "|".join(re.escape(keyword) for keyword in keywords)
    pattern = rf"(?:{joined})\s*[:：]?\s*[¥￥]?\s*([0-9]+(?:\.[0-9]+)?)"
    match = re.search(pattern, text, re.I)
    return money(match.group(1)) if match else None

def extract_effective_price(text):
    return extract_price_after_keywords(text, ("券后价", "券后价格", "优惠后价格", "活动后价格", "最终到手价", "预计到手价", "到手价", "实付价", "最终价"))

def extract_base_price(text):
    return extract_price_after_keywords(text, ("原价", "吊牌价", "商品价", "售价", "价格"))

def extract_dewu_channel_price(text):
    return extract_price_after_keywords(text, ("得物渠道售价", "得物售价", "得物渠道价格"))

def extract_current_price(text):
    return extract_price_after_keywords(text, ("当前同款同规格", "当前价格", "当前价", "当前到手价"))

def extract_7d_low(text):
    if not text:
        return None
    patterns = [
        r"(?:近7天|过去7天|最近7天|7日|7天).{0,150}?(?:最低价|最低)\s*[:：]?\s*[¥￥]?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
        r"(?:7天最低价|近7日最低价)\s*[:：]?\s*[¥￥]?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            value = money(match.group(1))
            if value is not None:
                return value
    return None

def extract_7d_high(text):
    if not text:
        return None
    patterns = [
        r"(?:近7天|过去7天|最近7天|7日|7天).{0,150}?(?:最高价|最高)\s*[:：]?\s*[¥￥]?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
        r"(?:7天最高价|近7日最高价)\s*[:：]?\s*[¥￥]?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            value = money(match.group(1))
            if value is not None:
                return value
    return None

def extract_sales(text):
    result = {"sales_7d": None, "sales_30d": None, "sales_total": None, "sales_velocity_7d": None, "turnover_evidence": None, "turnover_confidence": "unknown"}
    if not text:
        return result
    patterns = {
        "sales_7d": [r"(?:近7天|近7日|7天销量|7日销量)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(万)?"],
        "sales_30d": [r"(?:月销|月销量|近30天销量|近30日销量)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(万)?"],
        "sales_total": [r"(?:全网销量|总销|总销量|累计销量)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(万)?"],
    }
    for field, field_patterns in patterns.items():
        for pattern in field_patterns:
            match = re.search(pattern, text, re.I)
            if match:
                value = to_float(match.group(1))
                if value is None:
                    continue
                if match.group(2) == "万":
                    value *= 10000
                result[field] = money(value)
                break
    if result["sales_7d"]:
        velocity = round(result["sales_7d"] / 7, 2)
        result["sales_velocity_7d"] = velocity
        result["turnover_confidence"] = "high"
        result["turnover_evidence"] = f"近7日销量 {result['sales_7d']:g}，日均约 {velocity:.2f}"
    elif result["sales_30d"]:
        velocity = round(result["sales_30d"] / 30, 2)
        result["sales_velocity_7d"] = velocity
        result["turnover_confidence"] = "medium"
        result["turnover_evidence"] = f"月销 {result['sales_30d']:g}，日均约 {velocity:.2f}"
    elif result["sales_total"]:
        result["turnover_confidence"] = "low"
        result["turnover_evidence"] = f"累计/全网销量 {result['sales_total']:g}，不能直接证明7日周转"
    return result

def extract_coupon_evidence(text):
    if not text:
        return []
    results = []
    for keyword in COUPON_KEYWORDS:
        for match in list(re.finditer(re.escape(keyword), text, re.I))[:5]:
            evidence = clean_text(text[max(0, match.start()-80): min(len(text), match.end()+180)])
            if evidence and evidence not in results:
                results.append(evidence)
    return results[:30]

def extract_coupon_offers(text, links):
    text = clean_text(text)
    links = links or []
    offers = []
    def stackable_near(position):
        window = text[max(0, position-100): min(len(text), position+160)]
        return any(marker in window for marker in ("可叠加", "叠加使用", "可同时使用", "同时使用", "一起使用", "可以叠加"))
    coupon_links = [x for x in links if x.get("is_coupon")]
    full_reduce = re.compile(r"满\s*([0-9]+(?:\.[0-9]+)?)\s*元?[^。；;\n]{0,25}?(?:减|立减|优惠)\s*([0-9]+(?:\.[0-9]+)?)\s*元?", re.I)
    for match in full_reduce.finditer(text):
        threshold, amount = money(match.group(1)), money(match.group(2))
        if amount is None:
            continue
        offers.append({"type": "满减", "platform": "", "amount": amount, "threshold": threshold, "url": None, "stackable": stackable_near(match.start()), "evidence": clean_text(match.group(0)), "source": "shihuo_detail_text"})
    coupon_patterns = [
        ("店铺券", r"店铺券[^。；;\n]{0,45}?(?:减\s*)?([0-9]+(?:\.[0-9]+)?)\s*元?"),
        ("品牌券", r"品牌券[^。；;\n]{0,45}?(?:减\s*)?([0-9]+(?:\.[0-9]+)?)\s*元?"),
        ("平台券", r"平台券[^。；;\n]{0,45}?(?:减\s*)?([0-9]+(?:\.[0-9]+)?)\s*元?"),
        ("优惠券", r"优惠券[^。；;\n]{0,45}?(?:减\s*)?([0-9]+(?:\.[0-9]+)?)\s*元?"),
        ("优惠券", r"([0-9]+(?:\.[0-9]+)?)\s*元优惠券"),
    ]
    for offer_type, pattern in coupon_patterns:
        for match in re.finditer(pattern, text, re.I):
            amount = money(match.group(1))
            if amount is None:
                continue
            nearby = text[max(0, match.start()-100): min(len(text), match.end()+160)]
            link = next((x for x in coupon_links if x.get("platform")), None)
            offers.append({"type": offer_type, "platform": link.get("platform", "") if link else "", "amount": amount, "threshold": None, "url": link.get("url") if link else None, "stackable": any(marker in nearby for marker in ("可叠加", "叠加使用", "可同时使用", "同时使用", "一起使用")), "evidence": clean_text(nearby), "source": "shihuo_detail_text"})
    subsidy_patterns = [
        r"(?:平台补贴|百亿补贴|官方补贴|补贴)[^0-9]{0,30}([0-9]+(?:\.[0-9]+)?)\s*元",
        r"(?:直降|立减)[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*元",
    ]
    for pattern in subsidy_patterns:
        for match in re.finditer(pattern, text, re.I):
            amount = money(match.group(1))
            if amount is None:
                continue
            link = next((x for x in coupon_links if x.get("platform")), None)
            offers.append({"type": "平台补贴/直降", "platform": link.get("platform", "") if link else "", "amount": amount, "threshold": None, "url": link.get("url") if link else None, "stackable": False, "evidence": clean_text(match.group(0)), "source": "shihuo_detail_text"})
    unique = []
    seen = set()
    for offer in offers:
        offer["url"] = clean_url(offer.get("url"))
        key = (offer.get("type"), offer.get("platform"), offer.get("amount"), offer.get("threshold"), offer.get("url"), offer.get("evidence"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(offer)
    return unique[:30]

def build_product_from_detail(page, url, fallback_text=""):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=DETAIL_TIMEOUT)
        page.wait_for_timeout(int(DETAIL_WAIT_SECONDS * 1000))
        text = clean_text(page.locator("body").inner_text(timeout=5000))
        links = collect_external_links(page)
        product = parse_detail_text(text, url, fallback_text, links)
        return product
    except Exception as exc:
        print("详情读取失败：", exc)
        return None

def parse_detail_text(text, url, fallback_text, links):
    name = clean_text(fallback_text)[:200] or None
    product = {
        "name": name,
        "shihuo_url": clean_url(url),
        "source_url": clean_url(url),
        "external_links": links,
        "official_store_links": [
            x for x in links if x.get("store_type") in {"官方直营/自营", "官方旗舰店", "旗舰店"}
        ],
        "coupon_urls": unique_list([x.get("url") for x in links if x.get("is_coupon")]),
        "coupon_evidence": extract_coupon_evidence(text),
        "promotion_offers": extract_coupon_offers(text, links),
    }
    product.update({
        "product_code": extract_product_code(text),
        "color": extract_color(text),
        "current_size": extract_current_size(text),
        "size_price_map": extract_size_price_map(text),
        "effective_buy_price": extract_effective_price(text),
        "buy_price": extract_base_price(text),
        "dewu_price": extract_dewu_channel_price(text) or extract_current_price(text),
        "price_7d_low": extract_7d_low(text),
        "price_7d_high": extract_7d_high(text),
        **extract_sales(text),
    })
    product = clean_product_links(product)
    return product

def build_fallback_product(url, text):
    return clean_product_links({
        "name": clean_text(text)[:200] or None,
        "shihuo_url": clean_url(url),
        "source_url": clean_url(url),
        "coupon_urls": [],
        "promotion_offers": [],
    })

def collect_product_links(page, keyword, page_number):
    url = SEARCH_URL.format(keyword=quote(keyword), page=page_number)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        page.wait_for_timeout(int(SEARCH_WAIT_SECONDS * 1000))
    except Exception as exc:
        print(f"搜索页失败 {keyword}: {exc}")
        return []
    results = []
    try:
        anchors = page.locator("a")
        count = min(anchors.count(), 800)
    except Exception:
        return []
    seen = set()
    for index in range(count):
        try:
            anchor = anchors.nth(index)
            href = anchor.get_attribute("href", timeout=1000)
            if not href:
                continue
            href = urljoin(page.url, href)
            if not is_product_url(href) or href in seen:
                continue
            text = clean_text(anchor.inner_text(timeout=1000))
            seen.add(href)
            results.append({"url": href, "text": text})
            if len(results) >= MAX_PRODUCTS:
                break
        except Exception:
            continue
    return results

def merge_products(existing, new_products):
    merged = {}
    for product in existing:
        if not isinstance(product, dict):
            continue
        product = clean_product_links(product)
        name = clean_text(product.get("name"))
        if name:
            merged[name.lower()] = product
    for product in new_products:
        if not isinstance(product, dict):
            continue
        product = clean_product_links(product)
        name = clean_text(product.get("name"))
        if not name:
            continue
        key = name.lower()
        if key not in merged:
            merged[key] = product
            continue
        old = merged[key]
        for field, value in product.items():
            if value is not None:
                old[field] = value
        old["coupon_urls"] = clean_url_list(old.get("coupon_urls", []) + product.get("coupon_urls", []))
        old["all_coupon_urls"] = clean_url_list(old.get("all_coupon_urls", []) + product.get("all_coupon_urls", []))
        old["buy_urls"] = clean_url_list(old.get("buy_urls", []) + product.get("buy_urls", []))
        old["promotion_offers"] = clean_offer_list(old.get("promotion_offers", []) + product.get("promotion_offers", []))
        old["promotion_links"] = clean_offer_list(old.get("promotion_links", []) + product.get("promotion_links", []))
        if isinstance(old.get("official_store_links"), list):
            old["official_store_links"] = [
                x for x in old["official_store_links"]
                if isinstance(x, dict) and valid_url(x.get("url"))
            ]
        old["evidence_count"] = sum(1 for value in old.get("evidence", {}).values() if value) if isinstance(old.get("evidence"), dict) else 0
    return list(merged.values())

def main():
    print("=" * 70)
    print("真实浏览器公开商品采集器")
    print("=" * 70)
    existing_data = safe_json_load(OUTPUT_FILE)
    existing_data = clean_existing_data(existing_data)
    existing_products = existing_data.get("products", []) if isinstance(existing_data, dict) else []
    if not isinstance(existing_products, list):
        existing_products = []
    collected = []
    product_links = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        search_page = context.new_page()
        for keyword in KEYWORDS[:MAX_KEYWORDS]:
            links = collect_product_links(search_page, keyword, 1)
            for link in links:
                if link["url"] not in {item["url"] for item in product_links}:
                    product_links.append(link)
                if len(product_links) >= MAX_DETAIL_LINKS:
                    break
            if len(product_links) >= MAX_DETAIL_LINKS:
                break
        detail_page = context.new_page()
        for index, link in enumerate(product_links[:MAX_DETAIL_LINKS], start=1):
            print(f"[{index}/{min(len(product_links), MAX_DETAIL_LINKS)}] 读取详情：{link['url']}")
            product = build_product_from_detail(detail_page, link["url"], link.get("text", ""))
            if product is None:
                product = build_fallback_product(link["url"], link.get("text", ""))
            collected.append(product)
        browser.close()
    print("本次详情商品：", len(collected))
    products = existing_products if not collected else merge_products(existing_products, collected)
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(products),
        "source": "识货",
        "products": products,
    }
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("最终商品数量：", len(products))
    print("有买入价：", sum(item.get("buy_price") is not None for item in products))
    print("有识货链接：", sum(bool(item.get("shihuo_url")) for item in products))
    print("有优惠证据：", sum(bool(item.get("coupon_urls") or item.get("coupon_evidence") or item.get("promotion_offers")) for item in products))
    print("历史无效链接清理完成。")
    print("=" * 70)

if __name__ == "__main__":
    main()
