#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册后持有期信号挖掘 + 回测

目标：
  - 不兼容主监控脚本的复杂逻辑
  - 只研究“同意注册后 N 天”的持有期策略
  - 支持固定候选规则回测和简单网格搜索

用法：
  --backtest                 回测内置候选规则
  --mine                     网格搜索最优规则
  --limit 100                只取最近 N 只样本
  --top 20                   网格搜索输出前 N 条
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from itertools import product

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.backtest_cache import BacktestCache

BACKTEST_START_DATE = '2024-01-01'
MAX_HOLD_DAYS = 20


def find_idx(dates, target):
    """找到 d <= target 的最后一个索引"""
    result = 0
    for i, d in enumerate(dates):
        if d <= target:
            result = i
        else:
            break
    return result


def calc_stats(trades):
    """计算简单统计值"""
    if not trades:
        return None
    rets = sorted(t['ret'] for t in trades)
    n = len(rets)
    avg = sum(rets) / n
    std = (sum((x - avg) ** 2 for x in rets) / n) ** 0.5
    sharpe = avg / std if std > 0 else 0
    win = sum(1 for x in rets if x > 0) / n * 100
    avg_hold = sum(t['hold'] for t in trades) / n
    return {
        'n': n,
        'avg': avg,
        'win': win,
        'std': std,
        'sharpe': sharpe,
        'avg_hold': avg_hold,
        'best': max(rets),
        'worst': min(rets),
    }


def parse_anchor(progress_full):
    """从 progress_full 里提取同意注册日期"""
    if not progress_full:
        return ''
    for line in progress_full.replace('<br>', '\n').split('\n'):
        if '同意注册' in line:
            m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
            if m:
                return m.group(1)
    return ''


def _calendar_diff(left: str, right: str) -> int:
    try:
        ldt = datetime.strptime(left, '%Y-%m-%d').date()
        rdt = datetime.strptime(right, '%Y-%m-%d').date()
        return (ldt - rdt).days
    except Exception:
        return 0


@dataclass(frozen=True)
class HoldRule:
    key: str
    label: str
    display_name: str
    condition: object


RULES = [
    HoldRule(
        key='hold_core',
        label='age5-12+pre3<=0+mom10>=0+rc>=0+vol<=1.0',
        display_name='注册后核心',
        condition=lambda f: 5 <= f['age'] <= 12
        and f['pre3'] <= 0
        and f['mom10'] >= 0
        and f['rc'] >= 0
        and f['vol_ratio5'] <= 1.0,
    ),
    HoldRule(
        key='hold_loose',
        label='age5-12+pre3<=0+mom10>=-2+vol<=1.0',
        display_name='注册后宽松',
        condition=lambda f: 5 <= f['age'] <= 12
        and f['pre3'] <= 0
        and f['mom10'] >= -2
        and f['vol_ratio5'] <= 1.0,
    ),
    HoldRule(
        key='hold_pullback',
        label='age5-12+pre3<=-2+mom10>=0+rc>=0+vol<=1.0',
        display_name='注册后回撤反弹',
        condition=lambda f: 5 <= f['age'] <= 12
        and f['pre3'] <= -2
        and f['mom10'] >= 0
        and f['rc'] >= 0
        and f['vol_ratio5'] <= 1.0,
    ),
]


def build_samples(cache, limit=0):
    """构建历史样本缓存：每只债券保留注册后完整价格序列"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    bonds = cache.get_jisilu_bonds(phase='注册', limit=0)
    samples = []
    candidates = []

    for b in bonds:
        sc = b.get('stock_code')
        if not sc:
            continue
        anchor = parse_anchor(b.get('progress_full', ''))
        if not anchor or anchor < BACKTEST_START_DATE or anchor > today_str:
            continue
        candidates.append((anchor, b))

    candidates.sort(key=lambda x: x[0], reverse=True)
    if limit:
        candidates = candidates[:limit]

    for anchor, b in candidates:
        sc = b.get('stock_code')
        prices = cache.get_kline_as_dict(sc, days=1500, skip_freshness_check=True)
        if not prices:
            continue
        sd = sorted(prices.keys())
        ri = find_idx(sd, anchor)
        if ri >= len(sd) - 1:
            continue
        samples.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'prices': prices,
            'dates': sd,
            'reg_idx': ri,
        })

    return samples


def compute_factors(sample, idx):
    """计算某个交易日的持有期因子"""
    prices = sample['prices']
    sd = sample['dates']
    anchor = sample['anchor']
    reg_idx = sample['reg_idx']
    reg_dt = datetime.strptime(anchor, '%Y-%m-%d')
    signal_date = sd[idx]
    reg_close = prices[signal_date]['close']
    if reg_close <= 0 or idx < 10:
        return None

    pre3 = ((reg_close - prices[sd[idx - 3]]['close']) / prices[sd[idx - 3]]['close'] * 100) if idx >= 3 else 0
    pre5 = ((reg_close - prices[sd[idx - 5]]['close']) / prices[sd[idx - 5]]['close'] * 100) if idx >= 5 else 0
    mom10 = ((reg_close - prices[sd[idx - 10]]['close']) / prices[sd[idx - 10]]['close'] * 100) if idx >= 10 else 0
    rc = ((reg_close - prices[sd[idx - 1]]['close']) / prices[sd[idx - 1]]['close'] * 100) if idx > 0 else 0

    vol_now = prices[signal_date].get('volume', 0)
    vol_avg5 = 0
    if idx >= 5:
        vlist = [prices[sd[idx - k]].get('volume', 0) for k in range(1, 6)
                 if prices[sd[idx - k]].get('volume', 0) > 0]
        if vlist:
            vol_avg5 = sum(vlist) / len(vlist)
    vol_ratio5 = (vol_now / vol_avg5) if vol_avg5 > 0 else 1

    consec_down = 0
    for k in range(1, idx):
        prev_c = prices[sd[idx - k]]['close']
        curr_c = reg_close if k == 1 else prices[sd[idx - k + 1]]['close']
        if curr_c < prev_c:
            consec_down += 1
        else:
            break

    age = _calendar_diff(signal_date, anchor)
    buy_idx = idx + 1
    buy_price = prices[sd[buy_idx]].get('open', 0) if buy_idx < len(sd) else 0

    return {
        'pre3': pre3,
        'pre5': pre5,
        'mom10': mom10,
        'rc': rc,
        'vol_ratio5': vol_ratio5,
        'consec_down': consec_down,
        'age': age,
        'buy_price': buy_price,
        'signal_date': signal_date,
        'current_close': reg_close,
    }


def first_match_trade(sample, cond):
    """按首个触发日生成一笔交易"""
    sd = sample['dates']
    prices = sample['prices']
    today_str = datetime.now().strftime('%Y-%m-%d')

    for idx in range(sample['reg_idx'] + 1, len(sd)):
        if sd[idx] > today_str:
            break
        factors = compute_factors(sample, idx)
        if not factors or not cond(factors):
            continue
        buy_price = factors['buy_price']
        if not buy_price or buy_price <= 0:
            return None

        hold_days = []
        for off in range(1, MAX_HOLD_DAYS + 1):
            j = idx + off
            if j >= len(sd) or sd[j] > today_str:
                break
            p = prices[sd[j]]
            hold_days.append({
                'off': off,
                'date': sd[j],
                'close': p.get('close', 0),
            })
        if len(hold_days) < 2:
            return None

        exit_off = None
        exit_price = None
        for i, day in enumerate(hold_days):
            if i == 0:
                continue
            if day['close'] <= 0:
                continue
            ret = ((day['close'] - buy_price) / buy_price) * 100
            if ret >= 5 or ((buy_price - day['close']) / buy_price) * 100 >= 5 or day['off'] - 1 >= 10:
                exit_off, exit_price = day['off'], day['close']
                break
        if exit_off is None:
            last = hold_days[-1]
            exit_off, exit_price = last['off'], last['close']

        return {
            'ret': ((exit_price - buy_price) / buy_price) * 100,
            'hold': exit_off - 1,
            'signal_date': factors['signal_date'],
            'age': factors['age'],
            'buy_price': buy_price,
            'signal_factors': factors,
        }

    return None


def backtest_rule(samples, rule):
    """回测单条规则"""
    trades = []
    for sample in samples:
        trade = first_match_trade(sample, rule.condition)
        if trade:
            trades.append(trade)
    return calc_stats(trades), trades


def grid_search(samples, top_n=20):
    """简单网格搜索"""
    candidates = []
    for age_lo, age_hi, pre_max, mom_min, rc_min, vol_max in product(
        [4, 5, 6],
        [10, 12, 14],
        [-2, -1, 0],
        [-1, 0, 1],
        [-1, 0],
        [0.9, 1.0],
    ):
        if age_lo >= age_hi:
            continue

        rule = HoldRule(
            key=f'age{age_lo}_{age_hi}_p{pre_max}_m{mom_min}_r{rc_min}_v{vol_max}',
            label=f'age{age_lo}-{age_hi}+pre3<={pre_max}+mom10>={mom_min}+rc>={rc_min}+vol<={vol_max}',
            display_name='grid',
            condition=lambda f, age_lo=age_lo, age_hi=age_hi, pre_max=pre_max, mom_min=mom_min, rc_min=rc_min, vol_max=vol_max: (
                age_lo <= f['age'] <= age_hi
                and f['pre3'] <= pre_max
                and f['mom10'] >= mom_min
                and f['rc'] >= rc_min
                and f['vol_ratio5'] <= vol_max
            ),
        )

        stats, trades = backtest_rule(samples, rule)
        if not stats or stats['n'] < 10:
            continue
        candidates.append((stats['avg'], stats['sharpe'], stats['win'], stats['n'], stats['avg_hold'], rule, stats))

    candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return candidates[:top_n]


def print_rule_stats(rule, stats):
    """打印规则统计"""
    if not stats:
        print(f"  {rule.display_name}: 样本不足")
        return
    eff = stats['avg'] / stats['avg_hold'] * 245 if stats['avg_hold'] > 0 else 0
    print(
        f"  {rule.display_name:<10} "
        f"{stats['n']:>4} {stats['avg']:>+6.2f}% {stats['win']:>5.1f}% "
        f"{stats['sharpe']:>+5.2f} {stats['avg_hold']:>4.1f}d {eff:>+7.1f}% "
        f"[{rule.label}]"
    )


def main():
    cache = BacktestCache()
    args = sys.argv[1:]
    do_backtest = '--backtest' in args or '--mine' in args
    do_mine = '--mine' in args
    top_n = 20
    limit = 0

    for i, arg in enumerate(args):
        if arg == '--top' and i + 1 < len(args):
            try:
                top_n = int(args[i + 1])
            except ValueError:
                pass
        if arg == '--limit' and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                pass

    if not do_backtest:
        print("可用: --backtest, --mine, --limit N, --top N")
        return

    samples = build_samples(cache, limit=limit)
    print(f"\n{'=' * 100}")
    print("注册后持有期挖掘")
    print(f"{'=' * 100}")
    print(f"样本数: {len(samples)}")

    print(f"\n{'-' * 100}")
    print("内置候选规则回测 (TP5/SL5)")
    print(f"{'-' * 100}")
    for rule in RULES:
        stats, _ = backtest_rule(samples, rule)
        print_rule_stats(rule, stats)

    if do_mine:
        print(f"\n{'-' * 100}")
        print(f"网格搜索 Top {top_n}")
        print(f"{'-' * 100}")
        best = grid_search(samples, top_n=top_n)
        if not best:
            print("  无满足最小样本条件的组合")
            return
        for avg, sharpe, win, n, avg_hold, rule, stats in best:
            eff = avg / avg_hold * 245 if avg_hold > 0 else 0
            print(
                f"  {rule.key:<28} "
                f"{n:>4} {avg:>+6.2f}% {win:>5.1f}% {sharpe:>+5.2f} "
                f"{avg_hold:>4.1f}d {eff:>+7.1f}% [{rule.label}]"
            )


if __name__ == '__main__':
    main()
