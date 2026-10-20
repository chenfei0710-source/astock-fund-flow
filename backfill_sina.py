#!/usr/bin/env python3
"""Plan E 补抓脚本：EM 全站 403 时，用 akshare stock_zh_a_spot（新浪）+ THS + akshare 涨停池
用法:
  python3 backfill_sina.py 2026-10-20 --live   # 实时模式：用新浪全市场快照（适合今日盘中/收盘后）
  python3 backfill_sina.py 2026-10-19         # 历史模式：用 stock_zh_a_hist 按涨幅榜单逐只拉（慢，5000 只×2秒）
补抓指定日期的 stock_reco（个股推荐）。
"""
import sys, os, sqlite3, asyncio
from pathlib import Path
from datetime import date, timedelta
import argparse

REPO = Path(__file__).parent
DB_PATH = REPO / "fund_flow.db"

# 复用 scraper.py 的函数
sys.path.insert(0, str(REPO))
import scraper  # noqa
from scraper import (
    save_stock_reco, compute_technicals, load_adaptive_weights,
    fetch_ths_stock_flow, DEFAULT_WEIGHTS, save_ths_sector_flow,
)


def fetch_sina_spot():
    """用 akshare 新浪接口拉全市场实时快照"""
    import akshare as ak
    df = ak.stock_zh_a_spot()
    print(f"[Plan E] 新浪快照 {len(df)} 只")
    return df


def sina_df_to_candidates(df, ths_stock_map):
    """新浪 DataFrame → 候选列表"""
    candidates = []
    for _, row in df.iterrows():
        try:
            raw_code = str(row['代码'])
            # 新浪代码格式：sh600519 / sz000001 / bj920000
            if raw_code.startswith(('sh', 'sz', 'bj')):
                code = raw_code[2:]
                market_prefix = raw_code[:2]
            else:
                code = raw_code.zfill(6)
                market_prefix = ''
            # 过滤北交所（数据少、流动性差）
            if market_prefix == 'bj' or raw_code.startswith('bj'):
                continue
            name = str(row['名称'])
            close = float(row['最新价'])
            chg = float(row['涨跌幅'])
            # 过滤 ST / 新股
            if 'ST' in name or name.startswith(('N', 'C')):
                continue
            if close <= 0 or not (1.0 <= chg <= 6.0):
                continue
            vol = float(row['成交量']) if '成交量' in row else 0
            if vol <= 0:
                continue
            zhuli = ths_stock_map.get(code, 0.0)
            amount = float(row['成交额']) if '成交额' in row else 0
            prev_close = float(row['昨收']) if '昨收' in row else close
            today_open = float(row['今开']) if '今开' in row else close
            today_high = float(row['最高']) if '最高' in row else close
            today_low = float(row['最低']) if '最低' in row else close
            amplitude = round((today_high - today_low) / prev_close * 100, 2) if prev_close > 0 else 0
            vol_ratio = 1.0
            candidates.append({
                'code': code, 'name': name,
                'price': round(close, 2), 'chg': round(chg, 2),
                'zhuli': zhuli,
                'vol_ratio': vol_ratio,
                'vol_2x': 1.0 if vol_ratio >= 2 else 0,
                'today_open': today_open, 'prev_close': prev_close,
                'today_high': today_high, 'today_low': today_low,
                'amplitude': amplitude,
                'amount': amount,
            })
        except (ValueError, TypeError, KeyError):
            continue
    candidates.sort(key=lambda x: (x['zhuli'], x['chg'], x['amount']), reverse=True)
    return candidates


def _enrich_with_klines(candidates, trade_date, top_n=30, target_count=15):
    """拉历史 K 线算技术面，返回 enriched 列表"""
    import akshare as ak
    weights = load_adaptive_weights()
    top = candidates[:top_n]
    print(f"[Plan E] TOP{top_n} 候选，开始拉历史 K 线")

    scored = []
    kline_fetched = 0
    today_obj = date.fromisoformat(trade_date)
    beg = (today_obj - timedelta(days=120)).strftime('%Y%m%d')
    end = today_obj.strftime('%Y%m%d')

    for s in top:
        code = s['code']
        klines = None
        for attempt in range(2):
            try:
                df_k = ak.stock_zh_a_hist(symbol=code, period='daily',
                                          start_date=beg, end_date=end, adjust='qfq')
                if df_k is not None and not df_k.empty:
                    klines = df_k
                    break
            except Exception as e:
                if attempt == 1:
                    print(f"  [K线] {code} 失败: {str(e)[:60]}")
                import time; time.sleep(0.3)
        if klines is None or len(klines) < 5:
            continue
        kline_fetched += 1
        closes = klines['收盘'].astype(float).tolist()
        opens = klines['开盘'].astype(float).tolist()
        volumes = klines['成交量'].astype(float).tolist()
        if len(closes) < 5:
            continue
        tech = compute_technicals(closes, volumes, opens, weights) if len(closes) >= 20 else None
        if tech is None:
            tech = {'ma5': closes[-1], 'ma10': closes[-1], 'ma20': closes[-1],
                    'ma_align': 0, 'macd_signal': 'unknown', 'macd_above_zero': 0,
                    'rsi': 50.0, 'vol_2x': s['vol_2x'],
                    'yang_cross': 0, 'pullback_10d': 0,
                    'score': 1, 'signal': '数据不足'}
        if tech.get('macd_signal') == 'death':
            continue
        scored.append({**s, 'sector': '全市场精选', 'market_regime': 'normal', **tech})
        if len(scored) >= target_count:
            break
        import time; time.sleep(0.15)

    print(f"[Plan E] K线拉取 {kline_fetched}/{top_n} 只，评分后 {len(scored)} 只")

    # 兜底：不足 target_count 补快照估算
    if len(scored) < target_count:
        have = {s['code'] for s in scored}
        for s in top:
            if s['code'] not in have:
                today_open = s.get('today_open', s['price'])
                prev_close = s.get('prev_close', s['price'])
                yang_cross = 1 if (today_open < prev_close and s['price'] > prev_close) else 0
                s.update({
                    'ma5': s['price'], 'ma10': s['price'], 'ma20': s['price'],
                    'ma_align': 1 if s['price'] > prev_close else 0,
                    'macd_signal': 'unknown', 'macd_above_zero': 0,
                    'rsi': 50.0, 'yang_cross': yang_cross, 'pullback_10d': 0,
                    'score': 1, 'signal': '快照估算',
                })
                scored.append(s)
                if len(scored) >= target_count:
                    break

    scored.sort(key=lambda x: (x.get('score', 0), x.get('zhuli', 0), x['chg']), reverse=True)
    return scored[:target_count]


async def backfill_live(trade_date):
    """实时模式：用新浪全市场快照，适合今天"""
    print(f"===== Plan E 补抓（实时模式）{trade_date} =====")

    try:
        ths_rows = fetch_ths_stock_flow(pages=5)
        save_ths_sector_flow(ths_rows, trade_date)
        ths_map = {r[2]: float(r[5]) for r in ths_rows if r[2] and r[5]}
        print(f"[THS] 个股资金流 {len(ths_map)} 只")
    except Exception as e:
        print(f"[THS] 失败（继续，主力字段用 0）: {e}")
        ths_map = {}

    df = fetch_sina_spot()
    candidates = sina_df_to_candidates(df, ths_map)
    print(f"[候选] 过滤后 {len(candidates)} 只（涨幅 1-6%，非ST/新股/北交所）")

    if not candidates:
        print("❌ 无候选，退出")
        return

    top15 = _enrich_with_klines(candidates, trade_date, top_n=30, target_count=15)

    if top15:
        save_stock_reco([{'sector': '全市场精选', 'stocks': top15}], trade_date)
        print(f"✅ 保存 {len(top15)} 只 stock_reco for {trade_date}")
    else:
        print(f"❌ 无有效推荐 for {trade_date}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('date', help='YYYY-MM-DD')
    parser.add_argument('--live', action='store_true', help='用新浪实时快照（适合今天）')
    args = parser.parse_args()

    if args.live:
        asyncio.run(backfill_live(args.date))
    else:
        print("历史模式暂未实现，请加 --live")
        sys.exit(1)
