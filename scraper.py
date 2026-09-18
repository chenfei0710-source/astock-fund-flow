#!/usr/bin/env python3
"""
A股资金流向日度爬虫 - GitHub Actions 版
数据来源：东方财富（超大单/大单/散户板块拆分）+ 同花顺（行业总体净流向）
"""

import asyncio
import sqlite3
import json
import re
import gzip
import ssl
import urllib.request
from datetime import date
from pathlib import Path

# curl_cffi：模拟 Chrome TLS 指纹，绕过境外 IP 封锁
try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    from curl_cffi import requests as curl_requests
    CURL_AVAILABLE = True
except ImportError:
    CURL_AVAILABLE = False
    print("[警告] curl_cffi 未安装，回退到标准 urllib")

BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "fund_flow.db"

def safe_float(v):
    try:
        return float(v) if v not in (None, '', '-') else 0.0
    except:
        return 0.0

def yi(v):
    return round(safe_float(v) / 1e8, 2)

def today_str():
    # 使用北京时间
    from datetime import timezone, timedelta
    cst = timezone(timedelta(hours=8))
    return date.today().strftime('%Y-%m-%d')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_flow (
            date TEXT PRIMARY KEY,
            zhuli_net REAL, chaoda_net REAL, dadan_net REAL,
            zhongdan_net REAL, sanhu_net REAL, source TEXT,
            ts TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sector_flow_em (
            date TEXT, sector_code TEXT, sector_name TEXT,
            chg_pct REAL, zhuli_net REAL, chaoda_net REAL,
            dadan_net REAL, zhongdan_net REAL, sanhu_net REAL,
            zhuli_ratio REAL,
            ts TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (date, sector_code)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sector_flow_ths (
            date TEXT, sector_name TEXT, sector_index REAL,
            chg_pct REAL, inflow REAL, outflow REAL, net REAL,
            top_stock TEXT, top_chg TEXT,
            ts TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (date, sector_name)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_reco (
            date TEXT, sector_name TEXT,
            stock_code TEXT, stock_name TEXT,
            price REAL, chg_pct REAL, zhuli_net REAL,
            ma5 REAL, ma10 REAL, ma20 REAL,
            ma_align INTEGER,
            macd_signal TEXT, macd_above_zero INTEGER,
            rsi REAL, vol_ratio REAL, vol_2x INTEGER,
            yang_cross INTEGER, pullback_10d INTEGER,
            score INTEGER, signal TEXT,
            PRIMARY KEY (date, stock_code)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS strategy_review (
            review_date TEXT PRIMARY KEY,
            prev_date TEXT,
            total_reco INTEGER,
            up_count INTEGER,
            win_rate REAL,
            avg_gain REAL,
            max_gain REAL,
            max_loss REAL,
            strategy_score INTEGER,
            detail_json TEXT
        )
    """)
    conn.commit()
    conn.close()

# ── 东方财富板块（curl_cffi 直连 → akshare 备用）──────────────
def fetch_em_sector_flow(trade_date):
    # 方案1：curl_cffi 直连 push2 API（Chrome TLS 指纹，绕过封锁）
    items = _fetch_em_sector_curl()
    if items:
        return items
    # 方案2：akshare fallback
    return _fetch_em_sector_akshare()

def _fetch_em_sector_curl():
    """curl_cffi 直连东方财富 push2 板块资金 API"""
    if not CURL_AVAILABLE:
        return []
    print(f"[东方财富] curl_cffi 直连 push2 API...")
    try:
        api_url = (
            "https://push2.eastmoney.com/api/qt/clist/get"
            "?pn=1&pz=200&po=1&np=1"
            "&ut=bd1d9ddb04089700cf9c27f6f7426281"
            "&fltt=2&invt=2&fid=f62"
            "&fs=m:90+t:2+f:!50"
            "&fields=f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"
        )
        resp = curl_requests.get(api_url, headers={
            'Referer': 'https://data.eastmoney.com/zjlx/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        }, impersonate='chrome120', timeout=20)
        if resp.status_code != 200 or not resp.text.strip():
            print(f"[东方财富] curl_cffi 响应异常: {resp.status_code}")
            return []
        result = resp.json()
        raw = result.get('data', {}).get('diff', [])
        if not raw:
            print(f"[东方财富] curl_cffi 返回空数据")
            return []
        items = []
        for item in raw:
            items.append({
                'f12': item.get('f12', ''),
                'f14': str(item.get('f14', '')),
                'f3':  safe_float(item.get('f3')),
                'f62': safe_float(item.get('f62')),   # 原始单位：元
                'f66': safe_float(item.get('f66')),
                'f72': safe_float(item.get('f72')),
                'f78': safe_float(item.get('f78')),
                'f84': safe_float(item.get('f84')),
                'f184': safe_float(item.get('f184')),
                '_pre_converted': False,   # 需要 yi() 转换
            })
        print(f"[东方财富] curl_cffi 获取 {len(items)} 个板块")
        return items
    except Exception as e:
        print(f"[东方财富] curl_cffi 失败: {e}")
        return []

def _fetch_em_sector_akshare():
    print(f"[东方财富] akshare fallback 获取板块资金流向...")
    try:
        import akshare as ak
        df = ak.stock_sector_fund_flow_rank(indicator="今日")
        items = []
        for _, row in df.iterrows():
            def wan2yi(v):
                try: return round(float(v) / 10000, 2)
                except: return 0.0
            items.append({
                'f12': '',
                'f14': str(row.get('名称', '')),
                'f3':  safe_float(row.get('今日涨跌幅', 0)),
                'f62': wan2yi(row.get('主力净流入-净额', 0)),
                'f66': wan2yi(row.get('超大单净流入-净额', 0)),
                'f72': wan2yi(row.get('大单净流入-净额', 0)),
                'f78': wan2yi(row.get('中单净流入-净额', 0)),
                'f84': wan2yi(row.get('小单净流入-净额', 0)),
                'f184': safe_float(row.get('主力净流入-净占比', 0)),
                '_pre_converted': True,
            })
        print(f"[东方财富] akshare 获取 {len(items)} 个板块")
        return items
    except Exception as e:
        print(f"[东方财富] akshare 失败: {e}")
        return []

def save_em_sector_flow(items, trade_date):
    if not items:
        return 0
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    saved = 0
    for item in items:
        code = item.get('f12', '')
        name = item.get('f14', '')
        if not name:
            continue
        # akshare 数据已预转换为亿，原始 API 数据需 yi() 转换
        to_yi = (lambda v: safe_float(v)) if item.get('_pre_converted') else (lambda v: yi(v))
        cur.execute("""
            INSERT OR REPLACE INTO sector_flow_em
            (date, sector_code, sector_name, chg_pct,
             zhuli_net, chaoda_net, dadan_net, zhongdan_net, sanhu_net, zhuli_ratio)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            trade_date, code, name,
            safe_float(item.get('f3')),
            to_yi(item.get('f62')), to_yi(item.get('f66')),
            to_yi(item.get('f72')), to_yi(item.get('f78')),
            to_yi(item.get('f84')), safe_float(item.get('f184')),
        ))
        saved += 1
    conn.commit()
    conn.close()
    print(f"[东方财富] 保存 {saved} 条")
    return saved

# ── 东方财富大盘主力（curl_cffi → akshare fallback）─────────────────────────
def fetch_em_market_flow(trade_date):
    print(f"[大盘主力] 获取中...")
    # 优先 curl_cffi（push2his 通常可访问）
    api_url = (
        "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        "?lmt=5&klt=101&secid=1.000001"
        "&fields1=f1,f2,f3,f7"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    )
    result = None
    try:
        resp = curl_requests.get(api_url, headers={
            'Referer': 'https://data.eastmoney.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        }, impersonate='chrome120', timeout=20)
        if resp.status_code == 200 and resp.text.strip():
            result = resp.json()
    except Exception as e:
        print(f"[大盘主力] curl_cffi 失败: {e}")

    # fallback：akshare
    if not result or not result.get('data'):
        try:
            import akshare as ak
            df = ak.stock_market_fund_flow()
            # 取最近一行作为今日数据
            row = df.iloc[-1]
            zhuli = round(safe_float(row.get('主力净流入-净额', 0)) / 1e8, 2)
            sanhu = round(safe_float(row.get('散户净流入-净额', 0)) / 1e8, 2)
            chaoda = round(safe_float(row.get('超大单净流入-净额', 0)) / 1e8, 2)
            dadan  = round(safe_float(row.get('大单净流入-净额', 0)) / 1e8, 2)
            zhong  = round(safe_float(row.get('中单净流入-净额', 0)) / 1e8, 2)
            print(f"[大盘主力] akshare: 主力={zhuli}亿 超大={chaoda}亿")
            return {
                'date': trade_date, 'zhuli_net': zhuli,
                'chaoda_net': chaoda, 'dadan_net': dadan,
                'zhongdan_net': zhong, 'sanhu_net': sanhu,
                'source': '东方财富'
            }
        except Exception as e:
            print(f"[大盘主力] akshare fallback 失败: {e}")
            return None

    if not result or not result.get('data'):
        print(f"[大盘主力] 无数据")
        return None
    klines = result['data'].get('klines', [])
    target_kline = None
    for kline in reversed(klines):
        parts = kline.split(',')
        if parts[0] == trade_date:
            target_kline = kline
            break
    if target_kline is None and klines:
        target_kline = klines[-1]
    if target_kline:
        parts = target_kline.split(',')
        actual_date = parts[0]
        zhuli  = yi(parts[1]) if len(parts) > 1 else 0
        sanhu  = yi(parts[2]) if len(parts) > 2 else 0
        zhong  = yi(parts[3]) if len(parts) > 3 else 0
        dadan  = yi(parts[4]) if len(parts) > 4 else 0
        chaoda = yi(parts[5]) if len(parts) > 5 else 0
        print(f"[大盘主力] {actual_date}: 主力={zhuli}亿 超大={chaoda}亿 大单={dadan}亿 散户={sanhu}亿")
        return {
            'date': actual_date, 'zhuli_net': zhuli,
            'chaoda_net': chaoda, 'dadan_net': dadan,
            'zhongdan_net': zhong, 'sanhu_net': sanhu,
            'source': '东方财富'
        }
    return None

def save_market_flow(data):
    if not data:
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO market_flow
        (date, zhuli_net, chaoda_net, dadan_net, zhongdan_net, sanhu_net, source)
        VALUES (?,?,?,?,?,?,?)
    """, (
        data['date'], data['zhuli_net'], data['chaoda_net'],
        data['dadan_net'], data['zhongdan_net'], data['sanhu_net'],
        data['source']
    ))
    conn.commit()
    conn.close()

# ── 同花顺行业板块 ─────────────────────────────────────────
def _get_hexin_v():
    import py_mini_racer, importlib, os
    # 找 akshare 包路径获取 ths.js
    import akshare
    akshare_dir = Path(akshare.__file__).parent
    ths_js_path = akshare_dir / "stock_feature" / "ths.js"
    with open(ths_js_path) as f:
        js_content = f.read()
    ctx = py_mini_racer.MiniRacer()
    ctx.eval(js_content)
    return ctx.call("v")

def fetch_ths_sector_flow():
    print("[同花顺] 获取行业资金流向...")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    v_code = _get_hexin_v()
    headers = {
        'Accept': 'text/html, */*; q=0.01',
        'Accept-Encoding': 'gzip, deflate',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'hexin-v': v_code,
        'Host': 'data.10jqka.com.cn',
        'Referer': 'http://data.10jqka.com.cn/funds/hyzjl/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
    }
    url = "http://data.10jqka.com.cn/funds/hyzjl/field/je/order/desc/page/1/ajax/1/free/1/"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        raw_bytes = resp.read()
    if raw_bytes[:2] == b'\x1f\x8b':
        raw_bytes = gzip.decompress(raw_bytes)
    raw = raw_bytes.decode('gbk', errors='replace')
    tbody = re.search(r'<tbody>(.*?)</tbody>', raw, re.S)
    if not tbody:
        return []
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody.group(1), re.S)
    result = []
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        clean = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        if len(clean) >= 10 and clean[1]:
            result.append(clean)
    print(f"[同花顺] 获取 {len(result)} 个行业")
    return result

def fetch_ths_stock_flow(pages=5):
    """同花顺个股资金流向，按净流入降序，抓前 N 页（每页约30只）"""
    print("[同花顺个股] 获取个股资金流向...")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    v_code = _get_hexin_v()
    headers = {
        'Accept': 'text/html, */*; q=0.01',
        'Accept-Encoding': 'gzip, deflate',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'hexin-v': v_code,
        'Host': 'data.10jqka.com.cn',
        'Referer': 'http://data.10jqka.com.cn/funds/gszjl/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
    }
    all_stocks = []
    for page in range(1, pages + 1):
        url = f"http://data.10jqka.com.cn/funds/gszjl/field/zjlr/order/desc/page/{page}/ajax/1/free/1/"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                raw_bytes = resp.read()
            if raw_bytes[:2] == b'\x1f\x8b':
                raw_bytes = gzip.decompress(raw_bytes)
            raw = raw_bytes.decode('gbk', errors='replace')
            tbody = re.search(r'<tbody>(.*?)</tbody>', raw, re.S)
            if not tbody:
                print(f"[同花顺个股] page {page}: 无 tbody，停止")
                break
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody.group(1), re.S)
            page_stocks = []
            for row in rows:
                cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
                clean = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                if len(clean) >= 6 and clean[1]:
                    page_stocks.append(clean)
            if not page_stocks:
                break
            if page == 1 and page_stocks:
                print(f"[同花顺个股] 列样本: {page_stocks[0]}")
            all_stocks.extend(page_stocks)
        except Exception as e:
            print(f"[同花顺个股] page {page} 失败: {e}")
            break
    print(f"[同花顺个股] 共获取 {len(all_stocks)} 只股票")
    return all_stocks

def save_ths_sector_flow(rows, trade_date):
    if not rows:
        return 0
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    saved = 0
    for r in rows:
        if len(r) < 10:
            continue
        try:
            cur.execute("""
                INSERT OR REPLACE INTO sector_flow_ths
                (date, sector_name, sector_index, chg_pct, inflow, outflow, net, top_stock, top_chg)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                trade_date, r[1], safe_float(r[2]),
                safe_float(r[3].replace('%', '')),
                safe_float(r[4]), safe_float(r[5]), safe_float(r[6]),
                r[8] if len(r) > 8 else '',
                r[9] if len(r) > 9 else '',
            ))
            saved += 1
        except Exception as e:
            print(f"  [同花顺] 保存行失败: {e}")
    conn.commit()
    conn.close()
    print(f"[同花顺] 保存 {saved} 条")
    return saved

# ── 个股技术面分析 ────────────────────────────────────────────
def compute_technicals(closes, volumes, opens=None):
    """计算 MA/MACD/RSI/量比/阳线穿均线/MACD0轴/调整10天，返回技术指标字典"""
    if len(closes) < 20:
        return None

    def ema_series(data, n):
        k = 2 / (n + 1)
        result = [data[0]]
        for v in data[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    ma5  = sum(closes[-5:])  / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma_align = 1 if ma5 > ma10 > ma20 else 0

    # MACD
    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = ema_series(dif, 9)
    macd_signal = 'neutral'
    if len(dif) >= 2:
        if dif[-1] > dea[-1] and dif[-2] <= dea[-2]:
            macd_signal = 'golden'
        elif dif[-1] < dea[-1] and dif[-2] >= dea[-2]:
            macd_signal = 'death'

    # MACD 在0轴上方：DIF > 0 且 DEA > 0
    macd_above_zero = 1 if (dif[-1] > 0 and dea[-1] > 0) else 0

    # RSI(14)
    rsi = 50.0
    if len(closes) >= 15:
        changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains  = [max(c, 0) for c in changes[-14:]]
        losses = [abs(min(c, 0)) for c in changes[-14:]]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100.0

    # 量比（今日成交量 / 近5日均量）
    vol_ratio = 1.0
    if volumes and len(volumes) >= 6:
        vol_ma5 = sum(volumes[-6:-1]) / 5
        vol_ratio = volumes[-1] / vol_ma5 if vol_ma5 > 0 else 1.0

    # 放倍量：今日量 >= 2倍 MA5
    vol_2x = 1 if vol_ratio >= 2.0 else 0

    # 阳线穿越均线：今日收盘 > 开盘（阳线），且收盘穿越 MA5/MA10/MA20 中的几条
    yang_cross_count = 0
    if opens and len(opens) >= 1:
        today_open  = opens[-1]
        today_close = closes[-1]
        is_yang = today_close > today_open
        if is_yang:
            for ma in [ma5, ma10, ma20]:
                # 今日收盘在均线上方，且开盘在均线下方（或昨日收盘在均线下方）
                prev_close = closes[-2] if len(closes) >= 2 else today_open
                if today_close > ma and prev_close < ma:
                    yang_cross_count += 1

    # 近10天调整形态：最近10天内有明显回调（最高价到最低价回撤 >= 5%），今日收阳反弹
    pullback_10d = 0
    if len(closes) >= 11:
        window = closes[-11:-1]
        high10 = max(window)
        low10  = min(window)
        if high10 > 0 and (high10 - low10) / high10 >= 0.05:
            # 今日收盘高于近10日均价（反弹）
            avg10 = sum(window) / 10
            if closes[-1] > avg10:
                pullback_10d = 1

    # ── 评分 v2（基于复盘信号命中率重新校准，满分10分）──
    # 复盘实证：MACD金叉命中率71%（最强），均线多头30%/0轴上25%/放倍量0%（负效应）
    score = 0

    # MACD 金叉：最强信号，权重提至+4；死叉强力惩罚
    if macd_signal == 'golden': score += 4
    if macd_signal == 'death':  score -= 3

    # MACD 0轴：复盘命中率仅25%，改为负向调整
    if macd_above_zero:         score -= 1

    # 均线多头排列：命中率仅31%，降权重至+1
    if ma_align:                score += 1

    # RSI：健康区间40-70（收紧），超买强力惩罚
    if 40 <= rsi <= 70:         score += 1
    if rsi > 75:                score -= 2

    # 量比：放倍量命中率0%，去掉；温和放量（1.2-2.5x）保留+1
    if 1.2 <= vol_ratio <= 2.5: score += 1

    # 阳线穿均线：命中率36%，保留但减小权重
    if yang_cross_count >= 2:   score += 2
    elif yang_cross_count == 1: score += 1

    # 10日回调反弹：命中率37.5%，保留
    if pullback_10d:             score += 1

    score = max(0, min(10, score))
    # 映射到0-5
    score5 = round(score / 10 * 5)

    signal = '强烈关注' if score5 >= 4 else ('值得关注' if score5 >= 2 else '观望')

    return {
        'ma5': round(ma5, 2), 'ma10': round(ma10, 2), 'ma20': round(ma20, 2),
        'ma_align': ma_align,
        'macd_signal': macd_signal,
        'macd_above_zero': macd_above_zero,
        'rsi': round(rsi, 1),
        'vol_ratio': round(vol_ratio, 2),
        'vol_2x': vol_2x,
        'yang_cross': yang_cross_count,
        'pullback_10d': pullback_10d,
        'score': score5, 'signal': signal
    }

async def fetch_all_stocks_and_screen(trade_date):
    """
    全市场扫描（沪深两市）：
    1. SSE codes+names via akshare（稳定可用）
    2. SZSE codes 按代码规律生成（无需网络），尝试 akshare 补充中文名
    3. yfinance 批量下载全部 K 线 → 初筛涨幅 0.5%~7% → 技术面评分 → TOP 20
    """
    import akshare as ak
    import yfinance as yf
    import pandas as pd

    stock_codes = {}   # code -> name（无名则空字符串）
    print("[全市场扫描] 获取 A 股代码列表...")

    # ── 上交所（akshare，稳定）──
    try:
        df_sh = ak.stock_info_sh_name_code()
        code_col = next((c for c in df_sh.columns if '代码' in c or 'code' in c.lower()), df_sh.columns[0])
        name_col = next((c for c in df_sh.columns if '简称' in c), None)
        for _, row in df_sh.iterrows():
            code = str(row[code_col]).zfill(6)
            name = str(row[name_col]) if name_col else ''
            if len(code) == 6:
                stock_codes[code] = name
        print(f"[全市场扫描] 上交所: {len(df_sh)} 只（含名称）")
    except Exception as e:
        print(f"[全市场扫描] 上交所失败: {e}")

    # ── 深交所名称（尝试，失败后用代码代替）──
    sz_name_map = {}
    try:
        df_sz = ak.stock_info_sz_name_code()
        code_col = next((c for c in df_sz.columns if '代码' in c), df_sz.columns[0])
        name_col = next((c for c in df_sz.columns if '简称' in c or '名称' in c), None)
        for _, row in df_sz.iterrows():
            code = str(row[code_col]).zfill(6)
            name = str(row[name_col]) if name_col else ''
            if len(code) == 6:
                sz_name_map[code] = name
        print(f"[全市场扫描] 深交所 akshare: {len(sz_name_map)} 只（含名称）")
    except Exception as e:
        print(f"[全市场扫描] 深交所 akshare 失败（按代码规律覆盖）: {e}")

    # ── 深交所代码规律生成（无需网络，100% 可用）──
    sz_ranges = (
        list(range(1,    1000))   # 000001-000999  沪深主板深圳
        + list(range(1001, 2000)) # 001001-001999
        + list(range(2001, 3000)) # 002001-002999  中小板
        + list(range(3001, 3200)) # 003001-003199  注册制新增
        + list(range(300001, 301000)) # 300001-300999 创业板
        + list(range(301001, 301600)) # 301001-301599 创业板注册制
    )
    sz_added = 0
    for n in sz_ranges:
        code = f"{n:06d}"
        if code not in stock_codes:
            stock_codes[code] = sz_name_map.get(code, '')
            sz_added += 1
    print(f"[全市场扫描] 深交所代码规律补充: {sz_added} 个，合计 {len(stock_codes)} 只")

    # ── 过滤纯 A 股（排除 ETF/债券）──
    def is_a_share(code):
        if len(code) != 6: return False
        if code[:2] in ['51','52','53','54','55','56','57','58']: return False
        if code[:2] in ['10','11','12','13','14']: return False
        if code[:3] in ['159','160','161','162','163','164','165']: return False
        return code[0] in '6038' or code[:3] in ['000','001','002','003','004','005']

    all_codes = [(c, n) for c, n in stock_codes.items() if is_a_share(c)]
    print(f"[全市场扫描] 过滤后纯 A 股 {len(all_codes)} 只，开始 yfinance 批量下载...")

    def to_yf(code):
        return f"{code}.SS" if code.startswith(('60', '68', '90')) else f"{code}.SZ"

    yf_to_code = {to_yf(c): c for c, _ in all_codes}
    yf_to_name = {to_yf(c): n for c, n in all_codes}
    yf_tickers  = list(yf_to_code.keys())

    kline_map = {}
    batch_size = 500
    total_batches = (len(yf_tickers) + batch_size - 1) // batch_size

    for i in range(0, len(yf_tickers), batch_size):
        batch = yf_tickers[i:i+batch_size]
        bn = i // batch_size + 1
        print(f"[全市场扫描] yfinance 批次 {bn}/{total_batches}，{len(batch)} 只...")
        try:
            df = yf.download(
                tickers=batch, period='60d', interval='1d',
                auto_adjust=True, progress=False, threads=True,
            )
            if df.empty:
                await asyncio.sleep(1)
                continue

            is_multi = df.columns.nlevels > 1
            for ticker in batch:
                code = yf_to_code.get(ticker, '')
                if not code: continue
                try:
                    if is_multi:
                        lvl0 = df.columns.get_level_values(0)
                        if 'Close' not in lvl0 or ticker not in df['Close'].columns: continue
                        c_ser = df['Close'][ticker]
                        o_ser = df['Open'][ticker]   if 'Open'   in lvl0 and ticker in df['Open'].columns   else pd.Series(dtype=float)
                        v_ser = df['Volume'][ticker] if 'Volume' in lvl0 and ticker in df['Volume'].columns else pd.Series(dtype=float)
                    else:
                        c_ser = df['Close']  if 'Close'  in df.columns else pd.Series(dtype=float)
                        o_ser = df['Open']   if 'Open'   in df.columns else pd.Series(dtype=float)
                        v_ser = df['Volume'] if 'Volume' in df.columns else pd.Series(dtype=float)
                    tmp = pd.DataFrame({'c': c_ser, 'o': o_ser, 'v': v_ser}).dropna(subset=['c'])
                    tmp['o'] = tmp['o'].fillna(0)
                    tmp['v'] = tmp['v'].fillna(0)
                    if len(tmp) >= 5:
                        kline_map[code] = {'closes': tmp['c'].tolist(), 'opens': tmp['o'].tolist(), 'volumes': tmp['v'].tolist()}
                except Exception: pass
            print(f"  批次 {bn}: 累计有效 {len(kline_map)} 只")
        except Exception as e:
            print(f"  批次 {bn} 失败: {e}")
        await asyncio.sleep(1)

    print(f"[全市场扫描] yfinance 完成，有效 {len(kline_map)} 只")
    if not kline_map:
        return [{'sector': '全市场精选', 'stocks': []}], {}

    # ── 初筛：涨 0.5%~7%，非ST ──
    candidates = []
    price_map_from_spot = {}

    for code, kdata in kline_map.items():
        closes = kdata['closes']; opens = kdata['opens']; volumes = kdata['volumes']
        name   = yf_to_name.get(to_yf(code), '') or code

        if len(closes) < 2: continue
        close, prev = closes[-1], closes[-2]
        if prev <= 0 or close <= 0: continue

        chg = (close - prev) / prev * 100
        price_map_from_spot[code] = close

        if name != code and 'ST' in name.upper(): continue  # 有名称才过滤ST
        # v2：涨幅收紧至1%~6%（去掉微涨和追高区间）
        if 1.0 <= chg <= 6.0:
            candidates.append({
                'code': code, 'name': name,
                'price': round(close, 2), 'chg': round(chg, 2), 'zhuli': 0.0,
                'closes': closes, 'opens': opens, 'volumes': volumes,
            })

    candidates.sort(key=lambda x: x['chg'], reverse=True)
    candidates = candidates[:100]
    print(f"[全市场扫描] 初筛 {len(candidates)} 只（涨 1%~6%，非ST）")

    # ── 技术面评分 ──
    scored = []
    for s in candidates:
        closes = s.pop('closes'); opens = s.pop('opens'); volumes = s.pop('volumes')
        tech = compute_technicals(closes, volumes, opens) if len(closes) >= 20 else None
        if tech is None: continue
        # v2：排除死叉股（score5=0时 signal='观望' 已过滤，但死叉可能score仍>0）
        if tech.get('macd_signal') == 'death':
            continue
        scored.append({**s, 'sector': '全市场精选', **tech})

    scored.sort(key=lambda x: (x['score'], x['chg']), reverse=True)
    top15 = scored[:15]

    print(f"[全市场扫描] 评分完成，TOP15：")
    for i, s in enumerate(top15, 1):
        print(f"  {i:2d}. {s['name']}({s['code']}) 评分:{s['score']}/5 涨:{s['chg']:+.2f}% {s['signal']}")

    return [{'sector': '全市场精选', 'stocks': top15}], price_map_from_spot

def save_stock_reco(reco_list, trade_date):
    if not reco_list:
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    saved = 0
    for sector_data in reco_list:
        sname = sector_data['sector']
        for s in sector_data['stocks']:
            cur.execute("""
                INSERT OR REPLACE INTO stock_reco
                (date, sector_name, stock_code, stock_name,
                 price, chg_pct, zhuli_net,
                 ma5, ma10, ma20, ma_align,
                 macd_signal, macd_above_zero,
                 rsi, vol_ratio, vol_2x,
                 yang_cross, pullback_10d,
                 score, signal)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                trade_date, sname, s['code'], s['name'],
                s['price'], s['chg'], s['zhuli'],
                s['ma5'], s['ma10'], s['ma20'], s['ma_align'],
                s['macd_signal'], s['macd_above_zero'],
                s['rsi'], s['vol_ratio'], s['vol_2x'],
                s['yang_cross'], s['pullback_10d'],
                s['score'], s['signal']
            ))
            saved += 1
    conn.commit()
    conn.close()
    print(f"[个股分析] 保存 {saved} 条推荐数据")

def run_strategy_review(trade_date, today_price_map):
    """
    复盘昨日推荐标的今日表现：
    - 胜率（上涨比例）
    - 平均涨跌幅
    - 各信号命中率
    - 策略评分 + 优化建议
    """
    conn = sqlite3.connect(DB_PATH)
    # 找昨日有推荐数据的最近一天
    row = conn.execute(
        "SELECT DISTINCT date FROM stock_reco WHERE date < ? ORDER BY date DESC LIMIT 1",
        (trade_date,)
    ).fetchone()
    if not row:
        conn.close()
        print("[复盘] 无历史推荐数据，跳过")
        return
    prev_date = row[0]

    prev_recos = conn.execute(
        """SELECT stock_code, stock_name, price, score, signal,
                  ma_align, macd_signal, macd_above_zero,
                  rsi, vol_2x, yang_cross, pullback_10d
           FROM stock_reco WHERE date=? ORDER BY score DESC""",
        (prev_date,)
    ).fetchall()
    conn.close()

    if not prev_recos:
        print("[复盘] 昨日无推荐数据")
        return

    detail = []
    gains = []
    signal_hits = {'ma_align':0,'macd_golden':0,'macd_zero':0,'vol_2x':0,'yang_cross':0,'pullback_10d':0}
    signal_total = {k:0 for k in signal_hits}

    for r in prev_recos:
        code, name, prev_price, score, signal = r[0], r[1], r[2], r[3], r[4]
        ma_align, macd_sig, macd_zero, rsi, vol2x, yang, pb10 = r[5], r[6], r[7], r[8], r[9], r[10], r[11]

        today_price = today_price_map.get(str(code), 0)
        if prev_price <= 0 or today_price <= 0:
            continue

        gain = (today_price - prev_price) / prev_price * 100
        gains.append(gain)
        is_up = gain > 0

        detail.append({
            'code': code, 'name': name, 'score': score,
            'signal': signal, 'prev_price': round(prev_price, 2),
            'today_price': round(today_price, 2),
            'gain': round(gain, 2), 'up': is_up
        })

        # 统计各信号命中率
        if ma_align:
            signal_total['ma_align'] += 1
            if is_up: signal_hits['ma_align'] += 1
        if macd_sig == 'golden':
            signal_total['macd_golden'] += 1
            if is_up: signal_hits['macd_golden'] += 1
        if macd_zero:
            signal_total['macd_zero'] += 1
            if is_up: signal_hits['macd_zero'] += 1
        if vol2x:
            signal_total['vol_2x'] += 1
            if is_up: signal_hits['vol_2x'] += 1
        if yang:
            signal_total['yang_cross'] += 1
            if is_up: signal_hits['yang_cross'] += 1
        if pb10:
            signal_total['pullback_10d'] += 1
            if is_up: signal_hits['pullback_10d'] += 1

    if not gains:
        return

    total   = len(gains)
    up_count = sum(1 for g in gains if g > 0)
    win_rate = up_count / total
    avg_gain = sum(gains) / total
    max_gain = max(gains)
    max_loss = min(gains)

    # 策略评分（1-5）
    if win_rate >= 0.7 and avg_gain >= 1.5:
        strat_score = 5
    elif win_rate >= 0.6 and avg_gain >= 0.5:
        strat_score = 4
    elif win_rate >= 0.5:
        strat_score = 3
    elif win_rate >= 0.4:
        strat_score = 2
    else:
        strat_score = 1

    # 信号命中率统计
    signal_stats = {
        k: round(signal_hits[k]/signal_total[k]*100, 1) if signal_total[k] > 0 else None
        for k in signal_hits
    }

    print(f"[复盘] {prev_date} 推荐 {total} 只 → 上涨 {up_count} 只 | 胜率 {win_rate*100:.0f}% | 均涨 {avg_gain:+.2f}%")

    # 自动生成信号调优建议（写入 detail_json 供前端展示）
    tuning_hints = []
    for sig, rate in signal_stats.items():
        if rate is None:
            continue
        if rate >= 65:
            tuning_hints.append(f"{sig} 命中率{rate:.0f}%，表现优异，建议提高权重")
        elif rate < 40:
            tuning_hints.append(f"{sig} 命中率{rate:.0f}%，低于基准，建议降低权重或剔除")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO strategy_review
        (review_date, prev_date, total_reco, up_count, win_rate,
         avg_gain, max_gain, max_loss, strategy_score, detail_json)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        trade_date, prev_date, total, up_count, round(win_rate, 4),
        round(avg_gain, 3), round(max_gain, 3), round(max_loss, 3),
        strat_score, json.dumps({
            'detail': detail,
            'signal_stats': signal_stats,
            'tuning_hints': tuning_hints,
        }, ensure_ascii=False)
    ))
    conn.commit()
    conn.close()
    print(f"[复盘] 策略评分 {strat_score}/5，信号命中率: {signal_stats}")
    if tuning_hints:
        print(f"[复盘] 调优建议: {tuning_hints}")

# ── 主流程 ─────────────────────────────────────────────────
async def main():
    trade_date = today_str()
    print(f"\n{'='*50}")
    print(f"  抓取 {trade_date} 资金流向数据")
    print(f"{'='*50}\n")

    init_db()

    print("── Step 1: 东方财富板块资金 ──")
    em_items = fetch_em_sector_flow(trade_date)
    save_em_sector_flow(em_items, trade_date)

    print("── Step 2: 东方财富大盘主力 ──")
    market_data = fetch_em_market_flow(trade_date)
    save_market_flow(market_data)

    print("── Step 3: 同花顺行业板块 ──")
    try:
        ths_rows = fetch_ths_sector_flow()
        save_ths_sector_flow(ths_rows, trade_date)
    except Exception as e:
        print(f"[同花顺] 失败: {e}")

    print("── Step 4: 全市场个股扫描（资金+技术面精选 TOP20）──")
    price_map = {}
    try:
        reco, price_map = await fetch_all_stocks_and_screen(trade_date)
        save_stock_reco(reco, trade_date)
    except Exception as e:
        print(f"[全市场扫描] 失败: {e}")

    print("── Step 5: 策略复盘（检验昨日推荐表现）──")
    try:
        if price_map:
            run_strategy_review(trade_date, price_map)
        else:
            print("[复盘] 无价格数据，跳过")
    except Exception as e:
        print(f"[复盘] 失败: {e}")

    print(f"\n✅ 完成: {trade_date}")

if __name__ == '__main__':
    asyncio.run(main())
