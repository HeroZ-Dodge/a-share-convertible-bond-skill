#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略 D+3→D+9 回测 — 多样本量对比
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


def main():
    cache = BacktestCache()
    today_str = datetime.now().strftime('%Y-%m-%d')

    strategies = {
        '策略1: pre3≤2%+mom10<5%+rc>0%': lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0,
        '策略2: pre3≤2%+mom10<5%': lambda v: v['pre3'] <= 2 and v['mom10'] < 5,
        '策略3: rc<-2%': lambda v: v['rc'] < -2,
        '策略4: pre7<0%': lambda v: v['pre7'] < 0,
    }

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

        # D+3 买入价
        buy_price = None
        if ri + 3 < len(sd) and sd[ri + 3] <= today_str:
            buy_price = prices[sd[ri + 3]]['close']

        # D+9 卖出价
        sell_price = None
        if ri + 9 < len(sd) and sd[ri + 9] <= today_str:
            sell_price = prices[sd[ri + 9]]['close']

        # 因子
        pre3 = 0
        if ri >= 3:
            p3 = prices[sd[ri-3]]['close']
            if p3 > 0: pre3 = ((reg_price - p3) / p3) * 100
        pre7 = 0
        if ri >= 7:
            p7 = prices[sd[ri-7]]['close']
            if p7 > 0: pre7 = ((reg_price - p7) / p7) * 100
        rc = 0
        if ri > 0:
            prev = prices[sd[ri-1]]['close']
            if prev > 0: rc = ((reg_price - prev) / prev) * 100
        mom10 = 0
        if ri >= 10:
            p10 = prices[sd[ri-10]]['close']
            if p10 > 0: mom10 = ((reg_price - p10) / p10) * 100

        pool.append({
            'code': sc, 'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor, 'reg_price': reg_price,
            'buy_price': buy_price, 'sell_price': sell_price,
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    limits = [50, 100, 150, 200]

    for sname, sfn in strategies.items():
        print(f"\n{'=' * 90}")
        print(f"  {sname}")
        print(f"  窗口: D+3 → D+9 (持有6天)")
        print(f"{'=' * 90}")

        print(f"  {'limit':>6} {'触发':>5} {'有效n':>5} "
              f"{'平均':>7} {'中位':>7} "
              f"{'胜率':>6} {'标准差':>7} "
              f"{'夏普':>6} {'最佳':>7} {'最差':>7}")
        print("  " + "-" * 80)

        for lim in limits:
            sample = pool[:lim]
            triggered = [v for v in sample if sfn(v) and v['buy_price'] and v['sell_price']]
            n = len(triggered)
            if n < 3:
                print(f"  {lim:>5} {'样本不足':>15}")
                continue

            rets = [((v['sell_price'] - v['buy_price']) / v['buy_price']) * 100 for v in triggered]
            avg = sum(rets) / len(rets)
            s = sorted(rets)
            med = s[len(s) // 2]
            win = sum(1 for x in rets if x > 0) / len(rets) * 100
            std = (sum((x - avg) ** 2 for x in rets) / len(rets)) ** 0.5
            sh = avg / std if std > 0 else 0

            print(f"  {lim:>5} {len(sample):>4}  {n:>4}  "
                  f"{avg:>+6.2f}% {med:>+6.2f}% "
                  f"{win:>5.1f}% {std:>+6.2f}% "
                  f"{sh:>+5.2f} {max(rets):>+6.2f}% {min(rets):>+6.2f}%")

        # limit=100 逐只
        sample = pool[:100]
        triggered = [v for v in sample if sfn(v) and v['buy_price'] and v['sell_price']]
        if triggered:
            print(f"\n  逐只明细 (limit=100):")
            print(f"  {'名称':>12} {'注册日':>12} {'D+3价':>8} {'D+9价':>8} "
                  f"{'D+3→9':>7} {'D+0→9':>7} {'差值':>6}")
            print("  " + "-" * 75)

            triggered.sort(key=lambda x: ((x['sell_price'] - x['buy_price']) / x['buy_price']) * 100, reverse=True)
            for v in triggered:
                ret_d39 = ((v['sell_price'] - v['buy_price']) / v['buy_price']) * 100
                ret_d09 = ((v['sell_price'] - v['reg_price']) / v['reg_price']) * 100
                diff = ret_d39 - ret_d09
                marker = '★' if ret_d09 > 5 else ' '
                print(f"  {marker} {v['name']:>12} {v['anchor']:>12} "
                      f"{v['buy_price']:>7.2f} {v['sell_price']:>7.2f} "
                      f"{ret_d39:>+6.1f}% {ret_d09:>+6.1f}% {diff:>+5.1f}%")

    # 汇总对比
    print(f"\n\n{'=' * 90}")
    print(f"  汇总: D+3→D+9 vs D+0→D+9")
    print(f"{'=' * 90}")

    # 也需要 D+0→D+9 的数据
    for lim in limits:
        print(f"\n  limit={lim}")
        print(f"  {'策略':<45} {'D+0→D+9':>18} {'D+3→D+9':>18} {'差值':>8}")
        print(f"  {'':.<45} {'平均/胜率/夏普':>18} {'平均/胜率/夏普':>18} {'':>8}")
        print("  " + "-" * 95)

        sample = pool[:lim]
        for sname, sfn in strategies.items():
            # D+0→D+9
            d09 = [v for v in sample if sfn(v) and v['sell_price']]
            d39 = [v for v in sample if sfn(v) and v['buy_price'] and v['sell_price']]

            if not d09 or not d39:
                print(f"  {sname:<45} {'N/A':>15}")
                continue

            rets_d09 = [((v['sell_price'] - v['reg_price']) / v['reg_price']) * 100 for v in d09]
            rets_d39 = [((v['sell_price'] - v['buy_price']) / v['buy_price']) * 100 for v in d39]

            def calc(r):
                avg = sum(r)/len(r)
                s = sorted(r)
                win = sum(1 for x in r if x > 0)/len(r)*100
                std = (sum((x-avg)**2 for x in r)/len(r))**0.5
                sh = avg/std if std > 0 else 0
                return avg, win, sh

            a0, w0, sh0 = calc(rets_d09)
            a3, w3, sh3 = calc(rets_d39)

            print(f"  {sname:<45} "
                  f"{a0:>+5.1f}%/{w0:.0f}%/{sh0:+.2f}  "
                  f"{a3:>+5.1f}%/{w3:.0f}%/{sh3:+.2f}  "
                  f"{a3-a0:>+5.1f}%")


if __name__ == '__main__':
    main()
