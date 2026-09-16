#!/usr/bin/env python3
"""从 SQLite 导出最近60天数据为 JSON，供静态网页读取"""

import sqlite3
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "fund_flow.db"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

def export():
    conn = sqlite3.connect(DB_PATH)

    # 所有交易日期列表
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM sector_flow_em ORDER BY date DESC LIMIT 60"
    ).fetchall()]

    all_data = {}
    for d in dates:
        # 大盘主力
        mf = conn.execute(
            "SELECT zhuli_net,chaoda_net,dadan_net,zhongdan_net,sanhu_net FROM market_flow WHERE date=?", (d,)
        ).fetchone()
        market = dict(zip(['zhuli','chaoda','dadan','zhongdan','sanhu'], mf)) if mf else None

        # 东方财富板块
        em_rows = conn.execute("""
            SELECT sector_name, chg_pct, zhuli_net, chaoda_net, dadan_net,
                   zhongdan_net, sanhu_net, zhuli_ratio
            FROM sector_flow_em WHERE date=? ORDER BY zhuli_net DESC
        """, (d,)).fetchall()
        em_sectors = [
            dict(zip(['name','chg','zhuli','chaoda','dadan','zhongdan','sanhu','ratio'], r))
            for r in em_rows
        ]

        # 同花顺板块
        ths_rows = conn.execute("""
            SELECT sector_name, chg_pct, inflow, outflow, net, top_stock, top_chg
            FROM sector_flow_ths WHERE date=? ORDER BY net DESC
        """, (d,)).fetchall()
        ths_sectors = [
            dict(zip(['name','chg','inflow','outflow','net','top_stock','top_chg'], r))
            for r in ths_rows
        ]

        all_data[d] = {
            'market': market,
            'em_sectors': em_sectors,
            'ths_sectors': ths_sectors,
        }

    conn.close()

    # 写入 dates.json 和 data.json
    with open(DATA_DIR / "dates.json", 'w', encoding='utf-8') as f:
        json.dump(dates, f, ensure_ascii=False)

    with open(DATA_DIR / "data.json", 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, separators=(',', ':'))

    print(f"✅ 导出 {len(dates)} 个交易日数据 → data/")

if __name__ == '__main__':
    export()
