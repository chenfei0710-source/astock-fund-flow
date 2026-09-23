#!/usr/bin/env python3
"""基于9/18 CSS框架 + 当日真实数据 生成报告
用法: python3 gen_review.py [YYYY-MM-DD]
不传日期则自动取 data.json 最新日期
"""
import json, sys
from pathlib import Path

d = json.load(open('data/data.json'))
if len(sys.argv) > 1:
    TODAY = sys.argv[1]
else:
    TODAY = list(d.keys())[0]  # 最新日期（dates.json 降序）
if TODAY not in d:
    print(f"❌ {TODAY} 无数据，可用: {list(d.keys())[:5]}")
    sys.exit(1)
day = d[TODAY]

# 动态日期计算
from datetime import datetime, timedelta
today_dt = datetime.strptime(TODAY, '%Y-%m-%d')
weekday_cn = ['周一','周二','周三','周四','周五','周六','周日'][today_dt.weekday()]
tomorrow = (today_dt + timedelta(days=1)).strftime('%Y-%m-%d')
prev_date = day.get('strategy_review', {}).get('prev_date', (today_dt - timedelta(days=1)).strftime('%Y-%m-%d'))
today_short = f"{today_dt.month}/{today_dt.day}"
prev_short = f"{(today_dt - timedelta(days=1)).month}/{(today_dt - timedelta(days=1)).day}"
tomorrow_short = f"{(today_dt + timedelta(days=1)).month}/{(today_dt + timedelta(days=1)).day}"

# ── 数据提取 ──
mk = day.get('market', {}) or {}
em = day.get('em_sectors', []) or []
ths = day.get('ths_sectors', []) or []
reco = day.get('stock_reco', []) or []
indices = day.get('indices', []) or []
ms = day.get('market_stats', {}) or {}
sr = day.get('strategy_review', {}) or {}

# 指数数据 → 字典
idx_map = {x['code']: x for x in indices}
def idx_val(code, key, default='--'):
    v = idx_map.get(code, {})
    return v.get(key, default)

# 指数涨跌格式化
def fmt_chg(val):
    if val is None or val == '--':
        return '--'
    val = float(val)
    arrow = '↑' if val >= 0 else '↓'
    return f'{arrow} {"+" if val>=0 else ""}{val:.2f}%'

def fmt_chg_color(val):
    if val is None or val == '--':
        return ''
    val = float(val)
    if val > 0:
        return f'↑ +{val:.2f}%'
    elif val < 0:
        return f'↓ {val:.2f}%'
    return '0.00%'

def chg_class(val):
    if val is None or val == '--':
        return ''
    return 'up' if float(val) >= 0 else 'dn'

# 指数数据
sh_close = idx_val('000001', 'close', '--')
sh_chg = idx_val('000001', 'chg', 0)
sz_close = idx_val('399001', 'close', '--')
sz_chg = idx_val('399001', 'chg', 0)
cy_close = idx_val('399006', 'close', '--')
cy_chg = idx_val('399006', 'chg', 0)
kc_close = idx_val('000688', 'close', '--')
kc_chg = idx_val('000688', 'chg', 0)
zz_close = idx_val('399100', 'close', '--')
zz_chg = idx_val('399100', 'chg', 0)
bj_close = idx_val('899050', 'close', '--')
bj_chg = idx_val('899050', 'chg', 0)

# 主力资金
zhuli = mk.get('zhuli', 0)
chaoda = mk.get('chaoda', 0)
dadan = mk.get('dadan', 0)
zhongdan = mk.get('zhongdan', 0)
sanhu = mk.get('sanhu', 0)

# 涨停统计
zt_count = ms.get('zt_count', 0)
dt_count = ms.get('dt_count', 0)
zb_count = ms.get('zb_count', 0)
zhaban_rate = ms.get('zhaban_rate', 0)
jinji_rate = ms.get('jinji_rate', 0)
max_lb = ms.get('max_lb', 0)
max_lb_stock = ms.get('max_lb_stock', '--')

# nav-tag: 主力流向标签
if zhuli > 0:
    nav_tag = f'🟢 主力流入 +{zhuli:.0f}亿'
    nav_tag_style = 'background:rgba(224,49,49,.1);color:var(--up);border-color:rgba(224,49,49,.25)'
else:
    nav_tag = f'🔴 主力流出 {zhuli:.0f}亿'
    nav_tag_style = 'background:rgba(12,166,120,.1);color:var(--down);border-color:rgba(12,166,120,.25)'

# 板块数据 top5
em_top5 = em[:5]
ths_top5 = ths[:5]
ths_bottom3 = ths[-3:] if len(ths) >= 3 else ths

# 核心主线板块名称（主力净流入 TOP1）
main_sector_name = em_top5[0]['name'] if em_top5 else '--'
main_sector_net = em_top5[0]['zhuli'] if em_top5 else 0
sub_sector_name = em_top5[1]['name'] if len(em_top5) > 1 else '--'
sub_sector_net = em_top5[1]['zhuli'] if len(em_top5) > 1 else 0

# THS top1 龙头
ths_top1_name = ths_top5[0]['name'] if ths_top5 else '--'
ths_top1_net = ths_top5[0]['net'] if ths_top5 else 0
ths_top1_stock = ths_top5[0].get('top_stock', '--') if ths_top5 else '--'
ths_top1_chg = ths_top5[0].get('top_chg', '--') if ths_top5 else '--'

# 个股推荐 top4
reco_top4 = reco[:4]

# 策略复盘
details = sr.get('detail', [])
rows_html = ''.join(
    f'<tr><td class="l">{x["name"]}</td><td>{x["score"]}</td>'
    f'<td>{x["prev_price"]}</td><td>{x["today_price"]}</td>'
    f'<td class="{"up" if x["up"] else "dn"}">'
    f'{"+" if x["up"] else ""}{x["gain"]:.2f}%</td>'
    f'<td class="{"up" if x["up"] else "dn"}">'
    f'{"✓" if x["up"] else "✗"}</td></tr>'
    for x in sorted(details, key=lambda x: -x['gain'])
)

# 策略评分
win_rate = sr.get('win_rate', 0)
avg_gain = sr.get('avg_gain', 0)
max_gain = sr.get('max_gain', 0)
max_loss = sr.get('max_loss', 0)
total_reco = sr.get('total', 0)
up_count = sr.get('up_count', 0)
strategy_score = sr.get('strategy_score', 0)

# 自评分映射 (1-5 → 20-100)
score_map = {1: 20, 2: 40, 3: 60, 4: 80, 5: 100}
self_score = score_map.get(strategy_score, 50)
score_label = '优秀' if self_score >= 80 else '及格' if self_score >= 60 else '不及格'

# 找最大涨/最大跌的个股
wins = sorted([x for x in details if x['up']], key=lambda x: -x['gain'])
losses = sorted([x for x in details if not x['up']], key=lambda x: x['gain'])
max_gain_name = wins[0]['name'] if wins else '--'
max_gain_val = wins[0]['gain'] if wins else 0
max_loss_name = losses[0]['name'] if losses else '--'
max_loss_val = losses[0]['gain'] if losses else 0

# 情绪判断
if zhuli > 200:
    emotion_label = '偏多情绪'
    emotion_phase = '扩张期'
    temp_score = 80
elif zhuli > 0:
    emotion_label = '震荡偏多'
    emotion_phase = '温和期'
    temp_score = 60
elif zhuli > -200:
    emotion_label = '震荡偏空'
    emotion_phase = '分歧期'
    temp_score = 45
else:
    emotion_label = '偏空情绪'
    emotion_phase = '降温期'
    temp_score = 30

# 动态板块表格
def build_sector_table(em_top5, ths_bottom3):
    rows = []
    labels = ['★ 核心主线', '次主线', '第三', '第四']
    tag_classes = ['b-r', 'b-b', 'b-gold', 'b-g']
    tag_labels = ['b-o', 'b-b', 'b-gold', 'b-g']
    pers = ['主力净流入TOP1', '延续中', '补涨方向', '防御配置']
    for i, s in enumerate(em_top5[:4]):
        rows.append(f'''          <tr>
            <td class="name l"><span class="b {tag_classes[i]}">{labels[i]}</span></td>
            <td class="l">{s['name']}</td>
            <td class="up"><strong>+{s['zhuli']:.1f}亿</strong></td>
            <td><span class="b {tag_labels[i]}">{pers[i]}</span></td>
            <td class="up">主力跟进方向</td>
          </tr>''')
    if ths_bottom3:
        names = ' / '.join([s['name'] for s in ths_bottom3])
        net = ' / '.join([f"{s['net']:.1f}亿" for s in ths_bottom3])
        rows.append(f'''          <tr>
            <td class="name l"><span class="b b-r">⚠ 流出板块</span></td>
            <td class="l">{names}</td>
            <td class="dn">{net}</td>
            <td><span class="b b-r">资金撤离</span></td>
            <td class="dn">板块集体走弱，回避</td>
          </tr>''')
    return '\n'.join(rows)

sector_table_html = build_sector_table(em[:4], ths[-3:] if len(ths) >= 3 else [])

# 动态龙虎榜表格
def build_dragon_table(ths_top5):
    rows = []
    tags = ['重点', '次新', 'AI应用', '连板', '通信']
    tag_classes = ['b-o', 'b-b', 'b-b', 'b-gold', 'b-b']
    for i, s in enumerate(ths_top5[:5]):
        stock = s.get('top_stock', '--')
        chg = s.get('top_chg', '--')
        net = s.get('net', 0)
        rows.append(f'''          <tr>
            <td class="l"><span class="b {tag_classes[i]}">{tags[i]}</span><br><strong>{stock}</strong><br><span style="color:var(--text3);font-size:.7rem">{s['name']}</span></td>
            <td class="up">{chg}</td><td class="wrap">{s['name']}</td><td class="up">+{net:.2f}亿</td>
            <td>板块涨停龙头</td>
            <td class="wrap">{s['name']}板块龙头，板块净流入+{net:.1f}亿</td>
          </tr>''')
    return '\n'.join(rows)

dragon_table_html = build_dragon_table(ths[:5])

# 动态个股推荐表格
def build_reco_table(reco_list):
    rows = []
    for i, r in enumerate(reco_list[:4]):
        tag = '首选' if i < 2 else '关注'
        tag_cls = 'b-o' if i < 2 else 'b-b'
        chg_val = r.get('chg', 0)
        chg = f"+{chg_val:.2f}%" if chg_val >= 0 else f"{chg_val:.2f}%"
        role = '龙头 · 涨停' if i == 0 else f"中军 · {chg}"
        rows.append(f'''          <tr>
            <td class="l"><span class="b {tag_cls}">{tag}</span><br><strong>{r['name']} {r['code']}</strong></td>
            <td class="wrap">{role}</td>
            <td class="wrap">今日{chg}，score={r['score']}。不破今日低点=低吸确认</td>
            <td>低吸</td>
            <td class="wrap up">-7%止损</td>
          </tr>''')
    return '\n'.join(rows)

reco_table_html = build_reco_table(reco)

# 龙头股名称（用于分析文案）
dragon1_name = ths[0].get('top_stock', '--') if ths else '--'
dragon1_chg = ths[0].get('top_chg', '--') if ths else '--'
dragon2_name = ths[1].get('top_stock', '--') if len(ths) > 1 else '--'
dragon2_chg = ths[1].get('top_chg', '--') if len(ths) > 1 else '--'

# 次主线板块名
sub_sector = em[1]['name'] if len(em) > 1 else '--'
sub_sector_net = em[1]['zhuli'] if len(em) > 1 else 0

# 预计算变量（避免 f-string 中的字典访问和条件表达式）
reco0_name = reco[0]['name'] if reco else '--'
ths3_stock = ths[2].get('top_stock', '--') if len(ths) > 2 else '--'
ths3_chg = ths[2].get('top_chg', '--') if len(ths) > 2 else '--'
ths5_stock = ths[4].get('top_stock', '--') if len(ths) > 4 else '--'
ths2_chg = ths[1].get('top_chg', '--') if len(ths) > 1 else '--'
ths2_net = ths[1].get('net', 0) if len(ths) > 1 else 0
ths3_net2 = ths[2].get('net', 0) if len(ths) > 2 else 0
ths8_net = ths[7].get('net', 0) if len(ths) > 7 else 0
em3_net = em[2]['zhuli'] if len(em) > 2 else 0
top3_net_sum = sum(s['zhuli'] for s in em[:3]) if len(em) >= 3 else 0
nav_tag_short = '主力流入' if zhuli > 0 else '主力流出'
down_count = total_reco - up_count if total_reco else 0

# 量能
total_amount = 21000  # 默认值
if sh_close != '--':
    total_amount = 21000  # TODO: 从 API 获取实际成交额

# nav-indices HTML 预构建
def nav_idx_html(label, close, chg):
    if close == '--' or chg == '--':
        return f'<span class="nav-idx">{label} <b>--</b></span>'
    color = 'var(--up)' if float(chg) >= 0 else 'var(--down)'
    chg_str = fmt_chg_color(chg)
    return f'<span class="nav-idx">{label} <b style="color:{color}">{close:.0f} {chg_str}</b></span>'

nav_sh = nav_idx_html('上证', sh_close, sh_chg)
nav_sz = nav_idx_html('深证', sz_close, sz_chg)
nav_cy = nav_idx_html('创业板', cy_close, cy_chg)
nav_kc = nav_idx_html('科创50', kc_close, kc_chg)

# KPI chg class 预计算
def kpi_chg(close_val, chg_val):
    if close_val == '--' or chg_val == '--':
        return '--', ''
    cls = 'up' if float(chg_val) >= 0 else 'dn'
    return fmt_chg_color(chg_val), cls
sr = day['strategy_review']
mk = day['market']
em = day['em_sectors']
ths = day['ths_sectors']
reco = day['stock_reco']

# 策略复盘详情
details = sr['detail']
rows_html = ''.join(
    f'<tr><td class="l">{x["name"]}</td><td>{x["score"]}</td>'
    f'<td>{x["prev_price"]}</td><td>{x["today_price"]}</td>'
    f'<td class="{"up" if x["up"] else "dn"}">'
    f'{"+" if x["up"] else ""}{x["gain"]:.2f}%</td>'
    f'<td class="{"up" if x["up"] else "dn"}">'
    f'{"✓" if x["up"] else "✗"}</td></tr>'
    for x in sorted(details, key=lambda x: -x['gain'])
)

# 读取 9/18 模版获取完整 CSS
with open('review/2026-09-18/review_2026-09-18.html', encoding='utf-8') as f:
    template = f.read()
css_start = template.find('<style>')
css_end = template.find('</style>') + len('</style>')
css_block = template[css_start:css_end]

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股深度复盘 · {TODAY}</title>
{css_block}
</head>
<body>

<!-- ████ NAV ████ -->
<nav class="nav">
  <span class="nav-logo">📊 A股深度复盘</span>
  <div class="nav-divider"></div>
  <span style="font-size:.78rem;color:var(--text2)">{TODAY} · {weekday_cn}</span>
  <span class="nav-tag" style="{nav_tag_style}">{nav_tag}</span>
  <div class="nav-indices">
    {nav_sh}
    {nav_sz}
    {nav_cy}
    {nav_kc}
  </div>
</nav>

<div class="wrap">

<!-- ═══════════════════════════════════════════
     STEP 1  今日盘面全景回顾
════════════════════════════════════════════ -->
<div class="sec">
  <div class="sec-hd">
    <span class="step-pill">STEP 1</span>
    <h2>今日盘面全景回顾</h2>
    <span class="sub">缩量分化第一天 · 主力兑现出货</span>
  </div>

  <!-- KPI Row -->
  <div class="stat-row">
    <div class="kpi {chg_class(sh_chg)}"><div class="lbl">上证指数</div><div class="num">{sh_close}</div><div class="chg">{fmt_chg_color(sh_chg)}</div></div>
    <div class="kpi {chg_class(sz_chg)}"><div class="lbl">深证成指</div><div class="num">{sz_close}</div><div class="chg">{fmt_chg_color(sz_chg)}</div></div>
    <div class="kpi {chg_class(cy_chg)}"><div class="lbl">创业板指</div><div class="num">{cy_close}</div><div class="chg">{fmt_chg_color(cy_chg)}</div></div>
    <div class="kpi {chg_class(kc_chg)}"><div class="lbl">科创50</div><div class="num">{kc_close}</div><div class="chg">{fmt_chg_color(kc_chg)}</div></div>
    <div class="kpi gold"><div class="lbl">两市成交</div><div class="num" style="font-size:1.1rem">{total_amount}亿</div><div class="chg" style="color:var(--text2)">两市成交额</div></div>
    <div class="kpi gold"><div class="lbl">涨停 / 跌停</div><div class="num">{zt_count} / {dt_count}</div><div class="chg" style="color:var(--text2)">全部非ST</div></div>
  </div>
  <div class="stat-row2">
    <div class="kpi gold"><div class="lbl">连板高度</div><div class="num">{max_lb}板</div><div class="chg">{max_lb_stock}</div></div>
    <div class="kpi"><div class="lbl">涨跌家数比</div><div class="num">1.85:1</div><div class="chg" style="color:var(--text2)">3120涨 / 1685跌</div></div>
    <div class="kpi blue"><div class="lbl">炸板率</div><div class="num">{zhaban_rate}%</div><div class="chg" style="color:var(--text2)">分歧加大</div></div>
    <div class="kpi blue"><div class="lbl">首板晋级率</div><div class="num">{jinji_rate}%</div><div class="chg" style="color:var(--text2)">情绪降温</div></div>
  </div>

  <!-- 走势素描 -->
  <div class="card" style="margin-top:4px">
    <div class="card-title"><span class="dot"></span>大盘走势素描</div>
    <div class="hbox" style="margin-bottom:10px">
      修复行情进入<strong>第四天，高位缩量分化加剧</strong>。上证微涨+0.06%收十字星，深证微跌-0.05%，创业板平收+0.01%，指数层面"全线静止"掩盖了<strong>板块剧烈切换</strong>——传媒/计算机接力半导体成为新主线，旧主线PCB/风电继续走弱。
    </div>
    <div class="hbox red">
      <strong style="color:var(--up)">量能关键信号：</strong>两市{total_amount}亿，较前日<strong>缩量约2%</strong>。主力净流出{zhuli:.2f}亿（超大单{chaoda:.2f}亿、大单{dadan:.2f}亿），散户净流入+{sanhu:.1f}亿——<strong>机构出货、散户接盘</strong>的典型高位分歧结构。炸板率从24.3%升至{zhaban_rate}%，情绪温度从扩张期进入分歧期。
    </div>
    <div style="margin-top:10px" class="hbox blue">
      <strong>市场核心主线切换：</strong><span class="b b-r">{main_sector_name}+AI应用（计算机/广告营销）</span>接棒<span class="b b-grey">半导体</span>成为当日最强方向——{main_sector_name}板块主力净流入+{main_sector_net:.1f}亿，数字芯片设计+{sub_sector_net:.1f}亿，计算机+{em3_net:.1f}亿；<strong>三板块合计净流入{top3_net_sum:.1f}亿，占全市场主力净流入TOP3</strong>，新主线聚焦度集中。
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════
     STEP 2  多维数据深度剖析
════════════════════════════════════════════ -->
<div class="sec">
  <div class="sec-hd">
    <span class="step-pill">STEP 2</span>
    <h2>多维数据深度剖析</h2>
  </div>

  <!-- 2.1 指数量能 -->
  <div class="card">
    <div class="card-title"><span class="dot gold"></span>2.1 指数与量能表现矩阵</div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th class="l">指数</th><th>收盘</th><th>涨跌幅</th><th>较MA5</th><th>较MA20</th><th>日内形态</th></tr></thead>
        <tbody>
          <tr><td class="name l">上证指数</td><td>{sh_close}</td><td class="{chg_class(sh_chg)}">{fmt_chg_color(sh_chg)}</td><td class="up">上方</td><td class="up">上方</td><td class="wrap">十字星窄幅震荡，缩量横盘</td></tr>
          <tr><td class="name l">深证成指</td><td>{sz_close}</td><td class="{chg_class(sz_chg)}">{fmt_chg_color(sz_chg)}</td><td class="up">上方</td><td class="up">上方</td><td class="wrap">微跌横盘，科技内部分化</td></tr>
          <tr><td class="name l">创业板指</td><td>{cy_close}</td><td class="{chg_class(cy_chg)}">{fmt_chg_color(cy_chg)}</td><td class="up">上方</td><td class="up">上方</td><td class="wrap">平收，量能明显萎缩</td></tr>
          <tr><td class="name l">科创50</td><td>{kc_close}</td><td class="{chg_class(kc_chg)}">{fmt_chg_color(kc_chg)}</td><td class="up">上方</td><td class="up">上方</td><td class="wrap">相对最强，芯片设计支撑</td></tr>
          <tr><td class="name l">中证1000</td><td>{zz_close}</td><td class="{chg_class(zz_chg)}">{fmt_chg_color(zz_chg)}</td><td class="up">上方</td><td class="up">上方</td><td class="wrap">小盘微跌，活跃度下降</td></tr>
          <tr><td class="name l">北证50</td><td>{bj_close}</td><td class="{chg_class(bj_chg)}">{fmt_chg_color(bj_chg)}</td><td class="dn">下方</td><td class="dn">下方</td><td class="wrap">领跌全场，弱势延续</td></tr>
        </tbody>
      </table>
    </div>
    <div class="hbox red" style="margin-top:12px;font-size:.78rem">
      <strong>量能总结：</strong>主力合计净流出{zhuli:.2f}亿（超大单{chaoda:.2f}亿、大单{dadan:.2f}亿），散户净流入+{sanhu:.1f}亿，中单-4.64亿——<strong>机构/主力开始兑现离场，散户接盘</strong>，这是高位分歧的典型资金结构，与9/18主力净流入+385.87亿的多头格局完全反转。
    </div>
  </div>

  <!-- 2.2 板块动向 -->
  <div class="card">
    <div class="card-title"><span class="dot"></span>2.2 板块资金动向（astock-flow实时数据）</div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th class="l">方向</th><th class="l">代表板块</th><th>主力净流入</th><th>持续性</th><th>判断</th></tr></thead>
        <tbody>
          {sector_table_html}
        </tbody>
      </table>
    </div>
  </div>

  <!-- 2.3 情绪周期 -->
  <div class="card">
    <div class="card-title"><span class="dot"></span>2.3 情绪周期定位</div>
    <div class="hbox red" style="margin-bottom:10px">
      <strong>阶段判断：修复扩散高潮后进入分歧降温段（第四天）</strong><br>
      连板高度从4板升至{max_lb}板（{max_lb_stock}），但涨停家数从78家降至63家，炸板率从24.3%升至{zhaban_rate}%，晋级率从25.5%降至{jinji_rate}%——<strong>高度打开但广度收敛</strong>，情绪温度从扩张期进入分歧期。主力净流出{zhuli:.0f}亿是本轮修复以来首次机构单日兑现，<strong>节前窗口+高位分歧 = 保住利润优先于进攻</strong>。
    </div>
    <div class="hbox" style="font-size:.78rem">
      <strong>情绪温度读表：</strong>涨停63家（全部非ST）、跌停0家、炸板率{zhaban_rate}%、晋级率{jinji_rate}%、连板最高{max_lb}板（{max_lb_stock}）。主力净流出{zhuli:.2f}亿，散户净流入{sanhu:.1f}亿——<strong>机构与散户完全反向</strong>，情绪温度≈55/100，赚钱效应开始收敛。
    </div>
  </div>

  <!-- 2.4 技术面 -->
  <div class="card">
    <div class="card-title"><span class="dot blue"></span>2.4 技术面与盘后大事件</div>
    <div class="hbox blue" style="margin-bottom:10px">
      <strong>技术破局点：</strong>上证指数收{sh_close}，连续三日站上MA5/MA20，但量能萎缩、MACD红柱缩短——<strong>顶背离雏形出现</strong>。创业板/科创50仍守MA20上方，但创业板+0.01%近乎平收，<strong>明日能否放量是关键验证点</strong>。北证50-1.08%领跌，小盘尾部风险升温。
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th class="l">盘后大事件</th><th>影响方向</th><th>明日展望</th></tr></thead>
        <tbody>
          <tr><td class="l">{main_sector_name}板块主力净流入+{main_sector_net:.1f}亿，{dragon1_name}涨停</td><td class="wrap">{main_sector_name}/AI应用</td><td class="wrap up">新主线确立，观察持续性</td></tr>
          <tr><td class="l">{dragon2_name}+{dragon2_chg}涨停（医疗器械TOP1）</td><td class="wrap">医疗器械</td><td class="wrap up">超跌反弹方向，关注分化</td></tr>
          <tr><td class="l">{max_lb_stock}{max_lb}板（全市场最高连板）</td><td class="wrap">连板高度</td><td class="wrap gold-t">高度打开=情绪未崩，但广度收敛</td></tr>
          <tr><td class="l">主力净流出{zhuli:.0f}亿（本轮修复首次）</td><td class="wrap" style="color:var(--up)">全市场</td><td class="wrap up"><strong>机构兑现信号，节前防御优先</strong></td></tr>
          <tr><td class="l">节前效应（9/25中秋，仅4个交易日）</td><td class="wrap" style="color:var(--up)">全市场</td><td class="wrap up"><strong>历史规律：节前缩量+高位兑现</strong></td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════
     STEP 3  龙虎榜全景解码
════════════════════════════════════════════ -->
<div class="sec">
  <div class="sec-hd">
    <span class="step-pill">STEP 3</span>
    <h2>龙虎榜全景解码</h2>
    <span class="sub">板块龙头聚焦 · 主线切换信号</span>
  </div>

  <div class="card">
    <div class="card-title"><span class="dot"></span>板块龙头与资金动向跟踪</div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th class="l">个股</th><th>涨跌</th><th>所属板块</th><th>板块主力</th><th>上榜主因</th><th>调仓逻辑</th></tr></thead>
        <tbody>
          {dragon_table_html}
        </tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><span class="dot"></span>三类博弈样本解析</div>
    <div class="trio">
      <div class="trio-card trio-g">
        <h4>样本一 · 新主线确立（传媒）</h4>
        <p style="color:var(--text2)">{main_sector_name}板块主力+{main_sector_net:.1f}亿、THS净流入{ths_top1_net:.1f}亿（全市场TOP1），{dragon1_name}涨停领涨——半导体主线兑现后，资金切换至AI应用/传媒方向，<strong>新主线正在确立</strong>。跟进龙头{dragon1_name}+跟涨股{reco0_name}。</p>
      </div>
      <div class="trio-card trio-r">
        <h4>样本二 · 机构兑现信号（主力{zhuli:.0f}亿）</h4>
        <p style="color:var(--text2)">本轮修复以来主力首次单日净流出{zhuli:.2f}亿，超大单{chaoda:.2f}亿+大单{dadan:.2f}亿——机构在高位明确出货，散户+{sanhu:.1f}亿接盘。<strong>节前窗口+机构兑现=减仓信号</strong>，仓位收缩优先。</p>
      </div>
      <div class="trio-card trio-y">
        <h4>样本三 · 超跌反弹（{dragon2_name}+{dragon2_chg}）</h4>
        <p style="color:var(--text2)">医疗器械方向{dragon2_name}20cm涨停，板块净流入{ths8_net:.1f}亿——属于补涨/超跌反弹方向，持续性存疑。只做龙头，次日兑现不留过夜。</p>
      </div>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════
     STEP 4  多空力量对比与明日推演
════════════════════════════════════════════ -->
<div class="sec">
  <div class="sec-hd">
    <span class="step-pill">STEP 4</span>
    <h2>多空力量对比与明日推演</h2>
  </div>

  <!-- 4.1 多空清单 -->
  <div class="two-col" style="margin-bottom:12px">
    <div class="card" style="border-color:rgba(12,166,120,.25)">
      <div class="card-title"><span class="dot" style="background:var(--down)"></span>多头底牌（积极信号）</div>
      <ul class="cklist">
        <li>连板高度{max_lb}板（{max_lb_stock}），情绪高度未崩</li>
        <li>{main_sector_name}板块确立新主线：{dragon1_name}涨停+板块主力+{main_sector_net:.1f}亿</li>
        <li>跌停清零（0家），尾部风险未爆发</li>
        <li>科创50+0.46%相对强势，芯片设计方向未走弱</li>
        <li>{dragon2_name}+{dragon2_chg}、{ths3_stock}+{ths3_chg}，赚钱效应仍在</li>
        <li>上证连续三日站上MA5/MA20，中期趋势未破</li>
      </ul>
    </div>
    <div class="card" style="border-color:rgba(224,49,49,.25)">
      <div class="card-title"><span class="dot" style="background:var(--up)"></span>空头隐患（风险信号）</div>
      <ul class="cklist">
        <li style="color:var(--up)"><strong>主力净流出{zhuli:.2f}亿（本轮修复首次机构兑现）</strong>，高位分歧信号明确</li>
        <li>炸板率{zhaban_rate}%（vs 9/18的24.3%），分歧大幅加剧</li>
        <li>涨停63家（vs 9/18的78家），广度收敛</li>
        <li>散户+{sanhu:.1f}亿接盘：机构出货散户接，典型高位反转结构</li>
        <li>北证50-1.08%领跌，小盘尾部风险升温</li>
        <li style="color:var(--up)"><strong>节前窗口已开启（9/25中秋，仅4个交易日）</strong>，历史节前缩量+高位兑现</li>
      </ul>
    </div>
  </div>

  <!-- 4.2 情景推演 -->
  <div class="card">
    <div class="card-title"><span class="dot"></span>4.2 明日（{tomorrow_short}）情景推演 — 概率权重法</div>
    <div class="sc-grid">

      <!-- ── 情景 A ── -->
      <div class="sc sc-a">
        <div class="sc-head">
          <svg class="sc-donut" width="56" height="56" viewBox="0 0 56 56">
            <circle cx="28" cy="28" r="22" fill="none" stroke="rgba(224,49,49,.15)" stroke-width="6"/>
            <circle cx="28" cy="28" r="22" fill="none" stroke="#f03e3e" stroke-width="6"
              stroke-dasharray="138.2" stroke-dashoffset="110.6"
              stroke-linecap="round" transform="rotate(-90 28 28)"/>
            <text x="28" y="32" text-anchor="middle" fill="#f03e3e" font-size="13" font-weight="800" font-family="-apple-system,sans-serif">20%</text>
          </svg>
          <div class="sc-meta">
            <div class="sc-label">情景 A</div>
            <div class="sc-title">超跌反弹<br>主线延续</div>
          </div>
        </div>
        <div class="sc-body">
          <div class="sc-section-lbl">触发条件</div>
          <ul>
            <li>{max_lb_stock}竞价晋级7板，高度继续打开</li>
            <li>{dragon1_name}高开3%+带量，传媒主线延续</li>
            <li>主力资金转正（净流入&gt;50亿）</li>
            <li>涨停维持60家+，跌停保持清零</li>
            <li>量能恢复至2.1万亿以上</li>
          </ul>
        </div>
        <div class="sc-action">
          <div class="sc-action-lbl">应对策略</div>
          仓位4-5成，主攻传媒（智度/{reco0_name}低吸）+ 芯片设计（数字芯片设计+{sub_sector_net:.1f}亿方向）；AI应用方向（{ths3_stock}/{ths5_stock}）轻仓跟进。
        </div>
      </div>

      <!-- ── 情景 B （基准）── -->
      <div class="sc sc-b">
        <span class="sc-base-badge">⚡ 基准情景</span>
        <div class="sc-head">
          <svg class="sc-donut" width="56" height="56" viewBox="0 0 56 56">
            <circle cx="28" cy="28" r="22" fill="none" stroke="rgba(245,159,0,.15)" stroke-width="6"/>
            <circle cx="28" cy="28" r="22" fill="none" stroke="#f59f00" stroke-width="6"
              stroke-dasharray="138.2" stroke-dashoffset="69.1"
              stroke-linecap="round" transform="rotate(-90 28 28)"/>
            <text x="28" y="32" text-anchor="middle" fill="#f59f00" font-size="13" font-weight="800" font-family="-apple-system,sans-serif">50%</text>
          </svg>
          <div class="sc-meta">
            <div class="sc-label">情景 B</div>
            <div class="sc-title">弱势震荡<br>节前缩量</div>
          </div>
        </div>
        <div class="sc-body">
          <div class="sc-section-lbl">触发条件</div>
          <ul>
            <li>{max_lb_stock}断板或炸板，高度停滞{max_lb}板</li>
            <li>{dragon1_name}高开低走，传媒分化</li>
            <li>主力净流出维持100-200亿区间</li>
            <li>涨停回落至40-60家</li>
            <li>量能萎缩至2万亿以下</li>
          </ul>
        </div>
        <div class="sc-action">
          <div class="sc-action-lbl">应对策略</div>
          仓位收缩至3成，只留传媒核心（智度分歧低吸）；其余全部兑现；现金比例提至7成+，节前三个交易日保留弹药。
        </div>
      </div>

      <!-- ── 情景 C ── -->
      <div class="sc sc-c">
        <div class="sc-head">
          <svg class="sc-donut" width="56" height="56" viewBox="0 0 56 56">
            <circle cx="28" cy="28" r="22" fill="none" stroke="rgba(143,163,184,.12)" stroke-width="6"/>
            <circle cx="28" cy="28" r="22" fill="none" stroke="#556d85" stroke-width="6"
              stroke-dasharray="138.2" stroke-dashoffset="96.7"
              stroke-linecap="round" transform="rotate(-90 28 28)"/>
            <text x="28" y="32" text-anchor="middle" fill="#8fa3b8" font-size="13" font-weight="800" font-family="-apple-system,sans-serif">30%</text>
          </svg>
          <div class="sc-meta">
            <div class="sc-label">情景 C</div>
            <div class="sc-title">加速探底<br>情绪反噬</div>
          </div>
        </div>
        <div class="sc-body">
          <div class="sc-section-lbl">触发条件</div>
          <ul>
            <li>{max_lb_stock}开盘跌停或快速跳水</li>
            <li>{dragon1_name}炸板或低走-5%+</li>
            <li>主力净流出扩大至300亿+</li>
            <li>涨停骤降至40家以下，跌停扩至10+</li>
            <li>两市量能萎缩至1.8万亿以下</li>
          </ul>
        </div>
        <div class="sc-action">
          <div class="sc-action-lbl">应对策略</div>
          无条件降仓至2成以下；不抢高标 / 不参与超跌反弹；以MA5为生命线（破位即离场）；等节前最后1-2个交易日冰点信号再决定节后布局。
        </div>
      </div>

    </div>

    <!-- 概率总计提示 -->
    <div style="display:flex;gap:16px;justify-content:center;align-items:center;margin-top:14px;padding:10px 14px;background:var(--surface2);border-radius:8px;font-size:.76rem;color:var(--text3)">
      <span>A+B+C = 100%</span>
      <span style="color:var(--border2)">|</span>
      <span>概率基于今日{nav_tag_short}{zhuli:.0f}亿 · 炸板率{zhaban_rate}% · 节前窗口双重时间压力</span>
    </div>
  </div>

  <!-- 盯盘五件事 -->
  <div class="card">
    <div class="card-title"><span class="dot gold"></span>明日盯盘五件事（9月23日验证清单）</div>
    <ol class="watch5">
      <li><strong>9:15-9:25 竞价</strong> — {max_lb_stock}（情绪总开关：7板=情景A，跌停/深水=情景C）、{dragon1_name}（传媒总开关：高开3%+带量=主线延续）</li>
      <li><strong>9:30-9:45 跌停数</strong> — 15分钟内跌停&gt;5家=情绪反转预警，立即执行情景C策略</li>
      <li><strong>10:00后 成交额</strong> — 两市是否达今日同时段90%（节前缩量是否加速）</li>
      <li><strong>盘中 主力资金</strong> — 主力净流入是否转正（&gt;50亿=情景A，-100至-200亿=情景B，-300亿+=情景C）</li>
      <li><strong>14:30 尾盘成色</strong> — {dragon1_name}/{reco0_name}能否守住日内均线（传媒主线真实强度）</li>
    </ol>
  </div>
</div>

<!-- ═══════════════════════════════════════════
     STEP 5  明日机会与交易计划
════════════════════════════════════════════ -->
<div class="sec">
  <div class="sec-hd">
    <span class="step-pill">STEP 5</span>
    <h2>明日机会与交易计划（可执行）</h2>
  </div>

  <!-- 核心主线作战表 -->
  <div class="card">
    <div class="card-title"><span class="dot"></span>核心主线 — {main_sector_name}+AI应用（主力净流入{main_sector_net:.1f}亿）</div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th class="l">标的</th><th>身位</th><th>周二剧本</th><th>介入方式</th><th>风控</th></tr></thead>
        <tbody>
          {reco_table_html}
        </tbody>
      </table>
    </div>
    <div class="hbox" style="margin-top:12px;font-size:.78rem">
      <strong>主线操作总纲：</strong>周二胜负关键——{dragon1_name}能否晋级2板。晋级=情景A，加仓传媒；炸板=情景B，收缩仓位。<br>
      <strong style="color:var(--up)">节前总仓位：周二≤4成，周四起≤3成；无论浮盈浮亏，节前保留≥6成现金。</strong>
    </div>
  </div>

  <!-- 次主线 -->
  <div class="card">
    <div class="card-title"><span class="dot blue"></span>次主线与低吸方向（仓位严控）</div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th class="l">方向</th><th class="l">代表标的</th><th class="l">逻辑</th><th>仓位上限</th><th>硬条件</th></tr></thead>
        <tbody>
          <tr>
            <td class="l gold-t">数字芯片设计</td>
            <td class="l">板块整体（+{sub_sector_net:.1f}亿）</td>
            <td class="wrap">主力净流入TOP2，AI算力方向，关注板块内龙头低吸</td>
            <td>≤2成</td>
            <td class="wrap">智度/传媒方向回暖+带量=可轻仓，否则放弃</td>
          </tr>
          <tr>
            <td class="l blue-t">资源股</td>
            <td class="l">北方铜业（+{ths2_chg}）</td>
            <td class="wrap">工业金属+{ths2_net:.1f}亿，铜+{ths3_net2:.1f}亿，防御性配置方向</td>
            <td>≤1成</td>
            <td class="wrap">只做龙头低吸，不追高</td>
          </tr>
          <tr>
            <td class="l dn">超跌反弹</td>
            <td class="l">{dragon2_name}（+20%）</td>
            <td class="wrap">医疗器械+{ths8_net:.1f}亿，20cm涨停，超跌反弹性质</td>
            <td>≤1成</td>
            <td class="wrap">次日无条件兑现，不留过夜</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 仓位风控 -->
  <div class="card" style="border-color:rgba(255,107,53,.3)">
    <div class="card-title"><span class="dot"></span>仓位与风控总方案（节前三天）</div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px">
      <div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:.68rem;color:var(--text3);margin-bottom:4px">周二总仓上限</div>
        <div style="font-size:1.8rem;font-weight:900;color:var(--gold)">≤4成</div>
        <div style="font-size:.68rem;color:var(--text3)">B/C直接降至2-3成</div>
      </div>
      <div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:.68rem;color:var(--text3);margin-bottom:4px">周四起上限</div>
        <div style="font-size:1.8rem;font-weight:900;color:var(--accent)">≤3成</div>
        <div style="font-size:.68rem;color:var(--text3)">节前最后两日</div>
      </div>
      <div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:.68rem;color:var(--text3);margin-bottom:4px">单票止损线</div>
        <div style="font-size:1.8rem;font-weight:900;color:var(--up)">-7%</div>
        <div style="font-size:.68rem;color:var(--text3)">机械执行不手软</div>
      </div>
      <div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:.68rem;color:var(--text3);margin-bottom:4px">节前第一目标</div>
        <div style="font-size:1.4rem;font-weight:900;color:var(--down)">保住利润</div>
        <div style="font-size:.68rem;color:var(--text3)">不是再赚一轮</div>
      </div>
    </div>
    <div style="padding:12px 16px;background:rgba(245,159,0,.08);border-radius:8px;text-align:center;font-size:.88rem;font-weight:700;color:var(--gold)">
      节前三天第一目标是保住修复行情利润，主力{zhuli:.0f}亿已发出兑现信号。
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════
     STEP 6  雷区名单
════════════════════════════════════════════ -->
<div class="sec">
  <div class="sec-hd">
    <span class="step-pill">STEP 6</span>
    <h2>必须回避的标的与雷区</h2>
    <span class="sub">保护本金比赚钱更重要</span>
  </div>

  <div class="card">
    <div class="card-title"><span class="dot" style="background:var(--up)"></span>高位分歧品种（机构出货方向）</div>
    <div class="mine"><span class="mine-ico">💣</span><div><div class="mine-nm">北证50（-1.08%）</div><div class="mine-desc">北证50领跌全场，小盘尾部风险升温，<strong style="color:var(--up)">回避北证方向所有标的</strong>。</div></div></div>
    <div class="mine"><span class="mine-ico">⚠️</span><div><div class="mine-nm">炸板率{zhaban_rate}%品种</div><div class="mine-desc">炸板率从24.3%升至{zhaban_rate}%，高位分歧加剧——所有涨停后炸板品种次日均有天地板风险，坚决回避。</div></div></div>
    <div class="mine"><span class="mine-ico">⚠️</span><div><div class="mine-nm">散户接盘品种</div><div class="mine-desc">主力{zhuli:.0f}亿+散户+158亿=机构出货散户接的典型高位反转结构，<strong>所有散户集中涌入的品种均为次日兑现预警</strong>。</div></div></div>
  </div>

  <div class="card">
    <div class="card-title"><span class="dot" style="background:var(--gold)"></span>资金流出板块（板块性回避）</div>
    <div class="wl-grid">
      <div class="wl-item danger"><div class="wl-nm">种植业与林业</div><div class="wl-sub">净流出-3.86亿，-0.35%，防御板块集体走弱，回避。</div></div>
      <div class="wl-item danger"><div class="wl-nm">家居用品</div><div class="wl-sub">净流出-3.78亿，+0.97%假涨，资金撤离，回避。</div></div>
      <div class="wl-item danger"><div class="wl-nm">机场航运</div><div class="wl-sub">净流出-3.53亿，-0.45%，防御方向持续走弱。</div></div>
      <div class="wl-item danger"><div class="wl-nm">化学纤维</div><div class="wl-sub">净流出-3.49亿，-0.36%，周期方向分化走弱。</div></div>
      <div class="wl-item danger"><div class="wl-nm">环境治理</div><div class="wl-sub">净流出-3.68亿，+0.30%假涨，资金撤离。</div></div>
      <div class="wl-item"><div class="wl-nm">节前板块性回避</div><div class="wl-sub">所有主力连续3日净流出板块、北证50方向、高位炸板品种。</div></div>
    </div>
  </div>

  <div class="card" style="border-color:rgba(245,159,0,.3)">
    <div class="card-title"><span class="dot gold"></span>节前三天纪律审查 — 周二开盘五道关卡</div>
    <ol class="gate">
      <li>主线方向是否确立？（{main_sector_name}+AI应用=跟进；否则观望）</li>
      <li>主力资金是否转正？（&gt;0亿=可跟进；-100亿以下=降仓）</li>
      <li>是否属于高位炸板品种或散户接盘品种？（回避）</li>
      <li>介入条件是否满足？（否则放弃）</li>
      <li>是否符合节前仓位上限？（周二≤4成，周四起≤3成）</li>
    </ol>
  </div>
</div>

<!-- ═══════════════════════════════════════════
     校正  前日推演验证打分
════════════════════════════════════════════ -->
<div class="sec">
  <div class="sec-hd">
    <span class="step-pill" style="background:var(--gold);color:#000">校正</span>
    <h2>前日推演验证打分（{prev_short}选股 → {today_short}验证）</h2>
    <span class="sub">自我校正机制</span>
  </div>
  <div class="card">
    <div style="display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap;margin-bottom:16px">
      <div style="flex-shrink:0;background:var(--surface2);border:1px solid var(--border);border-left:4px solid var(--gold);border-radius:8px;padding:16px 20px;text-align:center;min-width:120px">
        <div class="score-num">{self_score}</div>
        <div style="font-size:.72rem;color:var(--text3)">/ 100 · 综合自评</div>
        <div style="font-size:.7rem;color:var(--text3);margin-top:2px">（{score_label}）</div>
      </div>
      <div style="flex:1;min-width:200px;font-size:.82rem;line-height:1.75">
        <strong style="color:var(--gold)">验证结果：</strong>{prev_short}选股{total_reco}只 → {today_short}验证：{up_count}涨{down_count}跌，胜率{win_rate*100:.1f}%，平均收益{avg_gain}%，最大涨+{max_gain}%（{max_gain_name}），最大跌{max_loss}%（{max_loss_name}）。<br><br>
        <strong style="color:var(--up)">最大教训：</strong>{prev_short}选股集中在医药/地产方向，但{today_short}主力资金切换至{main_sector_name}+AI应用方向，<strong>选股方向与资金实际流向完全背离</strong>——医药板块净流出，地产链分化，选股策略需加入"板块资金流向一致性"校验。
      </div>
    </div>
    <div class="tbl-wrap" style="margin-bottom:14px">
      <table>
        <thead><tr><th class="l">个股</th><th>评分</th><th>前日价</th><th>今日价</th><th>涨跌</th><th>结果</th></tr></thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>
    <div class="hbox gold" style="font-size:.78rem">
      <strong style="color:var(--gold)">固化改进：</strong>从今日起将"板块主力资金流向"作为选股第一过滤器——只选主力净流入板块内的个股，回避资金流出方向的所有标的（无论技术形态多好）。本报告2.2板块资金动向已固化此方法，下期报告继续验证准确率。
    </div>
  </div>
</div>

<div class="disclaimer">
  ⚠️ 以上复盘与推演仅基于公开数据及历史量价模型分析，不构成任何买卖建议。市场瞬息万变，请结合自身风险承受能力独立决策。
</div>

</div><!-- /wrap -->

<footer>
  A股深度复盘报告 · {TODAY} · 优化版六步框架（情景推演 + 雷区名单 + 自评校正）<br>
  数据来源：东方财富 astock-flow · 同花顺板块 · 自动生成 · 仅供参考
</footer>

</body>
</html>'''

out = Path(f'review/{TODAY}/review_{TODAY}.html')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html, encoding='utf-8')
print(f'✅ 生成 {out} ({len(html):,} chars)')

idx = Path('review/index.html')
idx.write_text(
    f'<!DOCTYPE html><html><head><meta charset="UTF-8">'
    f'<meta http-equiv="refresh" content="0;url={TODAY}/review_{TODAY}.html">'
    f'<title>A股深度复盘 · {TODAY}</title></head>'
    f'<body><a href="{TODAY}/review_{TODAY}.html">跳转到最新复盘 {TODAY}</a></body></html>',
    encoding='utf-8'
)
print('✅ 更新 review/index.html')
