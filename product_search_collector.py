import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


OUTPUT_FILE = Path("market_data_input.json")

TIMEOUT = 20


# ============================================================
# 中国大陆商品数据源
#
# 不绕过登录
# 不绕过验证码
# 不破解签名
# 不抓取受限制接口
#
# 后续只把获得官方授权的数据接口地址配置进来即可。
# ============================================================

SOURCE_CONFIG = [

    {
        "name": "识货",
        "env": "SHIHUO_API_URL",
        "platform": "shihuo",
    },

    {
        "name": "京东",
        "env": "JD_API_URL",
        "platform": "jd",
    },

    {
        "name": "淘宝天猫",
        "env": "TAOBAO_API_URL",
        "platform": "taobao",
    },

    {
        "name": "拼多多",
        "env": "PDD_API_URL",
        "platform": "pinduoduo",
    },

]


# ============================================================
# 搜索关键词
# ============================================================

KEYWORDS = [

    "Nike 运动鞋",
    "Nike 球鞋",
    "adidas 运动鞋",
    "adidas 球鞋",
    "New Balance 运动鞋",
    "ASICS 运动鞋",
    "PUMA 运动鞋",
    "潮鞋",
    "运动鞋",
    "服饰",
    "潮流服饰",
    "包袋",

]


def log(message):

    print(
        message,
        flush=True
    )


# ============================================================
# HTTP JSON
# ============================================================

def fetch_json(
    url,
    keyword=None
):

    if not url:
        return None

    if not url.startswith(
        (
            "http://",
            "https://"
        )
    ):
        log(
            "数据源地址不是 HTTP/HTTPS，跳过"
        )

        return None

    params = {}

    if keyword:

        params["keyword"] = keyword

    if params:

        separator = (
            "&"
            if "?" in url
            else "?"
        )

        url = (
            url
            + separator
            + urlencode(params)
        )

    request = Request(

        url,

        headers={

            "User-Agent":
                "dewu-flip-monitor/1.0",

            "Accept":
                "application/json",

        },

        method="GET",

    )

    try:

        with urlopen(
            request,
            timeout=TIMEOUT
        ) as response:

            content = response.read()

            return json.loads(
                content.decode(
                    "utf-8"
                )
            )

    except HTTPError as e:

        log(
            f"HTTP错误：{e.code}"
        )

    except URLError as e:

        log(
            f"连接失败：{e.reason}"
        )

    except Exception as e:

        log(
            f"读取数据失败：{e}"
        )

    return None


# ============================================================
# 从不同 JSON 结构中寻找商品
# ============================================================

def extract_items(data):

    if isinstance(
        data,
        list
    ):

        return data


    if not isinstance(
        data,
        dict
    ):

        return []


    possible_keys = [

        "products",
        "items",
        "goods",
        "list",
        "result",

    ]


    for key in possible_keys:

        value = data.get(key)

        if isinstance(
            value,
            list
        ):

            return value


    data_value = data.get(
        "data"
    )


    if isinstance(
        data_value,
        list
    ):

        return data_value


    if isinstance(
        data_value,
        dict
    ):

        for key in possible_keys:

            value = data_value.get(
                key
            )

            if isinstance(
                value,
                list
            ):

                return value


    return []


# ============================================================
# 数字处理
# ============================================================

def number(value):

    if value is None:

        return None


    if isinstance(
        value,
        (int, float)
    ):

        return float(value)


    text = str(
        value
    ).strip()


    if not text:

        return None


    text = (

        text
        .replace("¥", "")
        .replace("￥", "")
        .replace(",", "")
        .strip()

    )


    try:

        return float(
            text
        )

    except ValueError:

        return None


# ============================================================
# 获取字段
# ============================================================

def first_value(
    item,
    keys
):

    for key in keys:

        value = item.get(
            key
        )

        if value is not None:

            return value


    return None


# ============================================================
# 标准化商品
# ============================================================

def normalize(
    item,
    platform,
    source_name
):

    if not isinstance(
        item,
        dict
    ):

        return None


    name = first_value(

        item,

        [
            "name",
            "title",
            "product_name",
            "goods_name",
            "goodsName",
            "item_name",
        ],

    )


    if not name:

        return None


    buy_price = first_value(

        item,

        [
            "buy_price",
            "source_price",
            "lowest_price",
            "sale_price",
            "price",
            "goods_price",
            "item_price",
        ],

    )


    dewu_price = first_value(

        item,

        [
            "dewu_price",
            "dewuPrice",
            "market_price",
            "sell_price",
        ],

    )


    seller_count = first_value(

        item,

        [
            "seller_count",
            "sellerCount",
        ],

    )


    product_url = first_value(

        item,

        [
            "url",
            "product_url",
            "item_url",
            "goods_url",
        ],

    )


    product = {

        "name":
            str(name),

        "buy_prices": {

            platform:
                number(
                    buy_price
                )

        },

        "dewu_price":
            number(
                dewu_price
            ),

        "recent_avg_price":
            number(
                first_value(
                    item,
                    [
                        "recent_avg_price",
                        "recentAvgPrice",
                    ]
                )
            ),

        "recent_trade_time":
            first_value(
                item,
                [
                    "recent_trade_time",
                    "recentTradeTime",
                ]
            ),

        "seller_count":
            number(
                seller_count
            ),

        "days":
            number(
                first_value(
                    item,
                    [
                        "days",
                        "turnover_days",
                    ]
                )
            ),

        "liquidity":
            first_value(
                item,
                [
                    "liquidity",
                ]
            ),

        "downside_loss":
            number(
                first_value(
                    item,
                    [
                        "downside_loss",
                        "downsideLoss",
                    ]
                )
            ),

        "authenticity_verified":
            bool(
                item.get(
                    "authenticity_verified",
                    False
                )
            ),

        "new_condition_verified":
            bool(
                item.get(
                    "new_condition_verified",
                    False
                )
            ),

        "dewu_check_compatible":
            bool(
                item.get(
                    "dewu_check_compatible",
                    False
                )
            ),

        "technical_service_fee":
            number(
                item.get(
                    "technical_service_fee"
                )
            ),

        "technical_service_rate":
            number(
                item.get(
                    "technical_service_rate"
                )
            ),

        "transfer_fee":
            number(
                item.get(
                    "transfer_fee"
                )
            ),

        "transfer_fee_rate":
            number(
                item.get(
                    "transfer_fee_rate"
                )
            ),

        "operation_service_fee":
            number(
                item.get(
                    "operation_service_fee"
                )
            ),

        "consumer_shipping_subsidy":
            number(
                item.get(
                    "consumer_shipping_subsidy"
                )
            ),

        "after_sales_service_fee":
            number(
                item.get(
                    "after_sales_service_fee"
                )
            ),

        "seller_coupon_offset":
            number(
                item.get(
                    "seller_coupon_offset"
                )
            ),

        "expected_income":
            number(
                item.get(
                    "expected_income"
                )
            ),

        "source_note":
            (
                f"{source_name}"
                "商品数据"
            ),

        "data_source":
            platform,

        "product_url":
            product_url,

        "data_time":
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

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

            data = json.load(f)


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
            f"读取旧数据失败：{e}"
        )


    return []


# ============================================================
# 合并商品
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


            value = product[field]


            if value is not None:

                old[field] = value


    return list(
        result.values()
    )


# ============================================================
# 保存
# ============================================================

def save(products):

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

    log(
        "中国大陆商品数据采集器"
    )

    log("=" * 60)


    existing = load_existing()


    log(
        f"现有商品："
        f"{len(existing)} 条"
    )


    new_products = []


    configured_sources = 0


    for source in SOURCE_CONFIG:

        source_name = source[
            "name"
        ]

        env_name = source[
            "env"
        ]

        platform = source[
            "platform"
        ]


        url = os.getenv(
            env_name,
            ""
        ).strip()


        if not url:

            log(
                f"{source_name}："
                "暂未配置授权数据接口"
            )

            continue


        configured_sources += 1


        log("")

        log(
            f"开始采集："
            f"{source_name}"
        )


        for keyword in KEYWORDS:

            log(
                f"  搜索："
                f"{keyword}"
            )


            data = fetch_json(
                url,
                keyword
            )


            if data is None:

                continue


            items = extract_items(
                data
            )


            log(
                f"  返回商品："
                f"{len(items)} 条"
            )


            for item in items:

                product = normalize(

                    item,

                    platform,

                    source_name

                )


                if product:

                    new_products.append(
                        product
                    )


            time.sleep(1)


    log("")

    log(
        f"已配置数据源："
        f"{configured_sources}"
    )


    log(
        f"本次新增商品："
        f"{len(new_products)} 条"
    )


    # ========================================================
    # 没有真实数据时绝对不能清空旧数据
    # ========================================================

    if not new_products:

        log(
            "没有获得新的真实商品数据"
        )

        log(
            "保留现有商品数据"
        )

        save(existing)

        log(
            "本次不会覆盖旧数据"
        )

        return


    merged = merge(

        existing,

        new_products

    )


    save(
        merged
    )


    log("")

    log(
        f"合并后商品："
        f"{len(merged)} 条"
    )


    log("=" * 60)

    log(
        "商品采集完成"
    )


if __name__ == "__main__":

    main()
