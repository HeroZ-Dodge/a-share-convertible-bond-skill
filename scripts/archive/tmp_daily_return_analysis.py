#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
精确分析：注册日前每一天的涨跌贡献
"""

import sys
import re
import importlib.util
from datetime import datetime

sys.path.insert(0, '.')
spec = importlib.util.spec_from_file_location('backtest_cache', 'lib/backtest_cache.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
cache = mod.BacktestCache()


def parse_progress_dates(pf: str) -> dict:
    if not pf:
        return {}
    pf = pf.replace('<br>', '\n')
    dates = {}
    for m in re.finditer(r'(\d{4}-\d{2}-\d{2})\s+([^\n]+)', pf):
        dates[m.group(2).strip()] = m.group(1)
    return dates


def find_idx(sorted_dates, target):
    for i, d in enumerate(sorted_dates):
        if d >= target:
            return i
    return len(sorted_dates) - 1


def main():
    bonds = cache.get_latest_jisilu_data()

    valid = []
    for b in bonds:
        if not b.get('stock_code'):
            continue
        dates = parse_progress_dates(b.get('progress_full', ''))
        if '同意注册' in dates:
            valid.append({
                'code': b['stock_code'],
                'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
                'reg_date': dates['同意注册'],
            })

    print("=" * 120)
    print("逐日涨跌明细 (D-15 到 D+5)")
    print("=" * 120)

    all_daily = {}  # offset -> [chg, ...]

    for v in valid:
        sc = v['code']
        prices = cache.get_kline_as_dict(sc, days=240)
        if not prices:
            continue

        sd = sorted(prices.keys())
        reg_idx = find_idx(sd, v['reg_date'])
        today = datetime.now().strftime('%Y-%m-%d')

        # Baseline vol
        bvol = []
        for i in range(reg_idx - 30, reg_idx - 19):
            if 0 <= i < len(sd):
                bvol.append(prices[sd[i]]['volume'])
        bavg = sum(bvol) / len(bvol) if bvol else 1

        name = v['name']
        print(f"\n  {name} ({sc})  注册:{v['reg_date']}")
        print(f"  {'偏移':>5} {'日期':>12} {'收盘':>8} {'涨跌%':>7} {'累计%':>7} {'量比':>6}")
        print("  " + "-" * 60)

        for offset in range(-15, 6):
            idx = reg_idx + offset
            if idx < 0 or idx >= len(sd):
                continue
            d = sd[idx]
            if d > today:
                continue

            p = prices[d]
            chg = 0
            if idx > 0:
                prev = prices[sd[idx - 1]]['close']
                if prev > 0:
                    chg = ((p['close'] - prev) / prev) * 100
            vr = p['volume'] / bavg if bavg > 0 else 1

            # Cumulative return from D-7
            d7_idx = reg_idx - 7
            if d7_idx >= 0 and d7_idx < len(sd):
                d7_price = prices[sd[d7_idx]]['close']
                cum = ((p['close'] - d7_price) / d7_price) * 100
            else:
                cum = 0

            marker = ""
            if offset == 0:
                marker = " ←注册日"
            elif offset == -7:
                marker = " ←D-7"
            elif offset == -5:
                marker = " ←D-5"
            elif offset == -3:
                marker = " ←D-3"

            print(f"  {offset:>5} {d:>12} {p['close']:>8.2f} {chg:>6.2f}% {cum:>6.2f}% {vr:>5.2f}{marker}")

            if offset not in all_daily:
                all_daily[offset] = []
            all_daily[offset].append(chg)

    # ============================================================
    # 汇总统计
    # ============================================================
    print()
    print("=" * 120)
    print("逐日统计汇总 (D-15 到 D+5)")
    print("=" * 120)

    print(f"\n  {'偏移':>6} {'平均涨跌':>9} {'涨%':>6} {'跌%':>6} {'最大涨':>8} {'最大跌':>8} {'样本数':>6} {'信号'}")
    print("  " + "-" * 70)

    # Sort offsets
    for offset in sorted(all_daily.keys()):
        chgs = all_daily[offset]
        avg_chg = sum(chgs) / len(chgs)
        up_pct = sum(1 for c in chgs if c > 0) / len(chgs) * 100
        down_pct = sum(1 for c in chgs if c < 0) / len(chgs) * 100
        max_up = max(chgs)
        max_down = min(chgs)
        n = len(chgs)

        sig = ""
        if avg_chg > 1.5:
            sig = "🔥大涨"
        elif avg_chg > 1:
            sig = "📈上涨"
        elif avg_chg < -1.5:
            sig = "🔴大跌"
        elif avg_chg < -1:
            sig = "📉下跌"

        print(f"  D{offset:>4} {avg_chg:>+8.2f}% {up_pct:>5.0f}% {down_pct:>5.0f}% "
              f"{max_up:>+7.2f}% {max_down:>+7.2f}% {n:>5}  {sig}")

    # ============================================================
    # 关键问题：从D-7到注册日的累计收益是怎么来的？
    # ============================================================
    print()
    print("=" * 120)
    print("从D-7到注册日的收益分解")
    print("=" * 120)

    print(f"\n  {'债券':>12} {'D-7价':>8} {'D-6':>7} {'D-5':>7} {'D-4':>7} {'D-3':>7} {'D-2':>7} {'D-1':>7} {'D+0':>7} "
          f"{'累计':>7} {'哪3天涨最多'}")
    print("  " + "-" * 100)

    for v in valid:
        sc = v['code']
        prices = cache.get_kline_as_dict(sc, days=240)
        if not prices:
            continue

        sd = sorted(prices.keys())
        reg_idx = find_idx(sd, v['reg_date'])
        d7_idx = reg_idx - 7
        today = datetime.now().strftime('%Y-%m-%d')

        if d7_idx < 0 or reg_idx >= len(sd):
            continue

        name = v['name']
        d7_price = prices[sd[d7_idx]]['close']

        daily_rets = []
        for offset in range(-6, 1):
            idx = reg_idx + offset
            if idx < 0 or idx >= len(sd) or sd[idx] > today:
                daily_rets.append(None)
                continue
            curr_price = prices[sd[idx]]['close']
            ret = ((curr_price - d7_price) / d7_price) * 100
            daily_rets.append(round(ret, 1))

        # Find 3 days with highest individual daily gains
        dailies = []
        for i, off in enumerate(range(-6, 1)):
            idx = reg_idx + off
            if idx < 0 or idx >= len(sd) or sd[idx] > today:
                continue
            chg = 0
            if idx > 0:
                prev = prices[sd[idx - 1]]['close']
                if prev > 0:
                    chg = ((prices[sd[idx]]['close'] - prev) / prev) * 100
            dailies.append((off, chg))

        # Sort by chg, get top 3
        dailies_sorted = sorted(dailies, key=lambda x: x[1], reverse=True)
        top3 = dailies_sorted[:3]
        top3_str = "+".join([f"D{t[0]}{t[1]:+.1f}" for t in top3])

        rets_str = " ".join([f"{r:>+6.1f}" if r is not None else f"{'N/A':>6}" for r in daily_rets])

        # Cumulative at D+0
        cum = daily_rets[-1] if daily_rets[-1] is not None else 0

        print(f"  {name:>12} {d7_price:>8.2f} {rets_str}% {cum:>+6.1f}%  {top3_str}")

    # ============================================================
    # 累计收益曲线
    # ============================================================
    print()
    print("=" * 120)
    print("平均累计收益曲线 (D-7=0基准)")
    print("=" * 120)

    print()
    for offset in range(-7, 6):
        vals = []
        for v in valid:
            sc = v['code']
            prices = cache.get_kline_as_dict(sc, days=240)
            if not prices:
                continue
            sd = sorted(prices.keys())
            reg_idx = find_idx(sd, v['reg_date'])
            d7_idx = reg_idx - 7
            today = datetime.now().strftime('%Y-%m-%d')

            if d7_idx < 0 or reg_idx + offset >= len(sd):
                continue
            if sd[reg_idx + offset] > today:
                continue

            d7_price = prices[sd[d7_idx]]['close']
            curr_price = prices[sd[reg_idx + offset]]['close']
            ret = ((curr_price - d7_price) / d7_price) * 100
            vals.append(ret)

        if vals:
            avg = sum(vals) / len(vals)
            win = sum(1 for v in vals if v > 0)
            bar_len = int(abs(avg) * 2)
            if avg > 0:
                bar = "▓" * bar_len
            else:
                bar = "░" * bar_len
            print(f"  D{offset:>2}: {avg:>+6.2f}%  胜率{win}/{len(vals)}  {bar}")

    # ============================================================
    # 关键发现：注册日前后收益对比
    # ============================================================
    print()
    print("=" * 120)
    print("注册日前 vs 注册日后")
    print("=" * 120)

    # D-7 to D+0 vs D+0 to D+10
    print()
    pre_vals = []
    post_vals = []
    for v in valid:
        sc = v['code']
        prices = cache.get_kline_as_dict(sc, days=240)
        if not prices:
            continue
        sd = sorted(prices.keys())
        reg_idx = find_idx(sd, v['reg_date'])
        d7_idx = reg_idx - 7
        today = datetime.now().strftime('%Y-%m-%d')

        if d7_idx < 0 or reg_idx >= len(sd) or sd[reg_idx] > today:
            continue

        d7_price = prices[sd[d7_idx]]['close']
        reg_price = prices[sd[reg_idx]]['close']

        # Pre: D-7 to D+0
        ret_pre = ((reg_price - d7_price) / d7_price) * 100

        # Post: D+0 to D+5
        post5_idx = reg_idx + 5
        if post5_idx < len(sd) and sd[post5_idx] <= today:
            post5_price = prices[sd[post5_idx]]['close']
            ret_post = ((post5_price - reg_price) / reg_price) * 100
            post_vals.append(ret_post)

        pre_vals.append(ret_pre)

    if pre_vals:
        pre_avg = sum(pre_vals) / len(pre_vals)
        pre_win = sum(1 for v in pre_vals if v > 0)
        print(f"  注册前 (D-7→D+0): 平均{pre_avg:+.2f}%, 胜率{pre_win}/{len(pre_vals)}")
        print(f"    最佳: {max(pre_vals):+.2f}%")
        print(f"    最差: {min(pre_vals):+.2f}%")

    if post_vals:
        post_avg = sum(post_vals) / len(post_vals)
        post_win = sum(1 for v in post_vals if v > 0)
        print(f"  注册后 (D+0→D+5): 平均{post_avg:+.2f}%, 胜率{post_win}/{len(post_vals)}")
        print(f"    最佳: {max(post_vals):+.2f}%")
        print(f"    最差: {min(post_vals):+.2f}%")

    # ============================================================
    # 每日涨跌贡献占比
    # ============================================================
    print()
    print("=" * 120)
    print("每日涨跌贡献 (占D-7→D+0总收益的比例)")
    print("=" * 120)

    print()
    for offset in range(-7, 1):
        chgs = all_daily.get(offset, [])
        if chgs:
            avg = sum(chgs) / len(chgs)
            abs_avg = abs(avg)
            print(f"  D{offset:>2}: {avg:>+7.2f}%", end="")
            bar = "█" * int(abs_avg * 4)
            if avg > 0:
                print(f"  {bar}", end="")
            else:
                print(f"  {bar}", end="")
            print()

    print()
    pre_total = sum(all_daily.get(o, [0])[0] if all_daily.get(o, [0]) else 0
                    for o in range(-7, 0))
    print(f"  D-7到D-0总累计: {pre_total:+.2f}%")


if __name__ == '__main__':
    main()
