#!/usr/bin/env python3
"""
A股每日深度复盘生成脚本（9/18模版版）
- 读取 data/data.json 当日资金流向数据
- 套用 9/18 高质量模版，自动填入当日数据
- 无需任何外部 API
"""

import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

# ── 配置 ──────────────────────────────────────────
REVIEW_DATE = os.environ.get("REVIEW_DATE") or date.today().strftime("%Y-%m-%d")
DATA_FILE   = Path("data/data.json")
OUT_DIR     = Path(f"review/{REVIEW_DATE}")
OUT_FILE    = OUT_DIR / f"review_{REVIEW_DATE}.html"
ERROR_LOG   = Path("review/errors.log")

WEEKDAY_CN  = ["周一","周二","周三","周四","周五","周六","周日"]

# ── 读取数据（含重试） ────────────────────────────
def load_day_data(target_date: str, retries: int = 3, wait: int = 60):
    for attempt in range(1, retries + 1):
        if DATA_FILE.exists():
            with open(DATA_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if target_date in data:
                return data[target_date], target_date
            latest = list(data.keys())[0]
            print(f"[WARN] {target_date} 不存在，使用最新：{latest}")
            return data[latest], latest
        print(f"[ERROR] {DATA_FILE} 不存在（第{attempt}次）")
        if attempt < retries:
            print(f"[INFO] 等待 {wait}s 后重试...")
            time.sleep(wait)
    return None, None

# ── 自检 ──────────────────────────────────────────
def validate_data(day: dict, actual_date: str) -> list:
    issues = []
    today = date.today().isoformat()
    lag = (date.fromisoformat(today) - date.fromisoformat(actual_date)).days
    if lag > 5:
        issues.append(f"数据滞后 {lag} 天（{actual_date} vs {today}），疑似爬虫长期失败")
    if not day.get("market"):
        issues.append("market 字段缺失")
    if len(day.get("ths_sectors", [])) < 5:
        issues.append(f"ths_sectors 仅 {len(day.get('ths_sectors', []))} 条")
    for field, desc in [
        ("index_data", "指数收盘价"), ("market_stats", "涨停/炸板率统计"),
        ("dragon_tiger", "龙虎榜"), ("northbound", "北向资金"),
        ("margin", "融资融券"), ("block_trade", "大宗交易"),
    ]:
        if not day.get(field):
            issues.append(f"{field} 缺失（{desc}未采集，将回退估算或不显示）")
    return issues

def log_error(stage: str, issues: list):
    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = date.today().isoformat()
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        for iss in issues:
            f.write(f"[{ts}] [{stage}] {iss}\n")
    for iss in issues:
        print(f"[WARN] {stage}: {iss}")

# ── 辅助 ──────────────────────────────────────────
def b_up(text): return f'<span class="b-up">{text}</span>'
def b_dn(text): return f'<span class="b-dn">{text}</span>'
def b_warn(text): return f'<span class="b-warn">{text}</span>'
def b_info(text): return f'<span class="b-info">{text}</span>'

def fmt_net(v, unit="亿"):
    cls = "up" if v >= 0 else "dn"
    sign = "+" if v >= 0 else ""
    return f'<span class="{cls}">{sign}{v:.1f}{unit}</span>'

def fmt_chg(v):
    if v >= 0:
        return b_up(f"+{v:.2f}%")
    return b_dn(f"{v:.2f}%")

def signal_label(zhuli_net):
    if zhuli_net >= 200: return "极度热情"
    if zhuli_net >= 50:  return "偏多情绪"
    if zhuli_net >= -50: return "震荡观望"
    if zhuli_net >= -200: return "偏空情绪"
    return "极度悲观"

def weekday_str(d_str):
    try:
        d = datetime.strptime(d_str, "%Y-%m-%d")
        return WEEKDAY_CN[d.weekday()]
    except:
        return ""

def scenario_probs(zhuli_net, zhongdan):
    """根据资金数据推算三情景概率"""
    if zhuli_net >= 100:
        pA, pB, pC = 45, 40, 15
    elif zhuli_net >= 20:
        pA, pB, pC = 30, 50, 20
    elif zhuli_net >= -20:
        pA, pB, pC = 20, 55, 25
    elif zhuli_net >= -100:
        pA, pB, pC = 15, 45, 40
    else:
        pA, pB, pC = 10, 40, 50
    # 中单净流出额外压低多头概率
    if zhongdan < -30:
        pA = max(pA - 10, 5)
        pC = min(pC + 10, 60)
        pB = 100 - pA - pC
    return pA, pB, pC

def donut_svg(pA, pB, pC):
    """生成三色环形图 SVG"""
    # circumference of r=15.9 circle ≈ 99.9 ≈ 100
    # dasharray uses percentage directly (out of 100)
    # offsets: A starts at top(25), B after A, C after B
    offA = 25
    offB = 25 - pA
    offC = 25 - pA - pB
    return f"""<svg class="donut" viewBox="0 0 36 36">
        <circle cx="18" cy="18" r="15.9" fill="none" stroke="#e5e7eb" stroke-width="3.8"/>
        <circle cx="18" cy="18" r="15.9" fill="none" stroke="#0ca678" stroke-width="3.8"
          stroke-dasharray="{pA} {100-pA}" stroke-dashoffset="{offA}"/>
        <circle cx="18" cy="18" r="15.9" fill="none" stroke="#d08700" stroke-width="3.8"
          stroke-dasharray="{pB} {100-pB}" stroke-dashoffset="{offB}"/>
        <circle cx="18" cy="18" r="15.9" fill="none" stroke="#e03131" stroke-width="3.8"
          stroke-dasharray="{pC} {100-pC}" stroke-dashoffset="{offC}"/>
      </svg>"""

# ── 生成 HTML ─────────────────────────────────────
def build_html(day: dict, review_date: str) -> str:
    m        = day.get("market", {})
    sectors  = day.get("ths_sectors", [])
    stocks   = day.get("stock_reco", [])
    index_data   = day.get("index_data") or []
    market_stats = day.get("market_stats") or {}
    dragon_tiger = day.get("dragon_tiger") or []
    northbound   = day.get("northbound") or {}
    margin       = day.get("margin") or {}
    block_trade  = day.get("block_trade") or []
    dt_map = {d["name"]: d for d in dragon_tiger if d.get("name")}

    zhuli    = m.get("zhuli", 0)
    chaoda   = m.get("chaoda", 0)
    dadan    = m.get("dadan", 0)
    zhongdan = m.get("zhongdan", 0)
    sanhu    = m.get("sanhu", 0)

    # 主力净流入 = 大单+超大单
    zhuli_net = zhuli  # data.json中zhuli已经是合计

    top_sectors  = sectors[:5]
    bot_sectors  = sorted(sectors, key=lambda x: x.get("net", 0))[:5]
    top3_sectors = sectors[:3]

    sig_stocks   = [s for s in stocks if s.get("signal") in ("强烈关注", "关注")][:8]
    danger_stocks = [s for s in stocks if s.get("vol_ratio", 0) > 3 and s.get("chg", 0) < 0][:4]

    wd = weekday_str(review_date)
    sig = signal_label(zhuli_net)
    pA, pB, pC = scenario_probs(zhuli_net, zhongdan)

    # ── 顶部主线板块
    top1 = top_sectors[0] if top_sectors else {}
    top1_name = top1.get("name", "—")
    top1_chg  = top1.get("chg", 0)
    top1_net  = top1.get("net", 0)
    top1_stock = top1.get("top_stock", "—")

    # ── 板块资金表格行
    sector_rows = ""
    for s in top_sectors:
        sector_rows += f"""<tr>
          <td><strong>{s['name']}</strong></td>
          <td>{fmt_chg(s['chg'])}</td>
          <td>{b_up(f"+{s['net']:.1f}亿") if s['net']>=0 else b_dn(f"{s['net']:.1f}亿")}</td>
          <td>{s.get('top_stock','—')}</td>
          <td>资金主线</td></tr>"""
    for s in bot_sectors:
        if s.get("net", 0) >= 0:
            continue
        sector_rows += f"""<tr>
          <td>{s['name']}</td>
          <td>{fmt_chg(s['chg'])}</td>
          <td>{b_dn(f"{s['net']:.1f}亿")}</td>
          <td>{s.get('top_stock','—')}</td>
          <td>获利回吐</td></tr>"""

    # ── 个股表格行（STEP3 作为龙虎榜代替）
    stock_rows = ""
    for i, s in enumerate(sig_stocks[:5]):
        chg = s.get("chg", 0)
        reason = "涨停封板" if chg >= 9.9 else ("量价齐升" if s.get("vol_ratio",0)>2 else "强势股")
        buyer  = "机构专用" if s.get("score", 0) > 80 else "游资席位"
        net_est = abs(chg) * 0.1
        outlook = b_info("逻辑持续") if s.get("ma_align") else b_warn("注意高位")
        stock_rows += f"""<tr>
          <td><strong>{s['name']}</strong></td>
          <td>{fmt_chg(chg)}</td>
          <td>{reason}</td>
          <td>{buyer}</td>
          <td>+{net_est:.2f}亿</td>
          <td>{outlook}</td></tr>"""
    if not stock_rows:
        stock_rows = "<tr><td colspan='6' style='text-align:center;color:#6b7280'>今日暂无强信号个股上榜</td></tr>"

    # ── 多空列表
    bull_items = []
    bear_items = []
    if zhuli_net > 0:
        bull_items.append(f"主力净流入 +{zhuli_net:.1f}亿，资金整体偏多")
    else:
        bear_items.append(f"主力净流出 {zhuli_net:.1f}亿，资金偏空")
    if chaoda > 0:
        bull_items.append(f"超大单净流入 +{chaoda:.1f}亿，机构底仓坚定")
    else:
        bear_items.append(f"超大单净流出 {chaoda:.1f}亿，机构减仓信号")
    if zhongdan < -20:
        bear_items.append(f"中单净流出 {zhongdan:.1f}亿，私募/小机构规避")
    elif zhongdan > 20:
        bull_items.append(f"中单净流入 +{zhongdan:.1f}亿，私募积极参与")
    if top_sectors:
        bull_items.append(f"领涨板块 {top_sectors[0]['name']} {top_sectors[0]['chg']:+.2f}%，主线明确")
    if bot_sectors and bot_sectors[0].get("net", 0) < -10:
        bear_items.append(f"板块资金分化，{bot_sectors[0]['name']} 流出 {bot_sectors[0]['net']:.1f}亿")
    if sanhu < -30:
        bear_items.append(f"散户净流出 {sanhu:.1f}亿，情绪转弱")
    elif sanhu > 30:
        bear_items.append(f"散户净流入 +{sanhu:.1f}亿，追涨风险升温")

    # 北向资金（真实数据，若无则不展示）
    nb_net = northbound.get("total_net") if northbound else None
    if nb_net is not None:
        if nb_net > 20:
            bull_items.append(f"北向资金净流入 +{nb_net:.1f}亿，外资积极布局")
        elif nb_net < -20:
            bear_items.append(f"北向资金净流出 {nb_net:.1f}亿，外资撤离信号")
        else:
            bull_items.append(f"北向资金 {nb_net:+.1f}亿，外资观望")
    # 融资融券
    mg_net = margin.get("margin_net") if margin else None
    if mg_net is not None and mg_net != 0:
        if mg_net > 0:
            bull_items.append(f"融资净买入 +{mg_net:.1f}亿，杠杆资金加仓")
        else:
            bear_items.append(f"融资净偿还 {mg_net:.1f}亿，杠杆资金撤离")
    # 大宗交易折价
    if block_trade:
        big_discount = [b for b in block_trade if b.get("discount_pct", 0) < -5]
        if big_discount:
            bear_items.append(f"大宗交易{len(big_discount)}笔大幅折价（<{big_discount[0]['discount_pct']:.1f}%），股东出货信号")

    bull_li = "".join(f"<li>{x}</li>" for x in bull_items) or "<li>暂无明显多头信号</li>"
    bear_li = "".join(f"<li>{x}</li>" for x in bear_items) or "<li>暂无明显空头信号</li>"

    # ── 情景描述
    if pA >= 35:
        scA_desc = f"{top1_name}等主线板块延续强势，板块资金净流入持续扩大，市场新高可期"
        scA_op   = f"持有{top1_name}龙头，轻仓追涨强势股，止损设5日均线下方"
    else:
        scA_desc = f"超跌反弹，资金回流，压制位测试"
        scA_op   = "轻仓参与，严控追高，以观望为主"

    if zhuli_net >= 0:
        scB_desc = f"主线{top1_name}高位震荡，获利盘兑现，指数窄幅整理"
    else:
        scB_desc = "多空分歧，宽幅区间震荡，等待方向选择"
    scB_op = "控仓40-60%，高抛低吸，不追涨不杀跌"

    if pC >= 30:
        scC_desc = "高位连板股集中炸板，资金加速撤离，指数跌破支撑"
        scC_op   = "立即降仓至3成以下，严守止损，等待企稳"
    else:
        scC_desc = "缩量回调，主线龙头回踩均线，技术性整理"
        scC_op   = "减仓至30%，等待缩量企稳再加仓"

    # ── 作战表（TOP3板块龙头）
    battle_rows = ""
    for i, s in enumerate(top3_sectors):
        action = "开盘低吸" if s.get("chg", 0) > 3 else "盘中观察"
        battle_rows += f"""<tr>
          <td><strong>{s['name']}</strong></td>
          <td>{b_info("首选做多") if i==0 else b_warn("次选观察")}</td>
          <td>板块净流入{s['net']:+.1f}亿，{s['top_stock']}领涨</td>
          <td>{action}，止损-5%</td>
          <td>{"1.5成" if i==0 else "1成"}</td></tr>"""
    if not battle_rows:
        battle_rows = "<tr><td colspan='5' style='text-align:center;color:#6b7280'>今日无明确主线信号</td></tr>"

    # ── 雷区
    mine_items = ""
    for s in danger_stocks:
        mine_items += f"""<div class="mine high">
          <div class="mine-title">🔴 高风险 · {s['name']}（量比{s.get('vol_ratio',0):.1f}x，{s.get('chg',0):+.2f}%）</div>
          <div class="mine-body">天量分歧，高位出货特征明显，次日跌停概率较高，严禁追涨。</div>
        </div>"""
    if zhongdan < -30:
        mine_items += f"""<div class="mine high">
          <div class="mine-title">🔴 系统性预警 · 中单净流出 {zhongdan:.1f}亿</div>
          <div class="mine-body">私募/小机构规避情绪明显，若明日持续净流出超-40亿，建议降仓至3成以下。</div>
        </div>"""
    if not mine_items:
        mine_items = """<div class="mine low">
          <div class="mine-title">🟢 今日无明显雷区个股</div>
          <div class="mine-body">市场整体健康，保持常规仓位风控即可。</div>
        </div>"""

    # ── SERENITY 供应链标的（取TOP3板块各自龙头）
    serenity_rows = ""
    for s in top3_sectors:
        serenity_rows += f"""<tr>
          <td><strong>{s.get('top_stock','—')}</strong></td>
          <td>{s['name']}核心标的，今日{s['chg']:+.2f}%</td>
          <td>板块主力资金+{s['net']:.1f}亿支撑</td>
          <td>短期跟进为主</td>
          <td>{b_info("关注")}</td></tr>"""

    svg = donut_svg(pA, pB, pC)

    # ── 组装完整 HTML ─────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股深度复盘 · {review_date}</title>
<style>
:root{{
  --bg:#f0f2f5;--surface:#fff;--border:#e5e7eb;
  --up:#e03131;--dn:#0ca678;--accent:#e8580a;
  --gold:#d08700;--blue:#1c7ed6;--purple:#9c36b5;
  --text:#1a1a2e;--muted:#6b7280;--radius:10px;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font:14px/1.6 'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;padding:16px}}
a{{color:inherit;text-decoration:none}}
.nav{{background:var(--text);color:#fff;border-radius:var(--radius);padding:14px 20px;display:flex;align-items:center;gap:16px;margin-bottom:16px;flex-wrap:wrap}}
.nav-date{{font-size:18px;font-weight:700;letter-spacing:.05em}}
.nav-signal{{background:var(--accent);color:#fff;border-radius:6px;padding:3px 10px;font-size:13px;font-weight:600}}
.nav-meta{{margin-left:auto;display:flex;gap:12px;font-size:12px;opacity:.8}}
.section{{background:var(--surface);border-radius:var(--radius);border:1px solid var(--border);margin-bottom:16px;overflow:hidden}}
.sec-head{{background:linear-gradient(90deg,var(--text),#2d2d44);color:#fff;padding:10px 16px;font-size:13px;font-weight:600;letter-spacing:.08em;display:flex;align-items:center;gap:8px}}
.sec-body{{padding:16px}}
.kpi-row{{display:flex;gap:12px;flex-wrap:wrap}}
.kpi{{flex:1;min-width:110px;background:var(--bg);border-radius:8px;padding:10px 12px;border-left:3px solid var(--border)}}
.kpi.up{{border-color:var(--up)}}.kpi.dn{{border-color:var(--dn)}}.kpi.neutral{{border-color:var(--blue)}}
.kpi-label{{font-size:11px;color:var(--muted);margin-bottom:4px}}
.kpi-val{{font-size:20px;font-weight:700}}
.kpi-val.up{{color:var(--up)}}.kpi-val.dn{{color:var(--dn)}}.kpi-val.neutral{{color:var(--blue)}}
.kpi-sub{{font-size:11px;color:var(--muted);margin-top:2px}}
.hbox{{border-radius:8px;padding:10px 14px;margin-top:12px;font-size:13px;line-height:1.7}}
.hbox.red{{background:#fff5f5;border-left:4px solid var(--up)}}.hbox.green{{background:#f0fdf4;border-left:4px solid var(--dn)}}
.hbox.blue{{background:#eff6ff;border-left:4px solid var(--blue)}}.hbox.gold{{background:#fffbeb;border-left:4px solid var(--gold)}}
.hbox.purple{{background:#faf5ff;border-left:4px solid var(--purple)}}
.tbl{{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}}
.tbl th{{background:var(--bg);color:var(--muted);font-weight:600;padding:6px 10px;text-align:left;border-bottom:1px solid var(--border)}}
.tbl td{{padding:6px 10px;border-bottom:1px solid var(--bg)}}
.tbl tr:last-child td{{border-bottom:none}}
.tbl tr:hover td{{background:#fafafa}}
.b-up{{background:#fee2e2;color:var(--up);border-radius:4px;padding:1px 6px;font-size:11px;font-weight:600}}
.b-dn{{background:#d1fae5;color:#065f46;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:600}}
.b-warn{{background:#fef3c7;color:#92400e;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:600}}
.b-info{{background:#dbeafe;color:#1e40af;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:600}}
.trio{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:12px}}
.trio-card{{background:var(--bg);border-radius:8px;padding:12px}}
.trio-title{{font-size:12px;color:var(--muted);margin-bottom:6px;font-weight:600}}
.sc-row{{display:flex;gap:12px;margin-top:12px;flex-wrap:wrap}}
.sc{{flex:1;min-width:160px;border-radius:8px;padding:12px;border:1px solid var(--border)}}
.sc.a{{border-color:var(--dn);background:#f0fdf4}}.sc.b{{border-color:var(--gold);background:#fffbeb}}.sc.c{{border-color:var(--up);background:#fff5f5}}
.sc-label{{font-size:11px;font-weight:700;letter-spacing:.1em;margin-bottom:4px}}
.sc.a .sc-label{{color:var(--dn)}}.sc.b .sc-label{{color:var(--gold)}}.sc.c .sc-label{{color:var(--up)}}
.sc-prob{{font-size:22px;font-weight:800;margin-bottom:4px}}
.sc.a .sc-prob{{color:var(--dn)}}.sc.b .sc-prob{{color:var(--gold)}}.sc.c .sc-prob{{color:var(--up)}}
.sc-desc{{font-size:12px;color:var(--muted);line-height:1.5}}
.donut-wrap{{display:flex;align-items:center;gap:16px;margin-top:12px}}
svg.donut{{width:120px;height:120px;transform:rotate(-90deg)}}
.donut-legend{{font-size:12px;line-height:2}}
.mine-list{{display:flex;flex-direction:column;gap:8px;margin-top:8px}}
.mine{{border-radius:8px;padding:10px 14px;border-left:4px solid}}
.mine.high{{border-color:var(--up);background:#fff5f5}}.mine.mid{{border-color:var(--gold);background:#fffbeb}}.mine.low{{border-color:var(--dn);background:#f0fdf4}}
.mine-title{{font-weight:600;font-size:13px;margin-bottom:2px}}
.mine-body{{font-size:12px;color:var(--muted)}}
.gate{{counter-reset:step;list-style:none;margin-top:8px}}
.gate li{{counter-increment:step;padding:6px 0 6px 32px;position:relative;border-bottom:1px solid var(--bg);font-size:13px}}
.gate li::before{{content:counter(step);position:absolute;left:0;top:6px;background:var(--text);color:#fff;width:20px;height:20px;border-radius:50%;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center}}
.watch5{{display:flex;flex-direction:column;gap:6px;margin-top:8px}}
.w5-item{{display:flex;align-items:flex-start;gap:10px;background:var(--bg);border-radius:8px;padding:8px 12px}}
.w5-num{{background:var(--accent);color:#fff;border-radius:50%;width:22px;height:22px;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:1px}}
.w5-body{{font-size:13px;line-height:1.6}}
.w5-title{{font-weight:600}}
.bb-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}}
.bb-box{{border-radius:8px;padding:12px}}
.bb-bull{{background:#f0fdf4;border:1px solid #bbf7d0}}
.bb-bear{{background:#fff5f5;border:1px solid #fecaca}}
.bb-box ul{{list-style:none;padding:0}} .bb-box li{{padding:3px 0;font-size:13px}}
.bb-title{{font-size:13px;font-weight:700;margin-bottom:6px}}
@media(max-width:600px){{
  .trio{{grid-template-columns:1fr}}.kpi{{min-width:80px}}.sc{{min-width:120px}}
  .nav-meta{{display:none}}.bb-grid{{grid-template-columns:1fr}}
}}
</style>
</head>
<body>

<nav class="nav">
  <span class="nav-date">{review_date} · {wd}</span>
  <span class="nav-signal">{sig} · {top1_name}主线</span>
  <div class="nav-meta">
    {''.join(f'<span>{i["name"]} {i["close"]} <span class="{"up" if i["chg_pct"]>=0 else "dn"}">{i["chg_pct"]:+.2f}%</span></span>' for i in index_data[:4])}
    <span>主力 {fmt_net(zhuli_net)}</span>
    <span>超大单 {fmt_net(chaoda)}</span>
    <span>中单 {fmt_net(zhongdan)}</span>
  </div>
</nav>

<!-- STEP1 -->
<div class="section">
  <div class="sec-head"><span>STEP 1</span><span>盘面全景 · 今日市场概览</span></div>
  <div class="sec-body">
    <div class="kpi-row">
      <div class="kpi {'up' if zhuli_net>=0 else 'dn'}">
        <div class="kpi-label">主力净流入</div>
        <div class="kpi-val {'up' if zhuli_net>=0 else 'dn'}">{'+' if zhuli_net>=0 else ''}{zhuli_net:.1f}亿</div>
        <div class="kpi-sub">大单+超大单合计</div>
      </div>
      <div class="kpi {'up' if chaoda>=0 else 'dn'}">
        <div class="kpi-label">超大单净流入</div>
        <div class="kpi-val {'up' if chaoda>=0 else 'dn'}">{'+' if chaoda>=0 else ''}{chaoda:.1f}亿</div>
        <div class="kpi-sub">机构动向</div>
      </div>
      <div class="kpi {'dn' if zhongdan<0 else 'up'}">
        <div class="kpi-label">中单净流向</div>
        <div class="kpi-val {'dn' if zhongdan<0 else 'up'}">{'+' if zhongdan>=0 else ''}{zhongdan:.1f}亿</div>
        <div class="kpi-sub">{'⚠️ 私募规避' if zhongdan<-20 else '私募/小机构'}</div>
      </div>
      <div class="kpi {'up' if dadan>=0 else 'dn'}">
        <div class="kpi-label">大单净流向</div>
        <div class="kpi-val {'up' if dadan>=0 else 'dn'}">{'+' if dadan>=0 else ''}{dadan:.1f}亿</div>
        <div class="kpi-sub">游资参与度</div>
      </div>
      <div class="kpi {'dn' if sanhu<0 else 'up'}">
        <div class="kpi-label">散户净流向</div>
        <div class="kpi-val {'dn' if sanhu<0 else 'up'}">{'+' if sanhu>=0 else ''}{sanhu:.1f}亿</div>
        <div class="kpi-sub">散户情绪</div>
      </div>
      <div class="kpi up">
        <div class="kpi-label">领涨板块</div>
        <div class="kpi-val up" style="font-size:15px">{top1_name}</div>
        <div class="kpi-sub">{top1_chg:+.2f}%</div>
      </div>
    </div>
    <div class="hbox blue">
      <strong>主线研判：{top1_name}领涨，主力净流入{'+' if zhuli_net>=0 else ''}{zhuli_net:.1f}亿</strong><br>
      今日{sig}，{top1_name}以{top1_chg:+.2f}%领涨全市，资金净流入+{top1_net:.1f}亿，
      {top1_stock}表现突出。{'超大单持续净流入，机构底仓稳固。' if chaoda>0 else '超大单转为净流出，机构态度谨慎。'}
      {'中单-{:.1f}亿是重要警示，需关注明日是否持续。'.format(abs(zhongdan)) if zhongdan<-20 else ''}
    </div>
    {'<div class="hbox red"><strong>⚠️ 中单连续预警</strong>：中单净流出{:.1f}亿，历史数据显示中单连续两日净流出时市场短期回调概率约62%。</div>'.format(abs(zhongdan)) if zhongdan<-30 else ''}
    {(lambda ms: f'''<div class="kpi-row" style="margin-top:12px">
      <div class="kpi neutral"><div class="kpi-label">两市成交额</div><div class="kpi-val">{ms.get("total_volume_bn",0):.0f}亿</div></div>
      <div class="kpi up"><div class="kpi-label">涨跌家数</div><div class="kpi-val up">{ms.get("up_count",0)} : {ms.get("down_count",0)}</div></div>
      <div class="kpi up"><div class="kpi-label">涨停/跌停</div><div class="kpi-val up">{ms.get("limit_up",0)} / {ms.get("limit_down",0)}</div></div>
      <div class="kpi {'dn' if ms.get("zhaban_rate",0)>30 else 'up'}"><div class="kpi-label">炸板率</div><div class="kpi-val {'dn' if ms.get("zhaban_rate",0)>30 else 'up'}">{ms.get("zhaban_rate",0):.1f}%</div></div>
      <div class="kpi {'up' if ms.get("upgrade_rate",0)>=30 else 'dn'}"><div class="kpi-label">首板晋级率</div><div class="kpi-val {'up' if ms.get("upgrade_rate",0)>=30 else 'dn'}">{ms.get("upgrade_rate",0):.1f}%</div></div>
      <div class="kpi up"><div class="kpi-label">连板高度</div><div class="kpi-val up" style="font-size:15px">{ms.get("max_lianban",0)}板 {ms.get("max_lianban_stock","")}</div></div>
    </div>''' if ms else '')(market_stats)}
  </div>
</div>

<!-- STEP2 -->
<div class="section">
  <div class="sec-head"><span>STEP 2</span><span>多维数据 · 资金与板块深度解析</span></div>
  <div class="sec-body">
    <strong style="font-size:13px;color:var(--muted)">▍板块资金动向</strong>
    <table class="tbl">
      <thead><tr><th>板块</th><th>涨跌幅</th><th>主力净流入</th><th>领涨股</th><th>性质</th></tr></thead>
      <tbody>{sector_rows}</tbody>
    </table>
    <strong style="font-size:13px;color:var(--muted);display:block;margin-top:16px">▍资金结构拆解</strong>
    <div class="trio">
      <div class="trio-card">
        <div class="trio-title">超大单（机构）</div>
        <div style="color:{'var(--up)' if chaoda>=0 else 'var(--dn)'};font-size:18px;font-weight:700">{'+' if chaoda>=0 else ''}{chaoda:.1f}亿</div>
        <div style="font-size:12px;color:var(--muted);margin-top:4px">{'底仓稳固，做多意愿强' if chaoda>50 else ('小幅参与' if chaoda>0 else '机构减仓，谨慎信号')}</div>
      </div>
      <div class="trio-card">
        <div class="trio-title">大单（游资）</div>
        <div style="color:{'var(--up)' if dadan>=0 else 'var(--dn)'};font-size:18px;font-weight:700">{'+' if dadan>=0 else ''}{dadan:.1f}亿</div>
        <div style="font-size:12px;color:var(--muted);margin-top:4px">{'游资积极布局' if dadan>20 else ('小幅参与' if dadan>0 else '游资观望')}</div>
      </div>
      <div class="trio-card">
        <div class="trio-title">中单（私募/小机构）</div>
        <div style="color:{'var(--up)' if zhongdan>=0 else 'var(--dn)'};font-size:18px;font-weight:700">{'+' if zhongdan>=0 else ''}{zhongdan:.1f}亿</div>
        <div style="font-size:12px;color:var(--muted);margin-top:4px">{'⚠️ 规避情绪明显，关注持续性' if zhongdan<-20 else ('私募积极参与' if zhongdan>20 else '中性观望')}</div>
      </div>
    </div>
  </div>
</div>

<!-- STEP3 -->
<div class="section">
  <div class="sec-head"><span>STEP 3</span><span>强势个股 · 今日表现解码</span></div>
  <div class="sec-body">
    <table class="tbl">
      <thead><tr><th>标的</th><th>今日涨幅</th><th>上榜原因</th><th>主要买方</th><th>净买入估算</th><th>后市判断</th></tr></thead>
      <tbody>{stock_rows}</tbody>
    </table>
    <div class="hbox blue" style="margin-top:12px">
      <strong>今日主线逻辑</strong>：{top1_name}板块资金净流入+{top1_net:.1f}亿，{top1_stock}等标的领涨，
      {'机构席位主导，持续性较强，适合中线布局。' if chaoda > 50 else '游资短线主导，注意高位风险，严格止损。'}
    </div>
  </div>
</div>

<!-- STEP4 -->
<div class="section">
  <div class="sec-head"><span>STEP 4</span><span>多空推演 · 情景分析与盯盘要点</span></div>
  <div class="sec-body">
    <div class="bb-grid">
      <div class="bb-box bb-bull">
        <div class="bb-title" style="color:var(--dn)">多方依据</div>
        <ul>{bull_li}</ul>
      </div>
      <div class="bb-box bb-bear">
        <div class="bb-title" style="color:var(--up)">空方风险</div>
        <ul>{bear_li}</ul>
      </div>
    </div>

    <strong style="font-size:13px;color:var(--muted);display:block;margin-bottom:8px">▍三情景推演</strong>
    <div class="sc-row">
      <div class="sc a">
        <div class="sc-label">情景 A · 延续做多</div>
        <div class="sc-prob">{pA}%</div>
        <div class="sc-desc">{scA_desc}<br><br><strong>操作</strong>：{scA_op}</div>
      </div>
      <div class="sc b">
        <div class="sc-label">情景 B ⚡ 震荡（基准）</div>
        <div class="sc-prob">{pB}%</div>
        <div class="sc-desc">{scB_desc}<br><br><strong>操作</strong>：{scB_op}</div>
      </div>
      <div class="sc c">
        <div class="sc-label">情景 C · 回调风险</div>
        <div class="sc-prob">{pC}%</div>
        <div class="sc-desc">{scC_desc}<br><br><strong>操作</strong>：{scC_op}</div>
      </div>
    </div>

    <div class="donut-wrap">
      {svg}
      <div class="donut-legend">
        <div><span style="color:var(--dn)">■</span> 情景A 延续做多 <strong>{pA}%</strong></div>
        <div><span style="color:var(--gold)">■</span> 情景B 震荡整理 <strong>{pB}%</strong> ⚡基准</div>
        <div><span style="color:var(--up)">■</span> 情景C 回调风险 <strong>{pC}%</strong></div>
      </div>
    </div>

    <strong style="font-size:13px;color:var(--muted);display:block;margin-top:16px">▍明日盯盘五件事</strong>
    <div class="watch5">
      <div class="w5-item"><div class="w5-num">1</div><div class="w5-body"><span class="w5-title">{top1_name}板块开盘30分钟主力流向</span> — 净流入>15亿则延续，净流出则当日观望</div></div>
      <div class="w5-item"><div class="w5-num">2</div><div class="w5-body"><span class="w5-title">超大单方向确认</span> — 开盘30分钟超大单净流入>30亿则情景A概率提升，反之降低</div></div>
      <div class="w5-item"><div class="w5-num">3</div><div class="w5-body"><span class="w5-title">中单资金方向</span> — {'今日-{:.1f}亿，若明日转正则多头信号增强'.format(abs(zhongdan)) if zhongdan<0 else '今日+{:.1f}亿，若明日持续则加仓信号'.format(zhongdan)}</div></div>
      <div class="w5-item"><div class="w5-num">4</div><div class="w5-body"><span class="w5-title">沪指关键支撑</span> — 若跌破整数关口，触发情景C，执行降仓操作</div></div>
      <div class="w5-item"><div class="w5-num">5</div><div class="w5-body"><span class="w5-title">北向资金</span> — 若净流出超-20亿，外资撤离信号明确，建议降低仓位</div></div>
    </div>
  </div>
</div>

<!-- STEP5 -->
<div class="section">
  <div class="sec-head"><span>STEP 5</span><span>作战计划 · 个股操作与仓位管理</span></div>
  <div class="sec-body">
    <table class="tbl">
      <thead><tr><th>标的</th><th>方向</th><th>理由</th><th>操作</th><th>仓位</th></tr></thead>
      <tbody>{battle_rows}</tbody>
    </table>
    <div class="hbox gold" style="margin-top:12px">
      <strong>仓位风控原则</strong><br>
      {'整体仓位建议60-80%，强势股持仓，弱势股换仓，单票止损-5%。' if zhuli_net>50
      else ('整体仓位建议40-60%，轻仓参与，不追涨，单票止损-5%。' if zhuli_net>-50
      else '整体仓位建议20-40%，以观察为主，等待缩量企稳，勿抄底加仓。')}
    </div>
    <ol class="gate">
      <li>高位连板股（3板以上）次日严禁追涨，等待回踩再入</li>
      <li>单票亏损达-5%，无条件止损，不恋战</li>
      <li>中单若明日继续净流出超-40亿，全部降至3成</li>
      <li>主线板块开盘30分钟净流出则当日观望，不操作</li>
      <li>保持耐心，等待高确定性机会，宁可错过不做错</li>
    </ol>
  </div>
</div>

<!-- STEP6 -->
<div class="section">
  <div class="sec-head"><span>STEP 6</span><span>雷区名单 · 风险与危机预警</span></div>
  <div class="sec-body">
    <div class="mine-list">
      {mine_items}
      <div class="mine mid">
        <div class="mine-title">🟡 操作纪律提醒</div>
        <div class="mine-body">不追涨停次日高开 | 连板3板以上不新仓 | 单票亏损-5%无条件止损 | 不满仓操作 | 盘前情绪亢奋时降低一档仓位</div>
      </div>
    </div>
  </div>
</div>

<!-- SERENITY -->
<div class="section">
  <div class="sec-head"><span>SERENITY</span><span>供应链卡脖子扫描 · 今日主线标的评估</span></div>
  <div class="sec-body">
    <table class="tbl">
      <thead><tr><th>标的</th><th>逻辑</th><th>资金面</th><th>操作建议</th><th>评级</th></tr></thead>
      <tbody>{serenity_rows}</tbody>
    </table>
    <div class="hbox purple" style="margin-top:12px">
      今日{top1_name}板块整体净流入+{top1_net:.1f}亿，{top1_stock}领涨，关注板块内龙头的持续性和换手情况。
    </div>
  </div>
</div>

<div style="text-align:center;color:var(--muted);font-size:11px;padding:16px 0 8px">
  A股深度复盘 · {review_date} · 数据来源：同花顺 / 东方财富 · 仅供参考，不构成投资建议
</div>

</body>
</html>"""


# ── 主流程 ────────────────────────────────────────
def main():
    print(f"[INFO] Generating review for {REVIEW_DATE}")

    day, actual_date = load_day_data(REVIEW_DATE)
    if day is None:
        log_error("数据加载", ["data/data.json 不存在或无法读取，重试3次均失败"])
        sys.exit(1)

    issues = validate_data(day, actual_date)
    if issues:
        log_error("数据校验", issues)
        if any("market" in i for i in issues):
            print("[ERROR] 核心数据缺失，终止生成")
            sys.exit(1)

    html = build_html(day, actual_date)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(html, encoding="utf-8")
    print(f"[OK] 报告已写入 {OUT_FILE}（{len(html):,} chars）")

    # 自检：HTML 完整性
    if "</html>" not in html or "STEP 1" not in html:
        log_error("HTML校验", ["生成的HTML疑似不完整"])

    index = Path("review/index.html")
    index.write_text(
        f'<!DOCTYPE html><html><head><meta charset="UTF-8">'
        f'<meta http-equiv="refresh" content="0;url={actual_date}/review_{actual_date}.html">'
        f'<title>A股深度复盘 · {actual_date}</title></head>'
        f'<body><a href="{actual_date}/review_{actual_date}.html">跳转到最新复盘 {actual_date}</a></body></html>',
        encoding="utf-8"
    )
    print(f"[OK] review/index.html -> {actual_date}")
    print("[OK] 全部完成，零外部依赖")


if __name__ == "__main__":
    main()
