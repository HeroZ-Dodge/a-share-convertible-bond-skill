#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终稳定性验证 — 灵活时机策略 Top 候选
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

# 候选策略定义
strategies = {
    # 最佳平衡: 13.1% 信号率, sh=+0.43
    'A1': ('pre3<=-0.5+cd=0', lambda f: f['pre3'] <= -0.5 and f['consec_down'] == 0),

    # 高信号率: 19.9% 信号率, sh=+0.33
    'B1': ('pre3<=-1+cd<=1', lambda f: f['pre3'] <= -1 and f['consec_down'] <= 1),

    # 均衡: 16.9% 信号率, sh=+0.40
    'B2': ('pre3<=-1.5+cd<=1', lambda f: f['pre3'] <= -1.5 and f['consec_down'] <= 1),

    # 高夏普低信号率: 11.7%, sh=+0.38
    'C1': ('pre3<=-1+cd=0', lambda f: f['pre3'] <= -1 and f['consec_down'] == 0),

    # 宽松: 22.4% 信号率, sh=+0.33
    'D1': ('pre3<=-0.5+cd<=1', lambda f: f['pre3'] <= -0.5 and f['consec_down'] <= 1),

    # 对比：现有 broad_momentum
    'broad_mom': ('pre3<=2+mom10<5 (现有)', lambda f: f['pre3'] <= 2 and f['mom10'] < 5),
}

exits = [
    ('D+9', exit_fixed(9)),
    ('TP7/SL7', exit_tp_sl(7, 7)),
    ('TP5/SL5', exit_tp_sl(5, 5)),
    ('TP3/SL3', exit_tp_sl(3, 3)),
    ('TS3%', exit_trailing_stop(3)),
    ('TS5%', exit_trailing_stop(5)),
]

print(f"\n{'='*140}")
print(f"  灵活时机策略稳定性验证 (总样本={len(pool)})")
print(f"{'='*140}")

for key in ['A1', 'B1', 'B2', 'C1', 'D1', 'broad_mom']:
    name, cond_fn = strategies[key]

    # 找最大触发样本数
    max_n = 0
    for lim in [100, 150, 200, 0]:
        pl = pool[:lim] if lim else pool
        n = sum(1 for p in pl if cond_fn(p['factors']))
        max_n = max(max_n, n)

    if max_n < 3:
        print(f"\n  {name}: 信号不足")
        continue

    print(f"\n  {'='*70}")
    print(f"  📊 {name}")
    print(f"  {'='*70}")
    print(f"  {'退出':>10} {'L=100':>24} {'L=150':>24} {'L=200':>24} {'全量':>24}")
    print(f"  {'':>10} {'n avg sh eff':>24} {'n avg sh eff':>24} {'n avg sh eff':>24} {'n avg sh eff':>24}")
    print("  " + "-" * 115)

    for exit_name, exit_fn in exits:
        row = []
        for lim in [100, 150, 200, 0]:
            pl = pool[:lim] if lim else pool
            tr = []
            for p in pl:
                if cond_fn(p['factors']):
                    bp = get_buy_price(p, 1)
                    if bp and bp > 0:
                        tr.append((p, bp))
            if len(tr) < 3:
                row.append(f"{'--':>22}")
                continue
            trades = []
            for p, bp in tr:
                r = test_exit(p['hold_days'], bp, exit_fn)
                if r:
                    trades.append(r)
            if len(trades) < 3:
                row.append(f"{'--':>22}")
                continue
            stats = calc_stats(trades)
            eff = stats['avg'] / stats['avg_hold'] * 245 if stats['avg_hold'] > 0 else 0
            row.append(f"{stats['n']:>3} {stats['avg']:>+4.1f}% sh={stats['sharpe']:+.2f} eff={eff:+.0f}%")
        print(f"    {exit_name:>10} {row[0]:>26} {row[1]:>26} {row[2]:>26} {row[3]:>26}")


# 组合回测: 现有策略 + callback_end 的组合
print(f"\n{'='*140}")
print(f"  组合回测: broad_momentum + callback_end")
print(f"{'='*140}")

combo_strategies = {
    'broad_mom': lambda f: f['pre3'] <= 2 and f['mom10'] < 5,
    'callback_A1': lambda f: f['pre3'] <= -0.5 and f['consec_down'] == 0,
    'callback_B1': lambda f: f['pre3'] <= -1 and f['consec_down'] <= 1,
}

exit_fn = exit_tp_sl(5, 5)

for lim in [100, 150, 200, 0]:
    pl = pool[:lim] if lim else pool
    label = f'L={lim}' if lim else '全量'

    # broad_mom only
    tr_bm = []
    for p in pl:
        if combo_strategies['broad_mom'](p['factors']):
            bp = get_buy_price(p, 1)
            if bp and bp > 0:
                tr_bm.append((p, bp))

    # callback A1 only
    tr_cb = []
    for p in pl:
        if combo_strategies['callback_A1'](p['factors']):
            bp = get_buy_price(p, 1)
            if bp and bp > 0:
                tr_cb.append((p, bp))

    # union
    tr_union = []
    for p in pl:
        if combo_strategies['broad_mom'](p['factors']) or combo_strategies['callback_A1'](p['factors']):
            bp = get_buy_price(p, 1)
            if bp and bp > 0:
                tr_union.append((p, bp))

    print(f"\n  {label}:")
    for name, tr, mark in [('broad_mom', tr_bm, '[现有]'), ('callback_A1', tr_cb, '[新]'), ('union', tr_union, '[组合]')]:
        if len(tr) < 3:
            print(f"    {name}{mark}: 不足")
            continue
        trades = []
        for p, bp in tr:
            r = test_exit(p['hold_days'], bp, exit_fn)
            if r:
                trades.append(r)
        if len(trades) < 3:
            continue
        stats = calc_stats(trades)
        eff = stats['avg'] / stats['avg_hold'] * 245 if stats['avg_hold'] > 0 else 0
        sig_rate = len(tr) / len(pl) * 100
        print(f"    {name}{mark}: n={stats['n']:>3} 信号率={sig_rate:.1f}%  avg={stats['avg']:+.2f}%  win={stats['win']:.1f}%  sh={stats['sharpe']:+.2f}  eff={eff:+.0f}%")


print(f"\n{'='*140}")
