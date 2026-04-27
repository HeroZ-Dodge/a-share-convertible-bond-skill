#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于 T-1 数据的策略增强 — 用注册日前一天数据改善选股和退出

买入: D+1开盘买入 (注册日因子判断)
卖出: 动态 (TP/SL, trailing, 时间退出)
增强: 用注册日前一天(T-1)数据做二次过滤

T-1 可用数据:
  - 注册日前一天的价格/成交量/涨跌幅
  - 注册日前N天的趋势
  - 注册日当天的完整K线(pre3/mom10/rc/vol)
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

        # 注册日因子
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

        # T-1 数据 (注册日前一天)
        t1_close = prices[sd[ri-1]]['close'] if ri >= 1 else 0
        t1_open = prices[sd[ri-1]].get('open', 0) if ri >= 1 else 0
        t1_vol = prices[sd[ri-1]].get('volume', 0) if ri >= 1 else 0
        t1_body = ((t1_close - t1_open) / t1_open * 100) if t1_open > 0 else 0

        # T-1 前的趋势
        t5_close = prices[sd[ri-5]]['close'] if ri >= 5 else 0
        pre1 = ((t1_close - t5_close) / t5_close * 100) if t5_close > 0 and ri >= 5 else 0

        # D+1 开盘 (买入价)
        buy_idx = ri + 1
        buy_price = None
        if buy_idx < len(sd) and sd[buy_idx] <= today_str:
            buy_price = prices[sd[buy_idx]].get('open', 0)
        if not buy_price or buy_price <= 0: continue

        # 持仓数据
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
            't1_body': t1_body, 't1_vol': t1_vol, 'pre1': pre1,
            'buy_price': buy_price, 'hold_days': hold_days,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    return pool


def calc(trades):
    if not trades: return None
    rets = sorted([t['ret'] for t in trades])
    n = len(rets)
    avg = sum(rets)/n
    std = (sum((x-avg)**2 for x in rets)/n)**0.5
    sh = avg/std if std > 0 else 0
    win = sum(1 for x in rets if x > 0)/n*100
    return {'n':n, 'avg':avg, 'med':rets[n//2], 'win':win, 'std':std, 'sharpe':sh}


def run_tp_sl(pool, tp, sl, max_hold=10, strat_fn=None):
    """固定止盈止损"""
    if strat_fn: pool = [v for v in pool if strat_fn(v)]
    trades = []
    for v in pool:
        buy = v['buy_price']
        hold = v['hold_days']
        exit_off, exit_price, reason = None, None, None

        for i, day in enumerate(hold):
            if day['close'] <= 0: continue
            ret = ((day['close'] - buy) / buy) * 100
            if i > 0 and ret >= tp:
                exit_off, exit_price, reason = day['off'], day['close'], 'tp'
                break
            if i > 0 and ((buy - day['close']) / buy * 100) >= sl:
                exit_off, exit_price, reason = day['off'], day['close'], 'sl'
                break
            if i > 0 and day['off'] - 1 >= max_hold:
                exit_off, exit_price, reason = day['off'], day['close'], 'timeout'
                break

        if exit_off is None:
            last = hold[-1]
            exit_off, exit_price, reason = last['off'], last['close'], 'timeout'

        trades.append({'ret': ((exit_price - buy) / buy) * 100, 'hold': exit_off - 1, 'reason': reason})
    return trades


def strat_s1(v): return v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0
def strat_b1(v): return strat_s1(v) and v['vol_ratio'] < 0.8


def main():
    cache = BacktestCache()
    print("加载数据...", flush=True)
    pool = load_pool(cache)
    print(f"  总: {len(pool)}")

    s1_count = sum(1 for v in pool if strat_s1(v))
    b1_count = sum(1 for v in pool if strat_b1(v))
    print(f"  S1: {s1_count}, B1: {b1_count}")

    # ========== 1) T-1 数据与收益相关性 ==========
    print("\n" + "=" * 100)
    print("T-1 (注册日前一天) 数据与 D+1→D+9 收益相关性")
    print("=" * 100)

    # 用 S1 触发样本
    s1_pool = [v for v in pool if strat_s1(v)]
    b1_pool = [v for v in pool if strat_b1(v)]

    for label, sp in [('S1', s1_pool), ('B1', b1_pool)]:
        if not sp: continue
        t1_bodies = [v['t1_body'] for v in sp]
        pre1s = [v['pre1'] for v in sp]
        rets = []
        for v in sp:
            hold = v['hold_days']
            buy = v['buy_price']
            # D+9 收盘
            d9 = None
            for d in hold:
                if d['off'] == 8:
                    d9 = d
                    break
            if d9 and d9['close'] > 0:
                rets.append(((d9['close'] - buy) / buy) * 100)
            else:
                rets.append(0)

        avg_t1_body = sum(t1_bodies)/len(t1_bodies)
        avg_pre1 = sum(pre1s)/len(pre1s)
        avg_ret = sum(rets)/len(rets)

        # 按 t1_body 正/负分组
        pos_t1 = [rets[i] for i in range(len(rets)) if t1_bodies[i] > 0]
        neg_t1 = [rets[i] for i in range(len(rets)) if t1_bodies[i] <= 0]

        print(f"\n{label} (n={len(sp)}):")
        print(f"  t1_body均值={avg_t1_body:+.2f}%  pre1均值={avg_pre1:+.2f}%  平均收益={avg_ret:+.2f}%")
        if pos_t1:
            print(f"  T-1收涨: n={len(pos_t1)} 平均收益={sum(pos_t1)/len(pos_t1):+.2f}%")
        if neg_t1:
            print(f"  T-1收跌: n={len(neg_t1)} 平均收益={sum(neg_t1)/len(neg_t1):+.2f}%")

    # ========== 2) T-1 分组测试 ==========
    print("\n" + "=" * 100)
    print("T-1 分组 (注册日前一天涨跌) — S1 策略")
    print("=" * 100)

    # 用 S1 分组
    for tp, sl in [(3, 3), (5, 5)]:
        for t1_cond, t1_name in [
            (lambda v: v['t1_body'] > 0, 'T-1收涨'),
            (lambda v: v['t1_body'] <= 0, 'T-1收跌'),
        ]:
            filtered = [v for v in pool if strat_s1(v) and t1_cond(v)]
            trades = run_tp_sl(pool, tp, sl, max_hold=10, strat_fn=lambda v: strat_s1(v) and t1_cond(v))
            st = calc(trades)
            if st:
                print(f"  S1+TP{tp}/SL{sl} {t1_name}: n={st['n']} avg={st['avg']:+.2f}% "
                      f"win={st['win']:.0f}% sh={st['sharpe']:+.2f}")

    # ========== 3) 最优动态策略 — B1 深度 ==========
    print("\n" + "=" * 100)
    print("B1 最优退出策略 (D+1开盘买)")
    print("=" * 100)

    # 不同 TP/SL 组合
    configs = [
        ('固定D+9', 99, 99),
        ('TP3/SL3', 3, 3),
        ('TP4/SL4', 4, 4),
        ('TP5/SL5', 5, 5),
        ('TP6/SL4', 6, 4),
        ('TP5/SL3', 5, 3),
    ]

    for name, tp, sl in configs:
        mh = 8 if tp >= 99 else 10
        trades = run_tp_sl(pool, tp, sl, max_hold=mh, strat_fn=strat_b1)
        st = calc(trades)
        if not st: continue
        reasons = {}
        for t in trades:
            reasons[t['reason']] = reasons.get(t['reason'], 0) + 1

        print(f"\n  B1 {name}:")
        print(f"    n={st['n']} avg={st['avg']:+.2f}% med={st['med']:+.2f}% "
              f"win={st['win']:.0f}% sh={st['sharpe']:+.2f} hold={sum(t['hold'] for t in trades)/len(trades):.1f}d")
        print(f"    退出: {', '.join(f'{k}({v})' for k, v in sorted(reasons.items()))}")

    # ========== 4) 年化效率 ==========
    print("\n" + "=" * 100)
    print("年化效率对比")
    print("=" * 100)

    print(f"\n  {'策略':<20} {'样本':>4} {'单次':>7} {'持有':>5} {'年化':>8} {'夏普':>6}")
    print("  " + "-" * 70)

    for name, tp, sl in configs:
        mh = 8 if tp >= 99 else 10
        trades = run_tp_sl(pool, tp, sl, max_hold=mh, strat_fn=strat_b1)
        st = calc(trades)
        if not st or st['n'] < 5: continue
        avg_hold = sum(t['hold'] for t in trades)/len(trades)
        eff = st['avg'] / avg_hold * 245 if avg_hold > 0 else 0
        print(f"  {'B1 '+name:<20} {st['n']:>4} {st['avg']:>+6.2f}% {avg_hold:>4.1f}d "
              f"{eff:>+7.1f}% {st['sharpe']:>+5.2f}")

    # ========== 5) S1 同样对比 ==========
    print(f"\n  {'策略':<20} {'样本':>4} {'单次':>7} {'持有':>5} {'年化':>8} {'夏普':>6}")
    print("  " + "-" * 70)

    for name, tp, sl in configs:
        mh = 8 if tp >= 99 else 10
        trades = run_tp_sl(pool, tp, sl, max_hold=mh, strat_fn=strat_s1)
        st = calc(trades)
        if not st or st['n'] < 5: continue
        avg_hold = sum(t['hold'] for t in trades)/len(trades)
        eff = st['avg'] / avg_hold * 245 if avg_hold > 0 else 0
        print(f"  {'S1 '+name:<20} {st['n']:>4} {st['avg']:>+6.2f}% {avg_hold:>4.1f}d "
              f"{eff:>+7.1f}% {st['sharpe']:>+5.2f}")


if __name__ == '__main__':
    main()
