#!/bin/bash
# 每日 15:50 自动运行：检查 GitHub 数据完整性，EM 为空则从本地补推
# 同时把最新策略权重变化记录到 self_heal.log

REPO_DIR="/Users/admin/.assistant/fund_flow_github"
LOCAL_DB="/Users/admin/.assistant/fund_flow/fund_flow.db"
GITHUB_DB="$REPO_DIR/fund_flow.db"
LOG="$REPO_DIR/self_heal.log"
PYTHON="/Library/Developer/CommandLineTools/usr/bin/python3"
DATE=$(TZ='Asia/Shanghai' date '+%Y-%m-%d')
TS=$(TZ='Asia/Shanghai' date '+%Y-%m-%d %H:%M:%S')

echo "[$TS] ===== 自检开始 DATE=$DATE =====" >> "$LOG"

cd "$REPO_DIR"

# 1. 拉取最新远端状态
git pull origin main >> "$LOG" 2>&1

# 2. 检查 EM 板块数据是否存在
EM_COUNT=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('$GITHUB_DB')
n = conn.execute('SELECT COUNT(*) FROM sector_flow_em WHERE date=?', ('$DATE',)).fetchone()[0]
conn.close()
print(n)
" 2>/dev/null)

echo "[$TS] sector_flow_em[$DATE] = $EM_COUNT 条" >> "$LOG"

if [ "$EM_COUNT" = "0" ] || [ -z "$EM_COUNT" ]; then
    echo "[$TS] ⚠️  EM 数据缺失，从本地补推..." >> "$LOG"

    $PYTHON - << PYEOF >> "$LOG" 2>&1
import sqlite3

src = "$LOCAL_DB"
dst = "$GITHUB_DB"
date = "$DATE"

src_conn = sqlite3.connect(src)
dst_conn = sqlite3.connect(dst)

rows = src_conn.execute("""
    SELECT date, sector_code, sector_name, chg_pct, zhuli_net, chaoda_net,
           dadan_net, zhongdan_net, sanhu_net, zhuli_ratio
    FROM sector_flow_em WHERE date=?
""", (date,)).fetchall()

src_conn.close()
print(f"本地 EM 数据: {len(rows)} 条")

if rows:
    dst_conn.executemany("""
        INSERT OR REPLACE INTO sector_flow_em
        (date, sector_code, sector_name, chg_pct, zhuli_net, chaoda_net,
         dadan_net, zhongdan_net, sanhu_net, zhuli_ratio)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, rows)
    dst_conn.commit()
    print(f"补写完成: {len(rows)} 条")
else:
    print("本地也无数据，可能今日非交易日或行情未收盘")

dst_conn.close()
PYEOF

    # 重新导出 JSON
    $PYTHON export_json.py >> "$LOG" 2>&1

    # 提交推送
    git add data/ fund_flow.db >> "$LOG" 2>&1
    git diff --cached --quiet || git commit -m "自愈: 补全 $DATE EM板块数据" >> "$LOG" 2>&1
    git push origin main >> "$LOG" 2>&1
    echo "[$TS] ✅ 补推完成" >> "$LOG"
else
    echo "[$TS] ✅ EM 数据完整，无需补推" >> "$LOG"
fi

# 3. 记录当前权重版本（自我进化日志）
$PYTHON - << PYEOF >> "$LOG" 2>&1
import sqlite3, json
conn = sqlite3.connect("$GITHUB_DB")
row = conn.execute("SELECT updated_date, sample_days, weights_json FROM strategy_weights ORDER BY updated_date DESC LIMIT 1").fetchone()
conn.close()
if row:
    w = json.loads(row[2])
    print(f"当前权重版本: {row[0]}（基于{row[1]}天数据）MACD金叉={w.get('macd_golden')} MA排列={w.get('ma_align')} 0轴={w.get('macd_zero')}")
else:
    print("权重: 使用默认基准（数据积累中）")
PYEOF

echo "[$TS] ===== 自检完成 =====" >> "$LOG"
echo "" >> "$LOG"
