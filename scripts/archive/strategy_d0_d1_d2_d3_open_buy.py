#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册日策略回测 — 修正版：用次日开盘价作为买入价
注册公告通常盘后公布，D+0 当天无法买入
买入价 = 信号日后1天的开盘价
卖出价 = 目标日的开盘价或收盘价（可选）
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

        # 注册日因子（D+0 收盘价计算的因子）
        factors = calc_factors(prices, sd, ri)

        # === 修正版买入/卖出价格 ===
        # D+N 信号 = 注册日后等 N 天，第 N+1 天开盘买入
        # 注册日盘后公告 → D+1 开盘是最近买入点
        # D+0 信号（看到公告立刻买）= D+1 开盘价
        # D+1 信号（等1天再买）= D+2 开盘价
        # D+3 信号 = D+4 开盘价

        buy_prices = {}  # {signal_day: open_price}
        sell_prices = {} # {sell_day: {open, close}}

        # 信号日 0~5，对应次日开盘买入
        for sig_day in range(0, 6):
            buy_idx = ri + sig_day + 1  # 信号日次日开盘
            if buy_idx < len(sd) and sd[buy_idx] <= today_str:
                buy_prices[sig_day] = prices[sd[buy_idx]]['open']

        # 卖出日：目标日的开盘价和收盘价
        for sell_off in range(1, 16):
            sidx = ri + sell_off
            if sidx < len(sd) and sd[sidx] <= today_str:
                sell_prices[sell_off] = {
                    'open': prices[sd[sidx]]['open'],
                    'close': prices[sd[sidx]]['close'],
                }

        pool.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'reg_price': reg_price,
            'factors': factors,
            'buy_prices': buy_prices,
            'sell_prices': sell_prices,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    limits = [50, 100, 150, 200]

    print("=" * 120)
    print("注册日策略回测（修正版：次日开盘价买入）")
    print("注册公告盘后公布 → 最早次日开盘才能买入")
    print("买入价 = 信号日后1天的开盘价 | 卖出价 = 目标日收盘价")
    print("=" * 120)

    # ========== 第一部分：各策略，不同信号日 → 固定 D+9 卖出 ==========
    for sname, sfn in strategies.items():
        print(f"\n{'=' * 120}")
        print(f"  {sname}")
        print(f"  买入：信号日次日开盘 | 卖出：D+9 收盘")
        print(f"{'=' * 120}")

        print(f"\n  {'limit':>5} {'总样本':>6}", end='')
        for sig in range(0, 5):
            print(f" {'D+{sig}买':>14}".format(sig=sig), end='')
        print()
        print("  " + "-" * 120)

        for lim in limits:
            sample = pool[:lim]
            triggered = [v for v in sample if sfn(v['factors'])]
            n_all = len(triggered)

            print(f"  {lim:>5} {n_all:>6}", end='')

            for sig in range(0, 5):
                valid = []
                for v in triggered:
                    bp = v['buy_prices'].get(sig, 0)
                    sp_data = v['sell_prices'].get(9)
                    if bp > 0 and sp_data:
                        sp = sp_data['close']
                        if sp > 0:
                            ret = ((sp - bp) / bp) * 100
                            valid.append(ret)

                if len(valid) < 3:
                    print(f" {'N/A':>14}", end='')
                    continue

                n = len(valid)
                avg = sum(valid) / n
                s = sorted(valid)
                med = s[n // 2]
                win = sum(1 for x in valid if x > 0) / n * 100
                std = (sum((x - avg) ** 2 for x in valid) / n) ** 0.5
                sh = avg / std if std > 0 else 0

                print(f" {n:>3}只 {avg:>+4.1f}%/{win:.0f}%/{sh:+.2f} ", end='')
            print()

    # ========== 第二部分：策略1 窗口完整扫描 ==========
    print(f"\n\n{'=' * 120}")
    print("策略1 窗口扫描（修正版）")
    print("买：信号日次日开盘 | 卖：目标日收盘")
    print(f"{'=' * 120}")

    sample = pool[:100]
    triggered = [v for v in sample if strategies['策略1: pre3≤2%+mom10<5%+rc>0%'](v['factors'])]
    n_all = len(triggered)

    print(f"\n  总触发 {n_all} 只")
    print(f"\n  {'卖出日 →':>10}", end='')
    for soff in range(2, 13):
        print(f"  D+{soff:>2}收盘 ", end='')
    print()
    print("  " + "-" * 120)

    for boff in range(0, 6):
        print(f"  {'买入信号日 D+{bd}':>10}".format(bd=boff), end='')
        for soff in range(boff + 2, 13):
            valid = []
            hold = soff - boff - 1  # 实际持有天数
            for v in triggered:
                bp = v['buy_prices'].get(boff, 0)
                sp_data = v['sell_prices'].get(soff)
                if bp > 0 and sp_data:
                    sp = sp_data['close']
                    if sp > 0:
                        ret = ((sp - bp) / bp) * 100
                        valid.append(ret)

            if len(valid) < 3:
                print(f"  {'---':>7}", end='')
                continue

            n = len(valid)
            avg = sum(valid) / n
            win = sum(1 for x in valid if x > 0) / n * 100
            std = (sum((x - avg) ** 2 for x in valid) / n) ** 0.5
            sh = avg / std if std > 0 else 0

            print(f"  {n:>2} {avg:+.1f}%/{sh:+.2f}", end='')
        print()

    # ========== 第三部分：用开盘价卖出对比 ==========
    print(f"\n\n{'=' * 120}")
    print("卖出时机对比：收盘卖出 vs 开盘卖出")
    print(f"{'=' * 120}")

    sample = pool[:100]
    print(f"\n  策略1 (limit=100, 触发{n_all}只)")
    print(f"  {'卖出方式':>15} {'D+2':>12} {'D+3':>12} {'D+5':>12} {'D+7':>12} {'D+9':>12} {'D+12':>12}")
    print("  " + "-" * 90)

    for sname, sfn in strategies.items():
        triggered = [v for v in sample if sfn(v['factors'])]
        n_all = len(triggered)

        print(f"  {'收盘卖出':>15}", end='')
        for soff in [2, 3, 5, 7, 9, 12]:
            valid = []
            for v in triggered:
                bp = v['buy_prices'].get(0, 0)
                sp_data = v['sell_prices'].get(soff)
                if bp > 0 and sp_data:
                    sp = sp_data['close']
                    if sp > 0:
                        valid.append(((sp - bp) / bp) * 100)
            if len(valid) < 3:
                print(f"  {'---':>12}", end='')
                continue
            avg = sum(valid) / len(valid)
            win = sum(1 for x in valid if x > 0) / len(valid) * 100
            print(f" {avg:+.1f}%/{win:.0f}%", end='')
        print()

        print(f"  {'开盘卖出':>15}", end='')
        for soff in [2, 3, 5, 7, 9, 12]:
            valid = []
            for v in triggered:
                bp = v['buy_prices'].get(0, 0)
                sp_data = v['sell_prices'].get(soff)
                if bp > 0 and sp_data:
                    sp = sp_data['open']
                    if sp > 0:
                        valid.append(((sp - bp) / bp) * 100)
            if len(valid) < 3:
                print(f"  {'---':>12}", end='')
                continue
            avg = sum(valid) / len(valid)
            win = sum(1 for x in valid if x > 0) / len(valid) * 100
            print(f" {avg:+.1f}%/{win:.0f}%", end='')
        print()

    # ========== 第四部分：D+3 作为锚点（修正版） ==========
    print(f"\n\n{'=' * 120}")
    print("D+3 锚点修正版：用 D+3 因子 + D+4 开盘买入")
    print(f"{'=' * 120}")

    pool_d3 = []
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

        d3_idx = ri + 3
        if d3_idx >= len(sd) or sd[d3_idx] > today_str:
            continue

        factors_d0 = calc_factors(prices, sd, ri)
        factors_d3 = calc_factors(prices, sd, d3_idx)

        d0_to_d3 = ((prices[sd[d3_idx]]['close'] - reg_price) / reg_price) * 100

        # D+3 信号 → D+4 开盘买入
        buy_d4 = None
        buy_idx = ri + 4
        if buy_idx < len(sd) and sd[buy_idx] <= today_str:
            buy_d4 = prices[sd[buy_idx]]['open']

        # D+9 收盘卖出
        sell_d9 = None
        sell_idx = ri + 9
        if sell_idx < len(sd) and sd[sell_idx] <= today_str:
            sell_d9 = prices[sd[sell_idx]]['close']

        pool_d3.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'reg_price': reg_price,
            'd3_price': prices[sd[d3_idx]]['close'],
            'factors_d0': factors_d0,
            'factors_d3': factors_d3,
            'd0_to_d3': d0_to_d3,
            'buy_d4': buy_d4,
            'sell_d9': sell_d9,
        })

    pool_d3.sort(key=lambda x: x['anchor'], reverse=True)

    print(f"\n  {'':<10} {'limit':>5} {'D0触发':>6} {'D0→D9':>12} {'D0夏普':>6} "
          f"{'D3触发':>6} {'D3→D9':>12} {'D3夏普':>6} {'重合':>6}  判断")
    print("  " + "-" * 95)

    for sname, sfn in strategies.items():
        for lim in limits:
            sample = pool_d3[:lim]

            triggered_d0 = [v for v in sample if sfn(v['factors_d0']) and v['buy_d4'] and v['sell_d9']]
            triggered_d3 = [v for v in sample if sfn(v['factors_d3']) and v['buy_d4'] and v['sell_d9']]
            n_d0 = len(triggered_d0)
            n_d3 = len(triggered_d3)

            if n_d0 < 3 and n_d3 < 3:
                continue

            if n_d0 >= 3:
                rets_d0 = [((v['sell_d9'] - v['buy_d4']) / v['buy_d4']) * 100 for v in triggered_d0]
                avg_d0 = sum(rets_d0) / len(rets_d0)
                std_d0 = (sum((x - avg_d0) ** 2 for x in rets_d0) / len(rets_d0)) ** 0.5
                sh_d0 = avg_d0 / std_d0 if std_d0 > 0 else 0
            else:
                avg_d0 = 0; sh_d0 = 0

            if n_d3 >= 3:
                rets_d3 = [((v['sell_d9'] - v['buy_d4']) / v['buy_d4']) * 100 for v in triggered_d3]
                avg_d3 = sum(rets_d3) / len(rets_d3)
                std_d3 = (sum((x - avg_d3) ** 2 for x in rets_d3) / len(rets_d3)) ** 0.5
                sh_d3 = avg_d3 / std_d3 if std_d3 > 0 else 0
            else:
                avg_d3 = 0; sh_d3 = 0

            d0_codes = set(v['code'] for v in triggered_d0)
            d3_codes = set(v['code'] for v in triggered_d3)
            overlap = len(d0_codes & d3_codes)

            if sh_d3 >= sh_d0 * 0.9:
                verdict = "D3可用"
            elif sh_d3 >= sh_d0 * 0.5:
                verdict = "D3部分可用"
            else:
                verdict = "D3失效(事件驱动)"

            print(f"  {sname:<10} {lim:>5} {n_d0:>4} {avg_d0:>+5.1f}%/{sum(1 for x in rets_d0 if x > 0)/len(rets_d0)*100:.0f}% "
                  f"{sh_d0:>+5.2f}  {n_d3:>4} {avg_d3:>+5.1f}%/{sum(1 for x in rets_d3 if x > 0)/len(rets_d3)*100:.0f}% "
                  f"{sh_d3:>+5.2f}  {overlap}/{n_d3}  {verdict}")
        print()


if __name__ == '__main__':
    main()
