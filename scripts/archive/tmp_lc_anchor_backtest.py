#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于上市委通过日的恐慌买入策略回测
不依赖注册日锚点，用上市委通过日(L-0)作为起点
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


def get_return(prices, sorted_dates, buy_idx, hold_days):
    sell_idx = buy_idx + hold_days
    if sell_idx >= len(sorted_dates):
        return None
    buy_price = prices[sorted_dates[buy_idx]]['close']
    sell_price = prices[sorted_dates[sell_idx]]['close']
    if buy_price <= 0:
        return None
    return round(((sell_price - buy_price) / buy_price) * 100, 2)


def main():
    bonds = cache.get_latest_jisilu_data()
    today = datetime.now().strftime('%Y-%m-%d')

    # Collect bonds with BOTH dates
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
                'lc_date': lc,
                'reg_date': reg,
                'gap': gap,
            })

    print(f"共 {len(valid)} 只有完整数据的转债")
    print(f"间隔: 平均{sum(v['gap'] for v in valid)/len(valid):.1f}天, 范围{min(v['gap'] for v in valid)}~{max(v['gap'] for v in valid)}天")
    print()

    # ============================================================
    # 数据采集：以L-0（上市委通过日）为锚点
    # ============================================================
    print("=" * 100)
    print("数据采集：逐只提取L-0到L+60的K线数据")
    print("=" * 100)

    all_data = []
    for v in valid:
        sc = v['code']
        prices = cache.get_kline_as_dict(sc, days=240)
        if not prices:
            print(f"  {v['name']}: 无K线数据")
            continue

        sorted_dates = sorted(prices.keys())
        lc_idx = find_idx(sorted_dates, v['lc_date'])
        reg_idx = find_idx(sorted_dates, v['reg_date'])

        name = v['name']

        # Baseline volume: L-30 to L-20 (relative to listing committee date)
        baseline_vol = []
        for i in range(lc_idx - 30, lc_idx - 19):
            if 0 <= i < len(sorted_dates):
                baseline_vol.append(prices[sorted_dates[i]]['volume'])
        baseline_avg = sum(baseline_vol) / len(baseline_vol) if baseline_vol else 1

        # Map: for each day from L+20 to L+55, compute (chg, vol_ratio)
        window_data = {}
        for offset in range(20, 56):
            idx = lc_idx + offset
            if idx < 0 or idx >= len(sorted_dates):
                continue
            d = sorted_dates[idx]
            if d > today:
                continue
            p = prices[d]
            chg = compute_change(prices, sorted_dates, idx)
            vol_ratio = p['volume'] / baseline_avg if baseline_avg > 0 else 1
            window_data[offset] = {
                'date': d, 'close': p['close'], 'volume': p['volume'],
                'chg': chg, 'vol_ratio': vol_ratio,
            }

        # Where does D-7 fall in L terms?
        d7_as_l = reg_idx - 7 - lc_idx  # e.g., if gap=48, d7 is L+41

        row = {
            'name': name, 'code': sc,
            'lc_date': v['lc_date'], 'reg_date': v['reg_date'],
            'gap': v['gap'], 'd7_as_l': d7_as_l,
            'lc_idx': lc_idx, 'reg_idx': reg_idx,
            'prices': prices, 'sorted_dates': sorted_dates,
            'baseline_avg': baseline_avg,
            'window': window_data,
        }
        all_data.append(row)
        print(f"  {name} ({sc}) LC:{v['lc_date']} Reg:{v['reg_date']} Gap:{v['gap']}天 D-7=L+{d7_as_l}")

    print(f"\n共采集 {len(all_data)} 只转债\n")

    # ============================================================
    # 第一部分：观察 D-7 在 L 坐标系中的位置
    # ============================================================
    print("=" * 100)
    print("一、D-7恐慌信号在L坐标系中的分布")
    print("=" * 100)

    # For each bond, find the D-7 signal (which we know exists from previous analysis)
    # and see what L offset it corresponds to
    print(f"\n  {'债券':>12} {'Gap':>5} {'D-7=L+':>7} {'L+{d7_as_l-1}涨跌':>8} "
          f"{'L+{d7_as_l}量比':>7} {'信号'}")
    print("  " + "-" * 70)

    for r in all_data:
        d7_l = r['d7_as_l']
        d7 = r['window'].get(d7_l, {})
        if d7:
            tag = "⚠️恐慌" if d7['chg'] < -2 and d7['vol_ratio'] < 1.5 else ""
            print(f"  {r['name']:>12} {r['gap']:>5} {f'L+{d7_l}':>7} "
                  f"{d7['chg']:>+7.1f}% {d7['vol_ratio']:>6.2f} {tag}")
        else:
            print(f"  {r['name']:>12} {r['gap']:>5} {f'L+{d7_l}':>7} N/A (无数据)")

    # ============================================================
    # 第二部分：固定窗口扫描（不依赖注册日）
    # ============================================================
    print()
    print("=" * 100)
    print("二、固定扫描窗口 L+25 ~ L+50 逐日信号分布")
    print("  方法：以L-0为锚，扫描L+25到L+50，找出跌幅>2%+量比<1.5的日子")
    print("=" * 100)

    signal_days = []  # (name, l_offset, chg, vol_ratio, buy_price, next_day_data)

    for r in all_data:
        signals_in_window = []
        for offset in range(25, 51):
            d = r['window'].get(offset, {})
            if not d:
                continue
            if d['chg'] < -2 and d['vol_ratio'] < 1.5:
                # Found panic signal at this L+offset
                next_offset = offset + 1
                next_d = r['window'].get(next_offset, {})
                signals_in_window.append({
                    'l_offset': offset,
                    'chg': d['chg'],
                    'vol_ratio': d['vol_ratio'],
                    'close': d['close'],
                    'next_close': next_d['close'] if next_d else None,
                })

        if signals_in_window:
            for s in signals_in_window:
                signal_days.append({
                    'name': r['name'], 'gap': r['gap'], 'd7_as_l': r['d7_as_l'],
                    **s,
                })
            tag = ", ".join([f"L+{s['l_offset']}" for s in signals_in_window])
            print(f"  {r['name']:>12} Gap={r['gap']:>2}天 D-7=L+{r['d7_as_l']:>2} "
                  f"恐慌信号: {tag}")
        else:
            print(f"  {r['name']:>12} Gap={r['gap']:>2}天 D-7=L+{r['d7_as_l']:>2} 无恐慌信号")

    print(f"\n  共 {len(signal_days)} 只转债触发恐慌信号")

    # ============================================================
    # 第三部分：策略回测 — 恐慌次日买入
    # ============================================================
    print()
    print("=" * 100)
    print("三、策略回测：恐慌次日买入")
    print("  条件：L+25~L+50区间，某日跌幅>2% + 量比<1.5")
    print("  买入：信号次日（L+offset+1）")
    print("  卖出：持有3/5/7/10天")
    print("=" * 100)

    results = []
    for s in signal_days:
        name = s['name']
        r = next((x for x in all_data if x['name'] == name), None)
        if not r:
            continue

        buy_l = s['l_offset'] + 1
        buy_idx = r['lc_idx'] + buy_l
        prices = r['prices']
        sd = r['sorted_dates']

        if buy_idx < 0 or buy_idx >= len(sd):
            continue

        returns = {}
        for hold in [3, 5, 7, 10]:
            ret = get_return(prices, sd, buy_idx, hold)
            if ret is not None:
                returns[hold] = ret

        results.append({
            'name': s['name'], 'gap': s['gap'], 'd7_as_l': s['d7_as_l'],
            'signal_l': s['l_offset'], 'signal_chg': s['chg'], 'signal_vr': s['vol_ratio'],
            'buy_l': buy_l,
            'returns': returns,
        })

    print(f"\n  {'债券':>12} {'Gap':>5} {'信号L+':>7} {'信号跌幅':>8} {'信号量比':>7} "
          f"{'买入L+':>7} {'3天':>8} {'5天':>8} {'7天':>8} {'10天':>9}")
    print("  " + "-" * 95)

    for res in results:
        r3 = res['returns'].get(3); r5 = res['returns'].get(5)
        r7 = res['returns'].get(7); r10 = res['returns'].get(10)
        def f(v): return f'{v:+.2f}%' if v is not None else 'N/A'
        buy_l_str = f"L+{res['buy_l']}"
        print(f"  {res['name']:>12} {res['gap']:>5} {sig_l_str:>7} "
              f"{res['signal_chg']:>+7.1f}% {res['signal_vr']:>6.2f} "
              f"{buy_l_str:>7} {f(r3):>8} {f(r5):>8} {f(r7):>8} {f(r10):>9}")

    # Stats
    print()
    print("  --- 恐慌信号统计 ---")
    print(f"  触发: {len(results)}/{len(all_data)} ({len(results)/max(len(all_data),1)*100:.0f}%)")

    if results:
        for hold in [3, 5, 7, 10]:
            vals = [e['returns'][hold] for e in results if hold in e['returns']]
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                print(f"    持有{hold}天: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}({win/len(vals)*100:.0f}%), "
                      f"最佳{max(vals):+.2f}%, 最差{min(vals):+.2f}%")

    # ============================================================
    # 第四部分：逐日收益曲线（恐慌组）
    # ============================================================
    print()
    print("=" * 100)
    print("四、恐慌组逐日收益曲线 (买入后持有1-15天)")
    print("=" * 100)

    if results:
        print()
        for res in results:
            r = next((x for x in all_data if x['name'] == res['name']), None)
            if not r:
                continue
            buy_idx = r['lc_idx'] + res['buy_l']
            sd = r['sorted_dates']
            prices = r['prices']

            if buy_idx < 0 or buy_idx >= len(sd):
                continue

            buy_price = prices[sd[buy_idx]]['close']
            daily_ret = {}
            best_h = 0
            best_r = 0
            for h in range(1, 16):
                sell_idx = buy_idx + h
                if sell_idx < len(sd) and sd[sell_idx] <= today:
                    sell_price = prices[sd[sell_idx]]['close']
                    ret = round(((sell_price - buy_price) / buy_price) * 100, 2)
                    daily_ret[h] = ret
                    if ret > best_r:
                        best_r = ret
                        best_h = h

            line = f"  {res['name']:>12} Gap={res['gap']:>2} 信号L+{res['signal_l']:>2}"
            for h in range(1, 16):
                v = daily_ret.get(h)
                if v is not None:
                    marker = "★" if h == best_h else " "
                    line += f"  H+{h:2d}={v:>+5.1f}%{marker}"
                else:
                    line += f"  H+{h:2d}=N/A "
            line += f"  最佳L+{best_h}"
            print(line)

        # Aggregate stats
        print()
        print("  各持有期统计:")
        for h in range(1, 11):
            vals = []
            for res in results:
                r = next((x for x in all_data if x['name'] == res['name']), None)
                if not r:
                    continue
                buy_idx = r['lc_idx'] + res['buy_l']
                sd = r['sorted_dates']
                prices = r['prices']
                if buy_idx < 0 or buy_idx >= len(sd):
                    continue
                buy_price = prices[sd[buy_idx]]['close']
                sell_idx = buy_idx + h
                if sell_idx < len(sd) and sd[sell_idx] <= today:
                    sell_price = prices[sd[sell_idx]]['close']
                    ret = round(((sell_price - buy_price) / buy_price) * 100, 2)
                    vals.append(ret)
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                print(f"    H+{h:2d}天: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}({win/len(vals)*100:.0f}%), "
                      f"最佳{max(vals):+.2f}%, 最差{min(vals):+.2f}%")

    # ============================================================
    # 第五部分：实盘策略定义
    # ============================================================
    print()
    print("=" * 100)
    print("五、实盘策略 — 基于上市委通过日的恐慌买入")
    print("=" * 100)

    # Analyze: where do signals actually cluster?
    print()
    print("  信号位置分布:")
    if results:
        offsets = [r['signal_l'] for r in results]
        print(f"    最早: L+{min(offsets)}, 最晚: L+{max(offsets)}")
        print(f"    中位: L+{sorted(offsets)[len(offsets)//2]}")

    # Show the full window for analysis
    print()
    print("  逐日涨跌幅热力图（L+20到L+55）:")
    print(f"  {'L+':>4}", end="")
    for off in range(20, 56):
        print(f"  {off:2d}", end="")
    print()
    print("  " + "-" * 120)
    for r in all_data:
        line = f"  {r['name']:>12}"
        for off in range(20, 56):
            d = r['window'].get(off, {})
            if d:
                chg = d['chg']
                vr = d['vol_ratio']
                if chg < -3 and vr < 1.0:
                    marker = " 🔴"  # strong panic
                elif chg < -2 and vr < 1.5:
                    marker = " 🟠"  # panic
                elif chg < -1:
                    marker = f" {chg:>+4.1f}"
                elif chg > 3:
                    marker = f" 🟢{chg:4.0f}"
                else:
                    marker = f" {chg:>+5.1f}"
                line += marker
            else:
                line += "    ."
        print(line)

    print()
    print("  🔴=跌幅>3%+缩量, 🟠=跌幅>2%+量比<1.5, 🟢=涨>3%")
    print("  每个字符宽度=1天，横轴=L+20到L+55")

    # ============================================================
    # 第六部分：总结
    # ============================================================
    print()
    print("=" * 100)
    print("六、结论")
    print("=" * 100)

    print(f"""
  实盘策略：
  1. 监控条件：发现"上市委通过"公告 → 记录L-0日期
  2. 观察窗口：L+25 到 L+50（覆盖95%的注册前恐慌区间）
  3. 信号条件：某日跌幅>2% + 量比<1.5
  4. 买入时机：信号次日（L+offset+1）
  5. 卖出时机：持有4-6天（参考之前D-6买入的回测结果）
  6. 风控：超过8天未达目标 → 考虑止损

  关键问题：
  - 恐慌信号是否在L坐标系中聚集？（见上方热力图）
  - 如果信号分散在L+25到L+50各处，说明恐慌不是由"注册日前7天"触发
    而是由其他因素触发，策略需要调整
""")


if __name__ == '__main__':
    main()
