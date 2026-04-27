#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D+0 ~ D+3 买入对比 — 5 个样本量，带有效样本数
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

    buy_offsets = [0, 1, 2, 3]

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

        # D+9 卖出价
        d9_price = prices[sd[ri + 9]]['close'] if ri + 9 < len(sd) and sd[ri + 9] <= today_str else 0
        if d9_price == 0:
            continue

        # 各买入日价格
        buy_prices = {}
        for off in buy_offsets:
            idx = ri + off
            if idx < len(sd) and sd[idx] <= today_str:
                buy_prices[off] = prices[sd[idx]]['close']
            else:
                buy_prices[off] = 0

        # D+0 ~ D+3 买入相对 D+0 的价差
        d0_price = buy_prices.get(0, reg_price)
        gaps = {}
        for off in buy_offsets:
            bp = buy_prices.get(off, 0)
            if bp > 0 and d0_price > 0:
                gaps[off] = ((bp - d0_price) / d0_price) * 100
            else:
                gaps[off] = 0

        # 收益
        rets = {}
        for off in buy_offsets:
            bp = buy_prices.get(off, 0)
            if bp > 0:
                rets[off] = ((d9_price - bp) / bp) * 100
            else:
                rets[off] = None

        # 因子
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

        pool.append({
            'code': sc, 'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor, 'reg_price': reg_price,
            'buy_prices': buy_prices, 'gaps': gaps, 'rets': rets,
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)

    limits = [50, 100, 150, 200, 300]

    for sname, sfn in strategies.items():
        print(f"\n{'=' * 110}")
        print(f"  {sname}")
        print(f"{'=' * 110}")

        print(f"  {'limit':>6} {'总触发':>6}")

        for off in buy_offsets:
            label = f"D+{off}买"
            if off == 0: label = "D+0买"
            print(f"    {label:>8} {'n':>5} {'平均':>7} {'中位':>7} {'胜率':>6} {'夏普':>6} {'价差':>6}", end='')
        print()
        print("  " + "-" * 110)

        for lim in limits:
            sample = pool[:lim]
            triggered = [v for v in sample if sfn(v)]
            n_all = len(triggered)
            if n_all < 5:
                print(f"  {lim:>5} {n_all:>6}  {'样本不足':>15}")
                continue

            print(f"  {lim:>5} {n_all:>6}")

            for off in buy_offsets:
                # 过滤掉该偏移下无数据的
                valid = [v for v in triggered if v['rets'].get(off) is not None]
                n = len(valid)
                if n < 3:
                    print(f"    {'D+'+str(off):>6} {'n/a':>5}", end='')
                    continue

                rets = [v['rets'][off] for v in valid]
                avg = sum(rets) / len(rets)
                s = sorted(rets)
                med = s[len(s) // 2]
                win = sum(1 for x in rets if x > 0) / len(rets) * 100
                std = (sum((x - avg) ** 2 for x in rets) / len(rets)) ** 0.5
                sh = avg / std if std > 0 else 0
                gap = valid[0]['gaps'].get(off, 0) if valid else 0

                # 相对 D+0 的收益差
                if off == 0:
                    diff_tag = ''
                else:
                    d0_rets = [v['rets'].get(0) for v in valid if v['rets'].get(0) is not None]
                    d0_avg = sum(d0_rets) / len(d0_rets) if d0_rets else 0
                    d = avg - d0_avg
                    diff_tag = f" ({d:+.1f})"

                print(f"    {'D+'+str(off):>6} {n:>5} {avg:>+6.2f}% {med:>+6.2f}% {win:>5.1f}% {sh:>+5.2f} {gap:>+5.1f}%{diff_tag}", end='')
            print()

        # limit=100 逐只
        print(f"\n  逐只明细 (limit=100):")
        print(f"  {'名称':>12} {'注册日':>12} "
              f"{'D+0价':>7} {'D+1价':>7} {'D+2价':>7} {'D+3价':>7} "
              f"{'D+0→9':>7} {'D+1→9':>7} {'D+2→9':>7} {'D+3→9':>7} "
              f"{'价差D+3':>7}")
        print("  " + "-" * 120)

        sample = pool[:100]
        triggered = [v for v in sample if sfn(v)]
        triggered.sort(key=lambda x: x['gaps'].get(3, 0), reverse=True)

        for v in triggered:
            bp = v['buy_prices']
            rt = v['rets']
            gap3 = v['gaps'].get(3, 0)
            marker = '★' if rt.get(0, 0) > 5 else ' '

            def fmt_price(off):
                p = bp.get(off, 0)
                return f"{p:>7.2f}" if p > 0 else f"{'  N/A':>7}"

            def fmt_ret(off):
                r = rt.get(off)
                return f"{r:>+6.1f}%" if r is not None else f"{'  N/A':>7}"

            print(f"  {marker} {v['name']:>12} {v['anchor']:>12} "
                  f"{fmt_price(0)} {fmt_price(1)} {fmt_price(2)} {fmt_price(3)} "
                  f"{fmt_ret(0)} {fmt_ret(1)} {fmt_ret(2)} {fmt_ret(3)} "
                  f"{gap3:>+6.1f}%")


if __name__ == '__main__':
    main()
