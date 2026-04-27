#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册策略 4：注册前7天下跌(<0%)
"""
import sys, os, re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.backtest_cache import BacktestCache


def find_idx(sd, target):
    """找 <= target 的最后一个交易日（处理周末/节假日注册日）"""
    result = 0
    for i, d in enumerate(sd):
        if d <= target:
            result = i
        else:
            break
    return result


NAME = "策略4: pre7<0%"
BUY_OFFSET = 1
SELL_OFFSET = 9
DESCRIPTION = """
入场条件（注册日当天可判断）：
  - 注册前7天累计跌幅 > 0%   (注册前走势偏弱)
买入：注册日+1开盘价 | 退出：注册日+9收盘价
预期：平均 +4.3%, 胜率 66%, 夏普 0.38, 样本 44
"""


def check(bond_info, cache, today_str=None):
    if today_str is None:
        today_str = datetime.now().strftime('%Y-%m-%d')
    anchor = bond_info.get('anchor_date', '')
    if not anchor:
        return False, {}
    sc = bond_info['stock_code']
    prices = cache.get_kline_as_dict(sc, days=1500)
    if not prices:
        return False, {}
    sd = sorted(prices.keys())
    ri = find_idx(sd, anchor)
    reg_price = prices[sd[ri]]['close']
    if reg_price <= 0:
        return False, {}

    pre7_ret = 0
    if ri >= 7:
        p7 = prices[sd[ri - 7]]['close']
        if p7 > 0: pre7_ret = ((reg_price - p7) / p7) * 100

    ok = pre7_ret < 0
    return ok, {
        'pre7': round(pre7_ret, 2),
        'reg_price': round(reg_price, 2),
        'reg_date': anchor,
    }


def backtest(cache, bonds=None, limit=100):
    if bonds is None:
        bonds = cache.get_jisilu_bonds(phase='注册', limit=0)
    today_str = datetime.now().strftime('%Y-%m-%d')

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

        pre7_ret = 0
        if ri >= 7:
            p7 = prices[sd[ri - 7]]['close']
            if p7 > 0: pre7_ret = ((reg_price - p7) / p7) * 100

        # D+1 开盘价作为买入价
        buy_idx = ri + BUY_OFFSET
        buy_price = None
        if buy_idx < len(sd) and sd[buy_idx] <= today_str:
            buy_price = prices[sd[buy_idx]]['open']

        d9_idx = ri + SELL_OFFSET
        d9_price = None
        d9_ret = 0
        if d9_idx < len(sd) and sd[d9_idx] <= today_str:
            d9_price = prices[sd[d9_idx]]['close']
            if buy_price and buy_price > 0:
                d9_ret = ((d9_price - buy_price) / buy_price) * 100

        if not buy_price or buy_price <= 0 or not d9_price:
            continue

        pool.append({
            'code': sc, 'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'reg_date': anchor, 'reg_price': reg_price, 'buy_price': buy_price,
            'd9_price': d9_price, 'd9_ret': d9_ret, 'pre7': pre7_ret,
            'prices': prices, 'sd': sd, 'ri': ri,
        })

    pool.sort(key=lambda x: x['reg_date'], reverse=True)
    sample = pool[:limit]

    triggered = [v for v in sample if v['pre7'] < 0]

    return _report(triggered, sample)


def _report(triggered, sample):
    if not triggered:
        return {'name': NAME, 'triggered': 0, 'pcts': []}
    pcts = [t['d9_ret'] for t in triggered]
    s = sorted(pcts)
    n = len(s)
    avg = sum(s) / n
    med = s[n // 2]
    win_n = sum(1 for x in s if x > 0)
    win_rate = win_n / n * 100
    std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
    sharpe = avg / std if std > 0 else 0

    print("=" * 80)
    print(NAME)
    print("=" * 80)
    print(f"  样本: {n}/{len(sample)} (触发率 {n/len(sample)*100:.0f}%)")
    print(f"  平均收益: {avg:+.2f}%    中位数: {med:+.2f}%")
    print(f"  胜率:     {win_rate:.1f}%  ({win_n}/{n})")
    print(f"  标准差:   {std:.2f}%     夏普: {sharpe:+.2f}")
    print(f"  最佳:     +{max(s):.2f}%    最差: {min(s):.2f}%")
    hold = SELL_OFFSET - BUY_OFFSET
    print(f"  年化效率: {avg/hold*245:+.1f}%")

    print(f"\n  逐只明细:")
    triggered.sort(key=lambda x: x['d9_ret'], reverse=True)
    for t in triggered:
        marker = '★' if t['d9_ret'] > 5 else ' '
        print(f"  {marker} {t['name']:>12} {t['reg_date']}  买入价{t['buy_price']:.2f} → D+9价{t['d9_price']:.2f}  {t['d9_ret']:>+5.1f}%  pre7={t['pre7']:+.1f}%")

    return {'name': NAME, 'n': n, 'avg': avg, 'med': med, 'win': win_rate, 'std': std, 'sharpe': sharpe, 'pcts': pcts}


if __name__ == '__main__':
    cache = BacktestCache()
    print(DESCRIPTION)
    backtest(cache, limit=100)
