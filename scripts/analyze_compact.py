#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可转债抢权配债分析 - 紧凑输出模式

适合在聊天界面直接显示完整报告，不截断。

Usage:
    python3 analyze_compact.py              # 2026 年全部
    python3 analyze_compact.py --limit 5    # 最近 5 只
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.data_source import EastmoneyAPI, SinaFinanceAPI
from lib.bond_calculator import BondCalculator
from datetime import datetime


def main():
    import argparse
    parser = argparse.ArgumentParser(description='可转债分析 - 紧凑输出')
    parser.add_argument('--limit', '-n', type=int, default=0, help='分析数量 (0=全部)')
    parser.add_argument('--year', type=int, default=0, help='年份 (0=2026)')
    parser.add_argument('--month', type=int, default=0, help='月份 (0=全年)')
    args = parser.parse_args()
    
    # 默认 2026 年
    if args.year == 0:
        args.year = 2026
    
    calc = BondCalculator(target_bonds=10, bond_price=100)
    
    # 获取数据
    em = EastmoneyAPI()
    sina = SinaFinanceAPI()
    
    fetch_limit = args.limit if args.limit > 0 else 200
    all_bonds = em.fetch_listed_bonds(limit=fetch_limit)
    
    # 筛选年份/月份
    bonds = []
    for b in all_bonds:
        listing_date = b.get('listing_date', '')
        if not listing_date or not listing_date.startswith(str(args.year)):
            continue
        if args.month > 0:
            parts = listing_date.split('-')
            if len(parts) >= 2 and int(parts[1]) != args.month:
                continue
        bonds.append(b)
    
    if args.limit > 0:
        bonds = bonds[:args.limit]
    
    # 计算需要的日期范围
    min_date = None
    for b in bonds:
        record_date = b.get('record_date', '')
        if record_date and (min_date is None or record_date < min_date):
            min_date = record_date
    
    if min_date:
        days_needed = min((datetime.now() - datetime.strptime(min_date, '%Y-%m-%d')).days + 15, 365)
    else:
        days_needed = 90
    
    stock_prices = {}
    for b in bonds:
        if b.get('stock_code') and b['stock_code'] not in stock_prices:
            prices = sina.fetch_history(b['stock_code'], days=days_needed)
            if prices:
                stock_prices[b['stock_code']] = prices
    
    for b in bonds:
        b['listing_close'] = em.fetch_bond_listing_price(b['bond_code'], b['listing_date'])
    
    if not bonds:
        print("无数据")
        return
    
    # 计算分析
    analyses = [calc.analyze_quequan_profit(b, stock_prices) for b in bonds]
    
    # 输出紧凑报告
    if args.month > 0:
        print(f"## 📊 {args.year}年{args.month}月可转债抢权配债分析 ({len(analyses)}只)")
    else:
        print(f"## 📊 {args.year}年可转债抢权配债分析 ({len(analyses)}只)")
    print(f"*{datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")
    
    # 股价走势
    print("### 📈 股价走势")
    print("| # | 名称 | T-1 | T+1 | 涨跌 |")
    print("|---|------|-----|-----|------|")
    for i, a in enumerate(analyses, 1):
        p = a.stock_prices
        if p['T-1'] > 0 and p['T+1'] > 0:
            change = (p['T+1'] - p['T-1']) / p['T-1'] * 100
            arrow = "↑" if change > 0 else "↓"
            print(f"| {i} | {a.bond_name[:6]} | {p['T-1']:.2f} | {p['T+1']:.2f} | {change:+.1f}% {arrow} |")
    print()
    
    # 完整盈亏 (T-1 策略)
    print("### 💰 T-1 买入盈亏")
    print("| # | 名称 | 配债成本 | 股票盈亏 | 配债收益 | 总盈亏 |")
    print("|---|------|----------|----------|----------|--------|")
    for i, a in enumerate(analyses, 1):
        if a.total_costs['T-1'] > 0:
            status = "✅" if a.total_profits['T-1'] > 0 else "❌"
            print(f"| {i} | {a.bond_name[:6]} | {a.bond_cost:,.0f}元 | {a.stock_profits['T-1']:+.0f}元 | {a.bond_profit:+.0f}元 | **{a.total_profits['T-1']:+.0f}元** {status} |")
    print()
    
    # 统计
    profitable = sum(1 for a in analyses if a.total_profits['T-1'] > 0)
    avg_profit = sum(a.total_profits['T-1'] for a in analyses) / len(analyses)
    best = max(analyses, key=lambda x: x.total_profits['T-1'])
    worst = min(analyses, key=lambda x: x.total_profits['T-1'])
    
    print("### 📊 统计")
    print(f"- **T-1 胜率**: {profitable}/{len(analyses)} ({profitable/len(analyses)*100:.0f}%)")
    print(f"- **平均收益**: {avg_profit:+.0f}元")
    print(f"- **最佳**: {best.bond_name} ({best.total_profits['T-1']:+.0f}元)")
    print(f"- **最差**: {worst.bond_name} ({worst.total_profits['T-1']:+.0f}元)")


if __name__ == '__main__':
    main()
