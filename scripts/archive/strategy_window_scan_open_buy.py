#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修正版窗口扫描 — 信号日次日开盘买入
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


def calc_factors(prices, sd, ri):
    anchor_price = prices[sd[ri]]['close']

    pre3 = 0
    if ri >= 3:
        p3 = prices[sd[ri - 3]]['close']
        if p3 > 0: pre3 = ((anchor_price - p3) / p3) * 100

    pre7 = 0
    if ri >= 7:
        p7 = prices[sd[ri - 7]]['close']
        if p7 > 0: pre7 = ((anchor_price - p7) / p7) * 100

    rc = 0
    if ri > 0:
        prev = prices[sd[ri - 1]]['close']
        if prev > 0: rc = ((anchor_price - prev) / prev) * 100

    mom10 = 0
    if ri >= 10:
        p10 = prices[sd[ri - 10]]['close']
        if p10 > 0: mom10 = ((anchor_price - p10) / p10) * 100

    return {'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10}


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

        factors = calc_factors(prices, sd, ri)

        # 各信号日的次日开盘价
        buy_opens = {}
        for sig in range(0, 6):
            buy_idx = ri + sig + 1
            if buy_idx < len(sd) and sd[buy_idx] <= today_str:
                buy_opens[sig] = prices[sd[buy_idx]]['open']

        # 各卖出日的收盘价
        sell_closes = {}
        for soff in range(1, 16):
            sidx = ri + soff
            if sidx < len(sd) and sd[sidx] <= today_str:
                sell_closes[soff] = prices[sd[sidx]]['close']

        pool.append({
            'code': sc,
            'anchor': anchor,
            'factors': factors,
            'buy_opens': buy_opens,
            'sell_closes': sell_closes,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    limits = [50, 100, 150]

    # 卖出日列表
    sell_days = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

    for sname, sfn in strategies.items():
        print(f"\n{'=' * 130}")
        print(f"  {sname}")
        print(f"  买入: 信号日次日开盘 | 卖出: 目标日收盘")
        print(f"{'=' * 130}")

        for lim in limits:
            sample = pool[:lim]
            triggered = [v for v in sample if sfn(v['factors'])]
            n_all = len(triggered)

            if lim == limits[0]:
                print(f"\n  总触发: {n_all} 只")

            print(f"\n  limit={lim} (总触发 {n_all} 只)")
            print(f"  {'':>10}", end='')
            for soff in sell_days:
                print(f"  D+{soff:>2}收盘 ".format(soff=soff), end='')
            print()
            print("  " + "-" * 130)

            for boff in range(0, 6):
                print(f"  D+{boff}信号→".format(boff=boff), end='')
                for soff in sell_days:
                    hold = soff - boff - 1  # 持有天数
                    if hold <= 0:
                        print(f"  {'---':>8}", end='')
                        continue

                    valid = []
                    for v in triggered:
                        bp = v['buy_opens'].get(boff, 0)
                        sp = v['sell_closes'].get(soff, 0)
                        if bp > 0 and sp > 0:
                            valid.append(((sp - bp) / bp) * 100)

                    if len(valid) < 3:
                        print(f"  {'N/A':>8}", end='')
                        continue

                    n = len(valid)
                    avg = sum(valid) / n
                    win = sum(1 for x in valid if x > 0) / n * 100
                    std = (sum((x - avg) ** 2 for x in valid) / n) ** 0.5
                    sh = avg / std if std > 0 else 0

                    tag = ' ★' if sh >= 0.5 and boff == 0 else ''
                    print(f" {n:>2} {avg:+.1f}/{win:.0f}%/{sh:+.2f}{tag}", end='')
                print()

        # 汇总: 每个 limit 下最优窗口
        print(f"\n  最优窗口汇总")
        print(f"  {'策略':<45} {'limit':>5} {'最优窗口':>12} {'n':>5} {'平均':>7} {'胜率':>6} {'夏普':>6}")
        print("  " + "-" * 95)

        for lim in limits:
            sample = pool[:lim]
            triggered = [v for v in sample if sfn(v['factors'])]

            best = None
            for boff in range(0, 6):
                for soff in range(boff + 2, 13):
                    hold = soff - boff - 1
                    valid = []
                    for v in triggered:
                        bp = v['buy_opens'].get(boff, 0)
                        sp = v['sell_closes'].get(soff, 0)
                        if bp > 0 and sp > 0:
                            valid.append(((sp - bp) / bp) * 100)
                    if len(valid) < 3:
                        continue
                    n = len(valid)
                    avg = sum(valid) / n
                    win = sum(1 for x in valid if x > 0) / n * 100
                    std = (sum((x - avg) ** 2 for x in valid) / n) ** 0.5
                    sh = avg / std if std > 0 else 0
                    if best is None or sh > best[0]:
                        best = (sh, f"D+{boff}→D+{soff}(持{hold})", n, avg, win)

            if best:
                print(f"  {sname:<45} {lim:>5} {best[1]:>12} {best[2]:>4} {best[3]:>+6.1f}% {best[4]:>5.0f}% {best[0]:>+5.2f}")

    # 全策略最佳窗口对比
    print(f"\n\n{'=' * 110}")
    print("全策略最佳窗口对比（修正版）")
    print(f"{'=' * 110}")

    for lim in limits:
        sample = pool[:lim]
        print(f"\n  limit={lim}")
        print(f"  {'策略':<45} {'窗口':>12} {'n':>5} {'平均':>7} {'中位':>7} {'胜率':>6} {'标准差':>7} {'夏普':>6}")
        print("  " + "-" * 110)

        for sname, sfn in strategies.items():
            triggered = [v for v in sample if sfn(v['factors'])]

            best = None
            for boff in range(0, 6):
                for soff in range(boff + 2, 13):
                    hold = soff - boff - 1
                    valid = []
                    for v in triggered:
                        bp = v['buy_opens'].get(boff, 0)
                        sp = v['sell_closes'].get(soff, 0)
                        if bp > 0 and sp > 0:
                            valid.append(((sp - bp) / bp) * 100)
                    if len(valid) < 3:
                        continue
                    n = len(valid)
                    avg = sum(valid) / n
                    s = sorted(valid)
                    med = s[n // 2]
                    win = sum(1 for x in valid if x > 0) / n * 100
                    std = (sum((x - avg) ** 2 for x in valid) / n) ** 0.5
                    sh = avg / std if std > 0 else 0
                    if best is None or sh > best[0]:
                        best = (sh, f"D+{boff}→D+{soff}(持{hold})", n, avg, med, win, std)

            if best:
                print(f"  {sname:<45} {best[1]:>12} {best[2]:>4} {best[3]:>+6.1f}% {best[4]:>+6.1f}% {best[5]:>5.0f}% {best[6]:>+6.1f}% {best[0]:>+5.2f}")


if __name__ == '__main__':
    main()
