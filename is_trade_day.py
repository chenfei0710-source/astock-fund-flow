#!/usr/bin/env python3
"""判断今天（或指定日期）是否是A股交易日。

方案：拉取上证指数最近10根日K线，如果目标日期在其中就是交易日。
不依赖 akshare（避免 py_mini_racer 在 macOS LibreSSL 下的兼容问题）。

用法: python3 is_trade_day.py [YYYY-MM-DD]
  不传参数则判断今天（北京时间）。
退出码: 0=交易日, 1=非交易日, 2=查询失败(默认当交易日处理)
"""
import sys
import datetime
import os

# 确保用北京时间
os.environ['TZ'] = 'Asia/Shanghai'

def get_recent_trade_dates(datalen=10):
    """从新浪财经拉取上证指数最近N个交易日的日期"""
    import urllib.request
    import json

    url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol=sh000001&scale=240&datalen={datalen}&type=simple"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        text = resp.read().decode('utf-8')

    # 格式: /*<script>...</script>*/var([{...},{...},...])
    # 提取 JSON 数组
    start = text.find('[')
    end = text.rfind(']')
    if start < 0 or end < 0:
        raise ValueError(f"无法解析响应: {text[:200]}")

    data = json.loads(text[start:end + 1])
    dates = []
    for item in data:
        d = item.get('day', '')
        if d:
            # day 格式: "2026-10-20"
            dates.append(datetime.datetime.strptime(d[:10], '%Y-%m-%d').date())
    return dates

def main():
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
        try:
            target = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            print("日期格式错误，应为 YYYY-MM-DD", file=sys.stderr)
            sys.exit(2)
    else:
        target = datetime.date.today()

    # 快速判断周末
    weekday = target.weekday()  # 0=周一, 6=周日
    if weekday >= 5:
        wd_name = ['一', '二', '三', '四', '五', '六', '日'][weekday]
        print(f"周末（周{wd_name}），非交易日")
        sys.exit(1)

    try:
        trade_dates = get_recent_trade_dates(10)
        # 转成 set 加速查找
        trade_set = {d for d in trade_dates}

        if target in trade_set:
            print(f"{target} 是A股交易日")
            sys.exit(0)
        else:
            # 如果目标日期在今天之前，且不在最近10个交易日里 → 非交易日
            # 如果目标日期是今天或未来，检查最近一个交易日是否 >= target
            latest_trade = max(trade_set) if trade_set else None
            if latest_trade and target <= latest_trade:
                # target 在最近交易日范围内但不在列表里 → 节假日
                print(f"{target} 不是A股交易日（法定节假日）")
                sys.exit(1)
            elif latest_trade and target > latest_trade:
                # 目标日期在最新交易日之后，可能是今天还没收盘数据
                # 如果今天是工作日且还没到收盘时间(15:00)，默认当交易日处理
                now = datetime.datetime.now()
                if target == now.date() and now.hour < 15:
                    print(f"{target} 今天尚未收盘，默认按交易日处理")
                    sys.exit(0)
                else:
                    # 拉更多数据确认
                    trade_dates = get_recent_trade_dates(30)
                    trade_set = {d for d in trade_dates}
                    if target in trade_set:
                        print(f"{target} 是A股交易日")
                        sys.exit(0)
                    else:
                        print(f"{target} 不是A股交易日")
                        sys.exit(1)
            else:
                print(f"{target} 不是A股交易日")
                sys.exit(1)
    except Exception as e:
        print(f"查询交易日历失败: {e}", file=sys.stderr)
        print("默认当交易日处理（避免漏推）", file=sys.stderr)
        sys.exit(2)

if __name__ == '__main__':
    main()
