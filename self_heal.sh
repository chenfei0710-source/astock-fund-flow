#!/bin/bash
# 每日 15:50 自动运行：记录策略权重进化日志
# EM 数据已降级为可选，同花顺为主数据源，无需本地补推

REPO_DIR="/Users/admin/.assistant/fund_flow_github"
GITHUB_DB="$REPO_DIR/fund_flow.db"
LOG="$REPO_DIR/self_heal.log"
PYTHON="/Library/Developer/CommandLineTools/usr/bin/python3"
DATE=$(TZ='Asia/Shanghai' date '+%Y-%m-%d')
TS=$(TZ='Asia/Shanghai' date '+%Y-%m-%d %H:%M:%S')

echo "[$TS] ===== 自检开始 DATE=$DATE =====" >> "$LOG"

cd "$REPO_DIR"

# 1. 拉取最新远端状态
git pull --ff-only origin main >> "$LOG" 2>&1 || git pull --rebase origin main >> "$LOG" 2>&1

# 2. 检查同花顺数据完整性（主数据源）
THS_COUNT=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('$GITHUB_DB')
n = conn.execute('SELECT COUNT(*) FROM sector_flow_ths WHERE date=?', ('$DATE',)).fetchone()[0]
conn.close()
print(n)
" 2>/dev/null)

echo "[$TS] sector_flow_ths[$DATE] = $THS_COUNT 条" >> "$LOG"

if [ "$THS_COUNT" = "0" ] || [ -z "$THS_COUNT" ]; then
    echo "[$TS] ⚠️  同花顺数据为空，可能今日非交易日或 GitHub Actions 尚未完成" >> "$LOG"
else
    echo "[$TS] ✅ 同花顺数据完整" >> "$LOG"
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
