#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证灵活时机策略的稳定性
用法:
  python3 scripts/validate_flexible_strategies.py
  python3 scripts/validate_flexible_strategies.py --limit 200
"""
import sys, os, re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.backtest_cache import BacktestCache

# 直接 import 扫描脚本中的函数
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from strategy_scanner_flexible_timing import (
    build_pool, find_idx, calc_extended_factors, get_buy_price,
    test_exit, exit_tp_sl, exit_fixed, exit_trailing_stop, calc_stats
)


# ========== 定义候选策略 ==========

def s_callback_end(f):
    """回调结束: pre3<=-1 + 连续下跌天数=0 (D+1 买)"""
    return f['pre3'] <= -1 and f['consec_down'] == 0

def s_callback_end_strict(f):
    """回调结束(严格): pre3<=-2 + 连续下跌天数=0"""
    return f['pre3'] <= -2 and f['consec_down'] == 0

def s_callback_no_vol(f):
    """回调结束无其他条件: pre3<=-1 + consec_down=0 (同 s_callback_end)"""
    return f['pre3'] <= -1 and f['consec_down'] == 0

def s_callback_d2(f):
    """回调缩量+下跌结束 D+2买"""
    return f['pre3'] <= -1 and f['consec_down'] == 0 and f['vol_ratio5'] <= 0.85

def s_ma5_neg_vol(f):
    """MA5负偏离 + 缩量"""
    return f['pre3'] <= -1 and f['ma5_pct'] <= -1 and f['vol_ratio5'] <= 0.8

def s_vol3_strict(f):
    """回调结束 + vol_ratio3"""
    return f['pre3'] <= -1 and f['consec_down'] == 0 and f['vol_ratio3'] <= 0.8

def s_ma10_neg(f):
    """pre3回调 + MA10负偏离"""
    return f['pre3'] <= -2 and f['ma10_pct'] <= -2

def s_ma20_neg_vol(f):
    """MA20负偏离 + 缩量"""
    return f['ma20_pct'] <= -3 and f['vol_ratio5'] <= 0.8

def s_pre5_vol(f):
    """pre5回调 + 缩量"""
    return f['pre5'] <= -3 and f['vol_ratio5'] <= 0.8

def s_consec_down(f):
    """连续下跌>=2天"""
    return f['consec_down'] >= 2

def s_shrink_drop(f):
    """缩量+下跌共振 (已有因子)"""
    return f['pre3'] < -2 and f['vol_ratio5'] < 0.8

def s_callback_ma5(f):
    """回调结束 + MA5正偏离(超跌反弹)"""
    return f['pre3'] <= -1 and f['ma5_pct'] <= 0 and f['vol_ratio5'] <= 0.85


strategies = [
    ('回调结束(pre3<=-1+consec_down=0)', s_callback_end),
    ('回调结束严格(pre3<=-2+consec_down=0)', s_callback_end_strict),
    ('回调+MA5负偏离+缩量', s_ma5_neg_vol),
    ('回调+vol3<=0.8', s_vol3_strict),
    ('pre3<=-2+MA10<=-2', s_ma10_neg),
    ('MA20<=-3+缩量', s_ma20_neg_vol),
    ('pre5<=-3+缩量', s_pre5_vol),
    ('连续下跌>=2', s_consec_down),
    ('回调结束+vol5<=0.85(D+2)', s_callback_d2),
    ('回调+MA5<=0+vol<=0.85', s_callback_ma5),
]

exits = [
    ('D+9固定', exit_fixed(9)),
    ('TP7/SL7', exit_tp_sl(7, 7)),
    ('TP5/SL5', exit_tp_sl(5, 5)),
    ('TP3/SL3', exit_tp_sl(3, 3)),
    ('TS3%', exit_trailing_stop(3)),
    ('TS5%', exit_trailing_stop(5)),
]


def main():
    args = sys.argv[1:]
    limit = None
    i = 0
    while i < len(args):
        if args[i] == '--limit' and i + 1 < len(args):
            limit = int(args[i+1])
            i += 2
        else:
            i += 1

    cache = BacktestCache()
    pool = build_pool(cache)
    if limit:
        pool = pool[:limit]

    print(f"\n{'='*130}")
    print(f"  灵活时机策略稳定性验证 (N={len(pool)})")
    print(f"{'='*130}")

    for name, cond_fn in strategies:
        triggered = []
        for p in pool:
            if cond_fn(p['factors']):
                bp = get_buy_price(p, 1)
                if bp and bp > 0:
                    triggered.append((p, bp))

        if len(triggered) < 5:
            print(f"\n  {name}: 信号不足({len(triggered)})")
            continue

        print(f"\n  📊 {name} (样本={len(triggered)}, 信号率={len(triggered)/len(pool)*100:.1f}%)")
        print(f"  {'退出':>10} {'L=100':>20} {'L=150':>20} {'L=200':>20} {'全量':>20}")
        print(f"  {'':>10} {'n avg sh eff':>20} {'n avg sh eff':>20} {'n avg sh eff':>20} {'n avg sh eff':>20}")
        print("  " + "-" * 100)

        for exit_name, exit_fn in exits:
            row = []
            for lim in [100, 150, 200, 0]:
                pl = pool[:lim] if lim else pool
                # 重新从 pl 中找触发
                tr = []
                for p in pl:
                    if cond_fn(p['factors']):
                        bp = get_buy_price(p, 1)
                        if bp and bp > 0:
                            tr.append((p, bp))
                if len(tr) < 5:
                    row.append('        --')
                    continue
                trades = []
                for p, bp in tr:
                    r = test_exit(p['hold_days'], bp, exit_fn)
                    if r:
                        trades.append(r)
                if len(trades) < 5:
                    row.append('        --')
                    continue
                stats = calc_stats(trades)
                eff = stats['avg'] / stats['avg_hold'] * 245 if stats['avg_hold'] > 0 else 0
                row.append(f"{stats['n']:>3} {stats['avg']:>+4.1f}% sh={stats['sharpe']:+.2f} eff={eff:+.0f}%")
            print(f"    {exit_name:>10} {row[0]:>22} {row[1]:>22} {row[2]:>22} {row[3]:>22}")


if __name__ == '__main__':
    main()
