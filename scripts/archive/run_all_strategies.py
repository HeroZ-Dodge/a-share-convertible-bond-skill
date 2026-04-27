#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一回测运行器 — 运行所有注册策略并输出对比报告

用法：
  python3 scripts/run_all_strategies.py                  # 分别回测各策略
  python3 scripts/run_all_strategies.py --combine         # 同时展示组合结果（任一触发）
  python3 scripts/run_all_strategies.py --combine-all     # 组合结果（全部触发）
  python3 scripts/run_all_strategies.py --limit 50        # 限制样本数
  python3 scripts/run_all_strategies.py --single 1        # 只运行策略1
"""
import sys, os, re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.backtest_cache import BacktestCache

from scripts.strategy_pre3_mom10_rc import backtest as bt1, NAME as N1
from scripts.strategy_pre3_mom10 import backtest as bt2, NAME as N2
from scripts.strategy_rc_negative import backtest as bt3, NAME as N3
from scripts.strategy_pre7_negative import backtest as bt4, NAME as N4

STRATEGIES = [
    ('策略1: pre3≤2% + mom10<5% + rc>0%', bt1),
    ('策略2: pre3≤2% + mom10<5%', bt2),
    ('策略3: rc<-2%', bt3),
    ('策略4: pre7<0%', bt4),
]

# 组合条件函数
COMBO_CONDITIONS = {
    '任一触发': lambda v: v.get('_s1', False) or v.get('_s2', False) or v.get('_s3', False) or v.get('_s4', False),
    '至少2个': lambda v: sum([v.get('_s1', False), v.get('_s2', False), v.get('_s3', False), v.get('_s4', False)]) >= 2,
    '全部触发': lambda v: v.get('_s1', False) and v.get('_s2', False) and v.get('_s3', False) and v.get('_s4', False),
}


def find_idx(sd, target):
    """找 <= target 的最后一个交易日（处理周末/节假日注册日）"""
    result = 0
    for i, d in enumerate(sd):
        if d <= target:
            result = i
        else:
            break
    return result


def calc_factors(prices, sd, ri):
    """计算因子（D+0 收盘价）"""
    reg_price = prices[sd[ri]]['close']

    pre3 = 0
    if ri >= 3:
        p3 = prices[sd[ri - 3]]['close']
        if p3 > 0: pre3 = ((reg_price - p3) / p3) * 100

    pre7 = 0
    if ri >= 7:
        p7 = prices[sd[ri - 7]]['close']
        if p7 > 0: pre7 = ((reg_price - p7) / p7) * 100

    rc = 0
    if ri > 0:
        prev = prices[sd[ri - 1]]['close']
        if prev > 0: rc = ((reg_price - prev) / prev) * 100

    mom10 = 0
    if ri >= 10:
        p10 = prices[sd[ri - 10]]['close']
        if p10 > 0: mom10 = ((reg_price - p10) / p10) * 100

    return {'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10}


def backtest_all(cache, limit=100, combo_mode=None):
    """统一回测：分别运行 + 可选组合模式

    Args:
        cache: BacktestCache instance
        limit: 样本数
        combo_mode: None / 'union' / 'intersection'
    """
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
        reg_price = prices[sd[ri]]['close']
        if reg_price <= 0: continue

        # D+1 开盘价作为买入价
        buy_idx = ri + 1
        buy_price = None
        if buy_idx < len(sd) and sd[buy_idx] <= today_str:
            buy_price = prices[sd[buy_idx]]['open']

        d9_idx = ri + 9
        d9_price = None
        d9_ret = 0
        if d9_idx < len(sd) and sd[d9_idx] <= today_str:
            d9_price = prices[sd[d9_idx]]['close']
            if buy_price and buy_price > 0:
                d9_ret = ((d9_price - buy_price) / buy_price) * 100

        if not buy_price or buy_price <= 0 or not d9_price:
            continue

        factors = calc_factors(prices, sd, ri)

        # 各策略是否触发
        s1 = factors['pre3'] <= 2 and factors['mom10'] < 5 and factors['rc'] > 0
        s2 = factors['pre3'] <= 2 and factors['mom10'] < 5
        s3 = factors['rc'] < -2
        s4 = factors['pre7'] < 0

        pool.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'reg_price': reg_price,
            'buy_price': buy_price,
            'd9_price': d9_price,
            'd9_ret': d9_ret,
            'factors': factors,
            '_s1': s1, '_s2': s2, '_s3': s3, '_s4': s4,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    sample = pool[:limit]

    def report(triggered, label):
        if not triggered:
            return {'name': label, 'n': 0}
        pcts = [v['d9_ret'] for v in triggered]
        s = sorted(pcts)
        n = len(s)
        avg = sum(s) / n
        med = s[n // 2]
        win_n = sum(1 for x in s if x > 0)
        win = win_n / n * 100
        std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
        sh = avg / std if std > 0 else 0
        return {'name': label, 'n': n, 'avg': avg, 'med': med, 'win': win, 'std': std, 'sharpe': sh, 'pcts': pcts}

    print("=" * 90)
    print(f"注册策略统一回测 (limit={limit}, 买入=D+1开盘, 卖出=D+9收盘)")
    print("=" * 90)

    results = []

    # 分别运行
    for i, (name, fn) in enumerate(STRATEGIES):
        print(f"\n{'─' * 90}")
        print(f"  运行 {name} ...")
        print(f"{'─' * 90}")
        r = fn(cache, limit=limit)
        results.append((name, r))

    # 组合模式
    combos = []
    if combo_mode == 'union':
        combos.append(('组合: 任一触发', COMBO_CONDITIONS['任一触发']))
    elif combo_mode == 'intersection':
        combos.append(('组合: 全部触发', COMBO_CONDITIONS['全部触发']))
    elif combo_mode is not None:
        combos.extend([
            ('组合: 任一触发', COMBO_CONDITIONS['任一触发']),
            ('组合: 至少2个', COMBO_CONDITIONS['至少2个']),
            ('组合: 全部触发', COMBO_CONDITIONS['全部触发']),
        ])

    for cname, cfn in combos:
        print(f"\n{'─' * 90}")
        print(f"  {cname}")
        print(f"{'─' * 90}")
        triggered = [v for v in sample if cfn(v)]
        r = report(triggered, cname)

        if r['n'] > 0:
            print(f"  样本: {r['n']}/{len(sample)} (触发率 {r['n']/len(sample)*100:.0f}%)")
            print(f"  平均收益: {r['avg']:+.2f}%    中位数: {r['med']:+.2f}%")
            print(f"  胜率:     {r['win']:.1f}%")
            print(f"  标准差:   {r['std']:.2f}%     夏普: {r['sharpe']:+.2f}")
            print(f"  最佳:     +{max(r['pcts']):.2f}%    最差: {min(r['pcts']):.2f}%")

            print(f"\n  逐只明细:")
            triggered.sort(key=lambda x: x['d9_ret'], reverse=True)
            for t in triggered:
                marker = '★' if t['d9_ret'] > 5 else ' '
                tags = []
                if t['_s1']: tags.append('S1')
                if t['_s2']: tags.append('S2')
                if t['_s3']: tags.append('S3')
                if t['_s4']: tags.append('S4')
                tag_str = '/'.join(tags)
                print(f"  {marker} {t['name']:>12} {t['anchor']}  买入价{t['buy_price']:.2f}→D+9价{t['d9_price']:.2f}  {t['d9_ret']:>+5.1f}%  [{tag_str}]")

        results.append((cname, r))

    # 汇总对比
    print("\n" + "=" * 90)
    print("汇总对比")
    print("=" * 90)
    print(f"  {'策略':<45} {'样本':>5} {'平均':>7} {'中位':>7} {'胜率':>6} {'标准差':>7} {'夏普':>6}")
    print("  " + "-" * 90)

    sorted_results = sorted(
        [(n, r) for n, r in results if r.get('n', 0) > 0],
        key=lambda x: x[1].get('sharpe', 0), reverse=True
    )

    for name, r in sorted_results:
        star = '★' if r.get('sharpe', 0) > 0.4 and r.get('n', 0) >= 15 else ' '
        print("  {}{:.<43} {:>4} {:>+6.2f}% {:>+6.2f}% {:>5.1f}% {:>6.2f}% {:>+5.2f}".format(
            star, name, r.get('n', 0), r.get('avg', 0), r.get('med', 0),
            r.get('win', 0), r.get('std', 0), r.get('sharpe', 0)))

    print()
    if sorted_results:
        best_name, best_r = sorted_results[0]
        print(f"  按夏普排序最佳: {best_name}")
        print(f"    平均收益 {best_r.get('avg', 0):+.2f}%, 胜率 {best_r.get('win', 0):.1f}%, 夏普 {best_r.get('sharpe', 0):+.2f}")

    return results


if __name__ == '__main__':
    limit = 100
    single = None
    combo_mode = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--limit' and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == '--single' and i + 1 < len(args):
            single = int(args[i + 1]) - 1
            i += 2
        elif args[i] == '--combine':
            combo_mode = 'default'
            i += 1
        elif args[i] == '--combine-all':
            combo_mode = 'all'
            i += 1
        else:
            i += 1

    if single is not None:
        cache = BacktestCache()
        name, fn = STRATEGIES[single]
        print(f"运行 {name}")
        fn(cache, limit=limit)
    else:
        cache = BacktestCache()
        backtest_all(cache, limit=limit, combo_mode=combo_mode)
