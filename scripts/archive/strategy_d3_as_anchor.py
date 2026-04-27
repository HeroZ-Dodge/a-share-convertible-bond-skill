#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D+3 作为锚点日 — 如果把 D+3 当成"注册日"来判断策略，效果如何
回答：策略是"注册日事件驱动"还是"弱势股通用筛选"
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


def calc_factors_at(prices, sd, ri):
    """以 ri 日为锚点，计算 pre3/pre7/rc/mom10"""
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

        # D+3 价格
        d3_idx = ri + 3
        if d3_idx >= len(sd) or sd[d3_idx] > today_str:
            continue
        d3_price = prices[sd[d3_idx]]['close']

        # D+9 价格
        d9_idx = ri + 9
        if d9_idx >= len(sd) or sd[d9_idx] > today_str:
            continue
        d9_price = prices[sd[d9_idx]]['close']

        # D+0 因子（注册日锚点）
        factors_d0 = calc_factors_at(prices, sd, ri)

        # D+3 因子（把 D+3 当锚点）
        factors_d3 = calc_factors_at(prices, sd, d3_idx)

        # D+0→D+3 涨跌
        d0_to_d3 = ((d3_price - reg_price) / reg_price) * 100 if reg_price > 0 else 0

        pool.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'reg_price': reg_price,
            'd3_price': d3_price,
            'd9_price': d9_price,
            'factors_d0': factors_d0,
            'factors_d3': factors_d3,
            'd0_to_d3': d0_to_d3,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    limits = [50, 100, 150, 200]

    print("=" * 110)
    print("D+3 作为锚点日回测")
    print("如果把 D+3 当成锚点来算因子、判断策略，D+3-D+9 的效果如何")
    print("对比：D+0 因子触发 vs D+3 因子触发")
    print("=" * 110)

    for sname, sfn in strategies.items():
        print(f"\n{'=' * 110}")
        print(f"  {sname}")
        print(f"{'=' * 110}")

        # 表头
        print(f"\n  {'':<10} {'limit':>5} {'D0触发':>7} {'D0→D9收益':>12} {'D0夏普':>7} "
              f"{'D3触发':>7} {'D3→D9收益':>12} {'D3夏普':>7} {'触发重合':>7}")
        print("  " + "-" * 105)

        for lim in limits:
            sample = pool[:lim]

            # D+0 因子触发
            triggered_d0 = [v for v in sample if sfn(v['factors_d0'])]
            n_d0 = len(triggered_d0)
            if n_d0 > 0:
                rets_d0 = [((v['d9_price'] - v['reg_price']) / v['reg_price']) * 100 for v in triggered_d0]
                avg_d0 = sum(rets_d0) / len(rets_d0)
                std_d0 = (sum((x - avg_d0) ** 2 for x in rets_d0) / len(rets_d0)) ** 0.5
                sh_d0 = avg_d0 / std_d0 if std_d0 > 0 else 0
            else:
                rets_d0 = []
                avg_d0 = 0
                sh_d0 = 0

            # D+3 因子触发
            triggered_d3 = [v for v in sample if sfn(v['factors_d3'])]
            n_d3 = len(triggered_d3)
            if n_d3 > 0:
                rets_d3 = [((v['d9_price'] - v['d3_price']) / v['d3_price']) * 100 for v in triggered_d3]
                avg_d3 = sum(rets_d3) / len(rets_d3)
                std_d3 = (sum((x - avg_d3) ** 2 for x in rets_d3) / len(rets_d3)) ** 0.5
                sh_d3 = avg_d3 / std_d3 if std_d3 > 0 else 0
            else:
                rets_d3 = []
                avg_d3 = 0
                sh_d3 = 0

            # 重合数：同时被 D+0 和 D+3 触发的
            d0_codes = set(v['code'] for v in triggered_d0)
            d3_codes = set(v['code'] for v in triggered_d3)
            overlap = len(d0_codes & d3_codes)
            overlap_str = f"{overlap}/{n_d3}" if n_d3 > 0 else "0/0"

            print(f"  {'D0作为锚点':>10} {lim:>5} {n_d0:>5}只 "
                  f"{avg_d0:>+6.2f}%/{sum(1 for x in rets_d0 if x > 0)/len(rets_d0)*100:.0f}% "
                  f"{sh_d0:>+5.2f}      "
                  f"{'D3作为锚点':>10} {n_d3:>5}只 "
                  f"{avg_d3:>+6.2f}%/{sum(1 for x in rets_d3 if x > 0)/len(rets_d3)*100:.0f}% "
                  f"{sh_d3:>+5.2f}      {overlap_str}")

        # 逐只对比（limit=100）
        print(f"\n  逐只明细 (limit=100):")
        print(f"  {'名称':>12} {'注册日':>12} {'D0价':>7} {'D3价':>7} {'D9价':>7} "
              f"{'D0→D3':>6} {'D0因子':>6} {'D3因子':>6} {'D0触发':>6} {'D3触发':>6} "
              f"{'D0→D9':>7} {'D3→D9':>7}")
        print("  " + "-" * 110)

        sample = pool[:100]
        rows = []
        for v in sample:
            t0 = sfn(v['factors_d0'])
            t3 = sfn(v['factors_d3'])
            if not t0 and not t3:
                continue
            ret_d09 = ((v['d9_price'] - v['reg_price']) / v['reg_price']) * 100
            ret_d39 = ((v['d9_price'] - v['d3_price']) / v['d3_price']) * 100
            rows.append((v, t0, t3, ret_d09, ret_d39))

        rows.sort(key=lambda x: x[4], reverse=True)
        for v, t0, t3, ret_d09, ret_d39 in rows:
            marker = '★' if ret_d09 > 5 else ' '
            d0_tag = 'D0' if t0 else '  '
            d3_tag = 'D3' if t3 else '  '
            both_tag = ''
            if t0 and t3: both_tag = 'Both'
            elif t0 and not t3: both_tag = 'D0only'
            elif not t0 and t3: both_tag = 'D3only'
            else: both_tag = '---'

            print(f"  {marker} {v['name']:>12} {v['anchor']:>12} "
                  f"{v['reg_price']:>7.2f} {v['d3_price']:>7.2f} {v['d9_price']:>7.2f} "
                  f"{v['d0_to_d3']:>+5.1f}% "
                  f"p3={v['factors_d0']['pre3']:+.0f} "
                  f"p3={v['factors_d3']['pre3']:+.0f} "
                  f"{d0_tag:>4} {d3_tag:>4} "
                  f"{ret_d09:>+6.1f}% {ret_d39:>+6.1f}%  {both_tag}")

    # 汇总分析
    print(f"\n\n{'=' * 110}")
    print("汇总：D+0 锚点 vs D+3 锚点")
    print(f"{'=' * 110}")

    print(f"\n  {'策略':<42} {'D0夏普':>7} {'D3夏普':>7} {'D0收益':>8} {'D3收益':>8} "
          f"{'D0触发率':>7} {'D3触发率':>7} {'重合度':>7}  判断")
    print("  " + "-" * 105)

    sample = pool[:100]
    for sname, sfn in strategies.items():
        triggered_d0 = [v for v in sample if sfn(v['factors_d0'])]
        triggered_d3 = [v for v in sample if sfn(v['factors_d3'])]
        n_d0 = len(triggered_d0)
        n_d3 = len(triggered_d3)

        if n_d0 > 0:
            rets_d0 = [((v['d9_price'] - v['reg_price']) / v['reg_price']) * 100 for v in triggered_d0]
            avg_d0 = sum(rets_d0) / len(rets_d0)
            std_d0 = (sum((x - avg_d0) ** 2 for x in rets_d0) / len(rets_d0)) ** 0.5
            sh_d0 = avg_d0 / std_d0 if std_d0 > 0 else 0
        else:
            avg_d0 = 0; sh_d0 = 0

        if n_d3 > 0:
            rets_d3 = [((v['d9_price'] - v['d3_price']) / v['d3_price']) * 100 for v in triggered_d3]
            avg_d3 = sum(rets_d3) / len(rets_d3)
            std_d3 = (sum((x - avg_d3) ** 2 for x in rets_d3) / len(rets_d3)) ** 0.5
            sh_d3 = avg_d3 / std_d3 if std_d3 > 0 else 0
        else:
            avg_d3 = 0; sh_d3 = 0

        trigger_rate_d0 = n_d0 / len(sample) * 100 if sample else 0
        trigger_rate_d3 = n_d3 / len(sample) * 100 if sample else 0

        d0_codes = set(v['code'] for v in triggered_d0)
        d3_codes = set(v['code'] for v in triggered_d3)
        overlap = len(d0_codes & d3_codes)
        overlap_ratio = overlap / n_d3 * 100 if n_d3 > 0 else 0

        # 判断
        if sh_d3 >= sh_d0 * 0.9:
            verdict = "D3也能用(非事件驱动)"
        elif sh_d3 >= sh_d0 * 0.5:
            verdict = "D3部分有效(混合)"
        else:
            verdict = "D3失效(事件驱动)"

        print(f"  {sname:<42} "
              f"{sh_d0:>+5.2f} {sh_d3:>+5.2f} "
              f"{avg_d0:>+5.1f}% {avg_d3:>+5.1f}% "
              f"{trigger_rate_d0:>5.0f}% {trigger_rate_d3:>5.0f}% "
              f"{overlap_ratio:>5.0f}%  {verdict}")


if __name__ == '__main__':
    main()
