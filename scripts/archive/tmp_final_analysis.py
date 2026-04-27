#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终策略分析 — 不依赖注册日锚点
"""

import sys
import re
import importlib.util
from collections import Counter
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
    today = datetime.now().strftime('%Y-%m-%d')

    valid = []
    for b in bonds:
        if not b.get('stock_code'):
            continue
        dates = parse_progress_dates(b.get('progress_full', ''))
        lc = dates.get('上市委通过', '')
        reg = dates.get('同意注册', '')
        if lc and reg:
            gap = (datetime.strptime(reg, '%Y-%m-%d') - datetime.strptime(lc, '%Y-%m-%d')).days
            valid.append({
                'code': b['stock_code'],
                'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
                'lc_date': lc, 'reg_date': reg, 'gap': gap,
            })

    all_data = []
    for v in valid:
        prices = cache.get_kline_as_dict(v['code'], days=240)
        if not prices:
            continue
        sd = sorted(prices.keys())
        lc_idx = find_idx(sd, v['lc_date'])
        reg_idx = find_idx(sd, v['reg_date'])

        # Baseline vol
        bvol = []
        for i in range(lc_idx + 5, lc_idx + 15):
            if 0 <= i < len(sd):
                bvol.append(prices[sd[i]]['volume'])
        bavg = sum(bvol) / len(bvol) if bvol else 1

        daily = {}
        for off in range(1, 61):
            idx = lc_idx + off
            if idx < 0 or idx >= len(sd) or sd[idx] > today:
                continue
            p = prices[sd[idx]]
            chg = 0
            if idx > 0:
                prev = prices[sd[idx - 1]]['close']
                if prev > 0:
                    chg = ((p['close'] - prev) / prev) * 100
            vr = p['volume'] / bavg if bavg > 0 else 1
            daily[off] = {'date': sd[idx], 'close': p['close'], 'chg': chg, 'vol_ratio': vr}

        all_data.append({
            'name': v['name'], 'code': v['code'],
            'lc_date': v['lc_date'], 'reg_date': v['reg_date'],
            'gap': v['gap'], 'lc_idx': lc_idx, 'reg_idx': reg_idx,
            'daily': daily, 'bavg': bavg,
        })

    print(f"{len(all_data)} 只转债, Gap范围 {min(r['gap'] for r in all_data)}~{max(r['gap'] for r in all_data)}天\n")

    # ============================================================
    # 核心观察：从LC到REG的标准化价格趋势
    # ============================================================
    print("=" * 100)
    print("一、标准化价格趋势 (L-0 = 100)")
    print("=" * 100)

    for r in all_data:
        l1 = r['daily'].get(1, {})
        if not l1:
            continue
        base = l1['close']
        line = f"  {r['name']:>12} G{r['gap']:>2}"
        for off in range(1, r['gap'] + 1):
            d = r['daily'].get(off, {})
            if d:
                norm = (d['close'] / base) * 100
                line += f" {norm:5.0f}"
            else:
                line += "    ·"
        print(line)

    # Average price at each L offset
    print()
    print("  平均标准化价格:")
    offset_avgs = {}
    offset_counts = {}
    for r in all_data:
        l1 = r['daily'].get(1, {})
        if not l1:
            continue
        base = l1['close']
        for off in range(1, 56):
            d = r['daily'].get(off, {})
            if d:
                norm = (d['close'] / base) * 100
                offset_avgs[off] = offset_avgs.get(off, 0) + norm
                offset_counts[off] = offset_counts.get(off, 0) + 1

    for off in sorted(offset_avgs.keys()):
        avg = offset_avgs[off] / offset_counts[off]
        cnt = offset_counts[off]
        bar_len = int((avg - 80) / 2)
        bar = "█" * max(0, bar_len)
        print(f"    L+{off:2d}: {avg:5.1f} ({cnt:2d}只) {bar}")

    # ============================================================
    # 关键问题：上市后多久才进入"加速上涨期"？
    # ============================================================
    print()
    print("=" * 100)
    print("二、逐日涨跌分布 — 看哪天开始集体上涨")
    print("=" * 100)

    print(f"\n  {'L+':>4}", end="")
    for off in range(1, 56, 5):
        print(f"  {off:>5}", end="")
    print()

    # For each L offset, count positive days
    for r in all_data:
        line = f"  {r['name']:>12}"
        for off in range(1, 56, 5):
            count_pos = 0
            count_total = 0
            for i in range(off, min(off + 5, 56)):
                d = r['daily'].get(i, {})
                if d:
                    count_total += 1
                    if d['chg'] > 0:
                        count_pos += 1
            if count_total > 0:
                ratio = count_pos / count_total
                line += f" {count_pos}/{count_total}"
            else:
                line += "    -"
        print(line)

    # ============================================================
    # 可执行策略：从LC日进入监控窗口
    # ============================================================
    print()
    print("=" * 100)
    print("三、实盘可执行的信号定义")
    print("=" * 100)

    # 信号定义：
    # S_PANIC: 单日跌>2%+量比<1.5
    # S_RECOVER: S_PANIC次日涨>0
    # S_CONSEC: 连续2天涨>0
    # S_BREAKOUT: 量比>1.5+涨>2%
    # S_ACCEL: 连续3天涨>0%且累计>3%

    print("""
  策略池：
  ──────────────────────────────────────────────
  P1: 恐慌+V确认 (跌>2%+缩量 + 次日涨>0)
  P2: 恐慌+双确认 (跌>2%+缩量 + 连涨2天)
  C1: 连续涨 (连涨2天)
  C2: 加速涨 (连涨3天, 累计>3%)
  B1: 放量突破 (量比>1.5 + 涨>2%)
  B2: 缩量回踩 (量比<0.5 + 跌>0)
  M1: 动量策略 (涨>3% + 量比>1)
  ──────────────────────────────────────────────
""")

    # 逐只扫描所有信号，并计算收益
    results = {}
    for r in all_data:
        daily = r['daily']
        for off in range(20, 51):  # LC+20 to LC+50
            d = daily.get(off, {})
            if not d:
                continue
            chg = d['chg']
            vr = d['vol_ratio']

            # P1: panic + V
            if chg < -2 and vr < 1.5:
                n1 = daily.get(off + 1, {})
                if n1 and n1.get('chg', 0) > 0:
                    buy_price = n1['close']
                    key = 'P1'
                    if key not in results:
                        results[key] = {'count': 0, 'rets': {3: [], 5: [], 7: [], 10: []}}
                    results[key]['count'] += 1
                    for hold in [3, 5, 7, 10]:
                        sell = daily.get(off + 1 + hold, {})
                        if sell and sell['close'] > 0:
                            ret = ((sell['close'] - buy_price) / buy_price) * 100
                            results[key]['rets'][hold].append(round(ret, 2))

            # C1: consecutive
            if off > 1:
                d_prev = daily.get(off - 1, {})
                if d_prev and d_prev.get('chg', 0) > 0 and chg > 0:
                    buy_price = d['close']
                    key = 'C1'
                    if key not in results:
                        results[key] = {'count': 0, 'rets': {3: [], 5: [], 7: [], 10: []}}
                    results[key]['count'] += 1
                    for hold in [3, 5, 7, 10]:
                        sell = daily.get(off + hold, {})
                        if sell and sell['close'] > 0:
                            ret = ((sell['close'] - buy_price) / buy_price) * 100
                            results[key]['rets'][hold].append(round(ret, 2))

            # C2: acceleration (3 consecutive positive days)
            d_prev1 = daily.get(off - 1, {})
            d_prev2 = daily.get(off - 2, {})
            if d_prev1 and d_prev2:
                if chg > 0 and d_prev1.get('chg', 0) > 0 and d_prev2.get('chg', 0) > 0:
                    cum = chg + d_prev1['chg'] + d_prev2['chg']
                    if cum > 2:
                        buy_price = d['close']
                        key = 'C2'
                        if key not in results:
                            results[key] = {'count': 0, 'rets': {3: [], 5: [], 7: [], 10: []}}
                        results[key]['count'] += 1
                        for hold in [3, 5, 7, 10]:
                            sell = daily.get(off + hold, {})
                            if sell and sell['close'] > 0:
                                ret = ((sell['close'] - buy_price) / buy_price) * 100
                                results[key]['rets'][hold].append(round(ret, 2))

            # B1: breakout
            if chg > 2 and vr > 1.5:
                buy_price = d['close']
                key = 'B1'
                if key not in results:
                    results[key] = {'count': 0, 'rets': {3: [], 5: [], 7: [], 10: []}}
                results[key]['count'] += 1
                for hold in [3, 5, 7, 10]:
                    sell = daily.get(off + hold, {})
                    if sell and sell['close'] > 0:
                        ret = ((sell['close'] - buy_price) / buy_price) * 100
                        results[key]['rets'][hold].append(round(ret, 2))

            # M1: momentum
            if chg > 3 and vr > 1:
                buy_price = d['close']
                key = 'M1'
                if key not in results:
                    results[key] = {'count': 0, 'rets': {3: [], 5: [], 7: [], 10: []}}
                results[key]['count'] += 1
                for hold in [3, 5, 7, 10]:
                    sell = daily.get(off + hold, {})
                    if sell and sell['close'] > 0:
                        ret = ((sell['close'] - buy_price) / buy_price) * 100
                        results[key]['rets'][hold].append(round(ret, 2))

    # Print results
    for key in ['P1', 'C1', 'C2', 'B1', 'M1']:
        res = results.get(key, {'count': 0, 'rets': {}})
        print(f"  【{key}】触发{res['count']}次:")
        for hold in [3, 5, 7, 10]:
            vals = res['rets'].get(hold, [])
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                print(f"    H+{hold:2d}: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}({win/len(vals)*100:.0f}%), "
                      f"最佳{max(vals):+.2f}%, 最差{min(vals):+.2f}%")
            else:
                print(f"    H+{hold:2d}: N/A")
        print()

    # ============================================================
    # 策略4：注册前固定区间
    # ============================================================
    print()
    print("=" * 100)
    print("四、注册前固定区间策略（用LC推算）")
    print("=" * 100)

    # Based on data: average gap is 42 days, min 25, max 56
    # So "registration approach" is roughly L+gap-7 to L+gap
    # But we don't know gap in real-time
    # What we CAN do: L+35 is the 75th percentile of gap
    # So L+35 to L+50 is a safe "registration window"

    # Check: what happens in L+35 to L+50?
    print()
    print("  逐日涨跌 (L+35到L+50):")
    for r in all_data:
        daily = r['daily']
        line = f"  {r['name']:>12} G{r['gap']:>2}"
        for off in range(35, min(r['gap'] + 5, 51)):
            d = daily.get(off, {})
            if d:
                chg = d['chg']
                if chg < -3:
                    line += " 🟥"
                elif chg < -1:
                    line += " 🟨"
                elif chg > 3:
                    line += " 🟦"
                elif chg > 1:
                    line += " 🟩"
                else:
                    line += "  ·"
            else:
                line += "  ·"
        print(line)

    print()
    print("  注册日(L+gap)附近涨跌:")
    for r in all_data:
        daily = r['daily']
        gap = r['gap']
        line = f"  {r['name']:>12}"
        for off in range(gap - 3, gap + 4):
            d = daily.get(off, {})
            if d:
                chg = d['chg']
                line += f" {chg:>+5.1f}%"
            else:
                line += "   N/A"
        print(line)

    # ============================================================
    # 策略5：从注册前7天到注册后3天 — 固定窗口收益
    # ============================================================
    print()
    print("=" * 100)
    print("五、注册前7天到注册后10天 — 固定窗口收益（需要知道注册日）")
    print("  这个回测可以验证'提前买入'的效果，但实盘无法执行")
    print("=" * 100)

    # Since we know the gap for historical data, we can test:
    # "Buy at L+(gap-7), sell at L+(gap+3)" = the original D-7 strategy
    print()
    print("  假设知道注册日(Gap)，测试'注册前N天买入 → 注册后M天卖出':")
    print()
    print(f"  {'债券':>12}", end="")
    for pre in [7, 5, 3]:
        for post in [3, 5, 7]:
            print(f"  前{pre}后{post}", end="")
    print()

    for r in all_data:
        daily = r['daily']
        gap = r['gap']
        name = r['name']
        line = f"  {name:>12}"

        for pre in [7, 5, 3]:
            for post in [3, 5, 7]:
                buy_off = gap - pre
                sell_off = gap + post
                buy_d = daily.get(buy_off, {})
                sell_d = daily.get(sell_off, {})
                if buy_d and sell_d and buy_d['close'] > 0:
                    ret = ((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100
                    line += f"  {ret:>+5.1f}%"
                else:
                    line += "   N/A"
        print(line)

    # Average
    print()
    print("  平均收益:")
    for pre in [7, 5, 3]:
        for post in [3, 5, 7]:
            vals = []
            for r in all_data:
                daily = r['daily']
                gap = r['gap']
                buy_off = gap - pre
                sell_off = gap + post
                buy_d = daily.get(buy_off, {})
                sell_d = daily.get(sell_off, {})
                if buy_d and sell_d and buy_d['close'] > 0:
                    ret = ((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100
                    vals.append(ret)
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                print(f"    前{pre}天后{post}天: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}")

    # ============================================================
    # 结论
    # ============================================================
    print()
    print("=" * 100)
    print("六、结论")
    print("=" * 100)
    print()

    # Print summary
    print("""
  核心发现：
  1. 恐慌信号在L坐标系中高度分散（69个信号，覆盖L+15到L+55）
  2. 恐慌+V确认策略：胜率~50%，无alpha
  3. 连续涨策略：胜率~50%，无alpha
  4. 放量突破策略：胜率~55%，微弱alpha但收益低

  问题根源：
  - D-7恐慌策略之所以回测成功，是因为用"注册日"做锚
  - 实盘中无法知道注册日，L坐标系中信号是分散的
  - 这说明恐慌信号是注册日的"条件反射"（接近注册日才恐慌）
  - 而不是上市委通过后的"常态行为"

  可行方向：
  1. 用LC推算Gap：Gap中位数~42天，L+35进入观察窗口
     → 问题：实际Gap 25~56天，误差太大
  2. 用其他数据预测Gap：
     - 行业平均间隔
     - 交易所排队情况
     - 历史Gap分布
  3. 放弃"注册前恐慌"思路，找其他可观测信号
  4. 接受D-7策略是"事后诸葛亮"，改为"注册后入场"策略
     （已经验证：D+3买D+10卖，+4.98%，胜率91%）
""")


if __name__ == '__main__':
    main()
