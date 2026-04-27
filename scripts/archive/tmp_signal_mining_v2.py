#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册前5-7天信号挖掘 — 系统性数据分析

对14只转债，逐只提取注册日前后所有维度数据，找信号规律
"""

import sys
import os
import re
import sqlite3
import json
from datetime import datetime, timedelta

sys.path.insert(0, '.')

# Bypass __init__.py to avoid monitor_db bug
def get_cache():
    import importlib.util
    spec = importlib.util.spec_from_file_location('backtest_cache', 'lib/backtest_cache.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.BacktestCache()

def get_api():
    import importlib.util
    spec = importlib.util.spec_from_file_location('data_source', 'lib/data_source.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.EastmoneyAPI()


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


def compute_change_pct(prices_dict, sorted_dates, i):
    """计算日涨跌幅"""
    if i <= 0:
        return 0
    prev = prices_dict[sorted_dates[i-1]]['close']
    curr = prices_dict[sorted_dates[i]]['close']
    if prev > 0:
        return ((curr - prev) / prev) * 100
    return 0


def main():
    cache = get_cache()
    em = get_api()
    bonds = cache.get_latest_jisilu_data()
    today = datetime.now().strftime('%Y-%m-%d')

    # Collect valid bonds
    valid = []
    for b in bonds:
        if not b.get('stock_code'):
            continue
        dates = parse_progress_dates(b.get('progress_full', ''))
        if '同意注册' in dates:
            valid.append(b)

    # ========== 第一步：逐只提取K线数据 ==========
    print("=" * 100)
    print("一、K线数据 — D-10 到 D+2 的价格、涨跌幅、成交量")
    print("=" * 100)

    all_records = []

    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        # Get K-line data from cache
        prices = cache.get_kline_as_dict(sc, days=120)
        if not prices:
            print(f"  {sc}: 无K线数据，跳过")
            continue

        sorted_dates = sorted(prices.keys())
        reg_idx = find_idx(sorted_dates, reg_date)

        # Baseline volume: D-30 to D-20
        baseline_vol = []
        for i, d in enumerate(sorted_dates):
            offset = i - reg_idx
            if -30 <= offset <= -20:
                baseline_vol.append(prices[d]['volume'])
        baseline_avg = sum(baseline_vol) / len(baseline_vol) if baseline_vol else 1

        name = (b.get('bond_name') or b.get('stock_name') or '?')[:12]
        bond_record = {
            'name': name, 'code': sc, 'reg': reg_date,
            'baseline_vol': baseline_avg,
            'window': {},
        }

        print(f"\n  {name} ({sc})  注册: {reg_date}  基线量: {baseline_avg/1e4:.0f}万")
        print(f"  {'偏移':>6} {'日期':>12} {'收盘':>8} {'涨跌%':>7} {'成交量':>12} {'量比':>6} {'信号'}")
        print("  " + "-" * 90)

        for i, d in enumerate(sorted_dates):
            offset = i - reg_idx
            if -10 <= offset <= 2:
                p = prices[d]
                chg = compute_change_pct(prices, sorted_dates, i)
                vol_ratio = p['volume'] / baseline_avg if baseline_avg > 0 else 1

                markers = []
                if chg > 3:
                    markers.append(f'涨{chg:.0f}%')
                elif chg < -3:
                    markers.append(f'跌{chg:.0f}%')
                if vol_ratio > 1.5:
                    markers.append('放量')
                if vol_ratio < 0.5:
                    markers.append('缩量')

                # Record window signals
                if -7 <= offset <= -5:
                    bond_record['window'][offset] = {
                        'close': p['close'], 'chg': chg,
                        'vol': p['volume'], 'vol_ratio': vol_ratio,
                        'markers': markers,
                    }

                sig = ' '.join(markers)
                if -7 <= offset <= -5:
                    sig = f'[D{offset}窗口] ' + sig
                if offset == 0:
                    sig += ' [注册日]'

                print(f"  {offset:>6} {d:>12} {p['close']:>8.2f} {chg:>7.2f}% "
                      f"{p['volume']:>12.0f} {vol_ratio:>6.2f} {sig}")

        all_records.append(bond_record)

    # ========== 第二步：主力资金流向 ==========
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

        # Bypass __init__ bug: directly call API
        flows = em.fetch_fund_flow(sc, days=120)
        if not flows:
            continue

        sorted_flows = sorted(flows, key=lambda x: x['date'])
        flow_dates = [f['date'] for f in sorted_flows]
        reg_idx = find_idx(flow_dates, reg_date)

        name = (b.get('bond_name') or b.get('stock_name') or '?')[:12]

        print(f"\n  {name} ({sc})  注册: {reg_date}")
        print(f"  {'偏移':>6} {'日期':>12} {'主力净流入':>12} {'占比%':>7} {'超大单':>10} {'大单':>10} {'信号'}")
        print("  " + "-" * 95)

        for i, f in enumerate(sorted_flows):
            offset = i - reg_idx
            if -10 <= offset <= 0:
                main_in = f.get('main_net_inflow', 0)
                main_rate = f.get('main_net_inflow_rate', 0)
                super_lg = f.get('超大单_net_inflow', 0)
                large = f.get('large_net_inflow', 0)

                def fmt_amt(v):
                    if abs(v) >= 1e8:
                        return f'{v/1e8:.2f}亿'
                    return f'{v/1e4:.0f}万'

                sig = ''
                if main_in > 1e7:
                    sig = '[主力大幅流入]'
                elif main_in < -1e7:
                    sig = '[主力大幅流出]'
                if abs(main_rate) > 10:
                    sig += f'[占比{main_rate:+.0f}%]'

                if -7 <= offset <= -5:
                    sig = f'[D{offset}窗口] ' + sig

                print(f"  {offset:>6} {f['date']:>12} {fmt_amt(main_in):>12} {main_rate:>6.1f}% "
                      f"{fmt_amt(super_lg):>10} {fmt_amt(large):>10} {sig}")

    # ========== 第三步：融资融券 ==========
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

        margin = em.fetch_margin_trading(sc, days=120)
        if not margin:
            continue

        sorted_margin = sorted(margin, key=lambda x: x['date'])
        margin_dates = [m['date'].split(' ')[0] for m in sorted_margin]
        reg_idx = find_idx(margin_dates, reg_date)

        name = (b.get('bond_name') or b.get('stock_name') or '?')[:12]

        print(f"\n  {name} ({sc})  注册: {reg_date}")
        print(f"  {'偏移':>6} {'日期':>12} {'融资余额':>10} {'融资买入':>10} {'涨跌%':>6} {'信号'}")
        print("  " + "-" * 85)

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

                print(f"  {offset:>6} {date_str:>12} {fmt_amt(mb):>10} {fmt_amt(mba):>10} "
                      f"{chg:>5.2f}% {sig}")

    # ========== 第四步：综合信号表 ==========
    print()
    print("=" * 100)
    print("四、综合信号表 — D-7~-5 窗口内出现的所有信号")
    print("=" * 100)

    print(f"\n  {'债券':>12} {'D-7涨跌':>8} {'D-6涨跌':>8} {'D-5涨跌':>8} "
          f"{'D-7量比':>7} {'D-6量比':>7} {'D-5量比':>7} "
          f"{'D-7信号':>10} {'D-6信号':>10} {'D-5信号':>10}")
    print("  " + "-" * 100)

    for rec in all_records:
        def get(offset):
            return rec['window'].get(offset, {})

        def fmt_chg(v):
            if v is None: return 'N/A'
            return f'{v:+.1f}%'

        def fmt_vr(v):
            if v is None: return 'N/A'
            return f'{v:.2f}'

        d7 = get(-7)
        d6 = get(-6)
        d5 = get(-5)

        sig7 = ' '.join(d7.get('markers', [])) if d7 else '-'
        sig6 = ' '.join(d6.get('markers', [])) if d6 else '-'
        sig5 = ' '.join(d5.get('markers', [])) if d5 else '-'

        print(f"  {rec['name']:>12} {fmt_chg(d7.get('chg')):>8} {fmt_chg(d6.get('chg')):>8} {fmt_chg(d5.get('chg')):>8} "
              f"{fmt_vr(d7.get('vol_ratio')):>7} {fmt_vr(d6.get('vol_ratio')):>7} {fmt_vr(d5.get('vol_ratio')):>7} "
              f"{sig7:>10} {sig6:>10} {sig5:>10}")


if __name__ == '__main__':
    main()
