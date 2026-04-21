#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析"同意注册"后股价变化

从集思录获取可转债进度数据，提取"同意注册"日期，
分析同意注册后股价的变化趋势。

Usage:
    python3 analyze_registration_impact.py
    
    # 分析前 N 只
    python3 analyze_registration_impact.py --limit 10
    
    # 分析指定天数范围
    python3 analyze_registration_impact.py --days 30
    
    # 输出 JSON
    python3 analyze_registration_impact.py --format json
"""

import argparse
import sys
import os
from datetime import datetime, timedelta
import re

# 添加 lib 目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.data_source import JisiluAPI, SinaFinanceAPI


def parse_progress_dates(progress_full: str) -> dict:
    """
    解析进度字符串，提取各个节点的日期
    
    Args:
        progress_full: 完整进度字符串 (如 "2025-05-28 董事会预案\n2026-03-31 同意注册")
        
    Returns:
        字典：{节点名称：日期字符串}
    """
    if not progress_full:
        return {}
    
    # 替换 HTML 换行符和空格
    progress_full = progress_full.replace('<br>', '\n').replace('\n', '\n')
    
    dates = {}
    # 匹配 "YYYY-MM-DD 节点名称" 格式
    pattern = r'(\d{4}-\d{2}-\d{2})\s+([^\n]+)'
    
    for match in re.finditer(pattern, progress_full):
        date_str = match.group(1)
        event = match.group(2).strip()
        dates[event] = date_str
    
    return dates


def get_trading_days_after(start_date: str, days: int = 30) -> list:
    """
    获取起始日期后的交易日列表 (简化版，按自然日计算)
    
    Args:
        start_date: 起始日期 (YYYY-MM-DD)
        days: 天数
        
    Returns:
        日期列表
    """
    result = []
    current = datetime.strptime(start_date, '%Y-%m-%d')
    
    for i in range(1, days + 1):
        next_day = current + timedelta(days=i)
        # 跳过周末 (简化处理)
        if next_day.weekday() < 5:  # 周一到周五
            result.append(next_day.strftime('%Y-%m-%d'))
    
    return result


def analyze_stock_after_registration(stock_code: str, registration_date: str, days: int = 30) -> dict:
    """
    分析股票在同意注册后的股价变化
    
    Args:
        stock_code: 股票代码
        registration_date: 同意注册日期 (YYYY-MM-DD)
        days: 分析天数
        
    Returns:
        分析结果字典
    """
    sina = SinaFinanceAPI()
    
    # 获取股价数据 (同意注册日前 5 天到后 days 天)
    total_days = days + 10
    prices = sina.fetch_history(stock_code, days=total_days)
    
    if not prices:
        return None
    
    # 找到同意注册日附近的交易日
    sorted_dates = sorted(prices.keys())
    
    # 找到最接近 registration_date 的日期作为基准
    reg_date_obj = datetime.strptime(registration_date, '%Y-%m-%d')
    
    # 找到基准日 (同意注册日或之后第一个交易日)
    base_date = None
    base_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= registration_date:
            base_date = d
            base_idx = i
            break
    
    if not base_date or base_idx is None:
        return None
    
    base_price = prices[base_date]['close']
    
    # 计算同意注册后每天的涨跌幅
    changes = []
    for i in range(base_idx, min(base_idx + days + 1, len(sorted_dates))):
        date = sorted_dates[i]
        price = prices[date]['close']
        change_pct = ((price - base_price) / base_price) * 100 if base_price > 0 else 0
        
        changes.append({
            'date': date,
            'price': round(price, 2),
            'change_pct': round(change_pct, 2),
            'days_after': i - base_idx,
        })
    
    # 统计
    if len(changes) < 2:
        return None
    
    max_price = max(c['price'] for c in changes)
    min_price = min(c['price'] for c in changes)
    final_change = changes[-1]['change_pct'] if changes else 0
    
    return {
        'stock_code': stock_code,
        'registration_date': registration_date,
        'base_date': base_date,
        'base_price': round(base_price, 2),
        'days_analyzed': len(changes) - 1,
        'max_price': round(max_price, 2),
        'max_change_pct': round(((max_price - base_price) / base_price) * 100, 2),
        'min_price': round(min_price, 2),
        'min_change_pct': round(((min_price - base_price) / base_price) * 100, 2),
        'final_change_pct': round(final_change, 2),
        'daily_changes': changes,
    }


def fetch_and_analyze(limit: int = 20, days: int = 30) -> list:
    """
    获取数据并分析
    
    Args:
        limit: 分析转债数量
        days: 分析同意注册后多少天
        
    Returns:
        分析结果列表
    """
    print(f"正在从集思录获取待发转债数据...")
    jsl = JisiluAPI(timeout=30)
    bonds = jsl.fetch_pending_bonds(limit=limit * 2)  # 多获取一些，因为有些可能没有同意注册日期
    
    # 筛选有"同意注册"日期的转债
    bonds_with_registration = []
    for bond in bonds:
        progress_full = bond.get('progress_full', '')
        dates = parse_progress_dates(progress_full)
        
        if '同意注册' in dates:
            bond['registration_date'] = dates['同意注册']
            bond['progress_dates'] = dates
            bonds_with_registration.append(bond)
    
    print(f"找到 {len(bonds_with_registration)} 只有'同意注册'日期的转债")
    print(f"正在分析同意注册后的股价变化 (后 {days} 天)...")
    print()
    
    results = []
    for idx, bond in enumerate(bonds_with_registration[:limit], 1):
        stock_code = bond.get('stock_code', '')
        reg_date = bond.get('registration_date', '')
        
        if not stock_code or not reg_date:
            continue
        
        print(f"[{idx}/{len(bonds_with_registration[:limit])}] {bond['bond_name']} ({stock_code}) - 同意注册：{reg_date}", end="")
        
        analysis = analyze_stock_after_registration(stock_code, reg_date, days=days)
        
        if analysis:
            analysis['bond_name'] = bond['bond_name']
            analysis['bond_code'] = bond.get('bond_code', '')
            results.append(analysis)
            
            final = analysis['final_change_pct']
            max_pct = analysis['max_change_pct']
            min_pct = analysis['min_change_pct']
            
            if final > 0:
                print(f" ✓ 最终：{final:+.2f}% (最高：{max_pct:+.2f}%, 最低：{min_pct:+.2f}%)")
            else:
                print(f" ✓ 最终：{final:.2f}% (最高：{max_pct:+.2f}%, 最低：{min_pct:+.2f}%)")
        else:
            print(" ⚠️ 无数据")
    
    return results


def print_summary(results: list):
    """打印统计摘要"""
    if not results:
        print("\n⚠️  没有分析结果")
        return
    
    print("\n" + "=" * 70)
    print("📊 同意注册后股价变化统计摘要")
    print("=" * 70)
    
    # 统计涨跌
    up_count = sum(1 for r in results if r['final_change_pct'] > 0)
    down_count = sum(1 for r in results if r['final_change_pct'] <= 0)
    
    print(f"分析数量：{len(results)} 只")
    print(f"上涨：{up_count} 只 ({up_count/len(results)*100:.1f}%)")
    print(f"下跌：{down_count} 只 ({down_count/len(results)*100:.1f}%)")
    print()
    
    # 平均变化
    avg_change = sum(r['final_change_pct'] for r in results) / len(results)
    print(f"平均最终涨跌幅：{avg_change:+.2f}%")
    
    # 最大涨幅/跌幅
    max_up = max(results, key=lambda x: x['final_change_pct'])
    max_down = min(results, key=lambda x: x['final_change_pct'])
    
    print(f"最大涨幅：{max_up['bond_name']} ({max_up['final_change_pct']:+.2f}%)")
    print(f"最大跌幅：{max_down['bond_name']} ({max_down['final_change_pct']:+.2f}%)")
    print()
    
    # 波动统计
    avg_max = sum(r['max_change_pct'] for r in results) / len(results)
    avg_min = sum(r['min_change_pct'] for r in results) / len(results)
    
    print(f"平均最高涨幅：{avg_max:+.2f}%")
    print(f"平均最低跌幅：{avg_min:+.2f}%")
    print(f"平均波动幅度：{avg_max - avg_min:.2f}%")
    print("=" * 70)


def print_detailed_results(results: list):
    """打印详细结果"""
    print("\n" + "=" * 90)
    print("📋 详细数据")
    print("=" * 90)
    print(f"{'债券名称':<12} {'股票代码':<10} {'同意注册日':<12} {'基准价':<10} {'最终涨跌':<12} {'最高':<12} {'最低':<12}")
    print("-" * 90)
    
    for r in results:
        bond_name = (r.get('bond_name') or 'N/A')[:12]
        print(f"{bond_name:<12} {r['stock_code']:<10} {r['registration_date']:<12} "
              f"{r['base_price']:<10.2f} {r['final_change_pct']:>+11.2f}% "
              f"{r['max_change_pct']:>+11.2f}% {r['min_change_pct']:>+11.2f}%")
    
    print("=" * 90)


def main():
    parser = argparse.ArgumentParser(description='分析同意注册后股价变化')
    
    parser.add_argument('--limit', '-n', type=int, default=20, help='分析转债数量 (默认：20)')
    parser.add_argument('--days', '-d', type=int, default=30, help='分析同意注册后多少天 (默认：30)')
    parser.add_argument('--format', '-f', choices=['text', 'json'], default='text', help='输出格式')
    
    args = parser.parse_args()
    
    # 获取并分析数据
    results = fetch_and_analyze(limit=args.limit, days=args.days)
    
    if not results:
        print("\n⚠️  没有分析结果")
        sys.exit(1)
    
    # 输出
    if args.format == 'json':
        import json
        # 移除每日数据以减少输出
        output = []
        for r in results:
            r_copy = r.copy()
            r_copy.pop('daily_changes', None)
            output.append(r_copy)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_summary(results)
        print_detailed_results(results)


if __name__ == '__main__':
    main()
