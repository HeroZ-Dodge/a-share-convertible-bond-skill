#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回测验证：手动抽查每只股票的逐日数据，确认策略A的计算正确"""
import sys
import os
import re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.backtest_cache import BacktestCache


def parse_anchor_date(bond: dict) -> str:
    pf = bond.get('progress_full', '')
    if not pf:
        return ''
    pf = pf.replace('<br>', '\n')
    for line in pf.split('\n'):
        if '同意注册' in line:
            m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
            if m:
                return m.group(1)
    return ''


def find_reg_idx(sorted_dates, target):
    for i, d in enumerate(sorted_dates):
        if d >= target:
            return i
    return len(sorted_dates) - 1


def main():
    cache = BacktestCache()
    today = datetime.now().strftime('%Y-%m-%d')

    all_bonds = cache.get_jisilu_bonds(phase='注册', status_cd='OK', limit=0)

    valid = []
    for b in all_bonds:
        sc = b.get('stock_code')
        if not sc:
            continue
        reg_date = parse_anchor_date(b)
        if not reg_date or reg_date > today:
            continue

        prices = cache.get_kline_as_dict(sc, days=600)
        if not prices or len(prices) < 100:
            continue

        sd = sorted(prices.keys())
        reg_idx = find_reg_idx(sd, reg_date)
        if reg_idx is None or reg_idx < 0:
            continue

        post_days = len(sd) - 1 - reg_idx
        if post_days < 12:
            continue

        reg_price = prices[sd[reg_idx]]['close']
        if reg_price <= 0:
            continue

        # 计算注册后每日收益
        post_returns = {}
        for off in range(1, 31):
            idx = reg_idx + off
            if idx >= len(sd) or sd[idx] > today:
                continue
            p = prices[sd[idx]]['close']
            ret = ((p - reg_price) / reg_price) * 100
            post_returns[off] = round(ret, 2)

        # 注册前7天收益
        pre7_ret = 0
        pre7_idx = reg_idx - 7
        if pre7_idx >= 0:
            pre7_price = prices[sd[pre7_idx]]['close']
            if pre7_price > 0:
                pre7_ret = ((reg_price - pre7_price) / pre7_price) * 100

        # 注册日涨跌
        reg_day_chg = 0
        if reg_idx > 0:
            prev = prices[sd[reg_idx - 1]]['close']
            if prev > 0:
                reg_day_chg = ((reg_price - prev) / prev) * 100

        valid.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'reg_date': reg_date,
            'reg_price': reg_price,
            'reg_idx': reg_idx,
            'post_returns': post_returns,
            'pre7_ret': round(pre7_ret, 2),
            'reg_day_chg': round(reg_day_chg, 2),
            'prices': prices,
            'sorted_dates': sd,
        })

    print(f"有效样本: {len(valid)} 只\n")

    # ============================================================
    # 逐只输出D+0到D+9的明细（前30只）
    # ============================================================
    print("=" * 120)
    print("逐只明细：注册日价格 vs D+9价格")
    print("=" * 120)
    print(f"\n  {'名称':>12} {'代码':>8} {'注册日':>12} {'注册价':>8} {'D+0→D+9收益':>10} {'D+1涨':>6} {'pre7%':>8}")
    print("  " + "-" * 70)

    total_gain = 0
    win_count = 0
    n_valid = 0

    for v in valid[:30]:
        d9_ret = v['post_returns'].get(9)
        d1_ret = v['post_returns'].get(1, 0)
        if d9_ret is None:
            continue

        n_valid += 1
        total_gain += d9_ret
        if d9_ret > 0:
            win_count += 1

        exit_price = v['reg_price'] * (1 + d9_ret / 100)
        print(f"  {v['name']:>12} {v['code']:>8} {v['reg_date']:>12} "
              f"{v['reg_price']:>8.2f} {d9_ret:>+9.2f}% "
              f"{'Y' if d1_ret > 0 else 'N':>5} {v['pre7_ret']:>+6.2f}%")

    # ============================================================
    # 全部样本统计
    # ============================================================
    all_d9 = [v['post_returns'].get(9) for v in valid if v['post_returns'].get(9) is not None]
    print(f"\n{'=' * 80}")
    print("全部样本 D+0→D+9 统计")
    print(f"{'=' * 80}")

    if all_d9:
        s = sorted(all_d9)
        n = len(s)
        avg = sum(s) / n
        med = s[n // 2]
        win_n = sum(1 for x in s if x > 0)
        win_rate = win_n / n * 100
        print(f"\n  有效样本: {n} 只")
        print(f"  平均收益: {avg:+.2f}%")
        print(f"  中位数:   {med:+.2f}%")
        print(f"  胜率:     {win_rate:.1f}% ({win_n}/{n})")
        print(f"  最佳:     {max(s):+.2f}%")
        print(f"  最差:     {min(s):+.2f}%")

        # 收益分布
        bins = [(-999, -5, '亏损>5%'), (-5, 0, '亏损0~5%'), (0, 2, '盈利0~2%'),
                (2, 5, '盈利2~5%'), (5, 10, '盈利5~10%'), (10, 999, '盈利>10%')]
        print(f"\n  收益分布:")
        for lo, hi, label in bins:
            cnt = sum(1 for x in s if lo <= x < hi)
            pct = cnt / n * 100
            bar = '█' * int(pct)
            print(f"    {label:>12}: {cnt:>3} ({pct:5.1f}%) {bar}")

    # ============================================================
    # 筛选效果验证
    # ============================================================
    print(f"\n{'=' * 80}")
    print("筛选条件验证")
    print(f"{'=' * 80}")

    conditions = [
        ('无筛选', lambda v: True),
        ('D+1涨', lambda v: v['post_returns'].get(1, 0) > 0),
        ('pre7<=2%', lambda v: v['pre7_ret'] <= 2),
        ('D+1涨+pre7<=2%', lambda v: v['post_returns'].get(1, 0) > 0 and v['pre7_ret'] <= 2),
    ]

    for cname, cfunc in conditions:
        subset = [v for v in valid if cfunc(v) and v['post_returns'].get(9) is not None]
        if not subset:
            continue
        d9_vals = [v['post_returns'][9] for v in subset]
        s2 = sorted(d9_vals)
        n2 = len(s2)
        avg2 = sum(s2) / n2
        win_n2 = sum(1 for x in s2 if x > 0)
        win_rate2 = win_n2 / n2 * 100
        std = (sum((x - avg2) ** 2 for x in s2) / n2) ** 0.5
        sharpe = avg2 / std if std > 0 else 0
        print(f"  {cname:>20}: 平均{avg2:>+5.2f}%  胜率{win_rate2:>5.1f}%  样本{n2}  夏普{sharpe:>+5.2f}")

    # ============================================================
    # 逐日收益验证：D+1到D+15
    # ============================================================
    print(f"\n{'=' * 80}")
    print("逐日收益验证（所有样本，无需筛选）")
    print(f"{'=' * 80}")
    print(f"\n  {'偏移':>6} {'平均':>7} {'中位':>7} {'胜率':>6} {'样本':>5} {'最小':>7} {'最大':>7}")
    print("  " + "-" * 55)

    for off in range(1, 16):
        vals = [v['post_returns'].get(off) for v in valid if v['post_returns'].get(off) is not None]
        if not vals:
            continue
        s3 = sorted(vals)
        n3 = len(s3)
        avg3 = sum(s3) / n3
        med3 = s3[n3 // 2]
        win3 = sum(1 for x in s3 if x > 0) / n3 * 100
        print(f"  D+{off:>2d}: {avg3:>+6.2f}% {med3:>+6.2f}% {win3:>5.1f}% {n3:>4} "
              f"{min(s3):>+6.1f}% {max(s3):>+6.1f}%")

    # ============================================================
    # 抽查5只股票的逐日K线
    # ============================================================
    print(f"\n{'=' * 80}")
    print("逐日K线抽查（前5只）")
    print(f"{'=' * 80}")

    for v in valid[:5]:
        print(f"\n  {v['name']} ({v['code']})  注册日:{v['reg_date']}  锚定价:{v['reg_price']:.2f}")
        print(f"  {'偏移':>5} {'日期':>12} {'收盘价':>8} {'相对锚定%':>10} {'日涨跌%':>7}")
        print("  " + "-" * 50)
        for off in range(-3, 13):
            idx = v['reg_idx'] + off
            sd = v['sorted_dates']
            if idx < 0 or idx >= len(sd) or sd[idx] > today:
                continue
            p = v['prices'][sd[idx]]['close']
            ret = ((p - v['reg_price']) / v['reg_price']) * 100
            dchg = 0
            if idx > 0:
                prev_p = v['prices'][sd[idx - 1]]['close']
                if prev_p > 0:
                    dchg = ((p - prev_p) / prev_p) * 100
            marker = ' ←注册日' if off == 0 else (' ←D+9' if off == 9 else '')
            print(f"  D{off:>+3d} {sd[idx]:>12} {p:>8.2f} {ret:>+9.2f}% {dchg:>+6.2f}%{marker}")


if __name__ == '__main__':
    main()
