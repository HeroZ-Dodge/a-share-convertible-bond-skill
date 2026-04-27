#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心分析：上市委通过后，逐日价格异动信号是否聚集？

思路：
1. 以L-0（上市委通过）为锚
2. 逐日看L+1到L+55的涨跌、成交量
3. 不依赖注册日，纯粹从价格数据中找"恐慌→修复"信号
4. 如果信号聚集在某个L区间 → 可以用
5. 如果信号分散 → 说明恐慌不是固定窗口触发的
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
    if i <= 0:
        return 0
    prev = prices[sorted_dates[i - 1]]['close']
    curr = prices[sorted_dates[i]]['close']
    if prev > 0:
        return ((curr - prev) / prev) * 100
    return 0


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

    print(f"{len(valid)} 只有完整数据的转债, 间隔{min(v['gap'] for v in valid)}~{max(v['gap'] for v in valid)}天")
    print()

    # ============================================================
    # 第一步：逐只提取L坐标系下的K线数据
    # ============================================================
    all_data = []
    for v in valid:
        prices = cache.get_kline_as_dict(v['code'], days=240)
        if not prices:
            continue
        sd = sorted(prices.keys())
        lc_idx = find_idx(sd, v['lc_date'])
        reg_idx = find_idx(sd, v['reg_date'])

        # Baseline vol: first 20 trading days after LC
        baseline_start = lc_idx + 5
        baseline_end = lc_idx + 15
        baseline_vol = []
        for i in range(baseline_start, baseline_end):
            if 0 <= i < len(sd):
                baseline_vol.append(prices[sd[i]]['volume'])
        baseline_avg = sum(baseline_vol) / len(baseline_vol) if baseline_vol else 1

        # Extract L+1 to L+60
        daily = {}
        for offset in range(1, 61):
            idx = lc_idx + offset
            if idx < 0 or idx >= len(sd):
                continue
            d = sd[idx]
            if d > today:
                continue
            p = prices[d]
            chg = compute_change(prices, sd, idx)
            vol_ratio = p['volume'] / baseline_avg if baseline_avg > 0 else 1
            daily[offset] = {'date': d, 'close': p['close'], 'chg': chg, 'vol_ratio': vol_ratio}

        row = {
            'name': v['name'], 'code': v['code'],
            'lc_date': v['lc_date'], 'reg_date': v['reg_date'],
            'gap': v['gap'], 'lc_idx': lc_idx, 'reg_idx': reg_idx,
            'daily': daily, 'baseline_avg': baseline_avg,
            'prices': prices, 'sorted_dates': sd,
        }
        all_data.append(row)

    # ============================================================
    # 热力图：L+10到L+55的逐日涨跌
    # ============================================================
    print("=" * 100)
    print("一、逐日涨跌幅热力图 (L+10到L+55)")
    print("  🟥跌幅>3%  🟧跌幅>2%  🟨跌幅>1%  🟩涨>1%  🟦涨>3%  ·无数据")
    print("=" * 100)

    for r in all_data:
        d7_l = r['reg_idx'] - 7 - r['lc_idx']  # where D-7 falls
        line = f"  {r['name']:>12} G{r['gap']:>2}"
        for off in range(10, 56):
            d = r['daily'].get(off, {})
            if d:
                chg = d['chg']
                if chg < -3:
                    line += " 🟥"
                elif chg < -2:
                    line += " 🟧"
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
        marker_pos = ""
        if 10 <= d7_l <= 55:
            marker_pos = f"  ←D-7在L+{d7_l}"
        print(line + marker_pos)

    print()
    print("  D-7位置：从注册日倒推7天，看看在L坐标系中落在哪里")
    print("  如果D-7位置附近密集出现🟥🟧 → 说明恐慌确实在注册前7天")
    print("  如果D-7附近没什么特别 → 说明恐慌信号是随机的")
    print()

    # ============================================================
    # 热力图2：量比
    # ============================================================
    print("=" * 100)
    print("二、逐日量比热力图 (L+10到L+55)")
    print("  🟥量比>2  🟧量比>1.5  🟨量比<0.5  ·无数据")
    print("=" * 100)

    for r in all_data:
        d7_l = r['reg_idx'] - 7 - r['lc_idx']
        line = f"  {r['name']:>12} G{r['gap']:>2}"
        for off in range(10, 56):
            d = r['daily'].get(off, {})
            if d:
                vr = d['vol_ratio']
                if vr > 2:
                    line += " 🟥"
                elif vr > 1.5:
                    line += " 🟧"
                elif vr < 0.5:
                    line += " 🟨"
                else:
                    line += "  ·"
            else:
                line += "  ·"
        marker_pos = ""
        if 10 <= d7_l <= 55:
            marker_pos = f"  ←D-7在L+{d7_l}"
        print(line + marker_pos)

    # ============================================================
    # 热力图3：综合信号
    # ============================================================
    print()
    print("=" * 100)
    print("三、综合信号热力图")
    print("  🔴恐慌(跌>2%+量比<1.5)  🟢修复(连续2天涨>0)  ⚫其他")
    print("=" * 100)

    for r in all_data:
        d7_l = r['reg_idx'] - 7 - r['lc_idx']
        line = f"  {r['name']:>12} G{r['gap']:>2}"
        for off in range(10, 56):
            d = r['daily'].get(off, {})
            if d:
                chg = d['chg']
                vr = d['vol_ratio']
                if chg < -2 and vr < 1.5:
                    line += " 🔴"
                elif chg > 0:
                    prev = r['daily'].get(off - 1, {})
                    if prev and prev.get('chg', 0) > 0:
                        line += " 🟢"
                    else:
                        line += "  ·"
                else:
                    line += "  ·"
            else:
                line += "  ·"
        marker_pos = ""
        if 10 <= d7_l <= 55:
            marker_pos = f"  ←D-7在L+{d7_l}"
        print(line + marker_pos)

    # ============================================================
    # 分析：恐慌信号在L坐标系中是否聚集？
    # ============================================================
    print()
    print("=" * 100)
    print("四、恐慌信号分布（L+10到L+55中跌幅>2%+量比<1.5的日子）")
    print("=" * 100)

    all_signals = []
    for r in all_data:
        signals = []
        for off in range(10, 56):
            d = r['daily'].get(off, {})
            if d and d['chg'] < -2 and d['vol_ratio'] < 1.5:
                signals.append(off)
        if signals:
            all_signals.extend([(r['name'], r['gap'], r['reg_idx'] - 7 - r['lc_idx'], s) for s in signals])
            print(f"  {r['name']:>12} Gap={r['gap']:>2} D-7=L+{r['reg_idx']-7-r['lc_idx']:>2} "
                  f"恐慌信号: {', '.join([f'L+{s}' for s in signals])}")
        else:
            print(f"  {r['name']:>12} Gap={r['gap']:>2} D-7=L+{r['reg_idx']-7-r['lc_idx']:>2} 无恐慌信号")

    print(f"\n  共 {len(all_signals)} 个恐慌信号点（{len(set(s[0] for s in all_signals))} 只转债）")

    # Histogram of signal positions
    if all_signals:
        print()
        print("  信号位置直方图 (每格代表触发该L+offset的转债数量):")
        from collections import Counter
        pos_counts = Counter(s[3] for s in all_signals)
        for off in range(10, 56):
            count = pos_counts.get(off, 0)
            if count > 0:
                bar = "█" * count
                # Check if any signal at this offset is close to D-7
                close_to_d7 = any(abs(off - d7_l) <= 2 for _, _, d7_l, o in all_signals if o == off)
                marker = " ←D-7附近" if close_to_d7 else ""
                print(f"    L+{off:2d}: {bar} ({count}){marker}")

    # ============================================================
    # 核心问题：上市委通过后的价格趋势
    # ============================================================
    print()
    print("=" * 100)
    print("五、上市后价格趋势（标准化到L-0=100）")
    print("=" * 100)

    # Normalize all prices to L-0=100
    print(f"\n  {'L+':>4}", end="")
    for off in range(0, 56, 5):
        print(f"     L+{off:2d}", end="")
    print()
    print("  " + "-" * 80)

    for off in range(0, 56, 5):
        closes = []
        for r in all_data:
            d = r['daily'].get(off, {})
            if d:
                closes.append(d['close'])
        if closes:
            avg = sum(closes) / len(closes)
            print(f"  L+{off:2d}: 平均收盘价 {avg:.2f} ({len(closes)}只)")

    # Show normalized trend for each bond
    print()
    print("  标准化价格趋势 (L-0=100):")
    for r in all_data:
        l0 = r['daily'].get(1, {})
        if not l0:
            continue
        base = l0['close']
        line = f"  {r['name']:>12} G{r['gap']:>2}"
        for off in range(0, 56, 5):
            d = r['daily'].get(off if off > 0 else 1, {})
            if d:
                norm = (d['close'] / base) * 100
                line += f" {norm:6.1f}"
            else:
                line += "    · "
        print(line)

    # ============================================================
    # 逐日扫描策略：不依赖锚点的纯信号策略
    # ============================================================
    print()
    print("=" * 100)
    print("六、逐日信号扫描策略（实盘可执行）")
    print("=" * 100)

    # Strategy: After LC, scan each day for:
    # Signal types:
    # A: 单日大跌(>2%)+缩量 → 恐慌
    # B: 恐慌后次日修复(涨>0) → 买入信号
    # C: 连续2天涨 → 动量确认
    # D: 放量突破(量比>1.5+涨>2%) → 资金进场

    print()
    print("  逐只分析：上市委通过后出现的所有信号")
    print()

    for r in all_data:
        name = r['name']
        daily = r['daily']
        events = []

        for off in range(1, 56):
            d = daily.get(off, {})
            if not d:
                continue
            chg = d['chg']
            vr = d['vol_ratio']

            # Signal A: panic sell
            if chg < -2 and vr < 1.5:
                events.append((off, 'A恐慌', f"跌{chg:.1f}%量比{vr:.2f}"))

            # Signal C: consecutive positive
            if off > 1:
                prev = daily.get(off - 1, {})
                if prev and chg > 0 and prev.get('chg', 0) > 0:
                    events.append((off, 'C连续涨', f"连涨2天"))

            # Signal D: volume breakout
            if chg > 2 and vr > 1.5:
                events.append((off, 'D放量突破', f"涨{chg:.1f}%放量{vr:.2f}"))

        if events:
            for off, sig_type, detail in events:
                d = daily.get(off, {})
                date_str = d.get('date', '?') if d else '?'
                print(f"  {name:>12} L+{off:>2} ({date_str}) {sig_type:>6} {detail}")
        else:
            print(f"  {name:>12} 无显著信号")

    # ============================================================
    # 统计：哪种信号最常见？信号之间有什么关联？
    # ============================================================
    print()
    print("=" * 100)
    print("七、信号统计分析")
    print("=" * 100)

    from collections import Counter
    all_events = []
    event_by_type = Counter()

    for r in all_data:
        daily = r['daily']
        for off in range(1, 56):
            d = daily.get(off, {})
            if not d:
                continue
            chg = d['chg']
            vr = d['vol_ratio']
            if chg < -2 and vr < 1.5:
                all_events.append((r['name'], r['gap'], off, 'A'))
                event_by_type['A'] += 1
            if off > 1:
                prev = daily.get(off - 1, {})
                if prev and chg > 0 and prev.get('chg', 0) > 0:
                    all_events.append((r['name'], r['gap'], off, 'C'))
                    event_by_type['C'] += 1
            if chg > 2 and vr > 1.5:
                all_events.append((r['name'], r['gap'], off, 'D'))
                event_by_type['D'] += 1

    print(f"\n  信号类型统计:")
    print(f"    A恐慌(跌>2%+缩量): {event_by_type['A']} 次")
    print(f"    C连续涨: {event_by_type['C']} 次")
    print(f"    D放量突破: {event_by_type['D']} 次")

    # For each panic signal, check what happens next
    print()
    print("  恐慌信号(A)后走势:")
    for r in all_data:
        daily = r['daily']
        for off in range(1, 55):
            d = daily.get(off, {})
            if not d or not (d['chg'] < -2 and d['vol_ratio'] < 1.5):
                continue
            # Found panic at this offset
            n1 = daily.get(off + 1, {})
            n2 = daily.get(off + 2, {})
            n3 = daily.get(off + 3, {})
            n5 = daily.get(off + 5, {})
            n7 = daily.get(off + 7, {})

            def fmt(d):
                if d:
                    return f"{d['chg']:>+4.1f}%"
                return "N/A"

            print(f"    {r['name']:>12} L+{off:>2}恐慌 → "
                  f"L+{off+1}:{fmt(n1)} L+{off+2}:{fmt(n2)} "
                  f"L+{off+3}:{fmt(n3)} L+{off+5}:{fmt(n5)} L+{off+7}:{fmt(n7)}")


if __name__ == '__main__':
    main()
