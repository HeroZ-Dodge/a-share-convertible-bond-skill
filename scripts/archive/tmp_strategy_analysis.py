#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心策略挖掘：不依赖注册日锚点，用可观测信号做交易决策

核心问题：恐慌信号太频繁（14只中有105个），怎么区分有效的和无效的？
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

    # Collect data
    all_data = []
    for v in valid:
        prices = cache.get_kline_as_dict(v['code'], days=240)
        if not prices:
            continue
        sd = sorted(prices.keys())
        lc_idx = find_idx(sd, v['lc_date'])
        reg_idx = find_idx(sd, v['reg_date'])

        # Baseline vol
        baseline_vol = []
        for i in range(lc_idx + 5, lc_idx + 15):
            if 0 <= i < len(sd):
                baseline_vol.append(prices[sd[i]]['volume'])
        baseline_avg = sum(baseline_vol) / len(baseline_vol) if baseline_vol else 1

        daily = {}
        for offset in range(1, 61):
            idx = lc_idx + offset
            if idx < 0 or idx >= len(sd) or sd[idx] > today:
                continue
            p = prices[sd[idx]]
            chg = compute_change(prices, sd, idx)
            vol_ratio = p['volume'] / baseline_avg if baseline_avg > 0 else 1
            daily[offset] = {'date': sd[idx], 'close': p['close'], 'chg': chg,
                             'volume': p['volume'], 'vol_ratio': vol_ratio}

        all_data.append({
            'name': v['name'], 'code': v['code'],
            'lc_date': v['lc_date'], 'reg_date': v['reg_date'],
            'gap': v['gap'], 'lc_idx': lc_idx, 'reg_idx': reg_idx,
            'daily': daily, 'prices': prices, 'sorted_dates': sd,
            'baseline_avg': baseline_avg,
        })

    # ============================================================
    # 假设：恐慌信号的有效性取决于3个维度
    #
    # 1. 位置：是否在上市委通过后足够久？（L+20之前太早，L+25+更接近注册）
    # 2. 前置涨幅：从L-0到恐慌日涨了多少？（涨了50%后恐慌 vs 还没涨就恐慌）
    # 3. 后续确认：恐慌次日是否修复？连续几天涨？
    # ============================================================

    # Find all panic signals (A signals)
    print("=" * 100)
    print("一、恐慌信号 + 次日修复验证")
    print("=" * 100)

    signals = []
    for r in all_data:
        daily = r['daily']
        # Find panic signals starting from L+15
        for offset in range(15, 56):
            d = daily.get(offset, {})
            if not d:
                continue
            if d['chg'] < -2 and d['vol_ratio'] < 1.5:
                # This is a panic signal
                # Check: cumulative return from L+1 to this point
                l1 = daily.get(1, {})
                if not l1:
                    continue
                cum_ret = ((d['close'] - l1['close']) / l1['close']) * 100

                # Check next day recovery
                n1 = daily.get(offset + 1, {})
                n2 = daily.get(offset + 2, {})
                n3 = daily.get(offset + 3, {})
                n5 = daily.get(offset + 5, {})

                next_chg = n1['chg'] if n1 else None

                # V-recovery: next day positive
                v_recovery = next_chg is not None and next_chg > 0

                # Double positive: next 2 days both positive
                dp = False
                if n1 and n2:
                    dp = n1.get('chg', 0) > 0 and n2.get('chg', 0) > 0

                signals.append({
                    'name': r['name'], 'gap': r['gap'],
                    'offset': offset,
                    'chg': d['chg'], 'vol_ratio': d['vol_ratio'],
                    'cum_ret': round(cum_ret, 1),
                    'next_chg': round(next_chg, 1) if next_chg is not None else None,
                    'v_recovery': v_recovery,
                    'double_positive': dp,
                    'n1': n1, 'n2': n2, 'n3': n3, 'n5': n5,
                })

    print(f"\n共 {len(signals)} 个恐慌信号 (L+15到L+55)")
    print(f"其中V型反转(次日修复): {sum(1 for s in signals if s['v_recovery'])} 个")
    print(f"其中连续2天涨: {sum(1 for s in signals if s['double_positive'])} 个")
    print()

    # ============================================================
    # 策略1：恐慌 + V型确认（次日涨>0）
    # ============================================================
    v_signals = [s for s in signals if s['v_recovery']]
    print("=" * 100)
    print("策略1: 恐慌 + V型确认")
    print("  条件: 跌幅>2%+量比<1.5 + 次日涨>0")
    print("  买入: 信号次日")
    print("=" * 100)

    print(f"\n  触发: {len(v_signals)}/{len(signals)} ({len(v_signals)/max(len(signals),1)*100:.0f}%)")

    if v_signals:
        # Stats for each holding period
        for label, skey in [("次日收盘", "n1"), ("+2天", "n2"), ("+3天", "n3"), ("+5天", "n5")]:
            vals = []
            for s in v_signals:
                sd_obj = s.get(skey)
                if sd_obj and sd_obj.get('close'):
                    buy_price = sd_obj['close']
                    # Return from buy to +N days after
                    ret_key = {
                        "次日收盘": 1, "+2天": 2, "+3天": 3, "+5天": 5
                    }[label]
                    sell_off = s['offset'] + ret_key
                    sell = s['n5' if ret_key <= 5 else 'n5']  # simplified
                    # Actually compute from the original data
                    r = next((x for x in all_data if x['name'] == s['name']), None)
                    if r:
                        daily = r['daily']
                        buy_idx_off = s['offset'] + 1  # buy next day
                        sell_idx_off = buy_idx_off + (ret_key - 1)
                        buy_d = daily.get(buy_idx_off, {})
                        sell_d = daily.get(sell_idx_off, {})
                        if buy_d and sell_d:
                            ret = ((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100
                            vals.append(round(ret, 2))

            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                print(f"    持有{label}: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}({win/len(vals)*100:.0f}%), "
                      f"最佳{max(vals):+.2f}%, 最差{min(vals):+.2f}%")

    # ============================================================
    # 策略2：恐慌 + 连续2天修复
    # ============================================================
    dp_signals = [s for s in signals if s['double_positive']]
    print()
    print("=" * 100)
    print("策略2: 恐慌 + 连续2天修复确认")
    print("  条件: 跌幅>2%+量比<1.5 + 次日连续2天涨>0")
    print("  买入: 第2天修复当日")
    print("=" * 100)

    print(f"\n  触发: {len(dp_signals)}/{len(signals)} ({len(dp_signals)/max(len(signals),1)*100:.0f}%)")

    if dp_signals:
        for label, days_after_buy in [("持有3天", 3), ("持有5天", 5), ("持有7天", 7)]:
            vals = []
            for s in dp_signals:
                r = next((x for x in all_data if x['name'] == s['name']), None)
                if r:
                    daily = r['daily']
                    buy_off = s['offset'] + 2  # buy on 2nd positive day
                    sell_off = buy_off + days_after_buy
                    buy_d = daily.get(buy_off, {})
                    sell_d = daily.get(sell_off, {})
                    if buy_d and sell_d and buy_d['close'] > 0:
                        ret = ((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100
                        vals.append(round(ret, 2))

            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                print(f"    {label}: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}({win/len(vals)*100:.0f}%), "
                      f"最佳{max(vals):+.2f}%, 最差{min(vals):+.2f}%")

    # ============================================================
    # 策略3：累计涨幅过滤 — 等涨够再买
    # ============================================================
    print()
    print("=" * 100)
    print("策略3: 累计涨幅过滤")
    print("  条件: 恐慌信号 + 从L+0到信号日累计涨幅<20%（没大涨过）")
    print("  假设：还没大涨过的恐慌，后面还有空间")
    print("=" * 100)

    filtered = [s for s in signals if s['cum_ret'] < 20]
    print(f"\n  触发: {len(filtered)}/{len(signals)} ({len(filtered)/max(len(signals),1)*100:.0f}%)")
    for label, days_after in [("持有3天", 3), ("持有5天", 5), ("持有7天", 7)]:
        vals = []
        for s in filtered:
            r = next((x for x in all_data if x['name'] == s['name']), None)
            if r:
                daily = r['daily']
                buy_off = s['offset'] + 1
                sell_off = buy_off + days_after
                buy_d = daily.get(buy_off, {})
                sell_d = daily.get(sell_off, {})
                if buy_d and sell_d and buy_d['close'] > 0:
                    ret = ((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100
                    vals.append(round(ret, 2))
        if vals:
            avg = sum(vals) / len(vals)
            win = sum(1 for v in vals if v > 0)
            print(f"    持有{label}: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}({win/len(vals)*100:.0f}%), "
                  f"最佳{max(vals):+.2f}%, 最差{min(vals):+.2f}%")

    # ============================================================
    # 策略4：恐慌 + 累计涨幅低 + V确认（组合）
    # ============================================================
    print()
    print("=" * 100)
    print("策略4: 组合条件（低涨幅 + 恐慌 + V确认）")
    print("  条件: 累计涨幅<15% + 恐慌 + 次日涨>0")
    print("=" * 100)

    combo = [s for s in v_signals if s['cum_ret'] < 15]
    print(f"\n  触发: {len(combo)}/{len(signals)} ({len(combo)/max(len(signals),1)*100:.0f}%)")

    if combo:
        for label, days_after in [("持有3天", 3), ("持有5天", 5), ("持有7天", 7), ("持有10天", 10)]:
            vals = []
            for s in combo:
                r = next((x for x in all_data if x['name'] == s['name']), None)
                if r:
                    daily = r['daily']
                    buy_off = s['offset'] + 1
                    sell_off = buy_off + days_after
                    buy_d = daily.get(buy_off, {})
                    sell_d = daily.get(sell_off, {})
                    if buy_d and sell_d and buy_d['close'] > 0:
                        ret = ((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100
                        vals.append(round(ret, 2))
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                print(f"    持有{label}: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}({win/len(vals)*100:.0f}%), "
                      f"最佳{max(vals):+.2f}%, 最差{min(vals):+.2f}%")

        # Print details
        print()
        for s in combo:
            n1_chg = s['next_chg'] or 0
            r = next((x for x in all_data if x['name'] == s['name']), None)
            if r:
                daily = r['daily']
                n2 = daily.get(s['offset'] + 2, {})
                n3 = daily.get(s['offset'] + 3, {})
                n5 = daily.get(s['offset'] + 5, {})
                n7 = daily.get(s['offset'] + 7, {})
                def f(v): return f"{v['chg']:>+5.1f}%" if v and v.get('chg') is not None else "N/A"
                print(f"    {s['name']:>12} L+{s['offset']:>2} 恐慌{s['chg']:>+5.1f}% "
                      f"累计{s['cum_ret']:+.0f}% | "
                      f"次日{f(n1_chg):>5} L+{s['offset']+2}:{f(n2)} L+{s['offset']+3}:{f(n3)} "
                      f"L+{s['offset']+5}:{f(n5)} L+{s['offset']+7}:{f(n7)}")

    # ============================================================
    # 策略5：只在前半段扫描（L+15到L+30）
    # ============================================================
    print()
    print("=" * 100)
    print("策略5: 缩小窗口 L+15~L+30 + V确认")
    print("  假设：上市委通过后30天内是最佳信号窗口")
    print("=" * 100)

    early = [s for s in v_signals if 15 <= s['offset'] <= 30]
    print(f"\n  触发: {len(early)}/{len(signals)} ({len(early)/max(len(signals),1)*100:.0f}%)")

    if early:
        for label, days_after in [("持有3天", 3), ("持有5天", 5), ("持有7天", 7)]:
            vals = []
            for s in early:
                r = next((x for x in all_data if x['name'] == s['name']), None)
                if r:
                    daily = r['daily']
                    buy_off = s['offset'] + 1
                    sell_off = buy_off + days_after
                    buy_d = daily.get(buy_off, {})
                    sell_d = daily.get(sell_off, {})
                    if buy_d and sell_d and buy_d['close'] > 0:
                        ret = ((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100
                        vals.append(round(ret, 2))
            if vals:
                avg = sum(vals) / len(vals)
                win = sum(1 for v in vals if v > 0)
                print(f"    持有{label}: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}({win/len(vals)*100:.0f}%), "
                      f"最佳{max(vals):+.2f}%, 最差{min(vals):+.2f}%")

    # ============================================================
    # 策略6：纯"连续涨"信号（不依赖恐慌）
    # ============================================================
    print()
    print("=" * 100)
    print("策略6: 连续2天涨（不依赖恐慌信号）")
    print("  条件: L+15~L+50区间，连续2天涨>0")
    print("  买入: 第2天")
    print("=" * 100)

    consecutive_signals = []
    for r in all_data:
        daily = r['daily']
        for offset in range(15, 51):
            d1 = daily.get(offset, {})
            d2 = daily.get(offset + 1, {})
            if d1 and d2 and d1.get('chg', 0) > 0 and d2.get('chg', 0) > 0:
                consecutive_signals.append({
                    'name': r['name'], 'gap': r['gap'],
                    'offset': offset + 1,  # buy on 2nd day
                })

    print(f"\n  触发: {len(consecutive_signals)} 次")

    for label, days_after in [("持有3天", 3), ("持有5天", 5), ("持有7天", 7)]:
        vals = []
        for s in consecutive_signals:
            r = next((x for x in all_data if x['name'] == s['name']), None)
            if r:
                daily = r['daily']
                buy_off = s['offset']
                sell_off = buy_off + days_after
                buy_d = daily.get(buy_off, {})
                sell_d = daily.get(sell_off, {})
                if buy_d and sell_d and buy_d['close'] > 0:
                    ret = ((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100
                    vals.append(round(ret, 2))
        if vals:
            avg = sum(vals) / len(vals)
            win = sum(1 for v in vals if v > 0)
            print(f"    持有{label}: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}({win/len(vals)*100:.0f}%), "
                  f"最佳{max(vals):+.2f}%, 最差{min(vals):+.2f}%")

    # ============================================================
    # 策略7：放量突破
    # ============================================================
    print()
    print("=" * 100)
    print("策略7: 放量突破（量比>1.5 + 涨>2%）")
    print("=" * 100)

    breakout_signals = []
    for r in all_data:
        daily = r['daily']
        for offset in range(15, 51):
            d = daily.get(offset, {})
            if d and d.get('chg', 0) > 2 and d.get('vol_ratio', 1) > 1.5:
                breakout_signals.append({
                    'name': r['name'], 'gap': r['gap'],
                    'offset': offset,
                })

    print(f"\n  触发: {len(breakout_signals)} 次")

    for label, days_after in [("持有3天", 3), ("持有5天", 5), ("持有7天", 7)]:
        vals = []
        for s in breakout_signals:
            r = next((x for x in all_data if x['name'] == s['name']), None)
            if r:
                daily = r['daily']
                buy_off = s['offset'] + 1  # buy next day
                sell_off = buy_off + days_after
                buy_d = daily.get(buy_off, {})
                sell_d = daily.get(sell_off, {})
                if buy_d and sell_d and buy_d['close'] > 0:
                    ret = ((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100
                    vals.append(round(ret, 2))
        if vals:
            avg = sum(vals) / len(vals)
            win = sum(1 for v in vals if v > 0)
            print(f"    持有{label}: 平均{avg:+.2f}%, 胜率{win}/{len(vals)}({win/len(vals)*100:.0f}%), "
                  f"最佳{max(vals):+.2f}%, 最差{min(vals):+.2f}%")

    # ============================================================
    # 汇总
    # ============================================================
    print()
    print("=" * 100)
    print("策略对比汇总")
    print("=" * 100)

    # Print a comparison table
    print()

    # Strategy 1: Panic + V recovery
    print("  【S1】恐慌+V确认, L+15+, 买次日")
    for days in [3, 5, 7]:
        vals = []
        for s in v_signals:
            r = next((x for x in all_data if x['name'] == s['name']), None)
            if r:
                daily = r['daily']
                buy_off = s['offset'] + 1
                sell_off = buy_off + days
                buy_d = daily.get(buy_off, {})
                sell_d = daily.get(sell_off, {})
                if buy_d and sell_d and buy_d['close'] > 0:
                    vals.append(round(((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100, 2))
        if vals:
            avg = sum(vals)/len(vals)
            win = sum(1 for v in vals if v > 0)
            print(f"    H+{days}: {avg:+.2f}%, {win}/{len(vals)}")

    # Strategy 4: combo
    print("  【S4】低涨幅+恐慌+V确认, 买次日")
    for days in [3, 5, 7]:
        vals = []
        for s in combo:
            r = next((x for x in all_data if x['name'] == s['name']), None)
            if r:
                daily = r['daily']
                buy_off = s['offset'] + 1
                sell_off = buy_off + days
                buy_d = daily.get(buy_off, {})
                sell_d = daily.get(sell_off, {})
                if buy_d and sell_d and buy_d['close'] > 0:
                    vals.append(round(((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100, 2))
        if vals:
            avg = sum(vals)/len(vals)
            win = sum(1 for v in vals if v > 0)
            print(f"    H+{days}: {avg:+.2f}%, {win}/{len(vals)}")

    # Strategy 6: consecutive
    print("  【S6】连续2天涨, L+15+, 买第2天")
    for days in [3, 5, 7]:
        vals = []
        for s in consecutive_signals:
            r = next((x for x in all_data if x['name'] == s['name']), None)
            if r:
                daily = r['daily']
                buy_off = s['offset']
                sell_off = buy_off + days
                buy_d = daily.get(buy_off, {})
                sell_d = daily.get(sell_off, {})
                if buy_d and sell_d and buy_d['close'] > 0:
                    vals.append(round(((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100, 2))
        if vals:
            avg = sum(vals)/len(vals)
            win = sum(1 for v in vals if v > 0)
            print(f"    H+{days}: {avg:+.2f}%, {win}/{len(vals)}")

    # Strategy 7: breakout
    print("  【S7】放量突破, L+15+, 买次日")
    for days in [3, 5, 7]:
        vals = []
        for s in breakout_signals:
            r = next((x for x in all_data if x['name'] == s['name']), None)
            if r:
                daily = r['daily']
                buy_off = s['offset'] + 1
                sell_off = buy_off + days
                buy_d = daily.get(buy_off, {})
                sell_d = daily.get(sell_off, {})
                if buy_d and sell_d and buy_d['close'] > 0:
                    vals.append(round(((sell_d['close'] - buy_d['close']) / buy_d['close']) * 100, 2))
        if vals:
            avg = sum(vals)/len(vals)
            win = sum(1 for v in vals if v > 0)
            print(f"    H+{days}: {avg:+.2f}%, {win}/{len(vals)}")


if __name__ == '__main__':
    main()
