#!/bin/bash
# 每个交易日 16:10 自动提醒（crontab: 10 16 * * 1-5）
# 在数据抓取(15:35) + 自愈校验(15:50) + 报告生成 全部完成后触发
# 同时发送 macOS 通知 + 飞书机器人"富哥小跟班"消息

REPO_DIR="/Users/admin/.assistant/fund_flow_github"
PYTHON="/Library/Developer/CommandLineTools/usr/bin/python3"
DATE=$(TZ='Asia/Shanghai' date '+%Y-%m-%d')
TS=$(TZ='Asia/Shanghai' date '+%H:%M:%S')
REPORT_URL="https://chenfei0710-source.github.io/astock-fund-flow/review/"

# ── 飞书机器人配置（从本地配置文件读取，避免泄露密钥）──
FEISHU_CONFIG="/Users/admin/.assistant/fund_flow_github/.feishu.env"
if [ -f "$FEISHU_CONFIG" ]; then
    source "$FEISHU_CONFIG"
else
    echo "[飞书] 配置文件 $FEISHU_CONFIG 不存在，跳过飞书通知"
fi

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

# ── 飞书发消息函数 ──
send_feishu() {
    local title="$1"
    local content="$2"
    # 获取 tenant_access_token
    local token
    token=$(curl -s -X POST "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal" \
        -H "Content-Type: application/json" \
        -d "{\"app_id\":\"$FEISHU_APP_ID\",\"app_secret\":\"$FEISHU_APP_SECRET\"}" \
        | $PYTHON -c "import sys,json; print(json.load(sys.stdin).get('tenant_access_token',''))" 2>/dev/null)
    if [ -z "$token" ] || [ -z "$FEISHU_APP_ID" ] || [ -z "$FEISHU_APP_SECRET" ] || [ -z "$FEISHU_OPEN_ID" ]; then
        echo "[飞书] 配置不完整，跳过"
        return 1
    fi
    # 构造富文本卡片消息
    local card_json
    card_json=$($PYTHON -c "
import json
elements = [
    {'tag':'div','text':{'tag':'lark_md','content':'$content'}},
    {'tag':'action','actions':[{'tag':'button','text':{'tag':'lark_md','content':'📊 查看完整复盘报告'},'url':'$REPORT_URL','type':'primary'}]}
]
card = json.dumps({'schema':'2.0','header':{'title':{'tag':'plain_text','content':'$title'},'template':'green' if '✅' in '$title' else ('red' if '⚠️' in '$title' else 'orange')},'body':{'elements':elements}})
print(card)
" 2>/dev/null)
    # 发送消息
    curl -s -X POST "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "{\"receive_id\":\"$FEISHU_OPEN_ID\",\"msg_type\":\"interactive\",\"content\":$(echo "$card_json" | $PYTHON -c "import sys,json; print(json.dumps(json.load(sys.stdin)))")}" \
        > /dev/null 2>&1
    echo "[飞书] 消息已发送"
}

# macOS 原生通知 + 飞书消息
if [ "$THS" != "0" ] && [ -n "$THS" ] && [ "$REPORT_OK" = "1" ]; then
    # 解析数据
    IFS='|' read -r ZT DT ZB_RATE MAX_LB MAX_LB_STOCK <<< "$ZT_STATS"
    IFS='|' read -r ZHULI CHAODA DADAN SANHU <<< "$MK_STATS"

    # 构建通知内容
    MSG="📊 $DATE 数据已更新\n"
    MSG+="主力: ${ZHULI}亿 | 涨停: ${ZT} | 炸板率: ${ZB_RATE}%\n"
    MSG+="连板: ${MAX_LB}板(${MAX_LB_STOCK}) | THS板块: ${THS}条\n"

    # 飞书富文本内容
    FS_CONTENT="**📊 $DATE 数据已更新**\n\n"
    FS_CONTENT+="**主力资金**: ${ZHULI}亿 | **涨停**: ${ZT} | **炸板率**: ${ZB_RATE}%\n"
    FS_CONTENT+="**连板高度**: ${MAX_LB}板（${MAX_LB_STOCK}）| **THS板块**: ${THS}条\n"

    if [ "$WIN_RATE" != "无" ]; then
        IFS='|' read -r WR GAIN TOTAL UP <<< "$WIN_RATE"
        MSG+="策略验证: 胜率${WR} | 均涨${GAIN} | ${UP}/${TOTAL}涨\n"
        FS_CONTENT+="\n**策略验证**: 胜率${WR} | 均涨${GAIN} | ${UP}/${TOTAL}涨\n"
    fi

    if [ "$IDX_STATS" != "无" ]; then
        MSG+="指数: ${IDX_STATS}\n"
        FS_CONTENT+="**指数**: ${IDX_STATS}\n"
    fi

    MSG+="\n点击查看报告 → $REPORT_URL"

    osascript -e "display notification \"$MSG\" with title \"✅ A股复盘已更新 · $DATE\" sound name \"Glass\""
    send_feishu "✅ A股复盘已更新 · $DATE" "$FS_CONTENT"

elif [ "$THS" != "0" ] && [ -n "$THS" ]; then
    # 数据有但报告未生成
    osascript -e "display notification \"📊 $DATE 数据已更新（THS=$THS条），报告生成中...
$REPORT_URL\" with title \"A股数据已更新·报告待生成\" sound name \"Glass\""
    send_feishu "📊 A股数据已更新·报告待生成 · $DATE" "**📊 $DATE 数据已更新**（THS=${THS}条），报告生成中..."

else
    # 数据异常
    osascript -e "display notification \"⚠️ $DATE 数据可能异常（THS=$THS），请检查
$REPORT_URL\" with title \"⚠️ A股数据异常\" sound name \"Basso\""
    send_feishu "⚠️ A股数据异常 · $DATE" "**⚠️ $DATE 数据可能异常**（THS=${THS}），请检查"

fi
