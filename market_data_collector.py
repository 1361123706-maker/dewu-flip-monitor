#!/usr/bin/env python3

"""
市场数据采集接口

作用：
1. 从合法的数据接口获取商品行情
2. 统一转换成监控系统格式
3. 把得物卖出费用拆开保存
4. 不猜测缺失数据
5. 不绕过登录、验证码、签名、加密或反爬

注意：
真正的数据接口地址通过 GitHub Secrets / 环境变量提供。
不要把 API Key 写进代码。
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


ROOT = Path(__file__).resolve().parent

OUTPUT_FILE = ROOT / "market_data_input.json"


# ============================================================
# 环境变量
# ============================================================

DEWU_API_URL = os.getenv("DEWU_API_URL", "").strip()
SHIHUO_API_URL = os.getenv("SHIHUO_API_URL", "").strip()

DEWU_API_KEY = os.getenv("DEWU_API_KEY", "").strip()
SHIHUO_API_KEY = os.getenv("SHIHUO_API_KEY", "").strip()


# ============================================================
# 基础工具
# ============================================================

def to_number(value):
    """
    转换成数字。
    无法确认时返回 None。
    """

    if value is None or value == "":
        return None

    try:
        return float(value)

    except (TypeError, ValueError):
        return None


def to_bool(value):
    """
    转换布尔值。
    无法确认时返回 False。
    """

    if value is True:
        return True

    if value in (1, "1", "true", "True", "是", "已确认"):
        return True

    return False


def fetch_json(url, api_key=""):
    """
    从合法 HTTP API 获取 JSON。

    不处理：
    - 验证码
    - 登录绕过
    - 签名破解
    - 加密破解
    - 反爬绕过
    """

    if not url:
        return None

    headers = {
        "User-Agent": "dewu-flip-monitor/1.0",
        "Accept": "application/json",
    }

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = Request(
        url,
        headers=headers,
        method="GET"
    )

    try:

        with urlopen(
            request,
            timeout=20
        ) as response:

            data = response.read()

        return json.loads(
            data.decode("utf-8")
        )

    except HTTPError as e:

        print(
            f"接口 HTTP 错误："
            f"{e.code} {url}"
        )

    except URLError as e:

        print(
            f"接口连接失败："
            f"{url} / {e}"
        )

    except Exception as e:

        print(
            f"接口读取失败："
            f"{url} / {e}"
        )

    return None


# ============================================================
# 得物数据标准化
# ============================================================

def normalize_dewu(item):
    """
    把得物接口返回的数据转换成统一格式。

    不同接口字段名称可能不同，
    所以这里只接受明确存在的数据。
    """

    if not isinstance(item, dict):
        return None

    name = (
        item.get("name")
        or item.get("product_name")
        or item.get("title")
        or ""
    )

    name = str(name).strip()

    if not name:
        return None


    # --------------------------------------------------------
    # 出售价格
    # --------------------------------------------------------

    dewu_price = to_number(
        item.get("dewu_price")
        or item.get("sale_price")
        or item.get("price")
    )


    # --------------------------------------------------------
    # 最近成交
    # --------------------------------------------------------

    recent_avg_price = to_number(
        item.get("recent_avg_price")
        or item.get("recent_trade_price")
        or item.get("average_trade_price")
    )

    recent_trade_time = (
        item.get("recent_trade_time")
        or item.get("last_trade_time")
    )


    # --------------------------------------------------------
    # 市场数量
    # --------------------------------------------------------

    seller_count = to_number(
        item.get("seller_count")
        or item.get("bid_count")
        or item.get("merchant_count")
    )


    # --------------------------------------------------------
    # 周转
    # --------------------------------------------------------

    days = to_number(
        item.get("days")
        or item.get("turnover_days")
        or item.get("estimated_days")
    )


    # --------------------------------------------------------
    # 下跌风险
    # --------------------------------------------------------

    downside_loss = to_number(
        item.get("downside_loss")
        or item.get("estimated_downside_loss")
    )


    # --------------------------------------------------------
    # 得物实际卖出费用
    # --------------------------------------------------------

    technical_service_fee = to_number(
        item.get("technical_service_fee")
    )

    transfer_fee = to_number(
        item.get("transfer_fee")
    )

    operation_service_fee = to_number(
        item.get("operation_service_fee")
    )

    consumer_shipping_subsidy = to_number(
        item.get("consumer_shipping_subsidy")
    )

    after_sales_service_fee = to_number(
        item.get("after_sales_service_fee")
    )

    seller_coupon_offset = to_number(
        item.get("seller_coupon_offset")
    )


    # --------------------------------------------------------
    # 得物预计收入
    # --------------------------------------------------------

    expected_income = to_number(
        item.get("expected_income")
    )


    # --------------------------------------------------------
    # 商品状态
    # --------------------------------------------------------

    authenticity_verified = to_bool(
        item.get("authenticity_verified")
    )

    new_condition_verified = to_bool(
        item.get("new_condition_verified")
    )

    dewu_check_compatible = to_bool(
        item.get("dewu_check_compatible")
    )


    return {

        "name": name,

        "buy_prices": {},

        "dewu_price": dewu_price,

        "recent_avg_price":
            recent_avg_price,

        "recent_trade_time":
            recent_trade_time,

        "seller_count":
            seller_count,

        "days":
            days,

        "liquidity":
            item.get("liquidity"),

        "downside_loss":
            downside_loss,


        # ================================================
        # 得物真实费用
        # ================================================

        "technical_service_fee":
            technical_service_fee,

        "technical_service_rate":
            to_number(
                item.get(
                    "technical_service_rate"
                )
            ),

        "transfer_fee":
            transfer_fee,

        "transfer_fee_rate":
            to_number(
                item.get(
                    "transfer_fee_rate"
                )
            ),

        "operation_service_fee":
            operation_service_fee,

        "consumer_shipping_subsidy":
            consumer_shipping_subsidy,

        "after_sales_service_fee":
            after_sales_service_fee,

        "seller_coupon_offset":
            seller_coupon_offset,

        "expected_income":
            expected_income,


        # ================================================
        # 商品状态
        # ================================================

        "authenticity_verified":
            authenticity_verified,

        "new_condition_verified":
            new_condition_verified,

        "dewu_check_compatible":
            dewu_check_compatible,


        # ================================================
        # 来源
        # ================================================

        "source_note":
            item.get(
                "source_note",
                "来自合法数据接口"
            ),

        "data_source":
            item.get(
                "data_source",
                "api"
            ),

        "data_time":
            datetime.now(
                timezone.utc
            ).isoformat()

    }


# ============================================================
# 识货数据标准化
# ============================================================

def normalize_shihuo(item):
    """
    把识货接口返回的数据转换成统一格式。
    """

    if not isinstance(item, dict):
        return None

    name = (
        item.get("name")
        or item.get("product_name")
        or item.get("title")
        or ""
    )

    name = str(name).strip()

    if not name:
        return None


    buy_price = to_number(
        item.get("buy_price")
        or item.get("price")
        or item.get("lowest_price")
    )

    return {

        "name": name,

        "buy_prices": {

            "识货":
                buy_price

        } if buy_price is not None else {},

        "dewu_price":
            to_number(
                item.get("dewu_price")
            ),

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

        "authenticity_verified":
            to_bool(
                item.get(
                    "authenticity_verified"
                )
            ),

        "new_condition_verified":
            to_bool(
                item.get(
                    "new_condition_verified"
                )
            ),

        "dewu_check_compatible":
            False,

        "source_note":
            item.get(
                "source_note",
                "来自识货合法数据接口"
            ),

        "data_source":
            "shihuo_api",

        "data_time":
            datetime.now(
                timezone.utc
            ).isoformat()

    }


# ============================================================
# 合并数据
# ============================================================

def merge_product(old, new):
    """
    同一个商品来自多个平台时进行合并。

    已确认的数据优先。
    空数据不会覆盖已有数据。
    """

    result = dict(old)

    for key, value in new.items():

        if value is None:
            continue

        if value == "":
            continue

        if key == "buy_prices":

            result.setdefault(
                "buy_prices",
                {}
            )

            result["buy_prices"].update(
                value
            )

            continue

        result[key] = value

    return result


# ============================================================
# 主程序
# ============================================================

def main():

    print()
    print("=" * 60)
    print("       市场数据接口采集程序")
    print("=" * 60)


    products = {}


    # ========================================================
    # 读取得物接口
    # ========================================================

    if DEWU_API_URL:

        print("正在读取得物合法数据接口...")

        data = fetch_json(
            DEWU_API_URL,
            DEWU_API_KEY
        )

        if data:

            items = data.get(
                "products",
                data if isinstance(
                    data,
                    list
                ) else []
            )

            if isinstance(
                items,
                dict
            ):
                items = [items]

            for item in items:

                product = normalize_dewu(
                    item
                )

                if not product:
                    continue

                name = product["name"]

                products[name] = merge_product(
                    products.get(
                        name,
                        {}
                    ),
                    product
                )

            print(
                f"得物接口读取："
                f"{len(items)} 条"
            )

        else:

            print(
                "得物接口暂时没有返回有效数据"
            )

    else:

        print(
            "未配置 DEWU_API_URL，"
            "跳过得物接口"
        )


    # ========================================================
    # 读取识货接口
    # ========================================================

    if SHIHUO_API_URL:

        print("正在读取识货合法数据接口...")

        data = fetch_json(
            SHIHUO_API_URL,
            SHIHUO_API_KEY
        )

        if data:

            items = data.get(
                "products",
                data if isinstance(
                    data,
                    list
                ) else []
            )

            if isinstance(
                items,
                dict
            ):
                items = [items]

            for item in items:

                product = normalize_shihuo(
                    item
                )

                if not product:
                    continue

                name = product["name"]

                products[name] = merge_product(
                    products.get(
                        name,
                        {}
                    ),
                    product
                )

            print(
                f"识货接口读取："
                f"{len(items)} 条"
            )

        else:

            print(
                "识货接口暂时没有返回有效数据"
            )

    else:

        print(
            "未配置 SHIHUO_API_URL，"
            "跳过识货接口"
        )


    # ========================================================
    # 保存
    # ========================================================

    result = {

        "products":
            list(
                products.values()
            )

    }

    OUTPUT_FILE.write_text(

        json.dumps(
            result,
            ensure_ascii=False,
            indent=2
        ),

        encoding="utf-8"

    )


    print()
    print(
        f"最终标准化商品："
        f"{len(products)}"
    )

    print(
        f"已写入："
        f"{OUTPUT_FILE.name}"
    )

    print("=" * 60)


if __name__ == "__main__":

    main()
