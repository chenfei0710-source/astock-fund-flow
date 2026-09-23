#!/bin/bash
# 每个交易日 16:10 自动提醒（crontab: 10 16 * * 1-5）
# 在数据抓取(15:35) + 自愈校验(15:50) + 报告生成 全部完成后触发

REPO_DIR="/Users/admin/.assistant/fund_flow_github"
PYTHON="/Library/Developer/CommandLineTools/usr/bin/python3"
DATE=$(TZ='Asia/Shanghai' date '+%Y-%m-%d')
TS=$(TZ='Asia/Shanghai' date '+%H:%M:%S')
REPORT_URL="https://chenfei0710-source.github.io/astock-fund-flow/review/"

# 确认今日数据已就绪
THS=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('$REPO_DIR/fund_flow.db')
n = conn.execute('SELECT COUNT(*) FROM sector_flow_ths WHERE date=?', ('$DATE',)).fetchone()[0]
conn.close()
print(n)
" 2>/dev/null)

# 检查报告是否生成
REPORT_FILE="$REPO_DIR/review/$DATE/review_$DATE.html"
if [ -f "$REPORT_FILE" ]; then
    REPORT_OK=1
else
    REPORT_OK=0
fi

# 涨停统计
ZT_STATS=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('$REPO_DIR/fund_flow.db')
r = conn.execute('SELECT zt_count,dt_count,zhaban_rate,max_lb,max_lb_stock FROM market_stats WHERE date=?', ('$DATE',)).fetchone()
conn.close()
if r: print(f'{r[0]}|{r[1]}|{r[2]}|{r[3]}|{r[4]}')
else: print('无')
" 2>/dev/null)

# 主力资金
MK_STATS=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('$REPO_DIR/fund_flow.db')
r = conn.execute('SELECT zhuli_net,chaoda_net,dadan_net,sanhu_net FROM market_flow WHERE date=?', ('$DATE',)).fetchone()
conn.close()
if r: print(f'{r[0]:.0f}|{r[1]:.0f}|{r[2]:.0f}|{r[3]:.0f}')
else: print('无')
" 2>/dev/null)

# 策略复盘
WIN_RATE=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('$REPO_DIR/fund_flow.db')
r = conn.execute('SELECT win_rate, avg_gain, total_reco, up_count FROM strategy_review WHERE review_date=?', ('$DATE',)).fetchone()
conn.close()
if r: print(f'{r[0]*100:.0f}%|{r[1]:+.2f}%|{r[2]}|{r[3]}')
else: print('无')
" 2>/dev/null)

# 指数数据
IDX_STATS=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('$REPO_DIR/fund_flow.db')
rows = conn.execute(\"SELECT name,close,chg_pct FROM index_daily WHERE date=? AND code IN ('000001','399001','399006','000688') ORDER BY code\", ('$DATE',)).fetchall()
conn.close()
if rows:
    parts = [f\"{r[0]}{'↑' if r[2]>=0 else '↓'}{abs(r[2]):.2f}%\" for r in rows]
    print(' '.join(parts))
else: print('无')
" 2>/dev/null)

# macOS 原生通知
if [ "$THS" != "0" ] && [ -n "$THS" ] && [ "$REPORT_OK" = "1" ]; then
    # 解析数据
    IFS='|' read -r ZT DT ZB_RATE MAX_LB MAX_LB_STOCK <<< "$ZT_STATS"
    IFS='|' read -r ZHULI CHAODA DADAN SANHU <<< "$MK_STATS"

    # 构建通知内容
    MSG="📊 $DATE 数据已更新\n"
    MSG+="主力: ${ZHULI}亿 | 涨停: ${ZT} | 炸板率: ${ZB_RATE}%\n"
    MSG+="连板: ${MAX_LB}板(${MAX_LB_STOCK}) | THS板块: ${THS}条\n"

    if [ "$WIN_RATE" != "无" ]; then
        IFS='|' read -r WR GAIN TOTAL UP <<< "$WIN_RATE"
        MSG+="策略验证: 胜率${WR} | 均涨${GAIN} | ${UP}/${TOTAL}涨\n"
    fi

    if [ "$IDX_STATS" != "无" ]; then
        MSG+="指数: ${IDX_STATS}\n"
    fi

    MSG+="\n点击查看报告 → $REPORT_URL"

    osascript -e "display notification \"$MSG\" with title \"✅ A股复盘已更新 · $DATE\" sound name \"Glass\""

elif [ "$THS" != "0" ] && [ -n "$THS" ]; then
    # 数据有但报告未生成
    osascript -e "display notification \"📊 $DATE 数据已更新（THS=$THS条），报告生成中...
$REPORT_URL\" with title \"A股数据已更新·报告待生成\" sound name \"Glass\""
else
    # 数据异常
    osascript -e "display notification \"⚠️ $DATE 数据可能异常（THS=$THS），请检查
$REPORT_URL\" with title \"⚠️ A股数据异常\" sound name \"Basso\""
fi
