#!/usr/bin/env python3
"""
报告数据自检：对照 HTML 里的数值与数据库真实值
用法: python3 verify_report.py [YYYY-MM-DD]
不传日期则检查最新一期

退出码:
  0 = 全部通过
  1 = 有数据不一致（打印告警清单）
  2 = 报告/数据库不存在
"""
import sqlite3, re, sys, json
from pathlib import Path

DB_PATH = Path(__file__).parent / 'fund_flow.db'
REVIEW_DIR = Path(__file__).parent / 'review'

def get_trade_date():
    if len(sys.argv) > 1:
        return sys.argv[1]
    # 最新一期
    dirs = sorted([d.name for d in REVIEW_DIR.iterdir() if d.is_dir() and re.match(r'\d{4}-\d{2}-\d{2}', d.name)])
    return dirs[-1] if dirs else None

def load_db(date):
    conn = sqlite3.connect(DB_PATH)
    db = {}
    # market_flow
    row = conn.execute("SELECT zhuli_net, chaoda_net, dadan_net, zhongdan_net, sanhu_net, source FROM market_flow WHERE date=?", (date,)).fetchone()
    if row:
        db['zhuli'] = row[0]; db['chaoda'] = row[1]; db['dadan'] = row[2]
        db['zhongdan'] = row[3]; db['sanhu'] = row[4]; db['mf_source'] = row[5]
    # index_daily
    db['indices'] = {}
    for r in conn.execute("SELECT code, name, close, chg_pct FROM index_daily WHERE date=?", (date,)):
        db['indices'][r[0]] = {'name': r[1], 'close': r[2], 'chg': r[3]}
    # market_stats
    row = conn.execute("SELECT zt_count, dt_count, zb_count, zhaban_rate, jinji_rate, max_lb, max_lb_stock, total_amount FROM market_stats WHERE date=?", (date,)).fetchone()
    if row:
        db['zt'] = row[0]; db['dt'] = row[1]; db['zb'] = row[2]
        db['zhaban'] = row[3]; db['jinji'] = row[4]; db['max_lb'] = row[5]
        db['max_lb_stock'] = row[6]; db['total_amount'] = row[7] or 0
    # sector_flow_em top1
    row = conn.execute("SELECT sector_name, zhuli_net FROM sector_flow_em WHERE date=? ORDER BY zhuli_net DESC LIMIT 1", (date,)).fetchone()
    if row:
        db['em_top1_name'] = row[0]; db['em_top1_net'] = row[1]
    conn.close()
    return db

def load_html(date):
    p = REVIEW_DIR / date / f'review_{date}.html'
    if not p.exists():
        return None
    return p.read_text(encoding='utf-8')

# ── 检查项：(HTML 抽取函数, 期望值, 字段名, 容差) ──
def check(html, db):
    issues = []
    def find_num(pattern, text, default=None):
        m = re.search(pattern, text)
        return float(m.group(1)) if m else default

    # 1. 两市成交额
    if db.get('total_amount'):
        v = find_num(r'两市成交</div><div class="num"[^>]*>([\d.]+)亿', html)
        if v and abs(v - db['total_amount']) > 1:
            issues.append(f"两市成交额: HTML={v} DB={db['total_amount']}")

    # 2. 主力净流入（KPI 卡 + 叙事段）
    if 'zhuli' in db:
        # KPI 卡里的主力值
        v = find_num(r'主力净流出</div><div class="num"[^>]*>([\d.]+)亿', html)
        if not v:
            v = find_num(r'主力净流入</div><div class="num"[^>]*>([\d.]+)亿', html)
        if v and abs(v - abs(db['zhuli'])) > 1:
            issues.append(f"主力KPI卡: HTML={v} DB={abs(db['zhuli'])}")

        # 量能关键信号段
        v = find_num(r'主力净流出([-\d.]+)亿', html)
        if v and abs(v - db['zhuli']) > 1:
            issues.append(f"主力净流出叙事: HTML={v} DB={db['zhuli']}")

        # 超大单（注意"大单"会误匹配到"超大单"，用边界排除）
        v = find_num(r'超大单([-\d.]+)亿', html)
        if v and db.get('chaoda') is not None and abs(v - db['chaoda']) > 1:
            issues.append(f"超大单: HTML={v} DB={db['chaoda']}")

        # 大单：用负向断言排除"超大单"
        v = find_num(r'(?<!超)大单([-\d.]+)亿', html)
        if v and db.get('dadan') is not None and abs(v - db['dadan']) > 1:
            issues.append(f"大单: HTML={v} DB={db['dadan']}")

        # 散户
        v = find_num(r'散户净流入\+?([-\d.]+)亿', html)
        if v and db.get('sanhu') is not None and abs(v - db['sanhu']) > 1:
            issues.append(f"散户净流入: HTML={v} DB={db['sanhu']}")

        # 中单
        v = find_num(r'中单([-\d.]+)亿', html)
        if v and db.get('zhongdan') is not None and abs(v - db['zhongdan']) > 0.5:
            issues.append(f"中单: HTML={v} DB={db['zhongdan']}")

    # 3. 指数涨跌（上证/深证/创业板/科创50/北证50）
    idx_codes = {'000001': '上证', '399001': '深证', '399006': '创业板', '000688': '科创50', '899050': '北证50'}
    for code, label in idx_codes.items():
        if code in db.get('indices', {}):
            chg = db['indices'][code]['chg']
            close = db['indices'][code]['close']
            # 查 HTML 里 "上证 <b ...>3824 ↓ -1.67%</b>" 或 KPI 卡
            m = re.search(rf'{label}[^<]*<b[^>]*>([\d.]+)\s*[↑↓]\s*([+-]?[\d.]+)%</b>', html)
            if m:
                html_close = float(m.group(1))
                html_chg = float(m.group(2))
                if abs(html_close - close) > 5:
                    issues.append(f"{label}收盘: HTML={html_close} DB={close}")
                if abs(html_chg - chg) > 0.05:
                    issues.append(f"{label}涨跌: HTML={html_chg}% DB={chg}%")

    # 4. 涨停/跌停/炸板/连板
    if 'zt' in db:
        # KPI 卡 "涨停 / 跌停" 合并显示 "33 / 56"
        m = find_num(r'涨停\s*/\s*跌停</div><div class="num"[^>]*>(\d+)\s*/\s*(\d+)', html)
        if m:
            # 实际返回的是第一个数，需要重新抓
            pass
        m = re.search(r'涨停\s*/\s*跌停</div><div class="num"[^>]*>(\d+)\s*/\s*(\d+)', html)
        if m:
            zt_html = int(m.group(1)); dt_html = int(m.group(2))
            if zt_html != db['zt']:
                issues.append(f"涨停KPI: HTML={zt_html} DB={db['zt']}")
            if dt_html != db['dt']:
                issues.append(f"跌停KPI: HTML={dt_html} DB={db['dt']}")
        v = find_num(r'炸板率</div><div class="num"[^>]*>([\d.]+)', html)
        if v and abs(float(v) - db['zhaban']) > 0.1:
            issues.append(f"炸板率KPI: HTML={v} DB={db['zhaban']}")
        v = find_num(r'连板高度</div><div class="num"[^>]*>(\d+)板', html)
        if v and int(v) != db['max_lb']:
            issues.append(f"连板高度KPI: HTML={int(v)} DB={db['max_lb']}")
        # 叙事段"涨停 N 家、跌停 N 家"
        m = re.search(r'涨停\s*(\d+)\s*家[、,]?\s*跌停\s*(\d+)\s*家', html)
        if m:
            zt_html = int(m.group(1)); dt_html = int(m.group(2))
            if zt_html != db['zt']:
                issues.append(f"涨停叙事: HTML={zt_html} DB={db['zt']}")
            if dt_html != db['dt']:
                issues.append(f"跌停叙事: HTML={dt_html} DB={db['dt']}")

    # 5. 板块 TOP1
    if 'em_top1_name' in db and db['em_top1_net'] > 0:
        if db['em_top1_name'] not in html:
            issues.append(f"EM板块TOP1 '{db['em_top1_name']}' 在 HTML 中未找到")

    return issues

def main():
    date = get_trade_date()
    if not date:
        print("❌ 找不到任何报告日期")
        sys.exit(2)
    print(f"=== 报告自检 {date} ===")
    html = load_html(date)
    if html is None:
        print(f"❌ 报告文件不存在: review/{date}/review_{date}.html")
        sys.exit(2)
    db = load_db(date)
    if not db:
        print(f"❌ 数据库无 {date} 数据")
        sys.exit(2)

    # 数据完整性预警
    if db.get('mf_source') and '估算' in db['mf_source']:
        print(f"⚠️  market_flow 用估算值（source={db['mf_source']}）—— 主力/超大单/大单可能不准")
    if db.get('total_amount', 0) == 0:
        print(f"⚠️  total_amount=0 —— HTML 应显示 '--'")
    for code, label in [('000001','上证'),('399001','深证'),('399006','创业板')]:
        if code not in db.get('indices', {}):
            print(f"⚠️  {label}指数 数据缺失")

    issues = check(html, db)
    if not issues:
        print("✅ 全部通过：HTML 数据与数据库一致")
        sys.exit(0)
    else:
        print(f"❌ 发现 {len(issues)} 处不一致:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        sys.exit(1)

if __name__ == '__main__':
    main()
