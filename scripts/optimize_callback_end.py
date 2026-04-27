#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优化"回调结束"策略 — 调参提高信号率
核心: pre3 + consec_down 的不同阈值组合
"""
import sys, os
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.backtest_cache import BacktestCache
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from strategy_scanner_flexible_timing import (
    build_pool, get_buy_price, test_exit, exit_tp_sl, exit_fixed,
    exit_trailing_stop, calc_stats
)

cache = BacktestCache()
pool = build_pool(cache)

exit_fn = exit_tp_sl(5, 5)

# 扫描 pre3 和 consec_down 的各种组合
print(f"{'='*100}")
print(f"  回调结束策略参数扫描 (exit=TP5/SL5, buy=D+1)")
print(f"{'='*100}")
print(f"  {'pre3':>6} {'consec_d':>8} {'样本':>5} {'信号率':>6} {'平均':>7} {'胜率':>6} {'夏普':>6} {'L=100 sh':>8} {'L=50 sh':>8}")
print("  " + "-" * 85)

for pre3_th in [0, -0.5, -1, -1.5, -2, -2.5, -3]:
    for cd_th in [0, 0.5, 1, 1.5, 2]:
        # Build condition: pre3 <= pre3_th AND consec_down == 0
        def cond(f, pth=pre3_th, cd=cd_th):
            if cd == 0:
                return f['pre3'] <= pth and f['consec_down'] == 0
            else:
                return f['pre3'] <= pth and f['consec_down'] <= cd

        triggered = []
        for p in pool:
            if cond(p['factors']):
                bp = get_buy_price(p, 1)
                if bp and bp > 0:
                    triggered.append((p, bp))

        if len(triggered) < 3:
            continue

        trades = []
        for p, bp in triggered:
            r = test_exit(p['hold_days'], bp, exit_fn)
            if r:
                trades.append(r)

        if len(trades) < 3:
            continue

        stats = calc_stats(trades)
        sig_rate = len(triggered) / len(pool) * 100

        # L=100
        triggered_100 = []
        for p in pool[:100]:
            if cond(p['factors']):
                bp = get_buy_price(p, 1)
                if bp and bp > 0:
                    triggered_100.append((p, bp))
        stats_100 = None
        if len(triggered_100) >= 3:
            t100 = []
            for p, bp in triggered_100:
                r = test_exit(p['hold_days'], bp, exit_fn)
                if r:
                    t100.append(r)
            if len(t100) >= 3:
                stats_100 = calc_stats(t100)

        # L=50
        triggered_50 = []
        for p in pool[:50]:
            if cond(p['factors']):
                bp = get_buy_price(p, 1)
                if bp and bp > 0:
                    triggered_50.append((p, bp))
        stats_50 = None
        if len(triggered_50) >= 3:
            t50 = []
            for p, bp in triggered_50:
                r = test_exit(p['hold_days'], bp, exit_fn)
                if r:
                    t50.append(r)
            if len(t50) >= 3:
                stats_50 = calc_stats(t50)

        sh_100_str = f"{stats_100['sharpe']:+.2f}" if stats_100 else "--"
        sh_50_str = f"{stats_50['sharpe']:+.2f}" if stats_50 else "--"
        cd_label = "0" if cd_th == 0 else f"<={cd_th}"
        print(f"  {pre3_th:>5.1f} {cd_label:>8} {stats['n']:>5} {sig_rate:>5.1f}% {stats['avg']:>+6.2f}% {stats['win']:>5.1f}% {stats['sharpe']:>+5.2f} {sh_100_str:>8} {sh_50_str:>8}")


# Now try adding vol_ratio condition for sample expansion
print(f"\n{'='*100}")
print(f"  回调结束 + vol 条件 (exit=TP5/SL5, buy=D+1)")
print(f"{'='*100}")
print(f"  {'条件':<50} {'样本':>5} {'信号率':>6} {'平均':>7} {'胜率':>6} {'夏普':>6} {'L=100 sh':>8} {'L=50 sh':>8}")
print("  " + "-" * 105)

vol_conditions = [
    ('+ vol5<=0.85', lambda f: f['vol_ratio5'] <= 0.85),
    ('+ vol5<=0.8', lambda f: f['vol_ratio5'] <= 0.8),
    ('+ vol5<=0.75', lambda f: f['vol_ratio5'] <= 0.75),
    ('+ vol3<=0.85', lambda f: f['vol_ratio3'] <= 0.85),
    ('+ vol3<=0.8', lambda f: f['vol_ratio3'] <= 0.8),
    ('+ vol10<=0.85', lambda f: f['vol_ratio10'] <= 0.85),
]

for name, vol_fn in vol_conditions:
    def cond(f, vfn=vol_fn):
        return f['pre3'] <= -1 and f['consec_down'] == 0 and vfn(f)

    triggered = []
    for p in pool:
        if cond(p['factors']):
            bp = get_buy_price(p, 1)
            if bp and bp > 0:
                triggered.append((p, bp))

    if len(triggered) < 3:
        continue

    trades = []
    for p, bp in triggered:
        r = test_exit(p['hold_days'], bp, exit_fn)
        if r:
            trades.append(r)

    if len(trades) < 3:
        continue

    stats = calc_stats(trades)
    sig_rate = len(triggered) / len(pool) * 100

    # L=100
    triggered_100 = []
    for p in pool[:100]:
        if cond(p['factors']):
            bp = get_buy_price(p, 1)
            if bp and bp > 0:
                triggered_100.append((p, bp))
    stats_100 = None
    if len(triggered_100) >= 3:
        t100 = []
        for p, bp in triggered_100:
            r = test_exit(p['hold_days'], bp, exit_fn)
            if r:
                t100.append(r)
        if len(t100) >= 3:
            stats_100 = calc_stats(t100)

    # L=50
    triggered_50 = []
    for p in pool[:50]:
        if cond(p['factors']):
            bp = get_buy_price(p, 1)
            if bp and bp > 0:
                triggered_50.append((p, bp))
    stats_50 = None
    if len(triggered_50) >= 3:
        t50 = []
        for p, bp in triggered_50:
            r = test_exit(p['hold_days'], bp, exit_fn)
            if r:
                t50.append(r)
        if len(t50) >= 3:
            stats_50 = calc_stats(t50)

    sh_100_str = f"{stats_100['sharpe']:+.2f}" if stats_100 else "--"
    sh_50_str = f"{stats_50['sharpe']:+.2f}" if stats_50 else "--"
    print(f"  pre3<=-1+consec_down=0{name:<42} {stats['n']:>5} {sig_rate:>5.1f}% {stats['avg']:>+6.2f}% {stats['win']:>5.1f}% {stats['sharpe']:>+5.2f} {sh_100_str:>8} {sh_50_str:>8}")


# Now test D+N variations
print(f"\n{'='*100}")
print(f"  回调结束 — 不同买入时机 (pre3<=-1 + consec_down=0)")
print(f"{'='*100}")

for buy_off in [1, 2, 3, 5]:
    for exit_name, exit_fn in [('TP5/SL5', exit_tp_sl(5,5)), ('TP7/SL7', exit_tp_sl(7,7)), ('D+9', exit_fixed(9)), ('TS3%', exit_trailing_stop(3))]:
        triggered = []
        for p in pool:
            if p['factors']['pre3'] <= -1 and p['factors']['consec_down'] == 0:
                bp = get_buy_price(p, buy_off)
                if bp and bp > 0:
                    triggered.append((p, bp))

        if len(triggered) < 3:
            continue

        trades = []
        for p, bp in triggered:
            r = test_exit(p['hold_days'], bp, exit_fn)
            if r:
                trades.append(r)

        if len(trades) < 3:
            continue

        stats = calc_stats(trades)
        sig_rate = len(triggered) / len(pool) * 100
        print(f"  D+{buy_off}买 {exit_name:>10}  样本={stats['n']:>3} 信号率={sig_rate:.1f}%  平均={stats['avg']:+.2f}%  胜率={stats['win']:.1f}%  夏普={stats['sharpe']:+.2f}  持有={stats['avg_hold']:.1f}d")


print(f"\n{'='*100}")
