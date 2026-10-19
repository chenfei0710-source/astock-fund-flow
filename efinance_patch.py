#!/usr/bin/env python3
"""efinance 补数据脚本：EM push2 被封时用 efinance 替代拉 stock_reco"""
import efinance as ef
import pandas as pd
import sqlite3, json, sys
from datetime import date, timedelta

DB_PATH = 'fund_flow.db'
TRADE_DATE = sys.argv[1] if len(sys.argv) > 1 else '2026-10-15'

sys.path.insert(0, '.')
from scraper import compute_technicals, save_stock_reco, DEFAULT_WEIGHTS, load_adaptive_weights

def main():
    print(f"=== efinance 补数据: {TRADE_DATE} ===")

    df = ef.stock.get_realtime_quotes()
    df = df[df['股票名称'].notna() & (df['股票名称'] != '')]
    df = df[df['股票代码'].str.match(r'^[036]\d{5}$')]
    for col in ['涨跌幅', '最新价', '量比', '换手率', '昨日收盘', '成交额']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['涨跌幅', '最新价'])
    df = df[df['最新价'] > 0]
    print(f"[efinance] 全市场快照: {len(df)} 只 A 股")

    df_active = df.nlargest(200, '成交额').copy()
    print(f"[efinance] 按 成交额 取 TOP 200")

    print(f"[efinance] 批量拉 history_bill (目标日期 {TRADE_DATE})...")
    fund_flow_data = []
    codes = df_active['股票代码'].tolist()
    for i, code in enumerate(codes):
        try:
            dfb = ef.stock.get_history_bill(code)
            if len(dfb) == 0:
                continue
            row_data = dfb[dfb['日期'] == TRADE_DATE]
            if len(row_data) == 0:
                continue
            r = row_data.iloc[0]
            vol_ratio_val = df_active.loc[df_active['股票代码'] == code, '量比']
            vr = float(vol_ratio_val.iloc[0]) if len(vol_ratio_val) > 0 and pd.notna(vol_ratio_val.iloc[0]) else 1.0
            fund_flow_data.append({
                'code': code,
                'name': r['股票名称'],
                'price': float(r['收盘价']),
                'chg': float(r['涨跌幅']),
                'zhuli': float(r['主力净流入']) / 1e8 if pd.notna(r['主力净流入']) else 0,
                'chaoda': float(r['超大单净流入']) / 1e8 if pd.notna(r['超大单净流入']) else 0,
                'dadan': float(r['大单净流入']) / 1e8 if pd.notna(r['大单净流入']) else 0,
                'vol_ratio': vr,
            })
            if (i+1) % 20 == 0:
                print(f"  {i+1}/{len(codes)} done, {len(fund_flow_data)} 有效")
        except:
            pass

    print(f"[efinance] 获取 {len(fund_flow_data)} 只 {TRADE_DATE} 资金流向数据")

    candidates = [s for s in fund_flow_data if 1.0 <= s['chg'] <= 6.0 and s['zhuli'] > 0]
    if len(candidates) < 15:
        candidates = sorted(fund_flow_data, key=lambda x: x['zhuli'], reverse=True)[:50]
        candidates = [s for s in candidates if s['chg'] <= 6.0 and s['chg'] >= -2.0]
    print(f"[efinance] 筛选后候选: {len(candidates)} 只")

    weights = load_adaptive_weights()
    print(f"[权重] {weights}")

    scored = []
    for s in candidates[:50]:
        code = s['code']
        try:
            dfk = ef.stock.get_quote_history(code, klt=101)
            if len(dfk) < 20:
                continue
            dfk = dfk.sort_values('日期').reset_index(drop=True)
            dfk_before = dfk[dfk['日期'] <= TRADE_DATE]
            dfk_use = dfk_before if len(dfk_before) >= 20 else dfk

            closes = dfk_use['收盘'].astype(float).tolist()
            opens = dfk_use['开盘'].astype(float).tolist()
            volumes = dfk_use['成交量'].astype(float).tolist()

            if len(closes) < 20:
                continue

            tech = compute_technicals(closes, volumes, opens, weights)
            if tech is None:
                continue
            if tech.get('macd_signal') == 'death':
                continue

            s.update(tech)
            s['sector'] = '全市场精选'
            scored.append(s)
            if len(scored) >= 15:
                break
        except Exception as e:
            print(f"  {code} K线失败: {str(e)[:50]}")

    print(f"[efinance] 技术面评分完成: {len(scored)} 只")

    if len(scored) < 15:
        have_codes = {s['code'] for s in scored}
        for s in candidates:
            if s['code'] not in have_codes:
                s.update({
                    'ma5': s['price'], 'ma10': s['price'], 'ma20': s['price'],
                    'ma_align': 1 if s['chg'] > 0 else 0,
                    'macd_signal': 'unknown', 'macd_above_zero': 0,
                    'rsi': 50.0, 'vol_2x': 1 if s['vol_ratio'] >= 2 else 0,
                    'yang_cross': 0, 'pullback_10d': 0,
                    'score': 1, 'signal': '快照估算',
                    'sector': '全市场精选',
                })
                scored.append(s)
                if len(scored) >= 15:
                    break

    scored.sort(key=lambda x: (x.get('score', 0), x.get('zhuli', 0), x['chg']), reverse=True)
    top15 = scored[:15]

    print(f"[efinance] 最终选出 {len(top15)} 只:")
    for s in top15:
        print(f"  {s['code']} {s['name']} 价={s['price']} 涨={s['chg']}% 主力={s['zhuli']:.2f}亿 分={s.get('score',0)} 信号={s.get('signal','?')}")

    if top15:
        reco_data = [{'sector': '全市场精选', 'stocks': top15}]
        save_stock_reco(reco_data, TRADE_DATE)
        print(f"\n✅ stock_reco 已写入 {TRADE_DATE}")
    else:
        print("\n❌ 无可用推荐数据")
        sys.exit(1)

if __name__ == '__main__':
    main()
