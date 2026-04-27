#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HS1 策略每日监控 — pre3≤2% + mom10≤3% + vol_ratio5≤0.8

模式:
  --scan   扫描今日注册日债券，判断是否触发 HS1 买入信号
  --hold   查看持仓中债券的止盈止损状态
  --once   扫描 + 持仓，一次运行
  --status 仅显示最近注册事件列表
"""
import sys, os, re
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.backtest_cache import BacktestCache


def find_idx(sd, target):
    result = 0
    for i, d in enumerate(sd):
        if d <= target:
            result = i
        else:
            break
    return result


def calc_factors(cache, sc, anchor):
    """计算 HS1 因子 + 持仓数据"""
    prices = cache.get_kline_as_dict(sc, days=1500)
    if not prices:
        return None
    sd = sorted(prices.keys())
    ri = find_idx(sd, anchor)
    reg = prices[sd[ri]]
    reg_close = reg['close']
    if reg_close <= 0 or ri < 10:
        return None

    # HS1 factors
    pre3 = ((reg_close - prices[sd[ri-3]]['close']) / prices[sd[ri-3]]['close'] * 100) if ri >= 3 else 0
    mom10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0

    vol_now = reg.get('volume', 0)
    vol_avg5 = 0
    if ri >= 5:
        vlist = [prices[sd[ri-k]].get('volume', 0) for k in range(1, 6)
                 if prices[sd[ri-k]].get('volume', 0) > 0]
        if vlist:
            vol_avg5 = sum(vlist) / len(vlist)
    vol_ratio5 = (vol_now / vol_avg5) if vol_avg5 > 0 else 1

    # D+1 buy price
    buy_idx = ri + 1
    buy_price = None
    if buy_idx < len(sd):
        buy_price = prices[sd[buy_idx]].get('open', 0)

    # Current price (latest available)
    today_str = datetime.now().strftime('%Y-%m-%d')
    latest_idx = find_idx(sd, today_str)
    if latest_idx < len(sd) and sd[latest_idx] <= today_str:
        current_close = prices[sd[latest_idx]].get('close', 0)
        current_date = sd[latest_idx]
    else:
        current_close = 0
        current_date = sd[-1] if sd else ''

    # Trading days since registration
    days_since = 0
    for i in range(ri + 1, len(sd)):
        if sd[i] > today_str:
            break
        days_since += 1

    # Holding P&L
    pnl_pct = None
    if buy_price and buy_price > 0 and current_close > 0:
        pnl_pct = ((current_close - buy_price) / buy_price) * 100

    return {
        'code': sc,
        'anchor': anchor,
        'pre3': pre3,
        'mom10': mom10,
        'vol_ratio5': vol_ratio5,
        'buy_price': buy_price,
        'current_close': current_close,
        'current_date': current_date,
        'days_since': days_since,
        'pnl_pct': pnl_pct,
        'triggered': pre3 <= 2 and mom10 <= 3 and vol_ratio5 <= 0.8,
    }


def scan_signals(cache):
    """扫描今日注册日债券的 HS1 信号"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    bonds = cache.get_latest_jisilu_data()
    if not bonds:
        bonds = cache.get_jisilu_bonds(phase='注册', limit=0)

    results = []
    for b in bonds:
        sc = b.get('stock_code')
        if not sc:
            continue
        pf = b.get('progress_full', '')
        if not pf:
            continue

        # Find registration date
        anchor = ''
        for line in pf.replace('<br>', '\n').split('\n'):
            if '同意注册' in line:
                m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                if m:
                    anchor = m.group(1)
                    break
        if not anchor or anchor > today_str:
            continue

        # Only consider recent registrations (within 15 trading days)
        try:
            anchor_dt = datetime.strptime(anchor, '%Y-%m-%d')
            today_dt = datetime.strptime(today_str, '%Y-%m-%d')
            calendar_diff = (today_dt - anchor_dt).days
        except ValueError:
            continue
        if calendar_diff > 20:
            continue

        info = calc_factors(cache, sc, anchor)
        if info:
            info['name'] = (b.get('bond_name') or b.get('stock_name') or '?')[:12]
            info['calendar_diff'] = calendar_diff
            results.append(info)

    # Sort by anchor date (most recent first)
    results.sort(key=lambda x: x['anchor'], reverse=True)
    return results


def main():
    cache = BacktestCache()
    mode = '--once'
    if len(sys.argv) > 1:
        mode = sys.argv[1]

    results = scan_signals(cache)
    if not results:
        print("无注册日债券数据")
        return

    today_str = datetime.now().strftime('%Y-%m-%d')

    # ========== 信号触发列表 ==========
    triggered = [r for r in results if r['triggered']]
    not_triggered = [r for r in results if not r['triggered']]

    if mode == '--status':
        print(f"\n  最近注册事件 ({today_str})")
        print(f"  {'名称':<12} {'代码':>8} {'注册日':<12} {'天数':>4} {'pre3':>7} {'mom10':>7} {'vol':>5} {'HS1':>4}")
        print("  " + "-" * 75)
        for r in results[:20]:
            flag = '★' if r['triggered'] else ' '
            print(f"  {flag} {r['name']:<12} {r['code']:>8} {r['anchor']:<12} {r['calendar_diff']:>4}d "
                  f"{r['pre3']:>+6.1f}% {r['mom10']:>+6.1f}% {r['vol_ratio5']:>5.2f} "
                  f"{'触发' if r['triggered'] else ''}")
        return

    # ========== 买入信号 ==========
    print(f"\n{'='*110}")
    print(f"HS1 每日监控 — {today_str}")
    print(f"{'='*110}")

    buy_signals = [r for r in triggered if r['days_since'] == 0]
    hold_signals = [r for r in triggered if 0 < r['days_since'] <= 10]
    past_hold = [r for r in triggered if r['days_since'] > 10]

    # 买入信号
    if buy_signals:
        print(f"\n  📢 买入信号 (D+1 开盘买入):")
        print(f"  {'名称':<12} {'代码':>8} {'注册日':<12} {'D+1买价':>8} {'pre3':>7} {'mom10':>7} {'vol':>5}")
        print("  " + "-" * 75)
        for r in buy_signals:
            if r['buy_price']:
                print(f"  {r['name']:<12} {r['code']:>8} {r['anchor']:<12} {r['buy_price']:>8.2f} "
                      f"{r['pre3']:>+6.1f}% {r['mom10']:>+6.1f}% {r['vol_ratio5']:>5.2f}")
            else:
                print(f"  {r['name']:<12} {r['code']:>8} {r['anchor']:<12} {'(无数据)':>8}")
    else:
        print(f"\n  今日无 D+1 买入信号")

    # 持仓监控
    if hold_signals:
        print(f"\n  📊 持仓监控 (TP5/SL5):")
        print(f"  {'名称':<12} {'代码':>8} {'持仓天数':>6} {'买价':>8} {'当前价':>8} {'浮动盈亏':>8} {'TP5':>4} {'SL5':>4}")
        print("  " + "-" * 75)
        for r in sorted(hold_signals, key=lambda x: x['days_since']):
            if r['buy_price'] and r['current_close'] and r['pnl_pct'] is not None:
                tp = '✅' if r['pnl_pct'] >= 5 else ' '
                sl = '⚠️' if r['pnl_pct'] <= -5 else ' '
                print(f"  {r['name']:<12} {r['code']:>8} D+{r['days_since']:>4} "
                      f"{r['buy_price']:>8.2f} {r['current_close']:>8.2f} {r['pnl_pct']:>+6.1f}% "
                      f"{tp} {sl}")
            else:
                print(f"  {r['name']:<12} {r['code']:>8} D+{r['days_since']:>4} {'(数据不足)':>20}")
    else:
        print(f"\n  当前无持仓")

    # 已过退出期
    if past_hold:
        print(f"\n  已过退出期的注册事件 ({len(past_hold)}只):")
        print(f"  {'名称':<12} {'代码':>8} {'注册日':<12} {'天数':>4} {'买价':>8} {'当前价':>8} {'总盈亏':>7}")
        print("  " + "-" * 75)
        for r in past_hold[:10]:
            if r['buy_price'] and r['current_close'] and r['pnl_pct'] is not None:
                print(f"  {r['name']:<12} {r['code']:>8} {r['anchor']:<12} {r['days_since']:>4}d "
                      f"{r['buy_price']:>8.2f} {r['current_close']:>8.2f} {r['pnl_pct']:>+6.1f}%")
            else:
                print(f"  {r['name']:<12} {r['code']:>8} {r['anchor']:<12} {r['days_since']:>4}d")

    # ========== 汇总 ==========
    print(f"\n{'='*110}")
    print(f"今日统计: 注册事件={len(results)} 只, HS1触发={len(triggered)} 只, "
          f"买入信号={len(buy_signals)} 只, 持仓={len(hold_signals)} 只")
    if not buy_signals and not hold_signals:
        print(f"今日无需操作")
    print(f"{'='*110}")


if __name__ == '__main__':
    main()
