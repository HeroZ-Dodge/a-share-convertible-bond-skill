#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册前5-7天信号挖掘 — 系统性数据分析

对14只转债，逐只提取注册日前后的多维数据，找信号规律
"""

import sys
import os
import re
from datetime import datetime, timedelta
import importlib.util

# Direct import to avoid __init__.py bug
sys.path.insert(0, '.')
spec = importlib.util.spec_from_file_location('backtest_cache', 'lib/backtest_cache.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

spec2 = importlib.util.spec_from_file_location('data_source', 'lib/data_source.py')
mod2 = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(mod2)


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


def main():
    cache = mod.BacktestCache()
    bonds = cache.get_latest_jisilu_data()
    em = mod2.EastmoneyAPI()

    today = datetime.now().strftime('%Y-%m-%d')

    # Collect valid bonds
    valid = []
    for b in bonds:
        if not b.get('stock_code'):
            continue
        dates = parse_progress_dates(b.get('progress_full', ''))
        if '同意注册' in dates:
            valid.append(b)

    # ========== PART 1: K线信号（价格 + 成交量） ==========
    print("=" * 100)
    print("一、K线信号 — D-10 到 D+2 的价格、成交量、涨跌幅")
    print("=" * 100)

    signal_records = []

    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        # Get K-line data
        prices = cache.get_kline_as_dict(sc, days=120)
        if not prices:
            print(f"  {sc}: 无K线数据")
            continue

        sorted_dates = sorted(prices.keys())
        reg_idx = find_idx(sorted_dates, reg_date)

        name = (b.get('bond_name') or b.get('stock_name') or '?')[:10]

        # Extract D-10 to D+2
        print(f"\n  {name:>10} ({sc})  注册: {reg_date}")
        print(f"  {'偏移':>6} {'日期':>12} {'收盘':>8} {'涨跌':>7} {'成交量':>12} {'量比':>6} {'信号'}")
        print("  " + "-" * 85)

        # Baseline volume: D-30 to D-20
        baseline_vol = []
        for i, d in enumerate(sorted_dates):
            offset = i - reg_idx
            if -30 <= offset <= -20:
                baseline_vol.append(prices[d]['volume'])
        baseline_avg = sum(baseline_vol) / len(baseline_vol) if baseline_vol else 1

        # Extract signal window
        record = {'name': name, 'code': sc, 'reg': reg_date}
        for i, d in enumerate(sorted_dates):
            offset = i - reg_idx
            if -10 <= offset <= 2:
                p = prices[d]
                vol_ratio = p['volume'] / baseline_avg if baseline_avg > 0 else 1
                chg = p.get('change_pct', 0)
                close = p['close']
                vol = p['volume']

                markers = []
                # Signal conditions
                if abs(chg) > 3:
                    markers.append(f'涨跌>{abs(chg):.0f}%')
                if vol_ratio > 1.5:
                    markers.append('放量')
                if vol_ratio < 0.5:
                    markers.append('缩量')

                # D-7~-5 window
                if -7 <= offset <= -5:
                    record[f'd{offset}'] = {'close': close, 'chg': chg, 'vol': vol, 'vol_ratio': vol_ratio, 'markers': markers}

                sig = ' '.join(markers) if markers else ''
                if -7 <= offset <= -5:
                    sig = f'[D{offset}窗口] ' + sig
                if offset == 0:
                    sig += ' [注册日]'

                print(f"  {offset:>6} {d:>12} {close:>8.2f} {chg:>7.2f}% {vol:>12.0f} {vol_ratio:>6.2f} {sig}")

        signal_records.append(record)

    # ========== PART 2: 主力资金流向日线 ==========
    print()
    print("=" * 100)
    print("二、主力资金流向 — D-10 到 D 的净流入")
    print("=" * 100)

    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        flows = cache.get_fund_flow(sc, days=120)
        if not flows:
            flows = cache.fetch_and_save_fund_flow(sc, days=120)
        if not flows:
            continue

        sorted_flows = sorted(flows, key=lambda x: x['date'])
        flow_dates = [f['date'] for f in sorted_flows]
        reg_idx = find_idx(flow_dates, reg_date)

        name = (b.get('bond_name') or b.get('stock_name') or '?')[:10]

        print(f"\n  {name:>10} ({sc})  注册: {reg_date}")
        print(f"  {'偏移':>6} {'日期':>12} {'主力净流入':>12} {'占比%':>8} {'超大单':>12} {'大单':>10} {'信号'}")
        print("  " + "-" * 90)

        for i, f in enumerate(sorted_flows):
            offset = i - reg_idx
            if -10 <= offset <= 0:
                main_in = f.get('main_net_inflow', 0)
                main_rate = f.get('main_net_inflow_rate', 0)
                super_lg = f.get('super_large_net_inflow', 0)
                large = f.get('large_net_inflow', 0)

                def fmt_amt(v):
                    if abs(v) >= 1e8:
                        return f'{v/1e8:.2f}亿'
                    return f'{v/1e4:.0f}万'

                sig = ''
                if main_in > 5e6:
                    sig = '[主力大幅净流入]'
                elif main_in < -5e6:
                    sig = '[主力大幅净流出]'
                if main_rate > 10:
                    sig += ' [净流入>10%]'
                elif main_rate < -10:
                    sig += ' [净流出>10%]'

                if -7 <= offset <= -5:
                    sig = f'[D{offset}窗口] ' + sig

                print(f"  {offset:>6} {f['date']:>12} {fmt_amt(main_in):>12} {main_rate:>7.1f}% "
                      f"{fmt_amt(super_lg):>12} {fmt_amt(large):>10} {sig}")

    # ========== PART 3: 融资融券 — 日级变化 ==========
    print()
    print("=" * 100)
    print("三、融资融券 — 注册日前融资余额日变化")
    print("=" * 100)

    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        margin = cache.fetch_and_save_margin_trading(sc, days=120)
        if not margin:
            continue

        sorted_margin = sorted(margin, key=lambda x: x['date'])
        margin_dates = [m['date'].split(' ')[0] for m in sorted_margin]
        reg_idx = find_idx(margin_dates, reg_date)

        name = (b.get('bond_name') or b.get('stock_name') or '?')[:10]

        print(f"\n  {name:>10} ({sc})  注册: {reg_date}")
        print(f"  {'偏移':>6} {'日期':>12} {'融资余额':>10} {'融资买入':>10} {'涨跌幅':>7} {'信号'}")
        print("  " + "-" * 80)

        for i, m in enumerate(sorted_margin):
            offset = i - reg_idx
            if -10 <= offset <= 0:
                date_str = m['date'].split(' ')[0]
                mb = m.get('margin_balance', 0)
                mba = m.get('margin_buy_amount', 0)
                chg = m.get('change_pct', 0)

                def fmt_amt(v):
                    if v >= 1e8:
                        return f'{v/1e8:.2f}亿'
                    return f'{v/1e4:.0f}万'

                sig = ''
                if mba > 3e7:
                    sig = '[大额融资买入]'

                if -7 <= offset <= -5:
                    sig = f'[D{offset}窗口] ' + sig

                print(f"  {offset:>6} {date_str:>12} {fmt_amt(mb):>10} {fmt_amt(mba):>10} {chg:>6.2f}% {sig}")

    # ========== PART 4: 综合信号表 ==========
    print()
    print("=" * 100)
    print("四、综合信号表 — D-7~-5 窗口内出现的所有信号")
    print("=" * 100)

    print(f"\n  {'债券':>10} {'D-7涨跌':>8} {'D-6涨跌':>8} {'D-5涨跌':>8} {'D-7量比':>7} {'D-6量比':>7} {'D-5量比':>7} {'窗口信号'}")
    print("  " + "-" * 95)

    for rec in signal_records:
        d7 = rec.get('d-7', {})
        d6 = rec.get('d-6', {})
        d5 = rec.get('d-5', {})

        chg7 = d7.get('chg', 0) if d7 else None
        chg6 = d6.get('chg', 0) if d6 else None
        chg5 = d5.get('chg', 0) if d5 else None
        vr7 = d7.get('vol_ratio', 0) if d7 else None
        vr6 = d6.get('vol_ratio', 0) if d6 else None
        vr5 = d5.get('vol_ratio', 0) if d5 else None

        def fmt_chg(v):
            if v is None: return 'N/A'
            return f'{v:+.1f}%'

        def fmt_vr(v):
            if v is None: return 'N/A'
            return f'{v:.2f}'

        # Collect all markers
        markers = []
        for offset, d in [(-7, d7), (-6, d6), (-5, d5)]:
            if d and 'markers' in d:
                for m in d['markers']:
                    markers.append(f'D{offset}{m}')

        signal_str = ' '.join(markers) if markers else '-'

        print(f"  {rec['name']:>10} {fmt_chg(chg7):>8} {fmt_chg(chg6):>8} {fmt_chg(chg5):>8} "
              f"{fmt_vr(vr7):>7} {fmt_vr(vr6):>7} {fmt_vr(vr5):>7}  {signal_str}")


if __name__ == '__main__':
    main()
