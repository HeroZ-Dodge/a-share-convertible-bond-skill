#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册日前5-7天信息泄漏信号挖掘

假设：注册日前5-7天的高胜率(+4.27%, 75%)来自消息泄漏
需要挖掘以下先行信号：

1. 融资融券 — 融资余额异常增加（杠杆资金提前建仓）
2. 大宗交易 — 机构/内部人之间转让筹码
3. 股东户数变化 — 筹码集中
4. 机构调研 — 调研密集度变化
5. 北向资金 — 外资提前布局
"""

import sys
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.backtest_cache import BacktestCache


def parse_progress_dates(progress_full: str) -> dict:
    if not progress_full:
        return {}
    progress_full = progress_full.replace('<br>', '\n')
    dates = {}
    pattern = r'(\d{4}-\d{2}-\d{2})\s+([^\n]+)'
    for match in re.finditer(pattern, progress_full):
        dates[match.group(2).strip()] = match.group(1)
    return dates


def get_trading_day_index(sorted_dates: list, target_date: str) -> int:
    """找到 target_date 对应的索引（最接近且不早于）"""
    for i, d in enumerate(sorted_dates):
        if d >= target_date:
            return i
    return len(sorted_dates) - 1


def main():
    cache = BacktestCache()
    bonds = cache.get_latest_jisilu_data()
    if not bonds:
        cache.save_jisilu_snapshot()
        bonds = cache.get_latest_jisilu_data()

    today = datetime.now().strftime('%Y-%m-%d')

    # 筛选有"同意注册"日期的债
    valid = []
    for b in bonds:
        if not b.get('stock_code'):
            continue
        dates = parse_progress_dates(b.get('progress_full', ''))
        if '同意注册' in dates:
            valid.append(b)

    print(f"找到 {len(valid)} 只有"同意注册"日期的转债\n")

    # ========== 1. 融资融券分析 ==========
    print("=" * 80)
    print("一、融资融券分析 — 注册日前后融资余额变化")
    print("=" * 80)

    margin_data = []
    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册')
        if not reg_date:
            continue

        # 获取注册日前60天到注册日的融资融券数据
        margin = cache.get_margin_data(sc, days=90)
        if not margin:
            continue

        # 计算注册日前30-10天和前10-0天的融资余额
        reg_idx = get_trading_day_index(sorted(m[0] for m in margin), reg_date)

        early_window = []  # D-30 ~ D-10
        pre_window = []    # D-10 ~ D-7
        risk_window = []   # D-7 ~ D-0
        post_window = []   # D+0 ~ D+10

        for md in margin:
            d = md['date']
            if d < reg_date:
                # 计算距离注册日的交易日数
                d_idx = get_trading_day_index(sorted(m[0] for m in margin), d)
                diff = reg_idx - d_idx
                if -30 <= diff <= -10:
                    early_window.append(md)
                elif -10 <= diff <= -7:
                    pre_window.append(md)
                elif -7 <= diff <= 0:
                    risk_window.append(md)
                elif 0 <= diff <= 10:
                    post_window.append(md)

        margin_data.append({
            'stock_code': sc,
            'bond_name': b.get('bond_name') or b.get('stock_name') or '?',
            'reg_date': reg_date,
            'early': early_window,
            'pre': pre_window,
            'risk': risk_window,
            'post': post_window,
        })

    # 打印汇总
    print(f"\n{'债券':>12} {'代码':>8} {'注册日':>12} {'D-30~-10':>10} {'D-7~-0':>10} {'D+0~+10':>10} {'变化趋势'}")
    print("-" * 85)

    for md in margin_data:
        name = md['bond_name'][:10]
        sc = md['stock_code']
        reg = md['reg_date']

        def avg_margin(window):
            if not window:
                return None
            return sum(m['margin_balance'] for m in window) / len(window)

        early_avg = avg_margin(md['early'])
        pre_avg = avg_margin(md['pre'])
        risk_avg = avg_margin(md['risk'])
        post_avg = avg_margin(md['post'])

        def fmt(v):
            if v is None:
                return 'N/A'
            if v >= 1e8:
                return f'{v/1e8:.1f}亿'
            return f'{v/1e4:.0f}万'

        trend = ''
        if early_avg and risk_avg:
            if risk_avg > early_avg * 1.1:
                trend = '↑ 融资增加'
            elif risk_avg < early_avg * 0.9:
                trend = '↓ 融资减少'
            else:
                trend = '→ 持平'

        print(f"{name:>12} {sc:>8} {reg:>12} {fmt(early_avg):>10} {fmt(risk_avg):>10} {fmt(post_avg):>10} {trend}")

    # 统计：是否有显著变化
    print()
    print("--- 融资融券统计 ---")
    all_early = []
    all_risk = []
    for md in margin_data:
        ea = avg_margin_helper(md['early'])
        ra = avg_margin_helper(md['risk'])
        if ea and ea > 0 and ra and ra > 0:
            ratio = ra / ea
            all_early.append(ea)
            all_risk.append(ra)
            print(f"  {md['bond_name'][:8]}: D-30~-10平均 {ea/1e8:.2f}亿 → D-7~0平均 {ra/1e8:.2f}亿 (比率 {ratio:.2f})")

    if all_early and all_risk:
        avg_early_ratio = sum(all_risk) / sum(all_early)
        print(f"\n  总体比率：D-7~0 / D-30~-10 = {avg_early_ratio:.2f}")
        if avg_early_ratio > 1.05:
            print("  → 注册前融资余额上升，可能有信息泄漏")
        elif avg_early_ratio < 0.95:
            print("  → 注册前融资余额下降，无明显泄漏信号")
        else:
            print("  → 融资余额变化不大，无明显泄漏信号")

    # ========== 2. 大宗交易分析 ==========
    print()
    print("=" * 80)
    print("二、大宗交易分析 — 注册日前30天内是否有大宗交易")
    print("=" * 80)

    block_trades = []
    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册')
        if not reg_date:
            continue

        try:
            bt = cache.get_block_trade_data(sc, days=90)
        except Exception as e:
            print(f"  获取大宗交易失败 {sc}: {e}")
            continue

        # 筛选注册前30天内的交易
        reg_dt = datetime.strptime(reg_date, '%Y-%m-%d')
        pre30_dt = reg_dt - timedelta(days=30)
        pre30_date = pre30_dt.strftime('%Y-%m-%d')

        pre30_trades = [t for t in bt if pre30_date <= t['date'] < reg_date]
        post_trades = [t for t in bt if t['date'] >= reg_date]

        block_trades.append({
            'stock_code': sc,
            'bond_name': b.get('bond_name') or b.get('stock_name') or '?',
            'reg_date': reg_date,
            'pre30_count': len(pre30_trades),
            'pre30_amount': sum(t['deal_amount'] for t in pre30_trades),
            'pre30_trades': pre30_trades,
        })

    print(f"\n{'债券':>12} {'代码':>8} {'注册日':>12} {'D-30~0':>6} {'D-30~0金额':>12} {'信号'}")
    print("-" * 65)

    for bt in block_trades:
        name = bt['bond_name'][:10]
        amount_str = f"{bt['pre30_amount']/1e8:.2f}亿" if bt['pre30_amount'] > 0 else '无'
        signal = ''
        if bt['pre30_count'] > 0 and bt['pre30_amount'] > 0:
            if bt['pre30_amount'] > 1e8:
                signal = '⚠️ 大额交易'
            else:
                signal = '有交易'
        else:
            signal = '无'
        print(f"{name:>12} {bt['stock_code']:>8} {bt['reg_date']:>12} "
              f"{bt['pre30_count']:>6} {amount_str:>12} {signal}")

    # ========== 3. 机构调研分析 ==========
    print()
    print("=" * 80)
    print("三、机构调研分析 — 注册日前60天调研密集度")
    print("=" * 80)

    research_data = []
    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册')
        if not reg_date:
            continue

        try:
            res = cache.get_institutional_research(sc, days=180)
        except Exception as e:
            continue

        if not res:
            research_data.append({
                'stock_code': sc,
                'bond_name': b.get('bond_name') or b.get('stock_name') or '?',
                'reg_date': reg_date,
                'pre60_count': 0, 'pre60_total': 0, 'pre30_count': 0,
                'baseline_count': 0,
            })
            continue

        reg_dt = datetime.strptime(reg_date, '%Y-%m-%d')
        pre60_dt = reg_dt - timedelta(days=60)
        pre30_dt = reg_dt - timedelta(days=30)
        pre120_dt = reg_dt - timedelta(days=120)

        pre60 = [r for r in res if pre60_dt.strftime('%Y-%m-%d') <= r['date'] < reg_date]
        pre30 = [r for r in res if pre30_dt.strftime('%Y-%m-%d') <= r['date'] < reg_date]
        baseline = [r for r in res if pre120_dt.strftime('%Y-%m-%d') <= r['date'] < pre60_dt.strftime('%Y-%m-%d')]

        research_data.append({
            'stock_code': sc,
            'bond_name': b.get('bond_name') or b.get('stock_name') or '?',
            'reg_date': reg_date,
            'pre60_count': len(pre60),
            'pre60_total': sum(r['num'] for r in pre60),
            'pre30_count': len(pre30),
            'baseline_count': len(baseline),
            'pre60_details': pre60,
        })

    print(f"\n{'债券':>12} {'代码':>8} {'注册日':>12} {'D-60~0':>6} {'D-60~0机构':>8} {'D-60~-30':>8} {'信号'}")
    print("-" * 75)

    for rd in research_data:
        name = rd['bond_name'][:10]
        baseline_str = f"D-120~-60: {rd['baseline_count']}" if rd['baseline_count'] else '无基线数据'
        signal = ''
        if rd['pre60_count'] > rd['baseline_count'] * 2:
            signal = '⚠️ 密集调研'
        elif rd['pre60_count'] > 0:
            signal = '有调研'

        print(f"{name:>12} {rd['stock_code']:>8} {rd['reg_date']:>12} "
              f"{rd['pre60_count']:>6} {rd['pre60_total']:>8} "
              f"{baseline_str:>14} {signal}")

    # ========== 4. 股东户数分析 ==========
    print()
    print("=" * 80)
    print("四、股东户数变化 — 注册日前是否有筹码集中")
    print("=" * 80)

    holder_data = []
    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册')
        if not reg_date:
            continue

        try:
            hc = cache.get_holder_count(sc)
        except Exception as e:
            continue

        if not hc:
            continue

        holder_data.append({
            'stock_code': sc,
            'bond_name': b.get('bond_name') or b.get('stock_name') or '?',
            'reg_date': reg_date,
            'records': hc,
        })

    for hd in holder_data:
        name = hd['bond_name'][:10]
        recs = hd['records']
        if not recs:
            continue
        print(f"\n  {name} ({hd['stock_code']})  注册日: {hd['reg_date']}")
        for r in recs[:5]:
            change_str = f"{r['holder_num_ratio']:+.2f}%" if r['holder_num_ratio'] else 'N/A'
            interval_str = f"{r['interval_change_pct']:+.2f}%" if r['interval_change_pct'] else 'N/A'
            print(f"    {r['end_date']}: {r['holder_num']:,}户 ({change_str})  "
                  f"区间涨跌 {interval_str}")

    # ========== 5. 北向资金分析 ==========
    print()
    print("=" * 80)
    print("五、北向资金持股 — 注册日前是否有外资提前布局")
    print("=" * 80)

    north_data = []
    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册')
        if not reg_date:
            continue

        try:
            nb = cache.get_northbound_data(sc, days=90)
        except Exception:
            continue

        if not nb:
            continue

        reg_idx = get_trading_day_index(sorted(n['trade_date'] for n in nb), reg_date)

        early_window = []  # D-60 ~ D-30
        pre_window = []    # D-30 ~ D-7
        risk_window = []   # D-7 ~ D+0

        for nd in nb:
            d = nd['trade_date']
            if d < reg_date:
                d_idx = get_trading_day_index(sorted(n['trade_date'] for n in nb), d)
                diff = reg_idx - d_idx
                if 30 <= diff <= 60:
                    early_window.append(nd)
                elif 7 <= diff <= 30:
                    pre_window.append(nd)
                elif 0 <= diff <= 7:
                    risk_window.append(nd)

        def avg_ratio(window):
            if not window:
                return None
            vals = [n['shares_ratio'] for n in window if n['shares_ratio']]
            return sum(vals) / len(vals) if vals else None

        north_data.append({
            'stock_code': sc,
            'bond_name': b.get('bond_name') or b.get('stock_name') or '?',
            'reg_date': reg_date,
            'early_ratio': avg_ratio(early_window),
            'pre_ratio': avg_ratio(pre_window),
            'risk_ratio': avg_ratio(risk_window),
        })

    print(f"\n{'债券':>12} {'代码':>8} {'D-60~-30':>10} {'D-30~-7':>10} {'D-7~0':>10} {'变化'}")
    print("-" * 70)

    for nd in north_data:
        name = nd['bond_name'][:10]

        def fmt_ratio(v):
            if v is None:
                return 'N/A'
            return f'{v:.2f}%'

        change = ''
        if nd['early_ratio'] and nd['risk_ratio']:
            if nd['risk_ratio'] > nd['early_ratio'] * 1.05:
                change = '↑ 外资增持'
            elif nd['risk_ratio'] < nd['early_ratio'] * 0.95:
                change = '↓ 外资减持'
            else:
                change = '→ 持平'

        print(f"{name:>12} {nd['stock_code']:>8} "
              f"{fmt_ratio(nd['early_ratio']):>10} {fmt_ratio(nd['pre_ratio']):>10} "
              f"{fmt_ratio(nd['risk_ratio']):>10} {change}")


def avg_margin_helper(window):
    if not window:
        return None
    vals = [m['margin_balance'] for m in window if m['margin_balance'] and m['margin_balance'] > 0]
    if not vals:
        return None
    return sum(vals) / len(vals)


if __name__ == '__main__':
    main()
