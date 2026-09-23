import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser
from urllib.robotparser import RobotFileParser


OUTPUT_FILE = Path("market_data_input.json")

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; dewu-flip-monitor/1.0; "
    "+https://github.com/1361123706-maker/dewu-flip-monitor)"
)

TIMEOUT = 20

MAX_PRODUCT_PAGES = 40

CRAWL_DELAY = 2


KEYWORDS = [
    "Nike",
    "adidas",
    "New Balance",
    "ASICS",
    "PUMA",
    "李宁",
    "安踏",
    "乔丹体育",
    "运动鞋",
    "球鞋",
    "潮鞋",
    "跑鞋",
    "服饰",
    "包袋",
]


SEED_URLS = [
    "https://www.shihuo.cn/",
    "https://www.shihuo.cn/page/pcHome",
]


# ============================================================
# 日志
# ============================================================

def log(message):
    print(message, flush=True)


# ============================================================
# robots.txt
#
# 只访问网站允许公开自动访问的路径。
# 不绕过 robots.txt。
# ============================================================

robots_cache = {}


def allowed_by_robots(url):

    parsed = urlparse(url)

    origin = (
        parsed.scheme
        + "://"
        + parsed.netloc
    )

    if origin in robots_cache:
        parser = robots_cache[origin]
        return parser.can_fetch(
            USER_AGENT,
            url
        )

    robots_url = (
        origin
        + "/robots.txt"
    )

    parser = RobotFileParser()

    parser.set_url(
        robots_url
    )

    try:

        parser.read()

        robots_cache[
            origin
        ] = parser

        return parser.can_fetch(
            USER_AGENT,
            url
        )

    except Exception as e:

        # robots.txt 无法读取时，
        # 为安全起见不继续自动抓取。
        log(
            f"无法读取 robots.txt："
            f"{origin}"
        )

        return False


# ============================================================
# 获取网页
# ============================================================

def fetch_html(url):

    if not allowed_by_robots(
        url
    ):

        log(
            f"robots.txt 不允许访问："
            f"{url}"
        )

        return None


    request = Request(

        url,

        headers={
            "User-Agent":
                USER_AGENT,

            "Accept":
                "text/html,"
                "application/xhtml+xml",

            "Accept-Language":
                "zh-CN,zh;q=0.9",

        },

        method="GET",

    )


    try:

        with urlopen(
            request,
            timeout=TIMEOUT
        ) as response:

            content = response.read()

            charset = (
                response.headers
                .get_content_charset()
                or "utf-8"
            )

            return content.decode(
                charset,
                errors="ignore"
            )


    except HTTPError as e:

        log(
            f"网页 HTTP 错误 "
            f"{e.code}：{url}"
        )

    except URLError as e:

        log(
            f"网页连接失败："
            f"{e.reason}"
        )

    except Exception as e:

        log(
            f"网页读取失败："
            f"{e}"
        )


    return None


# ============================================================
# HTML 文本提取
# ============================================================

class TextParser(
    HTMLParser
):

    def __init__(self):

        super().__init__()

        self.parts = []

        self.links = []

        self.current_href = None


    def handle_starttag(
        self,
        tag,
        attrs
    ):

        attrs = dict(attrs)

        if tag.lower() == "a":

            href = attrs.get(
                "href"
            )

            self.current_href = href


    def handle_endtag(
        self,
        tag
    ):

        if tag.lower() == "a":

            self.current_href = None


    def handle_data(
        self,
        data
    ):

        text = data.strip()

        if not text:
            return


        self.parts.append(
            text
        )


        if self.current_href:

            self.links.append(
                self.current_href
            )


def parse_html(
    html
):

    parser = TextParser()

    parser.feed(
        html
    )

    text = "\n".join(
        parser.parts
    )

    return (
        text,
        parser.links
    )


# ============================================================
# 找识货商品页面
# ============================================================

def extract_shihuo_product_links(
    base_url,
    links
):

    results = set()


    for link in links:

        if not link:
            continue


        full_url = urljoin(
            base_url,
            link
        )


        parsed = urlparse(
            full_url
        )


        if parsed.netloc not in (
            "www.shihuo.cn",
            "shihuo.cn",
        ):
            continue


        if (
            "/page/pcGoodsDetail"
            in parsed.path
        ):

            results.add(
                full_url
            )


    return results


# ============================================================
# 识货搜索入口
#
# 这是公开网页，不调用内部接口。
# ============================================================

def shihuo_search_url(
    keyword,
    page
):

    return (
        "https://m.shihuo.cn/"
        "search/searchResult/goods?"
        "keywords="
        + quote(keyword)
        + "&page="
        + str(page)
        + "&pagesize=30"
    )


# ============================================================
# 数字
# ============================================================

def number(
    value
):

    if value is None:
        return None


    value = str(
        value
    )


    value = (
        value
        .replace(
            ",",
            ""
        )
        .replace(
            "¥",
            ""
        )
        .replace(
            "￥",
            ""
        )
        .strip()
    )


    match = re.search(
        r"\d+(?:\.\d+)?",
        value
    )


    if not match:
        return None


    try:

        return float(
            match.group(0)
        )

    except Exception:

        return None


# ============================================================
# 从识货商品页面提取价格
# ============================================================

def extract_price(
    text,
    platform
):

    platform_map = {

        "pinduoduo":
            "拼多多",

        "taobao":
            "淘宝",

        "tmall":
            "天猫",

        "jd":
            "京东",

        "dewu":
            "得物",

    }


    name = platform_map.get(
        platform
    )


    if not name:
        return None


    pattern = (
        re.escape(name)
        + r".{0,120}?"
        + r"(?:售价|价格)"
        + r".{0,30}?"
        + r"([0-9]+(?:\.[0-9]+)?)"
    )


    match = re.search(
        pattern,
        text,
        flags=re.S
    )


    if not match:
        return None


    return number(
        match.group(1)
    )


# ============================================================
# 商品名称
# ============================================================

def extract_product_name(
    text
):

    lines = [

        x.strip()

        for x in text.splitlines()

        if x.strip()

    ]


    if not lines:
        return None


    for line in lines[:30]:

        if (
            "商品名称" in line
            and "：" in line
        ):

            return line.split(
                "：",
                1
            )[1].strip()


    # 识货页面通常把商品标题放在前面。
    for line in lines[:20]:

        if (
            len(line) >= 6
            and "识货" not in line
            and "价格" not in line
            and "下载" not in line
        ):

            return line[:200]


    return None


# ============================================================
# 识货商品标准化
# ============================================================

def parse_shihuo_product(
    url,
    html
):

    text, _ = parse_html(
        html
    )


    name = extract_product_name(
        text
    )


    if not name:
        return None


    pdd = extract_price(
        text,
        "pinduoduo"
    )


    taobao = extract_price(
        text,
        "taobao"
    )


    tmall = extract_price(
        text,
        "tmall"
    )


    jd = extract_price(
        text,
        "jd"
    )


    dewu = extract_price(
        text,
        "dewu"
    )


    buy_prices = {}


    if pdd is not None:
        buy_prices[
            "pinduoduo"
        ] = pdd


    if taobao is not None:
        buy_prices[
            "taobao"
        ] = taobao


    if tmall is not None:
        buy_prices[
            "tmall"
        ] = tmall


    if jd is not None:
        buy_prices[
            "jd"
        ] = jd


    if not buy_prices and dewu is None:
        return None


    # 如果多个货源价格都存在，
    # 后面的风控程序仍然会再次判断。
    lowest_buy = (
        min(
            buy_prices.values()
        )
        if buy_prices
        else None
    )


    product = {

        "name":
            name,

        "buy_prices":
            buy_prices,

        "dewu_price":
            dewu,

        "recent_avg_price":
            None,

        "recent_trade_time":
            None,

        "seller_count":
            None,

        "days":
            None,

        "liquidity":
            None,

        "downside_loss":
            None,

        "authenticity_verified":
            False,

        "new_condition_verified":
            False,

        "dewu_check_compatible":
            False,

        "technical_service_fee":
            None,

        "technical_service_rate":
            None,

        "transfer_fee":
            None,

        "transfer_fee_rate":
            None,

        "operation_service_fee":
            None,

        "consumer_shipping_subsidy":
            None,

        "after_sales_service_fee":
            None,

        "seller_coupon_offset":
            None,

        "expected_income":
            None,

        "source_note":
            "识货公开商品页面",

        "data_source":
            "shihuo_public_web",

        "product_url":
            url,

        "data_time":
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "lowest_buy_price":
            lowest_buy,

    }


    return product


# ============================================================
# 读取旧数据
# ============================================================

def load_existing():

    if not OUTPUT_FILE.exists():
        return []


    try:

        with OUTPUT_FILE.open(
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(
                f
            )


        products = data.get(
            "products",
            []
        )


        if isinstance(
            products,
            list
        ):

            return products


    except Exception as e:

        log(
            f"读取旧数据失败："
            f"{e}"
        )


    return []


# ============================================================
# 商品合并
# ============================================================

def merge(
    old_products,
    new_products
):

    result = {}


    for product in (
        old_products
        + new_products
    ):

        name = product.get(
            "name"
        )


        if not name:
            continue


        key = (
            name
            .strip()
            .lower()
        )


        if key not in result:

            result[key] = product

            continue


        old = result[key]


        old_prices = old.setdefault(
            "buy_prices",
            {}
        )


        new_prices = product.get(
            "buy_prices",
            {}
        )


        for platform, price in (
            new_prices.items()
        ):

            if price is not None:

                old_prices[
                    platform
                ] = price


        for field in product:

            if field == "buy_prices":
                continue


            value = product[
                field
            ]


            if value is not None:

                old[field] = value


    return list(
        result.values()
    )


# ============================================================
# 保存
# ============================================================

def save(
    products
):

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(

            {
                "products":
                    products
            },

            f,

            ensure_ascii=False,

            indent=2

        )


# ============================================================
# 主程序
# ============================================================

def main():

    log("")
    log("=" * 60)
    log("自动公开商品浏览采集器")
    log("=" * 60)


    existing = load_existing()


    log(
        f"已有商品："
        f"{len(existing)} 条"
    )


    discovered_links = set()


    # --------------------------------------------------------
    # 第一阶段：
    # 访问公开搜索页面
    # --------------------------------------------------------

    for keyword in KEYWORDS:

        log(
            f"搜索公开商品："
            f"{keyword}"
        )


        for page in range(
            1,
            3
        ):

            url = shihuo_search_url(
                keyword,
                page
            )


            html = fetch_html(
                url
            )


            if not html:

                continue


            _, links = parse_html(
                html
            )


            links = (
                extract_shihuo_product_links(
                    url,
                    links
                )
            )


            discovered_links.update(
                links
            )


            log(
                f"  第 {page} 页发现："
                f"{len(links)} 个商品页面"
            )


            time.sleep(
                CRAWL_DELAY
            )


    # --------------------------------------------------------
    # 第二阶段：
    # 打开商品详情页
    # --------------------------------------------------------

    product_links = list(
        discovered_links
    )[
        :MAX_PRODUCT_PAGES
    ]


    log("")
    log(
        f"准备读取商品详情："
        f"{len(product_links)} 个"
    )


    new_products = []


    for index, url in enumerate(
        product_links,
        start=1
    ):

        log(
            f"[{index}/"
            f"{len(product_links)}] "
            f"{url}"
        )


        html = fetch_html(
            url
        )


        if not html:

            continue


        product = (
            parse_shihuo_product(
                url,
                html
            )
        )


        if product:

            new_products.append(
                product
            )


            log(
                "  已取得："
                + product["name"]
            )


        time.sleep(
            CRAWL_DELAY
        )


    # --------------------------------------------------------
    # 第三阶段：
    # 合并
    # --------------------------------------------------------

    log("")

    log(
        f"本次获得商品："
        f"{len(new_products)} 条"
    )


    if not new_products:

        log(
            "没有取得新的真实公开商品数据"
        )

        log(
            "保留原有数据"
        )

        save(
            existing
        )

        return


    merged = merge(
        existing,
        new_products
    )


    save(
        merged
    )


    log(
        f"合并后商品："
        f"{len(merged)} 条"
    )


    log("=" * 60)

    log(
        "自动公开商品采集完成"
    )


if __name__ == "__main__":

    main()
