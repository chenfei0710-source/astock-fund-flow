#!/bin/bash
# 每日 17:35 自动跑数据校验 + 生成给用户的 review 汇总
# 在 notify.sh 推送飞书后跑，做更详细的完整性检查，结果通过 macOS 通知提醒
# 如果有数据质量问题，提醒用户检查

export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Library/Developer/CommandLineTools/usr/bin:$PATH"

REPO_DIR="/Users/admin/.assistant/fund_flow_github"
PYTHON="/Library/Developer/CommandLineTools/usr/bin/python3"
DATE=$(TZ='Asia/Shanghai' date '+%Y-%m-%d')
TS=$(TZ='Asia/Shanghai' date '+%H:%M:%S')
LOG="$REPO_DIR/daily_review.log"

cd "$REPO_DIR" || exit 1

# 拉最新
token=$(security find-internet-password -s github.com -w 2>/dev/null)
if [ -n "$token" ]; then
    git pull --ff-only "https://chenfei0710-source:${token}@github.com/chenfei0710-source/astock-fund-flow.git" main >> "$LOG" 2>&1 || \
    git pull --rebase "https://chenfei0710-source:${token}@github.com/chenfei0710-source/astock-fund-flow.git" main >> "$LOG" 2>&1
fi

echo "[$TS] ===== 每日 Review $DATE =====" >> "$LOG"

# 时间窗：只在 17:30-23:00 才允许推送异常通知，避免上午盘前误报
HOUR=$(TZ='Asia/Shanghai' date '+%H')
PUSH_NOTIFY=1
if [ "$HOUR" -lt 17 ] || [ "$HOUR" -ge 23 ]; then
    PUSH_NOTIFY=0
    echo "[$TS] ⏸️  非推送时间窗（当前 $HOUR 时），仅记录日志不推送" >> "$LOG"
fi

# 跑两个校验
HTML_VERIFY=$($PYTHON "$REPO_DIR/verify_report.py" "$DATE" 2>&1)
HTML_EXIT=$?
DATA_VERIFY=$($PYTHON "$REPO_DIR/verify_data_quality.py" "$DATE" 2>&1)
DATA_EXIT=$?

# 汇总
echo "HTML 数值校验 (exit=$HTML_EXIT):" >> "$LOG"
echo "$HTML_VERIFY" >> "$LOG"
echo "" >> "$LOG"
echo "数据质量校验 (exit=$DATA_EXIT):" >> "$LOG"
echo "$DATA_VERIFY" >> "$LOG"
echo "" >> "$LOG"

# 关键数据快照
SNAPSHOT=$($PYTHON -c "
import sqlite3, json
conn = sqlite3.connect('$REPO_DIR/fund_flow.db')
d = '$DATE'
out = []
# market_flow
mf = conn.execute('SELECT zhuli_net, source FROM market_flow WHERE date=?', (d,)).fetchone()
if mf:
    out.append(f'主力资金: {mf[0]:+.1f}亿 ({mf[1]})')
# stock_reco
sr = conn.execute('SELECT COUNT(*), SUM(CASE WHEN score=0 THEN 1 ELSE 0 END) FROM stock_reco WHERE date=?', (d,)).fetchone()
if sr and sr[0] > 0:
    if sr[1] == sr[0]:
        out.append(f'个股推荐: {sr[0]}条 (Plan C 兜底，无技术面评分)')
    else:
        out.append(f'个股推荐: {sr[0]}条 (含技术面评分)')
else:
    out.append('个股推荐: 0条 (❌)')
# strategy_review
rv = conn.execute('SELECT total_reco, up_count, win_rate, avg_gain FROM strategy_review WHERE review_date=?', (d,)).fetchone()
if rv and rv[0]:
    out.append(f'策略复盘: {rv[1]}/{rv[0]}涨 | 胜率{rv[2]*100:.0f}% | 均涨{rv[3]:+.2f}%')
else:
    out.append('策略复盘: ❌ 无数据')
conn.close()
print(' | '.join(out))
" 2>&1)
echo "数据快照: $SNAPSHOT" >> "$LOG"

# 通知用户（仅在推送时间窗内）
if [ "$PUSH_NOTIFY" = "1" ]; then
    if [ $HTML_EXIT -eq 0 ] && [ $DATA_EXIT -eq 0 ]; then
        STATUS="✅ 数据正常"
        osascript -e "display notification \"$SNAPSHOT\" with title \"✅ A股数据 Review · $DATE\" sound name \"Glass\"" 2>/dev/null
    elif [ $HTML_EXIT -ne 0 ] && [ $DATA_EXIT -ne 0 ]; then
        STATUS="❌ 数据异常"
        ISSUES=$(echo "$HTML_VERIFY $DATA_VERIFY" | grep -E "❌" | head -3)
        osascript -e "display notification \"$SNAPSHOT\n$ISSUES\" with title \"❌ A股数据异常 · $DATE\" sound name \"Basso\"" 2>/dev/null
    else
        STATUS="⚠️ 数据有告警"
        WARNINGS=$(echo "$DATA_VERIFY" | grep -E "⚠️" | head -3)
        osascript -e "display notification \"$SNAPSHOT\n$WARNINGS\" with title \"⚠️ A股数据告警 · $DATE\" sound name \"Glass\"" 2>/dev/null
    fi
else
    STATUS="⏸️ 非推送时间窗，跳过通知"
fi
echo "[$TS] $STATUS" >> "$LOG"
echo "" >> "$LOG"
