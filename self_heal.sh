#!/bin/bash
# 每日 15:50 自动运行（crontab: 50 15 * * 1-5）
# 两层自愈：
#   - THS数据缺失 → 本地重跑爬虫（国内IP，EM+THS都能抓）
#   - 记录策略权重进化日志

REPO_DIR="/Users/admin/.assistant/fund_flow_github"
GITHUB_DB="$REPO_DIR/fund_flow.db"
LOG="$REPO_DIR/self_heal.log"
PYTHON="/Library/Developer/CommandLineTools/usr/bin/python3"
DATE=$(TZ='Asia/Shanghai' date '+%Y-%m-%d')
TS=$(TZ='Asia/Shanghai' date '+%Y-%m-%d %H:%M:%S')

echo "[$TS] ===== 自检开始 DATE=$DATE =====" >> "$LOG"

cd "$REPO_DIR" || exit 1

# 1. 拉取最新远端状态
echo "[$TS] git pull..." >> "$LOG"
git pull --ff-only origin main >> "$LOG" 2>&1 || git pull --rebase origin main >> "$LOG" 2>&1

# 2. 检查同花顺数据完整性（主数据源）
THS_COUNT=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('$GITHUB_DB')
n = conn.execute('SELECT COUNT(*) FROM sector_flow_ths WHERE date=?', ('$DATE',)).fetchone()[0]
conn.close()
print(n)
" 2>/dev/null)

RECO_COUNT=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('$GITHUB_DB')
n = conn.execute('SELECT COUNT(*) FROM stock_reco WHERE date=?', ('$DATE',)).fetchone()[0]
conn.close()
print(n)
" 2>/dev/null)

echo "[$TS] sector_flow_ths[$DATE]=$THS_COUNT 条，stock_reco=$RECO_COUNT 条" >> "$LOG"

# 3. 数据缺失时：本地重跑爬虫（国内IP，EM+THS都能抓）
if [ "$THS_COUNT" = "0" ] || [ -z "$THS_COUNT" ]; then
    echo "[$TS] ⚠️  同花顺数据缺失，触发本地自愈..." >> "$LOG"

    # 本地环境补全依赖
    $PYTHON -m pip install --quiet curl_cffi py-mini-racer requests akshare yfinance >> "$LOG" 2>&1

    # 重跑爬虫（本地在国内，THS+EM都能抓）
    $PYTHON "$REPO_DIR/scraper.py" >> "$LOG" 2>&1
    SCRAPER_EXIT=$?

    if [ $SCRAPER_EXIT -eq 0 ]; then
        # 验证结果
        THS_AFTER=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('$GITHUB_DB')
n = conn.execute('SELECT COUNT(*) FROM sector_flow_ths WHERE date=?', ('$DATE',)).fetchone()[0]
conn.close()
print(n)
" 2>/dev/null)
        echo "[$TS] 自愈后 THS=$THS_AFTER 条" >> "$LOG"

        if [ "$THS_AFTER" != "0" ]; then
            # 导出 JSON 并推送
            $PYTHON "$REPO_DIR/export_json.py" >> "$LOG" 2>&1
            git add data/ fund_flow.db >> "$LOG" 2>&1
            git diff --cached --quiet || git commit -m "本地自愈: 补全 $DATE 数据（本机重跑）" >> "$LOG" 2>&1
            git push origin main >> "$LOG" 2>&1
            echo "[$TS] ✅ 本地自愈成功并推送" >> "$LOG"
        else
            echo "[$TS] ❌ 本地自愈后数据仍为空，可能今日非交易日" >> "$LOG"
        fi
    else
        echo "[$TS] ❌ 爬虫退出码=$SCRAPER_EXIT，检查上方日志" >> "$LOG"
    fi
else
    echo "[$TS] ✅ 数据完整，无需干预" >> "$LOG"
fi

# 5. 生成当日复盘报告（基于9/18 CSS框架 + 当日真实数据）
echo "[$TS] 生成复盘报告..." >> "$LOG"
$PYTHON "$REPO_DIR/gen_review.py" >> "$LOG" 2>&1
if [ $? -eq 0 ]; then
    # 校验报告文件：检查关键数据点是否写入
    REPORT_FILE="review/$DATE/review_$DATE.html"
    if [ -f "$REPORT_FILE" ]; then
        FILE_SIZE=$(wc -c < "$REPORT_FILE")
        # 检查报告里是否包含当日日期和主力资金数据
        if grep -q "$DATE" "$REPORT_FILE" && grep -q "主力" "$REPORT_FILE"; then
            echo "[$TS] ✅ 报告校验通过 ($FILE_SIZE bytes)" >> "$LOG"
            git add review/ >> "$LOG" 2>&1
            git diff --cached --quiet || git commit -m "复盘报告: $DATE" >> "$LOG" 2>&1
            git push origin main >> "$LOG" 2>&1
            echo "[$TS] ✅ 复盘报告已生成并推送" >> "$LOG"
        else
            echo "[$TS] ❌ 报告校验失败：缺少关键数据" >> "$LOG"
        fi
    else
        echo "[$TS] ❌ 报告文件未生成: $REPORT_FILE" >> "$LOG"
    fi
else
    echo "[$TS] ⚠️ 复盘报告生成失败，检查 gen_review.py" >> "$LOG"
fi

# 4. 记录当前权重版本（自我进化日志）
$PYTHON - << PYEOF >> "$LOG" 2>&1
import sqlite3, json
conn = sqlite3.connect("$GITHUB_DB")
row = conn.execute("SELECT updated_date, sample_days, weights_json FROM strategy_weights ORDER BY updated_date DESC LIMIT 1").fetchone()
conn.close()
if row:
    w = json.loads(row[2])
    print(f"策略权重: {row[0]}（基于{row[1]}天）MACD金叉={w.get('macd_golden')} MA排列={w.get('ma_align')} 0轴={w.get('macd_zero')} 回调={w.get('pullback_10d')}")
else:
    print("权重: 使用默认基准（数据积累中）")
PYEOF

echo "[$TS] ===== 自检完成 =====" >> "$LOG"
echo "" >> "$LOG"
