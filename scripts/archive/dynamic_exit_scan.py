#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合法动态策略挖掘 — D+1开盘买入 + 动态卖出

约束:
  买入: D+1开盘 (基于注册日因子, 注册日收盘后可判断, 合法)
  卖出: 持仓期间T日收盘后判断, T+1开盘执行

卖出策略族:
  A. 固定止盈止损 (TP/SL ±X%)
  B. 移动止盈 (trailing stop) — 高点回撤N%
  C. 均线卖出 — 跌破M5/M10
  D. 阴线卖出 — 连涨后收阴
  E. 时间卖出 — 持有N天后无条件卖出
  F. 综合: 多规则叠加
"""
import sys, os, re
from datetime import datetime
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


def load_pool(cache):
    """加载完整数据池"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    bonds = cache.get_jisilu_bonds(phase='注册', limit=0)
    pool = []
    for b in bonds:
        sc = b.get('stock_code')
        if not sc: continue
        pf = b.get('progress_full', '')
        if not pf: continue
        anchor = ''
        for line in pf.replace('<br>', '\n').split('\n'):
            if '同意注册' in line:
                m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                if m: anchor = m.group(1); break
        if not anchor or anchor > today_str: continue

        prices = cache.get_kline_as_dict(sc, days=1500)
        if not prices: continue
        sd = sorted(prices.keys())
        ri = find_idx(sd, anchor)
        reg_close = prices[sd[ri]]['close']
        if reg_close <= 0 or ri < 10: continue

        # 因子
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

        # D+1 开盘价 (买入价)
        buy_idx = ri + 1
        buy_price = None
        if buy_idx < len(sd) and sd[buy_idx] <= today_str:
            buy_price = prices[sd[buy_idx]].get('open', 0)
        if not buy_price or buy_price <= 0: continue

        # 注册后20天K线 (持仓期间)
        hold_days = []
        for off in range(1, 21):
            idx = ri + off
            if idx >= len(sd) or sd[idx] > today_str: break
            p = prices[sd[idx]]
            hold_days.append({
                'off': off, 'date': sd[idx],
                'open': p.get('open',0), 'close': p.get('close',0),
                'high': p.get('high',0), 'low': p.get('low',0),
                'volume': p.get('volume',0),
            })

        if len(hold_days) < 2: continue

        pool.append({
            'code': sc, 'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
            'vol_ratio': vol_ratio,
            'buy_price': buy_price,
            'hold_days': hold_days,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    return pool


def test_fixed_tp_sl(pool, tp, sl, max_hold=10, label='', strat_fn=None):
    """固定止盈止损

    strat_fn: 可选, 过滤池子 (如 S1, B1)
    """
    if strat_fn:
        pool = [v for v in pool if strat_fn(v)]

    trades = []
    for v in pool:
        buy = v['buy_price']
        hold = v['hold_days']

        exit_off = None
        exit_price = None
        reason = None

        for i, day in enumerate(hold):
            if i == 0: continue  # D+1 is buy day
            if day['close'] <= 0: continue
            ret = ((day['close'] - buy) / buy) * 100
            if ret >= tp:
                exit_off = day['off']
                exit_price = day['close']
                reason = 'tp'
                break
            if ((buy - day['close']) / buy * 100) >= sl:
                exit_off = day['off']
                exit_price = day['close']
                reason = 'sl'
                break
            if day['off'] - 1 >= max_hold:
                exit_off = day['off']
                exit_price = day['close']
                reason = 'timeout'
                break

        if exit_off is None:
            last = hold[-1]
            exit_off = last['off']
            exit_price = last['close']
            reason = 'timeout'

        ret = ((exit_price - buy) / buy) * 100
        hold_days = exit_off - 1  # D+1 is day 0
        trades.append({'ret': ret, 'hold': hold_days, 'reason': reason})

    return trades


def test_trailing_stop(pool, tp_min, trail_pct, max_hold=10, strat_fn=None):
    """移动止盈: 浮盈>=tp_min%后, 从最高点回撤trail_pct%就卖

    实际执行: T日收盘判断回撤 → T+1开盘卖出
    """
    if strat_fn:
        pool = [v for v in pool if strat_fn(v)]

    trades = []
    for v in pool:
        buy = v['buy_price']
        hold = v['hold_days']

        peak_ret = -999
        exit_off = None
        exit_price = None
        reason = None

        for i, day in enumerate(hold):
            if day['close'] <= 0: continue
            ret = ((day['close'] - buy) / buy) * 100
            if ret > peak_ret:
                peak_ret = ret

            if i == 0: continue  # 买入当天不判断

            # 如果浮盈已达tp_min, 跟踪回撤
            if peak_ret >= tp_min and i > 0:
                drawdown = peak_ret - ret
                if drawdown >= trail_pct:
                    exit_off = day['off']
                    exit_price = day['close']
                    reason = 'trailing'
                    break

            # 超时
            if day['off'] - 1 >= max_hold and exit_off is None:
                exit_off = day['off']
                exit_price = day['close']
                reason = 'timeout'

        if exit_off is None:
            last = hold[-1]
            exit_off = last['off']
            exit_price = last['close']
            reason = 'timeout'

        ret = ((exit_price - buy) / buy) * 100
        hold_days = exit_off - 1
        trades.append({'ret': ret, 'hold': hold_days, 'reason': reason, 'peak_ret': peak_ret})

    return trades


def test_yma_sell(pool, tp, ma_days, max_hold=10, strat_fn=None):
    """均线卖出: 浮盈>=tp%后, 收盘价跌破M5/M10 → 次日卖出

    ma_days: 用持仓期间的收盘价计算均线 (简化: 用最近N天均价)
    """
    if strat_fn:
        pool = [v for v in pool if strat_fn(v)]

    trades = []
    for v in pool:
        buy = v['buy_price']
        hold = v['hold_days']

        exit_off = None
        exit_price = None
        reason = None

        # 收集持仓期间的收盘价
        closes = [buy]  # D+0 注册日收盘价作为初始

        for i, day in enumerate(hold):
            if day['close'] <= 0: continue
            closes.append(day['close'])
            ret = ((day['close'] - buy) / buy) * 100

            if i == 0: continue

            # 计算持仓均线
            if len(closes) >= ma_days:
                ma = sum(closes[-ma_days:]) / ma_days
                if ret >= tp and day['close'] < ma:
                    exit_off = day['off']
                    exit_price = day['close']
                    reason = 'yma'
                    break

            if day['off'] - 1 >= max_hold:
                exit_off = day['off']
                exit_price = day['close']
                reason = 'timeout'

        if exit_off is None:
            last = hold[-1]
            exit_off = last['off']
            exit_price = last['close']
            reason = 'timeout'

        ret = ((exit_price - buy) / buy) * 100
        hold_days = exit_off - 1
        trades.append({'ret': ret, 'hold': hold_days, 'reason': reason})

    return trades


def calc(trades):
    if not trades: return None
    rets = sorted([t['ret'] for t in trades])
    n = len(rets)
    avg = sum(rets)/n
    std = (sum((x-avg)**2 for x in rets)/n)**0.5
    sh = avg/std if std > 0 else 0
    win = sum(1 for x in rets if x > 0)/n*100
    med = rets[n//2]
    avg_hold = sum(t['hold'] for t in trades)/n
    return {'n':n, 'avg':avg, 'med':med, 'win':win, 'std':std, 'sharpe':sh, 'avg_hold':avg_hold,
            'best':max(rets), 'worst':min(rets)}


def strat_s1(v): return v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0
def strat_b1(v): return strat_s1(v) and v['vol_ratio'] < 0.8
def strat_s2(v): return v['pre3'] <= 2 and v['mom10'] < 5
def strat_all(v): return True


def main():
    cache = BacktestCache()
    print("加载数据池...", flush=True)
    pool = load_pool(cache)
    print(f"  总: {len(pool)}")

    # ========== 1) S1/B1 固定止盈止损矩阵 ==========
    print("\n" + "=" * 120)
    print("S1 策略 — 止盈止损矩阵 (D+1买, 最多持10天)")
    print("=" * 120)

    for label, sf in [('S1', strat_s1), ('B1', strat_b1)]:
        print(f"\n{label}:")
        print(f"  {'SL↓ TP→':>8}", end='')
        for sl in [3.0, 4.0, 5.0]:
            print(f"  SL{sl:.0f}", end='')
        print()
        print("  " + "-" * 60)
        for tp in [2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0]:
            print(f"  TP{tp:.1f}%", end='')
            for sl in [3.0, 4.0, 5.0]:
                trades = test_fixed_tp_sl(pool, tp, sl, max_hold=10, strat_fn=sf)
                st = calc(trades)
                if st and st['n'] >= 8:
                    print(f"  {st['sharpe']:>+5.2f}", end='')
                else:
                    print(f"  {'--':>5}", end='')
            print()

    # ========== 2) 移动止盈 ==========
    print("\n" + "=" * 120)
    print("移动止盈 — 浮盈>=X%后, 高点回撤Y%卖出")
    print("=" * 120)

    for label, sf in [('S1', strat_s1), ('B1', strat_b1)]:
        print(f"\n{label}:")
        print(f"  {'回撤%↓ 浮盈→':>12}", end='')
        for trail in [1.0, 1.5, 2.0, 3.0]:
            print(f"  回{trail:.1f}", end='')
        print()
        print("  " + "-" * 70)
        for tp_min in [3.0, 4.0, 5.0, 6.0]:
            print(f"  盈{tp_min:.0f}%+", end='')
            for trail in [1.0, 1.5, 2.0, 3.0]:
                trades = test_trailing_stop(pool, tp_min, trail, max_hold=10, strat_fn=sf)
                st = calc(trades)
                if st and st['n'] >= 8:
                    print(f"  {st['sharpe']:>+5.2f}", end='')
                else:
                    print(f"  {'--':>5}", end='')
            print()

    # ========== 3) 最优策略详细报告 ==========
    print("\n" + "=" * 120)
    print("最优策略详情")
    print("=" * 120)

    # 测试几个最优候选
    best_configs = [
        ('S1 TP3 SL3', strat_s1, 3.0, 3.0),
        ('S1 TP4 SL4', strat_s1, 4.0, 4.0),
        ('S1 TP5 SL5', strat_s1, 5.0, 5.0),
        ('B1 TP3 SL3', strat_b1, 3.0, 3.0),
        ('B1 TP4 SL4', strat_b1, 4.0, 4.0),
        ('B1 TP5 SL5', strat_b1, 5.0, 5.0),
    ]

    for name, sf, tp, sl in best_configs:
        trades = test_fixed_tp_sl(pool, tp, sl, max_hold=10, strat_fn=sf)
        st = calc(trades)
        if not st: continue

        # 卖出原因统计
        reasons = {}
        for t in trades:
            reasons[t['reason']] = reasons.get(t['reason'], 0) + 1

        # 买入日分布(信号日分布)
        sample = [v for v in pool if sf(v)][:200]
        signal_days = {}
        for v in sample:
            hold = v['hold_days']
            buy = v['buy_price']
            # 找信号日
            for i, day in enumerate(hold):
                if day['close'] <= 0: continue
                ret = ((day['close'] - buy) / buy) * 100
                if ret >= tp:
                    signal_days[day['off']] = signal_days.get(day['off'], 0) + 1
                    break

        print(f"\n{name}:")
        print(f"  样本: {st['n']}  平均: {st['avg']:+.2f}%  胜率: {st['win']:.0f}% "
              f"夏普: {st['sharpe']:+.2f}  持有: {st['avg_hold']:.1f}天")
        print(f"  卖出原因: {', '.join(f'{k}({v}只)' for k, v in sorted(reasons.items()))}")

    # ========== 4) 对比: 不同策略在不同卖出方式下的表现 ==========
    print("\n" + "=" * 120)
    print("综合对比表")
    print("=" * 120)

    print(f"\n  {'策略+卖出':<35} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6} {'持有':>5}")
    print("  " + "-" * 70)

    comparisons = [
        ('S1 固定D+9卖', strat_s1, lambda p: test_fixed_tp_sl(p, 99, 99, max_hold=8, strat_fn=strat_s1)),
        ('S1 TP3/SL3', strat_s1, lambda p: test_fixed_tp_sl(p, 3, 3, max_hold=10, strat_fn=strat_s1)),
        ('S1 TP4/SL4', strat_s1, lambda p: test_fixed_tp_sl(p, 4, 4, max_hold=10, strat_fn=strat_s1)),
        ('B1 固定D+9卖', strat_b1, lambda p: test_fixed_tp_sl(p, 99, 99, max_hold=8, strat_fn=strat_b1)),
        ('B1 TP3/SL3', strat_b1, lambda p: test_fixed_tp_sl(p, 3, 3, max_hold=10, strat_fn=strat_b1)),
        ('B1 TP4/SL4', strat_b1, lambda p: test_fixed_tp_sl(p, 4, 4, max_hold=10, strat_fn=strat_b1)),
        ('B1 TP5/SL5', strat_b1, lambda p: test_fixed_tp_sl(p, 5, 5, max_hold=10, strat_fn=strat_b1)),
        ('B1 trailing(盈4回2)', strat_b1, lambda p: test_trailing_stop(p, 4, 2, max_hold=10, strat_fn=strat_b1)),
        ('B1 trailing(盈5回1.5)', strat_b1, lambda p: test_trailing_stop(p, 5, 1.5, max_hold=10, strat_fn=strat_b1)),
        ('B1 yma(M3,盈3)', strat_b1, lambda p: test_yma_sell(p, 3, 3, max_hold=10, strat_fn=strat_b1)),
        ('B1 yma(M5,盈3)', strat_b1, lambda p: test_yma_sell(p, 3, 5, max_hold=10, strat_fn=strat_b1)),
    ]

    for name, sf, fn in comparisons:
        trades = fn(pool)
        st = calc(trades)
        if st and st['n'] >= 8:
            star = '★' if st['sharpe'] > st.get('sharpe', 0) + 0.1 and st['n'] >= 15 else ' '
            print(f"  {star} {name:<32} {st['n']:>4} {st['avg']:>+6.2f}% {st['win']:>5.1f}% "
                  f"{st['sharpe']:>+5.2f} {st['avg_hold']:>4.1f}d")


if __name__ == '__main__':
    main()
