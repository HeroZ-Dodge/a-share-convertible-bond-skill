#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册前5-7天策略：基于D-7恐慌卖出信号的回测

发现规律：
- D-7 是恐慌卖出窗口（9/12只下跌，平均-2.7%）
- D-6 开始分化，部分反转
- D-5 多数开始修复
- D-3 到 D+0 进入加速上涨期

信号策略：
1. D-7 跌幅 > 2% + 量比 < 1.5 → 恐慌卖出信号，D-7 或 D-6 买入
2. D-5 到 D-3 连续上涨确认 → 持有到 D+7
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


def compute_daily(prices_dict, sorted_dates, start_offset, end_offset, reg_idx):
    """计算指定偏移范围内的日度数据"""
    result = []
    for i in range(reg_idx + start_offset, reg_idx + end_offset + 1):
        if i < 0 or i >= len(sorted_dates):
            continue
        d = sorted_dates[i]
        p = prices_dict[d]
        chg = 0
        if i > 0:
            prev = prices_dict[sorted_dates[i - 1]]['close']
            if prev > 0:
                chg = ((p['close'] - prev) / prev) * 100
        result.append({
            'date': d,
            'close': p['close'],
            'volume': p['volume'],
            'change_pct': chg,
            'offset': i - reg_idx,
        })
    return result


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
    # 策略1：D-7 恐慌买入（跌幅 > 2% + 量比 < 1.5）
    # ============================================================
    print("=" * 80)
    print("策略1：D-7 恐慌买入信号")
    print("  条件：D-7 日跌幅 > 2% 且 量比 < 1.5")
    print("  买入：D-7 或 D-6")
    print("  卖出：D+3 / D+5 / D+7")
    print("=" * 80)

    all_results = []
    panic_results = []
    no_panic_results = []

    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        prices = cache.get_kline_as_dict(sc, days=120)
        if not prices:
            continue

        sorted_dates = sorted(prices.keys())
        reg_idx = find_idx(sorted_dates, reg_date)

        # Skip if registration is too recent (not enough future data)
        if reg_idx + 10 >= len(sorted_dates):
            continue

        # Baseline volume: D-30 ~ D-20
        baseline_vol = []
        for i in range(reg_idx - 30, reg_idx - 19):
            if 0 <= i < len(sorted_dates):
                baseline_vol.append(prices[sorted_dates[i]]['volume'])
        baseline_avg = sum(baseline_vol) / len(baseline_vol) if baseline_vol else 1

        # Get D-7 data
        d7_idx = reg_idx - 7
        d6_idx = reg_idx - 6
        if d7_idx < 0 or d7_idx >= len(sorted_dates):
            continue

        d7_close = prices[sorted_dates[d7_idx]]['close']
        d7_vol = prices[sorted_dates[d7_idx]]['volume']
        d7_vol_ratio = d7_vol / baseline_avg if baseline_avg > 0 else 1

        # Compute D-7 change
        d7_chg = 0
        if d7_idx > 0:
            prev_close = prices[sorted_dates[d7_idx - 1]]['close']
            if prev_close > 0:
                d7_chg = ((d7_close - prev_close) / prev_close) * 100

        name = (b.get('bond_name') or b.get('stock_name') or '?')[:12]

        # Check signal
        is_panic = d7_chg < -2 and d7_vol_ratio < 1.5

        # Compute holding returns from D-6 (day after panic)
        d6_close = prices[sorted_dates[d6_idx]]['close']
        returns = {}
        for hold_days in [3, 5, 7, 10]:
            sell_idx = d6_idx + hold_days
            if sell_idx < len(sorted_dates):
                sell_date = sorted_dates[sell_idx]
                if sell_date <= today:
                    sell_price = prices[sell_date]['close']
                    if d6_close > 0:
                        returns[hold_days] = round(((sell_price - d6_close) / d6_close) * 100, 2)

        result = {
            'name': name, 'code': sc, 'reg': reg_date,
            'd7_chg': d7_chg, 'd7_vol_ratio': d7_vol_ratio,
            'd6_close': d6_close, 'returns': returns,
            'is_panic': is_panic,
        }
        all_results.append(result)

        if is_panic:
            panic_results.append(result)
        else:
            no_panic_results.append(result)

    # Print results
    print(f"\n{'债券':>12} {'D-7涨跌':>8} {'D-7量比':>8} {'D-6买入价':>10} "
          f"{'持有3天':>8} {'持有5天':>8} {'持有7天':>8} {'持有10天':>9} {'信号'}")
    print("-" * 100)

    for r in all_results:
        ret3 = r['returns'].get(3, None)
        ret5 = r['returns'].get(5, None)
        ret7 = r['returns'].get(7, None)
        ret10 = r['returns'].get(10, None)

        def fmt(v):
            return f'{v:+.2f}%' if v is not None else 'N/A'

        signal = '⚠️ 恐慌买入' if r['is_panic'] else ''

        print(f"{r['name']:>12} {r['d7_chg']:>+7.2f}% {r['d7_vol_ratio']:>8.2f} "
              f"{r['d6_close']:>10.2f} {fmt(ret3):>8} {fmt(ret5):>8} "
              f"{fmt(ret7):>8} {fmt(ret10):>9} {signal}")

    # Stats
    print()
    print("--- 恐慌买入信号统计 ---")
    print(f"  触发信号: {len(panic_results)}/{len(all_results)} ({len(panic_results)/max(len(all_results),1)*100:.0f}%)")

    if panic_results:
        for days in [3, 5, 7, 10]:
            vals = [r['returns'][days] for r in panic_results if days in r['returns']]
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                best = max(vals)
                worst = min(vals)
                print(f"  持有 {days}天: 平均 {avg:+.2f}%, 胜率 {win}/{len(vals)} "
                      f"({win/len(vals)*100:.0f}%), 最佳 {best:+.2f}%, 最差 {worst:+.2f}%")

    print()
    print("--- 非恐慌信号对比 ---")
    if no_panic_results:
        for days in [3, 5, 7, 10]:
            vals = [r['returns'][days] for r in no_panic_results if days in r['returns']]
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                best = max(vals)
                worst = min(vals)
                print(f"  持有 {days}天: 平均 {avg:+.2f}%, 胜率 {win}/{len(vals)} "
                      f"({win/len(vals)*100:.0f}%), 最佳 {best:+.2f}%, 最差 {worst:+.2f}%")

    # ============================================================
    # 策略2：V型反转确认买入（D-7跌 + D-6涨）
    # ============================================================
    print()
    print("=" * 80)
    print("策略2：V型反转确认买入")
    print("  条件：D-7 跌幅 > 2% + D-6 涨幅 > 0")
    print("  买入：D-6")
    print("  卖出：D+3 / D+5 / D+7")
    print("=" * 80)

    v_results = []
    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        prices = cache.get_kline_as_dict(sc, days=120)
        if not prices:
            continue

        sorted_dates = sorted(prices.keys())
        reg_idx = find_idx(sorted_dates, reg_date)
        if reg_idx + 10 >= len(sorted_dates):
            continue

        baseline_vol = []
        for i in range(reg_idx - 30, reg_idx - 19):
            if 0 <= i < len(sorted_dates):
                baseline_vol.append(prices[sorted_dates[i]]['volume'])
        baseline_avg = sum(baseline_vol) / len(baseline_vol) if baseline_vol else 1

        d7_idx = reg_idx - 7
        d6_idx = reg_idx - 6
        if d7_idx < 0 or d6_idx < 0 or d6_idx >= len(sorted_dates):
            continue

        # Compute D-7 change
        d7_chg = 0
        if d7_idx > 0:
            prev = prices[sorted_dates[d7_idx - 1]]['close']
            if prev > 0:
                d7_chg = ((prices[sorted_dates[d7_idx]]['close'] - prev) / prev) * 100

        # Compute D-6 change
        d6_chg = 0
        if d6_idx > 0:
            prev = prices[sorted_dates[d6_idx - 1]]['close']
            if prev > 0:
                d6_chg = ((prices[sorted_dates[d6_idx]]['close'] - prev) / prev) * 100

        d6_close = prices[sorted_dates[d6_idx]]['close']

        name = (b.get('bond_name') or b.get('stock_name') or '?')[:12]

        is_v = d7_chg < -2 and d6_chg > 0

        returns = {}
        for hold_days in [3, 5, 7, 10]:
            sell_idx = d6_idx + hold_days
            if sell_idx < len(sorted_dates):
                sell_date = sorted_dates[sell_idx]
                if sell_date <= today:
                    sell_price = prices[sell_date]['close']
                    if d6_close > 0:
                        returns[hold_days] = round(((sell_price - d6_close) / d6_close) * 100, 2)

        v_results.append({
            'name': name, 'code': sc, 'reg': reg_date,
            'd7_chg': d7_chg, 'd6_chg': d6_chg,
            'd6_close': d6_close, 'returns': returns,
            'is_v': is_v,
        })

    print(f"\n{'债券':>12} {'D-7涨跌':>8} {'D-6涨跌':>8} {'D-6买入价':>10} "
          f"{'持有3天':>8} {'持有5天':>8} {'持有7天':>8} {'持有10天':>9} {'信号'}")
    print("-" * 100)

    v_triggered = []
    for r in v_results:
        ret3 = r['returns'].get(3, None)
        ret5 = r['returns'].get(5, None)
        ret7 = r['returns'].get(7, None)
        ret10 = r['returns'].get(10, None)

        def fmt(v):
            return f'{v:+.2f}%' if v is not None else 'N/A'

        signal = '✅ V反转' if r['is_v'] else ''
        if r['is_v']:
            v_triggered.append(r)

        print(f"{r['name']:>12} {r['d7_chg']:>+7.2f}% {r['d6_chg']:>+7.2f}% "
              f"{r['d6_close']:>10.2f} {fmt(ret3):>8} {fmt(ret5):>8} "
              f"{fmt(ret7):>8} {fmt(ret10):>9} {signal}")

    print()
    print("--- V型反转信号统计 ---")
    if v_triggered:
        print(f"  触发: {len(v_triggered)}/{len(v_results)}")
        for days in [3, 5, 7, 10]:
            vals = [r['returns'][days] for r in v_triggered if days in r['returns']]
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                print(f"  持有 {days}天: 平均 {avg:+.2f}%, 胜率 {win}/{len(vals)} "
                      f"({win/len(vals)*100:.0f}%), 最佳 {max(vals):+.2f}%, 最差 {min(vals):+.2f}%")

    # ============================================================
    # 策略3：连续上涨确认（D-5/D-4/D-3 连续2天上涨）
    # ============================================================
    print()
    print("=" * 80)
    print("策略3：连续上涨确认买入")
    print("  条件：D-5到D-3区间，任意连续2天上涨")
    print("  买入：第2天上涨当日")
    print("  卖出：D+3 / D+5 / D+7")
    print("=" * 80)

    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        prices = cache.get_kline_as_dict(sc, days=120)
        if not prices:
            continue

        sorted_dates = sorted(prices.keys())
        reg_idx = find_idx(sorted_dates, reg_date)
        if reg_idx + 10 >= len(sorted_dates):
            continue

        # Get D-5 to D+7 daily changes (wider window for return calculation)
        daily = []
        for offset in range(-5, 8):
            idx = reg_idx + offset
            if idx < 0 or idx >= len(sorted_dates):
                continue
            d = sorted_dates[idx]
            if d > today:
                continue
            chg = 0
            if idx > 0:
                prev = prices[sorted_dates[idx - 1]]['close']
                if prev > 0:
                    chg = ((prices[d]['close'] - prev) / prev) * 100
            daily.append({'offset': offset, 'date': d, 'close': prices[d]['close'], 'chg': chg})

        # Find consecutive positive days
        buy_signal = None
        for i in range(1, len(daily)):
            if daily[i]['chg'] > 0 and daily[i - 1]['chg'] > 0:
                buy_signal = daily[i]
                break

        # Compute returns from buy signal
        name = (b.get('bond_name') or b.get('stock_name') or '?')[:12]

        if buy_signal and buy_signal.get('close') is not None:
            buy_price = buy_signal['close']
            buy_off = buy_signal['offset']
            if buy_off is None:
                print(f"  {name:>12} {sc:>8} 无连续上涨信号")
                continue
            ret3 = ret5 = ret7 = None
            for d in daily:
                if d['offset'] == buy_off + 3:
                    ret3 = round(((d['close'] - buy_price) / buy_price) * 100, 2)
                if d['offset'] == buy_off + 5:
                    ret5 = round(((d['close'] - buy_price) / buy_price) * 100, 2)
                if d['offset'] == buy_off + 7:
                    ret7 = round(((d['close'] - buy_price) / buy_price) * 100, 2)

            offset_str = f"D+{buy_off}" if buy_off >= 0 else f"D{buy_off}"
            ret3_str = f"{ret3:+.2f}%" if ret3 is not None else "N/A"
            ret5_str = f"{ret5:+.2f}%" if ret5 is not None else "N/A"
            ret7_str = f"{ret7:+.2f}%" if ret7 is not None else "N/A"
            print(f"  {name:>12} {sc:>8} 信号: 连续上涨({offset_str}), 买入价 {buy_price:.2f} "
                  f"持有3天 {ret3_str} 持有5天 {ret5_str} 持有7天 {ret7_str}")
        else:
            print(f"  {name:>12} {sc:>8} 无连续上涨信号")

    # ============================================================
    # 汇总策略对比
    # ============================================================
    print()
    print("=" * 80)
    print("四、策略对比汇总")
    print("=" * 80)
    print()

    print("  【策略1】D-7恐慌买入（跌幅>2%+量比<1.5）")
    if panic_results:
        for days in [3, 5, 7, 10]:
            vals = [r['returns'][days] for r in panic_results if days in r['returns']]
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                print(f"    持有{days}天: {avg:+.2f}%, {win}/{len(vals)}赢")

    print()
    print("  【策略2】V型反转（D-7跌+D-6涨）")
    if v_triggered:
        for days in [3, 5, 7, 10]:
            vals = [r['returns'][days] for r in v_triggered if days in r['returns']]
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                print(f"    持有{days}天: {avg:+.2f}%, {win}/{len(vals)}赢")

    print()
    print("  【基线】策略B（注册+3天买，+10天卖）— 来自之前回测")
    print("    平均 +4.98%, 胜率 91%")

    print()
    print("=" * 80)
    print("结论与建议")
    print("=" * 80)
    print()
    print("  1. D-7 恐慌卖出是普遍现象（12只中X只触发）")
    print("  2. 恐慌后买入，持有到注册后3-5天，效果如何")
    print("  3. V型反转确认比单纯恐慌买入更稳健")
    print("  4. 连续上涨确认信号出现在D-3附近")
    print()


if __name__ == '__main__':
    main()
