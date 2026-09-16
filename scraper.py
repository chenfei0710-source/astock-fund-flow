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
    conn.commit()
    conn.close()

# ── 东方财富板块（Playwright）──────────────────────────────
async def fetch_em_sector_flow(trade_date):
    from playwright.async_api import async_playwright
    print(f"[东方财富] 启动 Playwright...")
    items = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            locale='zh-CN',
        )
        page = await context.new_page()
        try:
            await page.goto('https://data.eastmoney.com/zjlx/', timeout=20000)
        except Exception as e:
            print(f"[东方财富] 页面加载: {type(e).__name__}")
        await asyncio.sleep(3)

        api_url = (
            "https://push2.eastmoney.com/api/qt/clist/get"
            "?pn=1&pz=200&po=1&np=1"
            "&ut=bd1d9ddb04089700cf9c27f6f7426281"
            "&fltt=2&invt=2&fid=f62"
            "&fs=m:90+t:2+f:!50"
            "&fields=f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"
        )
        result = await page.evaluate(f"""
            async () => {{
                const resp = await fetch("{api_url}", {{
                    credentials: 'include',
                    headers: {{
                        'Accept': 'application/json, */*',
                        'Referer': 'https://data.eastmoney.com/zjlx/'
                    }}
                }});
                return await resp.json();
            }}
        """)
        await browser.close()
        if result and result.get('data') and result['data'].get('diff'):
            items = result['data']['diff']
            print(f"[东方财富] 获取 {len(items)} 个板块")
        else:
            print(f"[东方财富] 无数据: {str(result)[:200]}")
    return items

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
        cur.execute("""
            INSERT OR REPLACE INTO sector_flow_em
            (date, sector_code, sector_name, chg_pct,
             zhuli_net, chaoda_net, dadan_net, zhongdan_net, sanhu_net, zhuli_ratio)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            trade_date, code, name,
            safe_float(item.get('f3')),
            yi(item.get('f62')), yi(item.get('f66')),
            yi(item.get('f72')), yi(item.get('f78')),
            yi(item.get('f84')), safe_float(item.get('f184')),
        ))
        saved += 1
    conn.commit()
    conn.close()
    print(f"[东方财富] 保存 {saved} 条")
    return saved

# ── 东方财富大盘主力（Playwright）─────────────────────────
async def fetch_em_market_flow(trade_date):
    from playwright.async_api import async_playwright
    print(f"[大盘主力] 获取中...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            locale='zh-CN',
        )
        page = await context.new_page()
        try:
            await page.goto('https://data.eastmoney.com/zjlx/', timeout=20000)
        except:
            pass
        await asyncio.sleep(2)
        api_url = (
            "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
            "?lmt=5&klt=101&secid=1.000001"
            "&fields1=f1,f2,f3,f7"
            "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        )
        result = await page.evaluate(f"""
            async () => {{
                const resp = await fetch("{api_url}", {{
                    credentials: 'include',
                    headers: {{'Referer': 'https://data.eastmoney.com/'}}
                }});
                return await resp.json();
            }}
        """)
        await browser.close()
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

# ── 主流程 ─────────────────────────────────────────────────
async def main():
    trade_date = today_str()
    print(f"\n{'='*50}")
    print(f"  抓取 {trade_date} 资金流向数据")
    print(f"{'='*50}\n")

    init_db()

    print("── Step 1: 东方财富板块资金 ──")
    em_items = await fetch_em_sector_flow(trade_date)
    save_em_sector_flow(em_items, trade_date)

    print("── Step 2: 东方财富大盘主力 ──")
    market_data = await fetch_em_market_flow(trade_date)
    save_market_flow(market_data)

    print("── Step 3: 同花顺行业板块 ──")
    try:
        ths_rows = fetch_ths_sector_flow()
        save_ths_sector_flow(ths_rows, trade_date)
    except Exception as e:
        print(f"[同花顺] 失败: {e}")

    print(f"\n✅ 完成: {trade_date}")

if __name__ == '__main__':
    asyncio.run(main())
