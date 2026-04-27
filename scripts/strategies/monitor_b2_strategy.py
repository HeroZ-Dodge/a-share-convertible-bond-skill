#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B2 策略每日监控 — 注册日因子 + 缩量买入 + 动态退出

策略逻辑:
  买入条件 (B2):
    pre3 <= -2%  (近3日跌幅≥2%, 代表回调)
    mom10 <= -1% (近10日动量为负, 代表低位)
    vol_ratio5 <= 0.8 (缩量, 洗盘结束)
    → D+1 开盘买入

  卖出条件 (持仓期间T日收盘检查, T+1开盘执行):
    TP5/SL5: 盈利≥5%止盈 / 亏损≥5%止损
    或: 持有10天超时退出

  所有买入因子基于注册日收盘价计算, 注册日收盘后可判断, D+1开盘买入, 合法可执行。

用法:
  python3 scripts/monitor_b2_strategy.py              # 监控今日机会
  python3 scripts/monitor_b2_strategy.py --all-bonds  # 显示所有注册转债(含不在窗口的)
  python3 scripts/monitor_b2_strategy.py --detail     # 显示每只债的详细因子
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


def get_factors(cache, sc, anchor):
    prices = cache.get_kline_as_dict(sc, days=1500)
    if not prices:
        return None

    sd = sorted(prices.keys())
    ri = find_idx(sd, anchor)
    reg_close = prices[sd[ri]]['close']
    if reg_close <= 0 or ri < 10:
        return None

    reg = prices[sd[ri]]
    reg_open = reg.get('open', 0) or reg_close

    pre3 = ((reg_close - prices[sd[ri-3]]['close']) / prices[sd[ri-3]]['close'] * 100) if ri >= 3 else 0
    pre7 = ((reg_close - prices[sd[ri-7]]['close']) / prices[sd[ri-7]]['close'] * 100) if ri >= 7 else 0
    rc = ((reg_close - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri > 0 else 0
    mom10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0

    vol_now = prices[sd[ri]].get('volume', 0)
    vol_avg5 = 0
    if ri >= 5:
        vols = [prices[sd[ri-k]].get('volume',0) for k in range(1,6) if prices[sd[ri-k]].get('volume',0)>0]
        if vols: vol_avg5 = sum(vols)/len(vols)
    vol_ratio = (vol_now / vol_avg5) if vol_avg5 > 0 else 1

    # range7
    high7 = 0; low7 = 99999
    if ri >= 7:
        for k in range(ri-7, ri+1):
            h = prices[sd[k]].get('high', 0)
            l = prices[sd[k]].get('low', 99999)
            if h > high7: high7 = h
            if l < low7: low7 = l
    range7 = ((high7 - low7) / low7 * 100) if low7 > 0 else 0

    # D+1 开盘 (买入价)
    buy_idx = ri + 1
    buy_price = None
    if buy_idx < len(sd):
        buy_price = prices[sd[buy_idx]].get('open', 0)
        if buy_price <= 0:
            buy_price = None

    today_str = datetime.now().strftime('%Y-%m-%d')
    today_idx = find_idx(sd, today_str)
    if today_str not in prices:
        today_idx = len(sd) - 1
        if sd[today_idx] > today_str:
            today_idx = today_idx - 1

    day_offset = today_idx - ri
    latest_close = prices[sd[today_idx]]['close'] if today_idx < len(sd) else 0

    return {
        'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
        'vol_ratio': vol_ratio, 'range7': range7,
        'buy_price': buy_price,
        'day_offset': day_offset,
        'latest_close': latest_close,
        'reg_close': reg_close,
        'today_idx': today_idx,
    }


def main():
    show_all = False
    show_detail = False

    args = sys.argv[1:]
    for a in args:
        if a == '--all-bonds':
            show_all = True
        elif a == '--detail':
            show_detail = True

    cache = BacktestCache()
    today_str = datetime.now().strftime('%Y-%m-%d')

    print("=" * 90)
    print(f"B2 策略监控 — {today_str}")
    print("=" * 90)

    from lib.data_source import JisiluAPI
    jisilu = JisiluAPI()
    bonds = jisilu.fetch_pending_bonds(limit=200)
    if not bonds:
        print("  未获取到数据")
        return
    print(f"  获取到 {len(bonds)} 只待发转债")

    # 筛选已注册
    registered = []
    for b in bonds:
        sc = b.get('stock_code') or b.get('stock_id', '')
        if not sc: continue
        pf = b.get('progress_full', '')
        if not pf: continue
        anchor = ''
        for line in pf.replace('<br>', '\n').split('\n'):
            if '同意注册' in line:
                m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                if m:
                    anchor = m.group(1)
                    break
        if not anchor or anchor > today_str: continue
        name = (b.get('bond_name') or b.get('stock_name', '?'))[:12]
        registered.append((sc, anchor, name, b))

    if not registered:
        print("\n  当前无已注册转债")
        return
    print(f"  已注册: {len(registered)} 只")

    buy_candidates = []
    holding = []
    missed = []
    no_signal = []

    for sc, anchor, name, bond_info in registered:
        factors = get_factors(cache, sc, anchor)
        if factors is None: continue

        day_off = factors['day_offset']
        buy_price = factors['buy_price']

        # B2 条件: pre3<=-2 + mom10<=-1 + vol<=0.8
        b2_ok = factors['pre3'] <= -2 and factors['mom10'] <= -1 and factors['vol_ratio'] <= 0.8

        # B2-relaxed (样本更大): pre3<=2 + mom10<=-1 + vol<=0.8
        b2r_ok = factors['pre3'] <= 2 and factors['mom10'] <= -1 and factors['vol_ratio'] <= 0.8

        if day_off < 0:
            continue
        elif day_off == 0:
            if b2_ok:
                buy_candidates.append({
                    'name': name, 'code': sc, 'anchor': anchor,
                    'factors': factors, 'level': 'B2',
                })
            elif b2r_ok:
                buy_candidates.append({
                    'name': name, 'code': sc, 'anchor': anchor,
                    'factors': factors, 'level': 'B2R',
                })
        elif 1 <= day_off <= 10:
            if buy_price and buy_price > 0:
                ret = ((factors['latest_close'] - buy_price) / buy_price) * 100
                exit_reason = None
                if ret >= 5:
                    exit_reason = '止盈(≥5%)'
                elif ret <= -5:
                    exit_reason = '止损(≤-5%)'
                elif day_off >= 10:
                    exit_reason = '超时(≥10天)'
                holding.append({
                    'name': name, 'code': sc, 'anchor': anchor,
                    'factors': factors, 'buy_price': buy_price,
                    'ret': ret, 'day_off': day_off,
                    'exit_reason': exit_reason,
                    'b2_ok': b2_ok, 'b2r_ok': b2r_ok,
                })
        else:
            if b2_ok or b2r_ok:
                missed.append({'name': name, 'code': sc, 'anchor': anchor, 'day_off': day_off})

    # --- 买入建议 ---
    print("\n" + "─" * 90)
    print(f"买入建议 (明天 D+1 开盘): {len(buy_candidates)} 只")
    print("─" * 90)

    if buy_candidates:
        print(f"\n  {'名称':<12} {'代码':>8} {'注册日':<12} {'策略':>4} "
              f"{'pre3':>6} {'mom10':>7} {'rc':>6} {'vol比':>6} {'range7':>7} {'D+1开盘':>8}")
        print("  " + "-" * 88)
        for item in sorted(buy_candidates, key=lambda x: x['anchor'], reverse=True):
            f = item['factors']
            level = item['level']
            buy_str = f"{f['buy_price']:.2f}" if f['buy_price'] else "N/A"
            print(f"  {item['name']:<12} {item['code']:>8} {item['anchor']:<12} "
                  f"{'★' if level=='B2' else ' '}{level:>3} "
                  f"{f['pre3']:>+5.1f}% {f['mom10']:>+6.1f}% {f['rc']:>+5.1f}% "
                  f"{f['vol_ratio']:>5.2f} {f['range7']:>5.1f}% {buy_str:>8}")
    else:
        print("\n  当前无买入信号")

    # --- 持仓监控 ---
    if holding:
        print("\n" + "─" * 90)
        print(f"持仓监控 (D+1~D+10): {len(holding)} 只")
        print("─" * 90)

        print(f"\n  {'名称':<12} {'代码':>8} {'D+':>4} {'买入价':>8} {'最新价':>8} "
              f"{'浮盈':>7} {'状态':<12}")
        print("  " + "-" * 70)

        for item in sorted(holding, key=lambda x: x['ret'], reverse=True):
            f = item['factors']
            tag = ''
            if item['exit_reason']:
                tag = f"!!{item['exit_reason']}"
            elif item['ret'] > 0:
                tag = "  浮盈"
            else:
                tag = "  浮亏"

            level_str = 'B2' if item['b2_ok'] else ('B2R' if item['b2r_ok'] else '')
            print(f"  {item['name']:<12} {item['code']:>8} D+{item['day_off']:>2} "
                  f"{item['buy_price']:>8.2f} {f['latest_close']:>8.2f} "
                  f"{item['ret']:>+6.1f}% {tag:<12}")
    else:
        print("\n" + "─" * 90)
        print("持仓监控: 当前无持仓")
        print("─" * 90)

    # --- 汇总 ---
    print("\n" + "=" * 90)
    buy_b2 = sum(1 for i in buy_candidates if i['level'] == 'B2')
    buy_b2r = sum(1 for i in buy_candidates if i['level'] == 'B2R')
    need_exit = sum(1 for i in holding if i['exit_reason'])
    print(f"汇总: 已注册 {len(registered)} | "
          f"买入建议 {len(buy_candidates)} (B2={buy_b2} B2R={buy_b2r}) | "
          f"持仓 {len(holding)} (需退出={need_exit})")
    print("=" * 90)


if __name__ == '__main__':
    main()
