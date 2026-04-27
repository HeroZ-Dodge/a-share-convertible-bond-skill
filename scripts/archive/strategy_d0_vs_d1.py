#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D+0 vs D+1 买入对比 — 4个策略在 5 个样本量下的效果
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

        d1_price = prices[sd[ri + 1]]['close'] if ri + 1 < len(sd) else 0
        d9_price = prices[sd[ri + 9]]['close'] if ri + 9 < len(sd) and sd[ri + 9] <= today_str else 0

        if d9_price == 0:
            continue

        d1_chg = ((d1_price - reg_price) / reg_price * 100) if d1_price > 0 else 0

        # D+0 买入收益
        ret_d0 = ((d9_price - reg_price) / reg_price) * 100
        # D+1 买入收益
        ret_d1 = ((d9_price - d1_price) / d1_price * 100) if d1_price > 0 else 0

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
            'anchor': anchor, 'reg_price': reg_price, 'd1_price': d1_price,
            'd1_chg': d1_chg, 'ret_d0': ret_d0, 'ret_d1': ret_d1,
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)

    limits = [50, 100, 150, 200, 300]

    for sname, sfn in strategies.items():
        print(f"\n{'=' * 100}")
        print(f"  {sname}")
        print(f"{'=' * 100}")

        print(f"  {'limit':>6} {'触发':>5} "
              f"{'D+0买':>8} {'D+0胜率':>7} {'D+0夏普':>6} "
              f"{'D+1买':>8} {'D+1胜率':>7} {'D+1夏普':>6} "
              f"{'价差':>6} {'D+1差':>8}")
        print("  " + "-" * 95)

        for lim in limits:
            sample = pool[:lim]
            triggered = [v for v in sample if sfn(v)]
            n = len(triggered)
            if n < 5:
                print(f"  {lim:>5} {n:>5}  {'样本不足':>15}")
                continue

            # D+0 买入
            rets_d0 = [v['ret_d0'] for v in triggered]
            avg_d0 = sum(rets_d0) / len(rets_d0)
            win_d0 = sum(1 for x in rets_d0 if x > 0) / len(rets_d0) * 100
            std_d0 = (sum((x - avg_d0) ** 2 for x in rets_d0) / len(rets_d0)) ** 0.5
            sh_d0 = avg_d0 / std_d0 if std_d0 > 0 else 0

            # D+1 买入
            rets_d1 = [v['ret_d1'] for v in triggered]
            avg_d1 = sum(rets_d1) / len(rets_d1)
            win_d1 = sum(1 for x in rets_d1 if x > 0) / len(rets_d1) * 100
            std_d1 = (sum((x - avg_d1) ** 2 for x in rets_d1) / len(rets_d1)) ** 0.5
            sh_d1 = avg_d1 / std_d1 if std_d1 > 0 else 0

            # 平均价差 D+1 比 D+0 贵/便宜多少
            avg_gap = sum(v['d1_chg'] for v in triggered) / len(triggered)

            # D+1 比 D+0 差多少
            diff_avg = avg_d1 - avg_d0
            diff_win = win_d1 - win_d0
            diff_sh = sh_d1 - sh_d0

            tag = ''
            if sh_d1 >= sh_d0 * 0.95:
                tag = ' ≈持平'
            elif sh_d1 < sh_d0 * 0.8:
                tag = ' ↓下降'
            else:
                tag = ' ↓略降'

            print(f"  {lim:>5} {n:>5} "
                  f"{avg_d0:>+6.2f}% {win_d0:>5.1f}% {sh_d0:>+5.2f}  "
                  f"{avg_d1:>+6.2f}% {win_d1:>5.1f}% {sh_d1:>+5.2f}  "
                  f"{avg_gap:>+5.1f}% {diff_avg:>+6.2f}%{tag}")

        # 逐只明细（limit=100）
        print(f"\n  逐只明细 (limit=100):")
        print(f"  {'名称':>12} {'注册日':>12} {'D+1价':>8} {'D+0→D+9':>9} {'D+1→D+9':>9} {'价差':>6}")
        print("  " + "-" * 80)

        sample = pool[:100]
        triggered = [v for v in sample if sfn(v)]
        triggered.sort(key=lambda x: x['d1_chg'], reverse=True)

        for v in triggered:
            marker = '★' if v['ret_d0'] > 5 else ' '
            gap_tag = ''
            if v['d1_chg'] > 2:
                gap_tag = ' !贵'
            elif v['d1_chg'] < -1:
                gap_tag = ' !便宜'

            print(f"  {marker} {v['name']:>12} {v['anchor']:>12} "
                  f"{v['d1_price']:>7.2f} {v['ret_d0']:>+7.1f}% {v['ret_d1']:>+7.1f}% "
                  f"{v['d1_chg']:>+4.1f}%{gap_tag}")


if __name__ == '__main__':
    main()
