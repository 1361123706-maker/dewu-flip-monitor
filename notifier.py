import hashlib
import html
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

RESULT_FILE = "monitor_results.json"
STATE_FILE = "notification_state.json"
PUSHPLUS_URL = "https://www.pushplus.plus/send"
STATE_DAYS = 7
MAX_CANDIDATES_PER_MESSAGE = 20

def money(value):
    try:
        return f"¥{float(value):.2f}"
    except Exception:
        return "—"

def text(value, default="—"):
    if value is None:
        return default
    value = str(value).strip()
    return value if value else default

def escape(value):
    return html.escape(text(value))

def link(label, url):
    if not url:
        return escape(label)
    return f'<a href="{html.escape(str(url), quote=True)}">{escape(label)}</a>'

def fingerprint(item):
    raw = "|".join([
        text(item.get("product_code"), ""),
        text(item.get("color"), ""),
        text(item.get("sku_size"), ""),
        text(item.get("buy_price"), ""),
        text(item.get("dewu_price"), ""),
        text(item.get("buy_url"), ""),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def load_state():
    path = Path(STATE_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_state(state):
    Path(STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def clean_state(state):
    cutoff = datetime.now(timezone.utc) - timedelta(days=STATE_DAYS)
    cleaned = {}
    for key, value in state.items():
        try:
            sent_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if sent_at >= cutoff:
                cleaned[key] = value
        except Exception:
            continue
    return cleaned

def load_candidates():
    path = Path(RESULT_FILE)
    if not path.exists():
        print(f"找不到 {RESULT_FILE}，跳过通知。")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"读取 {RESULT_FILE} 失败：{exc}")
        return []
    candidates = data.get("candidates") or []
    if not isinstance(candidates, list):
        return []
    result = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        grade = item.get("grade")
        try:
            profitable = float(item.get("estimated_profit")) >= 15 and float(item.get("profit_rate")) >= 12
        except Exception:
            profitable = False
        if grade in {"A", "B"} and profitable:
            result.append(item)
    return result

def build_item_html(item):
    coupon_urls = item.get("coupon_urls") or item.get("all_coupon_urls") or []
    if not isinstance(coupon_urls, list):
        coupon_urls = [coupon_urls]
    coupon_links = [
        link(f"优惠/领券 {index}", url)
        for index, url in enumerate(coupon_urls[:8], 1)
        if isinstance(url, str) and url.startswith(("http://", "https://"))
    ]
    buy_url = item.get("buy_url")
    dewu_url = item.get("dewu_url") or item.get("dewu_link") or item.get("shihuo_url")
    lines = [
        f"<b>{escape(item.get('grade'))}｜{escape(item.get('name'))}</b>",
        f"货号：{escape(item.get('product_code'))}　颜色：{escape(item.get('color'))}",
        f"尺码：{escape(item.get('sku_size'))}",
        f"买入：<b>{money(item.get('buy_price'))}</b>",
        f"得物售价：<b>{money(item.get('dewu_price'))}</b>",
        f"预计净利润：<b>{money(item.get('estimated_profit'))}</b>　利润率：<b>{text(item.get('profit_rate'))}%</b>",
        f"7日低/高：{money(item.get('price_7d_low'))} / {money(item.get('price_7d_high'))}",
        f"当前距7日低点：{text(item.get('downside_to_7d_low'))}%",
        f"销量/周转：{escape(item.get('turnover_evidence'))}",
        f"活动状态：{escape(item.get('promotion_status'))}",
    ]
    lines.append("优惠：" + "　".join(coupon_links) if coupon_links else "优惠：本轮未发现可直接点击的优惠链接")
    if buy_url:
        lines.append("购买：" + link("打开购买链接", buy_url))
    if dewu_url:
        lines.append("得物：" + link("打开识货/得物链接", dewu_url))
    risks = item.get("hard_risks") or []
    lines.append("风险：" + escape("；".join(map(str, risks))) if risks else "风险：未触发硬风险")
    return "<br>".join(lines)

def send_pushplus(token, title, content):
    payload = {
        "token": token,
        "title": title,
        "content": content,
        "template": "html",
        "channel": "wechat",
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(PUSHPLUS_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        result = json.loads(raw)
    except Exception:
        raise RuntimeError(f"PushPlus 返回非 JSON：{raw[:500]}")
    return result

def main():
    token = os.getenv("PUSHPLUS_TOKEN", "").strip()
    candidates = load_candidates()
    print(f"A/B 盈利候选：{len(candidates)}")

    if not token:
        print("未配置 PUSHPLUS_TOKEN：跳过通知，本轮监控视为成功。")
        return

    state = clean_state(load_state())
    now = datetime.now(timezone.utc).isoformat()
    new_candidates = []
    for item in candidates:
        key = fingerprint(item)
        if key not in state:
            new_candidates.append((key, item))

    print(f"待发送新机会：{len(new_candidates)}")
    if not new_candidates:
        save_state(state)
        print("没有新的盈利机会，不重复发送。")
        return

    batch = new_candidates[:MAX_CANDIDATES_PER_MESSAGE]
    header = (
        f"<h2>🔥 得物套利新机会：{len(batch)} 个</h2>"
        "<p>仅展示通过 A/B 风控且满足利润 ≥ ¥15、利润率 ≥ 12% 的机会。</p>"
    )
    blocks = [
        f"<hr><b>#{index}</b><br>{build_item_html(item)}"
        for index, (_, item) in enumerate(batch, 1)
    ]
    footer = "<hr><small>生成时间：" + html.escape(datetime.now().strftime("%Y-%m-%d %H:%M:%S")) + "</small>"

    try:
        result = send_pushplus(token, f"🔥 得物套利机会 {len(batch)} 个", header + "".join(blocks) + footer)
        if result.get("code") != 200:
            print(f"PushPlus 暂未发送：{result}")
            print("通知失败不会让监控任务失败，盈利结果仍已保存。")
            return
    except Exception as exc:
        print(f"PushPlus 通知异常：{exc}")
        print("通知失败不会让监控任务失败，盈利结果仍已保存。")
        return

    for key, _ in batch:
        state[key] = now
    save_state(state)
    print(f"微信通知发送成功：{len(batch)} 个。")
    if len(new_candidates) > len(batch):
        print(f"还有 {len(new_candidates) - len(batch)} 个新机会未发送，将等待下一轮。")

if __name__ == "__main__":
    main()
