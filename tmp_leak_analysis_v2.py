#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册日前5-7天信息泄漏信号挖掘

假设：注册日前5-7天股价上涨(+4.27%, 75%胜率)来自消息泄漏
通过多维数据验证：

1. 融资融券 — 融资余额异常增加 = 杠杆资金提前建仓
2. 大宗交易 — 注册日前30天的大宗交易 = 筹码转让
3. 机构调研 — 注册前60天的密集调研 = 信息泄漏渠道
4. 股东户数 — 注册前的筹码集中 = 内部人吸筹
5. 北向资金 — 注册前外资增持 = 外资获知信息
"""

import sys
import os
import re
from datetime import datetime, timedelta

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


def find_date_index(sorted_dates: list, target_date: str) -> int:
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

    valid = []
    for b in bonds:
        if not b.get('stock_code'):
            continue
        dates = parse_progress_dates(b.get('progress_full', ''))
        if '同意注册' in dates:
            valid.append(b)

    print(f"找到 {len(valid)} 只有"同意注册"日期的转债\n")

    # ========== 1. 融资融券 ==========
    print("=" * 80)
    print("一、融资融券 — 注册日前融资余额变化")
    print("=" * 80)
    print("  逻辑：如果有人提前知道注册消息，可能通过融资加杠杆买入")
    print()

    margin_results = []
    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        data = cache.fetch_and_save_margin_trading(sc, days=120)
        if not data:
            continue

        # 按注册日分窗口
        trading_dates = sorted([d['date'] for d in data])
        reg_idx = find_date_index(trading_dates, reg_date)

        def avg_in_window(days_before_start, days_before_end):
            vals = []
            for d in data:
                d_idx = find_date_index(trading_dates, d['date'])
                diff = reg_idx - d_idx
                if days_before_end <= diff <= days_before_start:
                    mb = d['margin_balance']
                    if mb and mb > 0:
                        vals.append(mb)
            return sum(vals) / len(vals) if vals else None

        baseline = avg_in_window(40, 20)  # D-40 ~ D-20（基线期）
        pre10 = avg_in_window(19, 10)      # D-19 ~ D-10
        risk = avg_in_window(9, 0)          # D-9 ~ D-0（风险窗口）

        margin_results.append({
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:10],
            'code': sc,
            'reg': reg_date,
            'baseline': baseline,
            'pre10': pre10,
            'risk': risk,
            'risk_vs_base': (risk / baseline) if (risk and baseline and baseline > 0) else None,
        })

    print(f"  {'债券':>10} {'代码':>8} {'D-40~-20':>10} {'D-19~-10':>10} {'D-9~0':>10} {'比率':>6} {'信号'}")
    print("  " + "-" * 75)

    total_ratio = 0
    count_ratio = 0
    for r in margin_results:
        def fmt(v):
            if v is None or v == 0: return 'N/A'
            if v >= 1e8: return f'{v/1e8:.2f}亿'
            return f'{v/1e4:.0f}万'

        ratio_str = ''
        signal = ''
        if r['risk_vs_base']:
            ratio_str = f'{r["risk_vs_base"]:.2f}x'
            total_ratio += r['risk_vs_base']
            count_ratio += 1
            if r['risk_vs_base'] > 1.1:
                signal = '↑ 融资增加'
            elif r['risk_vs_base'] < 0.9:
                signal = '↓ 融资减少'
            else:
                signal = '→ 持平'

        print(f"  {r['name']:>10} {r['code']:>8} {fmt(r['baseline']):>10} "
              f"{fmt(r['pre10']):>10} {fmt(r['risk']):>10} {ratio_str:>6} {signal}")

    if count_ratio > 0:
        avg_ratio = total_ratio / count_ratio
        print()
        print(f"  平均比率（D-9~0 / D-40~-20）：{avg_ratio:.3f}x")
        if avg_ratio > 1.05:
            print("  结论：注册前融资余额上升，存在加杠杆行为，可能暗示信息泄漏")
        elif avg_ratio < 0.95:
            print("  结论：注册前融资余额下降，无泄漏信号")
        else:
            print("  结论：融资余额基本持平，无明显泄漏信号")

    # ========== 2. 大宗交易 ==========
    print()
    print("=" * 80)
    print("二、大宗交易 — 注册日前30天是否有大宗交易")
    print("=" * 80)
    print("  逻辑：大宗交易可能是内部人转让筹码给知情人")
    print()

    block_total = 0
    block_pre30_count = 0
    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        data = cache.fetch_and_save_block_trade(sc, days=120)
        if not data:
            continue

        try:
            reg_dt = datetime.strptime(reg_date, '%Y-%m-%d')
            pre30_dt = reg_dt - timedelta(days=30)
            pre30_str = pre30_dt.strftime('%Y-%m-%d')
        except:
            continue

        pre30 = [t for t in data if pre30_str <= t['trade_date'] < reg_date]
        post = [t for t in data if t['trade_date'] >= reg_date]

        amount_str = f"{sum(t['deal_amount'] for t in pre30)/1e8:.2f}亿" if pre30 else '0元'
        signal = ''
        if pre30:
            total_amt = sum(t['deal_amount'] for t in pre30)
            block_total += total_amt
            block_pre30_count += 1
            if total_amt > 5e7:
                signal = '⚠️ 大额!'
            else:
                signal = '有'

        print(f"  {(b.get('bond_name') or '?')[:10]:>10} {sc:>8} "
              f"注册前30天: {len(pre30)}笔/{amount_str} {signal}")
        if pre30:
            for t in pre30[:3]:
                buyer = (t.get('buyer_name', '') or '')[:20]
                premium = t.get('premium_ratio', 0)
                print(f"             {t['trade_date']} {t['deal_volume']:,}股 "
                      f"溢价{premium:+.1f}% 买方: {buyer}")

    if block_pre30_count > 0:
        print(f"\n  {len(valid)} 只债中有 {block_pre30_count} 只在注册前30天有大宗交易 "
              f"（占比 {block_pre30_count/len(valid)*100:.0f}%）")
        print(f"  总金额: {block_total/1e8:.2f}亿元")

    # ========== 3. 机构调研 ==========
    print()
    print("=" * 80)
    print("三、机构调研 — 注册前60天 vs 注册前120~60天（基线）")
    print("=" * 80)
    print("  逻辑：密集调研可能是信息泄漏渠道")
    print()

    survey_results = []
    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        data = cache.fetch_and_save_institutional_research(sc, days=200)

        try:
            reg_dt = datetime.strptime(reg_date, '%Y-%m-%d')
            pre60_dt = reg_dt - timedelta(days=60)
            pre120_dt = reg_dt - timedelta(days=120)
        except:
            continue

        pre60 = [r for r in data if pre60_dt.strftime('%Y-%m-%d') <= r['research_date'] < reg_date]
        baseline = [r for r in data if pre120_dt.strftime('%Y-%m-%d') <= r['research_date'] < pre60_dt.strftime('%Y-%m-%d')]

        pre60_institutions = sum(r['num'] for r in pre60)
        baseline_institutions = sum(r['num'] for r in baseline)

        signal = ''
        if len(pre60) > len(baseline) * 2:
            signal = '⚠️ 密集!'
        elif len(pre60) > 0:
            signal = '有'

        survey_results.append({
            'name': (b.get('bond_name') or '?')[:10],
            'code': sc,
            'pre60': len(pre60), 'pre60_inst': pre60_institutions,
            'baseline': len(baseline), 'baseline_inst': baseline_institutions,
            'details': pre60[:3],
        })

        print(f"  {(b.get('bond_name') or '?')[:10]:>10} {sc:>8} "
              f"D-60~0: {len(pre60)}次/{pre60_institutions}家机构  "
              f"基线(D-120~-60): {len(baseline)}次/{baseline_institutions}家机构  {signal}")
        if pre60:
            for r in pre60[:2]:
                print(f"             {r['research_date']} {r['survey_type'] or '调研'} "
                      f"{r['num']}家机构")

    total_pre60 = sum(s['pre60'] for s in survey_results)
    total_baseline = sum(s['baseline'] for s in survey_results)
    print()
    print(f"  总计：注册前60天 {total_pre60}次调研，基线期 {total_baseline}次调研")
    if total_baseline > 0:
        ratio = total_pre60 / total_baseline
        print(f"  比率: {ratio:.1f}x（>2x 说明注册前明显密集）")
    if total_pre60 > 0 and total_baseline == 0:
        print(f"  注：基线期无调研记录，注册前60天有 {total_pre60} 次调研")

    # ========== 4. 股东户数 ==========
    print()
    print("=" * 80)
    print("四、股东户数变化 — 筹码是否集中")
    print("=" * 80)
    print("  逻辑：股东减少 = 筹码集中到少数人手中")
    print()

    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        data = cache.fetch_and_save_holder_count(sc)
        if not data:
            continue

        print(f"  {(b.get('bond_name') or '?')[:10]:>10} {sc:>8}  注册日: {reg_date}")
        for r in data[:3]:
            change = f"{r['holder_num_ratio']:+.2f}%" if r['holder_num_ratio'] else 'N/A'
            interval = f"{r['interval_change_pct']:+.2f}%" if r['interval_change_pct'] else 'N/A'
            print(f"    {r['end_date']}: {r['holder_num']:,}户 ({change})  区间涨跌 {interval}")
            if r.get('investigators'):
                print(f"      调研: {r['investigators'][:50]}")

    # ========== 5. 北向资金 ==========
    print()
    print("=" * 80)
    print("五、北向资金持股 — 注册前是否有外资提前布局")
    print("=" * 80)
    print("  逻辑：外资可能通过特殊渠道提前获知注册信息")
    print()

    north_results = []
    for b in valid:
        sc = b['stock_code']
        dates = parse_progress_dates(b.get('progress_full', ''))
        reg_date = dates.get('同意注册', '')
        if not reg_date:
            continue

        data = cache.fetch_and_save_northbound(sc, days=120)
        if not data:
            continue

        trading_dates = sorted([d['trade_date'] for d in data])
        reg_idx = find_date_index(trading_dates, reg_date)

        def avg_ratio(days_before_start, days_before_end):
            vals = []
            for d in data:
                d_idx = find_date_index(trading_dates, d['trade_date'])
                diff = reg_idx - d_idx
                if days_before_end <= diff <= days_before_start:
                    sr = d['shares_ratio']
                    if sr and sr > 0:
                        vals.append(sr)
            return sum(vals) / len(vals) if vals else None

        baseline = avg_ratio(40, 20)
        risk = avg_ratio(9, 0)

        ratio = (risk / baseline) if (risk and baseline and baseline > 0) else None
        signal = ''
        if ratio:
            if ratio > 1.05:
                signal = '↑ 增持'
            elif ratio < 0.95:
                signal = '↓ 减持'
            else:
                signal = '→ 持平'

        north_results.append({
            'name': (b.get('bond_name') or '?')[:10],
            'code': sc,
            'baseline': baseline, 'risk': risk, 'ratio': ratio,
        })

        def fmt_r(v):
            if v is None: return 'N/A'
            return f'{v:.2f}%'

        print(f"  {(b.get('bond_name') or '?')[:10]:>10} {sc:>8} "
              f"D-40~-20: {fmt_r(baseline)} D-9~0: {fmt_r(risk)} "
              f"比率: {ratio:.2f}x  {signal}")

    if north_results:
        valid_ratios = [r['ratio'] for r in north_results if r['ratio']]
        if valid_ratios:
            avg_nr = sum(valid_ratios) / len(valid_ratios)
            print()
            print(f"  平均增持比率: {avg_nr:.3f}x")
            if avg_nr > 1.02:
                print("  结论：外资在注册前增持，可能存在信息泄漏")
            elif avg_nr < 0.98:
                print("  结论：外资在注册前减持，无泄漏信号")
            else:
                print("  结论：外资持股基本持平，无明显泄漏信号")

    # ========== 汇总 ==========
    print()
    print("=" * 80)
    print("六、综合判断")
    print("=" * 80)
    print()
    print("  数据维度汇总（需要更多信息的维度已标注）：")
    print()
    if margin_results:
        valid_margins = [r for r in margin_results if r['risk_vs_base']]
        if valid_margins:
            avg_mr = sum(r['risk_vs_base'] for r in valid_margins) / len(valid_margins)
            print(f"  [融资融券] 平均比率: {avg_mr:.3f}x  "
                  f"{'(有泄漏信号)' if avg_mr > 1.05 else '(无泄漏信号)' if avg_mr < 0.95 else '(持平)'}")

    if block_pre30_count > 0:
        print(f"  [大宗交易] {block_pre30_count}/{len(valid)} 只在注册前有大宗交易 "
              f"({block_pre30_count/len(valid)*100:.0f}%)")

    if survey_results:
        print(f"  [机构调研] 注册前60天 {total_pre60}次 vs 基线 {total_baseline}次")

    if north_results:
        valid_north = [r['ratio'] for r in north_results if r['ratio']]
        if valid_north:
            avg_nr = sum(valid_north) / len(valid_north)
            print(f"  [北向资金] 平均比率: {avg_nr:.3f}x  "
                  f"{'(外资增持)' if avg_nr > 1.02 else '(外资减持)' if avg_nr < 0.98 else '(持平)'}")

    print()


if __name__ == '__main__':
    main()
