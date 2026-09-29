#!/usr/bin/env python3
"""
前端 data.json 数据质量校验：确保 export_json.py 导出的字段
能让前端 index.html 正常渲染（不抛 TypeError），且数据非0非空。

用法: python3 verify_data_quality.py [YYYY-MM-DD]
不传日期则检查最新一期

退出码:
  0 = 全部通过
  1 = 发现数据质量问题（打印告警清单）
  2 = 数据文件不存在
"""
import json, sys, sqlite3
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / 'fund_flow.db'
DATA_JSON = ROOT / 'data' / 'data.json'
DATES_JSON = ROOT / 'data' / 'dates.json'

def get_trade_date():
    if len(sys.argv) > 1:
        return sys.argv[1]
    if DATES_JSON.exists():
        dates = json.loads(DATES_JSON.read_text())
        return dates[0] if dates else None
    return None

def check_date(date):
    """校验某一天的数据质量，返回 issues 列表"""
    issues = []

    # 1. 从 db 读
    conn = sqlite3.connect(DB_PATH)
    mf = conn.execute("SELECT zhuli_net, chaoda_net, dadan_net, sanhu_net, source FROM market_flow WHERE date=?", (date,)).fetchone()
    if not mf:
        issues.append("❌ market_flow 表无当日数据")
    else:
        if all(v == 0 for v in mf[:4]):
            issues.append(f"❌ market_flow 主力/超大单/大单/散户全0（source={mf[4]}）")
        if mf[4] and '估算' in mf[4]:
            issues.append(f"⚠️  market_flow 用估算值（source={mf[4]}）—— 主力可能不准")

    idx = conn.execute("SELECT code, name, close, chg_pct FROM index_daily WHERE date=?", (date,)).fetchall()
    if not idx:
        issues.append("❌ index_daily 表无当日数据")
    else:
        zero_chg = [r[1] for r in idx if r[3] == 0]
        if zero_chg:
            issues.append(f"❌ index_daily 涨跌幅全0的指数: {zero_chg}")
        # 必须有上证/深证/创业板
        must_have = {'000001': '上证', '399001': '深证', '399006': '创业板'}
        have = {r[0] for r in idx}
        for code, label in must_have.items():
            if code not in have:
                issues.append(f"⚠️  {label}指数({code}) 缺失")

    ms = conn.execute("SELECT zt_count, dt_count, zb_count, total_amount FROM market_stats WHERE date=?", (date,)).fetchone()
    if not ms:
        issues.append("❌ market_stats 表无当日数据")
    else:
        if ms[0] == 0 and ms[1] == 0:
            issues.append("❌ market_stats 涨停=0 且 跌停=0")
        if ms[3] == 0:
            issues.append("⚠️  market_stats total_amount=0（成交额未抓到）")

    em_count = conn.execute("SELECT COUNT(*), SUM(CASE WHEN zhuli_net=0 OR zhuli_net IS NULL THEN 1 ELSE 0 END) FROM sector_flow_em WHERE date=?", (date,)).fetchone()
    if em_count[0] == 0:
        issues.append("❌ sector_flow_em 表无当日数据")
    elif em_count[1] and em_count[1] > 5:
        issues.append(f"⚠️  sector_flow_em 有 {em_count[1]} 条 zhuli_net=0/NULL（超过5条）")

    ths_count = conn.execute("SELECT COUNT(*) FROM sector_flow_ths WHERE date=?", (date,)).fetchone()
    if ths_count[0] == 0:
        issues.append("❌ sector_flow_ths 表无当日数据")

    sr_count = conn.execute("SELECT COUNT(*), SUM(CASE WHEN price=0 OR price IS NULL THEN 1 ELSE 0 END), SUM(CASE WHEN chg_pct=0 OR chg_pct IS NULL THEN 1 ELSE 0 END) FROM stock_reco WHERE date=?", (date,)).fetchone()
    if sr_count[0] == 0:
        issues.append("❌ stock_reco 表无当日推荐（个股机会模块将不显示）")
    else:
        if sr_count[1]:
            issues.append(f"❌ stock_reco 有 {sr_count[1]} 条 price=0/NULL")
        if sr_count[2]:
            issues.append(f"❌ stock_reco 有 {sr_count[2]} 条 chg_pct=0/NULL")
        # 检查 score 是否全0（Plan C 兜底时）
        score_zero = conn.execute("SELECT COUNT(*) FROM stock_reco WHERE date=? AND score=0", (date,)).fetchone()[0]
        if sr_count[0] > 0 and score_zero == sr_count[0]:
            issues.append(f"⚠️  stock_reco 所有 {sr_count[0]} 条 score=0（疑似 Plan C 兜底，无技术面评分）")

    rv = conn.execute("SELECT total_reco, up_count, win_rate, detail_json FROM strategy_review WHERE review_date=?", (date,)).fetchone()
    if not rv:
        issues.append("❌ strategy_review 表无当日复盘数据")
    else:
        if rv[3]:
            detail = json.loads(rv[3])
            detail_count = len(detail.get('detail', []))
            if detail_count != rv[0]:
                issues.append(f"❌ strategy_review total_reco={rv[0]} 但 detail 只有 {detail_count} 条")
            if not detail.get('signal_stats'):
                issues.append("❌ strategy_review signal_stats 为空")
        else:
            issues.append("❌ strategy_review detail_json 为 NULL（昨日推荐股票价格未补全）")
    conn.close()

    # 2. 从 data.json 读，校验前端字段
    if not DATA_JSON.exists():
        issues.append("❌ data/data.json 不存在")
        return issues
    all_data = json.loads(DATA_JSON.read_text())
    if date not in all_data:
        issues.append(f"❌ data/data.json 中无 {date} 数据")
        return issues
    item = all_data[date]

    # 校验前端 stock_reco 渲染所需的字段
    sr_json = item.get('stock_reco', [])
    for i, s in enumerate(sr_json):
        for f in ['code', 'name', 'price', 'chg', 'vol_ratio']:
            if f not in s or s[f] is None:
                issues.append(f"❌ data.json stock_reco[{i}] 缺字段 {f}={s.get(f)}")
        # rsi 可以为 null，但前端要兜底
        if s.get('rsi') is not None and not isinstance(s.get('rsi'), (int, float)):
            issues.append(f"❌ data.json stock_reco[{i}] rsi 类型异常: {s.get('rsi')}")

    # 校验 strategy_review
    srv = item.get('strategy_review')
    if srv:
        detail = srv.get('detail', [])
        if not detail and srv.get('total', 0) > 0:
            issues.append(f"❌ data.json strategy_review.total={srv['total']} 但 detail 为空")

    return issues

def main():
    date = get_trade_date()
    if not date:
        print("❌ 找不到任何日期（data/dates.json 为空）")
        sys.exit(2)
    print(f"=== 前端数据质量校验 {date} ===\n")
    issues = check_date(date)
    if not issues:
        print("✅ 全部通过：data.json 字段完整，db 数据非0非空")
        sys.exit(0)
    else:
        print(f"发现 {len(issues)} 处问题:\n")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        sys.exit(1)

if __name__ == '__main__':
    main()
