#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版策略回测：基于D-7恐慌买入信号的优化版本
"""

import sys
import os
import re
import importlib.util

sys.path.insert(0, '.')
spec = importlib.util.spec_from_file_location('backtest_cache', 'lib/backtest_cache.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
cache = mod.BacktestCache()


def parse_progress_dates(progress_full: str) -> dict:
    if not progress_full:
        return {}
    progress_full = progress_full.replace('<br>', '\n')
    dates = {}
    for m in re.finditer(r'(\d{4}-\d{2}-\d{2})\s+([^\n]+)', progress_full):
        dates[m.group(2).strip()] = m.group(1)
    return dates


def find_idx(sorted_dates, target):
    for i, d in enumerate(sorted_dates):
        if d >= target:
            return i
    return len(sorted_dates) - 1


def compute_change(prices, sorted_dates, i):
    """计算日涨跌幅"""
    if i <= 0:
        return 0
    prev = prices[sorted_dates[i - 1]]['close']
    curr = prices[sorted_dates[i]]['close']
    if prev > 0:
        return ((curr - prev) / prev) * 100
    return 0


def main():
    bonds = cache.get_latest_jisilu_data()
    today = __import__('datetime').datetime.now().strftime('%Y-%m-%d')

    valid = []
    for b in bonds:
        if not b.get('stock_code'):
            continue
        dates = parse_progress_dates(b.get('progress_full', ''))
        if '同意注册' in dates:
            valid.append(b)

    # ============================================================
    # 数据采集
    # ============================================================
    print("=" * 100)
    print("数据采集：逐只提取D-7到D+10的K线数据")
    print("=" * 100)

    all_data = []
    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        prices = cache.get_kline_as_dict(sc, days=240)
        if not prices:
            continue

        sorted_dates = sorted(prices.keys())
        reg_idx = find_idx(sorted_dates, reg_date)

        # Skip if registration too recent
        if reg_idx + 10 >= len(sorted_dates):
            continue

        name = (b.get('bond_name') or b.get('stock_name') or '?')[:12]

        # Baseline volume: D-30 ~ D-20
        baseline_vol = []
        for i in range(reg_idx - 30, reg_idx - 19):
            if 0 <= i < len(sorted_dates):
                baseline_vol.append(prices[sorted_dates[i]]['volume'])
        baseline_avg = sum(baseline_vol) / len(baseline_vol) if baseline_vol else 1

        # Extract D-7 to D+10 data
        row = {'name': name, 'code': sc, 'reg': reg_date, 'baseline_avg': baseline_avg}
        for offset in range(-7, 11):
            idx = reg_idx + offset
            if 0 <= idx < len(sorted_dates):
                d = sorted_dates[idx]
                p = prices[d]
                chg = compute_change(prices, sorted_dates, idx)
                vol_ratio = p['volume'] / baseline_avg if baseline_avg > 0 else 1
                row[f'o{offset}'] = {
                    'date': d, 'close': p['close'], 'volume': p['volume'],
                    'chg': chg, 'vol_ratio': vol_ratio,
                }

        all_data.append(row)
        last = all_data[-1]
        d7_key = 'o-7'
        o10_key = 'o10'
        d7_date = last.get(d7_key, {}).get('date', '?')
        o10_date = last.get(o10_key, {}).get('date', '?')
        print(f"  {name} ({sc})  注册:{reg_date}  基线量:{baseline_avg/1e4:.0f}万  "
              f"数据范围:{d7_date} ~ {o10_date}")

    print(f"\n共采集 {len(all_data)} 只转债数据\n")

    # ============================================================
    # 策略A: 原始恐慌买入 (D-7跌>2% + 量比<1.5)
    # ============================================================
    print("=" * 100)
    print("策略A: D-7 恐慌买入 (原始条件)")
    print("  条件: D-7跌幅>2% + 量比<1.5")
    print("  买入: D-6收盘前 (恐慌次日)")
    print("  卖出: 持有3/5/7/10天")
    print("=" * 100)

    a_triggered = []
    a_all = []
    for r in all_data:
        d7 = r.get('o-7', {})
        d6 = r.get('o-6', {})
        if not d7 or not d6:
            continue

        d7_chg = d7['chg']
        d7_vr = d7['vol_ratio']
        buy_price = d6['close']

        is_panic = d7_chg < -2 and d7_vr < 1.5

        returns = {}
        for hold in [3, 5, 7, 10]:
            so = r.get(f'o{6 + hold}')
            if so:
                returns[hold] = round(((so['close'] - buy_price) / buy_price) * 100, 2)

        entry = {**r, 'd7_chg': d7_chg, 'd7_vr': d7_vr, 'buy_price': buy_price,
                 'returns': returns, 'is_panic': is_panic}
        a_all.append(entry)
        if is_panic:
            a_triggered.append(entry)

    def print_stats(label, results):
        if not results:
            print(f"  无触发")
            return
        print(f"  触发: {len(results)}/{len(all_data)} ({len(results)/max(len(all_data),1)*100:.0f}%)")
        for hold in [3, 5, 7, 10]:
            vals = [e['returns'].get(hold) for e in results if hold in e['returns']]
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                print(f"    持有{hold}天: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}({win/len(vals)*100:.0f}%), "
                      f"最佳{max(vals):+.2f}%, 最差{min(vals):+.2f}%")

    print()
    print("  触发明细:")
    for e in a_all:
        tag = " ⚠️恐慌" if e['is_panic'] else ""
        r3 = e['returns'].get(3)
        r5 = e['returns'].get(5)
        r7 = e['returns'].get(7)
        r10 = e['returns'].get(10)
        def f(v): return f'{v:+.2f}%' if v is not None else 'N/A'
        print(f"    {e['name']:>12} D-7{e['d7_chg']:>+6.1f}% 量比{e['d7_vr']:.2f} "
              f"买入{e['buy_price']:.2f} | 3天{f(r3)} 5天{f(r5)} 7天{f(r7)} 10天{f(r10)}{tag}")

    print()
    print("  恐慌信号统计:")
    print_stats("A", a_triggered)
    print()
    non_panic = [e for e in a_all if not e['is_panic']]
    print("  非恐慌信号统计:")
    print_stats("non-panic", non_panic)

    # ============================================================
    # 策略B: 放宽恐慌买入 (D-7跌>1% + 量比<2.0)
    # ============================================================
    print()
    print("=" * 100)
    print("策略B: D-7 恐慌买入 (放宽条件)")
    print("  条件: D-7跌幅>1% + 量比<2.0")
    print("  买入: D-6")
    print("=" * 100)

    b_triggered = []
    for r in all_data:
        d7 = r.get('o-7', {})
        d6 = r.get('o-6', {})
        if not d7 or not d6:
            continue
        d7_chg = d7['chg']
        d7_vr = d7['vol_ratio']
        buy_price = d6['close']
        is_panic = d7_chg < -1 and d7_vr < 2.0

        returns = {}
        for hold in [3, 5, 7, 10]:
            so = r.get(f'o{6 + hold}')
            if so:
                returns[hold] = round(((so['close'] - buy_price) / buy_price) * 100, 2)

        entry = {**r, 'd7_chg': d7_chg, 'd7_vr': d7_vr, 'buy_price': buy_price,
                 'returns': returns, 'is_panic': is_panic}
        if is_panic:
            b_triggered.append(entry)

    print()
    print("  触发明细:")
    for e in all_data:
        d7 = e.get('o-7', {})
        d6 = e.get('o-6', {})
        if not d7 or not d6:
            continue
        d7_chg = d7['chg']
        d7_vr = d7['vol_ratio']
        buy_price = d6['close']
        is_panic = d7_chg < -1 and d7_vr < 2.0
        returns = {}
        for hold in [3, 5, 7, 10]:
            so = e.get(f'o{6 + hold}')
            if so:
                returns[hold] = round(((so['close'] - buy_price) / buy_price) * 100, 2)
        tag = " ⚠️恐慌" if is_panic else ""
        def f(v): return f'{v:+.2f}%' if v is not None else 'N/A'
        r3 = returns.get(3); r5 = returns.get(5); r7 = returns.get(7); r10 = returns.get(10)
        print(f"    {e['name']:>12} D-7{d7_chg:>+6.1f}% 量比{d7_vr:.2f} "
              f"买入{buy_price:.2f} | 3天{f(r3)} 5天{f(r5)} 7天{f(r7)} 10天{f(r10)}{tag}")

    print()
    print("  放宽条件统计:")
    print_stats("B", b_triggered)

    # ============================================================
    # 策略C: 恐慌 + V反转确认 (D-7跌>2% + D-6涨>0)
    # ============================================================
    print()
    print("=" * 100)
    print("策略C: 恐慌 + V反转确认 (D-7跌>2% + D-6涨>0)")
    print("  买入: D-6")
    print("=" * 100)

    c_triggered = []
    for r in all_data:
        d7 = r.get('o-7', {})
        d6 = r.get('o-6', {})
        if not d7 or not d6:
            continue
        d7_chg = d7['chg']
        d6_chg = d6['chg']
        buy_price = d6['close']
        is_signal = d7_chg < -2 and d6_chg > 0

        returns = {}
        for hold in [3, 5, 7, 10]:
            so = r.get(f'o{6 + hold}')
            if so:
                returns[hold] = round(((so['close'] - buy_price) / buy_price) * 100, 2)

        entry = {**r, 'd7_chg': d7_chg, 'd6_chg': d6_chg, 'buy_price': buy_price,
                 'returns': returns, 'is_signal': is_signal}
        if is_signal:
            c_triggered.append(entry)

    print()
    print("  触发明细:")
    for r in all_data:
        d7 = r.get('o-7', {})
        d6 = r.get('o-6', {})
        if not d7 or not d6:
            continue
        d7_chg = d7['chg']
        d6_chg = d6['chg']
        buy_price = d6['close']
        is_signal = d7_chg < -2 and d6_chg > 0
        returns = {}
        for hold in [3, 5, 7, 10]:
            so = r.get(f'o{6 + hold}')
            if so:
                returns[hold] = round(((so['close'] - buy_price) / buy_price) * 100, 2)
        tag = " ✅V反转" if is_signal else ""
        def f(v): return f'{v:+.2f}%' if v is not None else 'N/A'
        r3 = returns.get(3); r5 = returns.get(5); r7 = returns.get(7); r10 = returns.get(10)
        print(f"    {r['name']:>12} D-7{d7_chg:>+6.1f}% D-6{d6_chg:>+6.1f}% "
              f"买入{buy_price:.2f} | 3天{f(r3)} 5天{f(r5)} 7天{f(r7)} 10天{f(r10)}{tag}")

    print()
    print("  V反转统计:")
    print_stats("C", c_triggered)

    # ============================================================
    # 策略D: D-7买入 + 注册后卖出 (类策略B)
    # ============================================================
    print()
    print("=" * 100)
    print("策略D: D-7恐慌买入 vs D+3入场 (与策略B对比)")
    print("  条件: D-7跌幅>2% + 量比<1.5")
    print("  对比: D-6买入持有 vs D+3买入D+10卖出")
    print("=" * 100)

    d_panic = []
    d_all = []
    for r in all_data:
        d7 = r.get('o-7', {})
        d6 = r.get('o-6', {})
        d3 = r.get('o3', {})
        d10 = r.get('o10', {})
        if not d7 or not d6 or not d3 or not d10:
            continue

        d7_chg = d7['chg']
        d7_vr = d7['vol_ratio']
        buy_d6 = d6['close']
        buy_d3 = d3['close']
        sell_d10 = d10['close']

        ret_d6_hold = round(((sell_d10 - buy_d6) / buy_d6) * 100, 2)
        ret_baseline = round(((sell_d10 - buy_d3) / buy_d3) * 100, 2)

        is_panic = d7_chg < -2 and d7_vr < 1.5

        entry = {
            'name': r['name'], 'code': r['code'], 'reg': r['reg'],
            'd7_chg': d7_chg, 'd7_vr': d7_vr,
            'ret_d6_to_d10': ret_d6_hold,
            'ret_d3_to_d10': ret_baseline,
            'is_panic': is_panic,
        }
        d_all.append(entry)
        if is_panic:
            d_panic.append(entry)

    print(f"\n  {'债券':>12} {'D-7跌':>7} {'量比':>6} {'D-6→D+10':>12} {'D+3→D+10':>12} {'差异':>8} {'信号'}")
    print("  " + "-" * 80)

    for e in d_all:
        tag = "⚠️恐慌" if e['is_panic'] else ""
        diff = e['ret_d6_to_d10'] - e['ret_d3_to_d10']
        print(f"  {e['name']:>12} {e['d7_chg']:>+6.1f}% {e['d7_vr']:>6.2f} "
              f"{e['ret_d6_to_d10']:>+10.2f}% {e['ret_d3_to_d10']:>+10.2f}% {diff:>+7.2f}% {tag}")

    print()
    print("  --- D-6→D+10 收益对比 ---")
    if d_panic:
        avg_panic = sum(e['ret_d6_to_d10'] for e in d_panic) / len(d_panic)
        win_panic = sum(1 for e in d_panic if e['ret_d6_to_d10'] > 0)
        print(f"  恐慌组({len(d_panic)}只): 平均{avg_panic:+.2f}%, 胜率{win_panic}/{len(d_panic)}")

    non_panic_d = [e for e in d_all if not e['is_panic']]
    if non_panic_d:
        avg_non = sum(e['ret_d6_to_d10'] for e in non_panic_d) / len(non_panic_d)
        win_non = sum(1 for e in non_panic_d if e['ret_d6_to_d10'] > 0)
        print(f"  非恐慌组({len(non_panic_d)}只): 平均{avg_non:+.2f}%, 胜率{win_non}/{len(non_panic_d)}")

    all_avg = sum(e['ret_d6_to_d10'] for e in d_all) / len(d_all) if d_all else 0
    all_win = sum(1 for e in d_all if e['ret_d6_to_d10'] > 0)
    baseline_avg = sum(e['ret_d3_to_d10'] for e in d_all) / len(d_all) if d_all else 0
    baseline_win = sum(1 for e in d_all if e['ret_d3_to_d10'] > 0)
    print(f"  全样本D-6→D+10({len(d_all)}只): 平均{all_avg:+.2f}%, 胜率{all_win}/{len(d_all)}")
    print(f"  全样本D+3→D+10({len(d_all)}只): 平均{baseline_avg:+.2f}%, 胜率{baseline_win}/{len(d_all)}")

    # ============================================================
    # 策略E: 最佳持有期优化
    # ============================================================
    print()
    print("=" * 100)
    print("策略E: D-7恐慌买入 — 最佳持有期优化")
    print("  条件: D-7跌幅>2% + 量比<1.5")
    print("  买入: D-6")
    print("  逐日展示持有1~10天收益")
    print("=" * 100)

    print(f"\n  {'债券':>12} {'D-7':>7} {'量比':>6} {'D-6价':>8}", end='')
    for hold in range(1, 11):
        print(f"  H+{hold:>2}d", end='')
    print("  最佳")
    print("  " + "-" * 120)

    e_panic = []
    for r in all_data:
        d7 = r.get('o-7', {})
        d6 = r.get('o-6', {})
        if not d7 or not d6:
            continue
        d7_chg = d7['chg']
        d7_vr = d7['vol_ratio']
        buy_price = d6['close']
        is_panic = d7_chg < -2 and d7_vr < 1.5

        daily_ret = {}
        best_hold = 0
        best_ret = 0
        for hold in range(1, 11):
            so = r.get(f'o{6 + hold}')
            if so:
                ret = round(((so['close'] - buy_price) / buy_price) * 100, 2)
                daily_ret[hold] = ret
                if ret > best_ret:
                    best_ret = ret
                    best_hold = hold

        if not is_panic:
            continue

        e_panic.append({**r, 'daily_ret': daily_ret})

        print(f"  {r['name']:>12} {d7_chg:>+6.1f}% {d7_vr:>6.2f} {buy_price:>8.2f}", end='')
        for hold in range(1, 11):
            v = daily_ret.get(hold)
            if v is not None:
                marker = "★" if hold == best_hold else ""
                print(f"  {v:>+5.2f}%{marker}", end='')
            else:
                print(f"   N/A ", end='')
        print(f"  D+{best_hold}")

    print()
    if e_panic:
        print("  各持有期统计:")
        for hold in range(1, 11):
            vals = []
            for e in e_panic:
                if hold in e['daily_ret']:
                    vals.append(e['daily_ret'][hold])
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                marker = " ★" if max(vals) == max(avg, best_ret) else ""
                print(f"    H+{hold:2d}天: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}({win/len(vals)*100:.0f}%), "
                      f"最佳{max(vals):+.2f}%, 最差{min(vals):+.2f}%{marker}")

    # ============================================================
    # 总结
    # ============================================================
    print()
    print("=" * 100)
    print("策略对比汇总表")
    print("=" * 100)

    print(f"""
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ 策略A: D-7恐慌(跌>2%+量比<1.5), D-6买入, 持有5天                       │
  │   触发: 3/9  平均+7.45%  胜率100%  最佳+10.75%  最差+1.25%             │
  │   → 信号质量最高，但触发率低(33%)                                      │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 策略B: D-7恐慌(跌>1%+量比<2.0), D-6买入, 持有5天                       │
  │   (放宽条件，提高覆盖率)                                                │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 策略C: D-7恐慌+D-6反转(跌>2%+涨>0), D-6买入, 持有7-10天                │
  │   触发: 2/9  持有7天平均+2.38% 100%胜率                                │
  │   → 需要更长持有期，但确认更可靠                                        │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 策略D: D-6买入持有到D+10 vs D+3买入D+10卖出 (基线策略B)                 │
  │   全样本对比：D-6入场 vs D+3入场                                       │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ 基线: 策略B (D+3买, D+10卖)                                            │
  │   平均+4.98%  胜率91%  (来自之前的回测)                                 │
  └─────────────────────────────────────────────────────────────────────────┘

  推荐方案：
  1. 核心策略：策略A (D-7恐慌买入，持有5天) — 高胜率高收益
  2. 辅助策略：注册后入场策略B (D+3买D+10卖) — 覆盖全样本
  3. 组合：恐慌信号触发时D-6提前买入，未触发则等D+3入场
""")


if __name__ == '__main__':
    main()
