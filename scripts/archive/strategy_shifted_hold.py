#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持有9天平移扫描 — D+0→D+9, D+1→D+10, D+2→D+11, D+3→D+12
回答：持有天数一样，只是整体平移，收益是不是差不多？
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

        # D+0 ~ D+5 买入价, D+9 ~ D+14 卖出价 (各偏移)
        buys = {}
        sells = {}
        for boff in range(0, 6):
            idx = ri + boff
            if idx < len(sd) and sd[idx] <= today_str:
                buys[boff] = prices[sd[idx]]['close']
        for soff in range(9, 16):
            idx = ri + soff
            if idx < len(sd) and sd[idx] <= today_str:
                sells[soff] = prices[sd[idx]]['close']

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
            'anchor': anchor, 'buys': buys, 'sells': sells,
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)

    limits = [100, 150, 200, 300]

    # 平移窗口: 买D+boff → 卖D+(boff+9)
    windows = [(0, 9), (1, 10), (2, 11), (3, 12)]

    for lim in limits:
        sample = pool[:lim]
        print(f"\n{'=' * 110}")
        print(f"  limit={lim}  —  持有9天平移扫描")
        print(f"{'=' * 110}")

        for sname, sfn in strategies.items():
            triggered = [v for v in sample if sfn(v)]
            n_all = len(triggered)
            if n_all < 5:
                continue

            print(f"\n  {sname} (总触发 {n_all} 只)")
            print(f"  {'窗口':>12} {'n':>5} {'平均':>7} {'中位':>7} {'胜率':>6} {'夏普':>6}")
            print("  " + "-" * 50)

            for boff, soff in windows:
                valid = []
                for v in triggered:
                    bp = v['buys'].get(boff, 0)
                    sp = v['sells'].get(soff, 0)
                    if bp > 0 and sp > 0:
                        ret = ((sp - bp) / bp) * 100
                        valid.append(ret)

                if len(valid) < 3:
                    print(f"  {'D+{boff}→D+{soff}':>12} {'N/A':>5}")
                    continue

                n = len(valid)
                avg = sum(valid) / n
                s = sorted(valid)
                med = s[n // 2]
                win = sum(1 for x in valid if x > 0) / n * 100
                std = (sum((x - avg) ** 2 for x in valid) / n) ** 0.5
                sh = avg / std if std > 0 else 0

                # 相对 D+0→D+9 的差异
                if boff == 0:
                    diff = ""
                else:
                    d0_valid = []
                    for v in triggered:
                        bp = v['buys'].get(0, 0)
                        sp = v['sells'].get(9, 0)
                        if bp > 0 and sp > 0:
                            d0_valid.append(((sp - bp) / bp) * 100)
                    d0_avg = sum(d0_valid) / len(d0_valid) if d0_valid else 0
                    diff = f" ({avg - d0_avg:+.1f})"

                print(f"  {'D+{}→D+{}'.format(boff, soff):>12} {n:>5} {avg:>+6.2f}% {med:>+6.2f}% {win:>5.1f}% {sh:>+5.2f}{diff}")

    # 额外：基准（无筛选）也跑一下，看平移本身的影响
    print(f"\n\n{'=' * 110}")
    print(f"  基准(无筛选) — 验证平移本身是否影响收益")
    print(f"{'=' * 110}")

    for lim in limits:
        sample = pool[:lim]
        print(f"\n  limit={lim} (全部 {len(sample)} 只)")
        print(f"  {'窗口':>12} {'n':>5} {'平均':>7} {'胜率':>6} {'夏普':>6}")
        print("  " + "-" * 40)

        for boff, soff in windows:
            valid = []
            for v in sample:
                bp = v['buys'].get(boff, 0)
                sp = v['sells'].get(soff, 0)
                if bp > 0 and sp > 0:
                    valid.append(((sp - bp) / bp) * 100)
            if len(valid) < 3:
                continue
            n = len(valid)
            avg = sum(valid) / n
            win = sum(1 for x in valid if x > 0) / n * 100
            std = (sum((x - avg) ** 2 for x in valid) / n) ** 0.5
            sh = avg / std if std > 0 else 0

            if boff == 0:
                diff = ""
            else:
                d0_valid = []
                for v in sample:
                    bp = v['buys'].get(0, 0)
                    sp = v['sells'].get(9, 0)
                    if bp > 0 and sp > 0:
                        d0_valid.append(((sp - bp) / bp) * 100)
                d0_avg = sum(d0_valid) / len(d0_valid) if d0_valid else 0
                diff = f" ({avg - d0_avg:+.1f})"

            print(f"  {'D+{}→D+{}'.format(boff, soff):>12} {n:>5} {avg:>+6.2f}% {win:>5.1f}% {sh:>+5.2f}{diff}")


if __name__ == '__main__':
    main()
