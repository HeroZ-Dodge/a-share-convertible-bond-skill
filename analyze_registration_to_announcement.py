#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析"同意注册"到"发行公告"期间的股价变化

根据集思录数据：
- 同意注册日期：从 progress_full 解析
- 发行公告日期：估算为申购日前 1-2 个交易日

Usage:
    python3 analyze_registration_to_announcement.py
    
    # 分析前 N 只
    python3 analyze_registration_to_announcement.py --limit 10
    
    # 输出 JSON
    python3 analyze_registration_to_announcement.py --format json
"""

import argparse
import sys
import os
from datetime import datetime, timedelta
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.data_source import JisiluAPI, EastmoneyAPI, SinaFinanceAPI


def parse_progress_dates(progress_full: str) -> dict:
    """解析进度字符串，提取各个节点的日期"""
    if not progress_full:
        return {}
    
    progress_full = progress_full.replace('<br>', '\n')
    dates = {}
    pattern = r'(\d{4}-\d{2}-\d{2})\s+([^\n]+)'
    
    for match in re.finditer(pattern, progress_full):
        date_str = match.group(1)
        event = match.group(2).strip()
        dates[event] = date_str
    
    return dates


def estimate_announcement_date(apply_date: str) -> str:
    """
    估算发行公告日期
    通常发行公告在申购日 (T 日) 前 1-2 个交易日发布
    这里简化为 T-2 日 (自然日，忽略周末)
    """
    if not apply_date:
        return None
    
    apply_dt = datetime.strptime(apply_date, '%Y-%m-%d')
    # 减去 2 个交易日 (简化：减 2 天，跳过周末)
    announce_dt = apply_dt - timedelta(days=2)
    
    # 如果是周末，继续往前推
    while announce_dt.weekday() >= 5:
        announce_dt -= timedelta(days=1)
    
    return announce_dt.strftime('%Y-%m-%d')


def get_stock_prices_in_range(stock_code: str, start_date: str, end_date: str) -> dict:
    """
    获取指定日期范围内的股价数据
    
    Args:
        stock_code: 股票代码
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        
    Returns:
        股价数据 {date: {open, close, high, low, volume}}
    """
    sina = SinaFinanceAPI()
    
    # 计算需要的天数 (从开始日期到今天)
    days_needed = (datetime.now() - datetime.strptime(start_date, '%Y-%m-%d')).days + 30
    days_needed = min(days_needed, 365)  # 最多 365 天
    
    prices = sina.fetch_history(stock_code, days=days_needed)
    
    # 筛选日期范围内的数据
    filtered = {}
    for date, data in prices.items():
        if start_date <= date <= end_date:
            filtered[date] = data
    
    return filtered


def analyze_period(stock_code: str, reg_date: str, announce_date: str) -> dict:
    """
    分析同意注册到发行公告期间的股价变化
    
    Args:
        stock_code: 股票代码
        reg_date: 同意注册日期
        announce_date: 发行公告日期 (估算)
        
    Returns:
        分析结果字典
    """
    # 获取股价数据 (同意注册日前 5 天到发行公告后 5 天)
    start_dt = datetime.strptime(reg_date, '%Y-%m-%d') - timedelta(days=5)
    end_dt = datetime.strptime(announce_date, '%Y-%m-%d') + timedelta(days=5)
    
    prices = get_stock_prices_in_range(
        stock_code,
        start_dt.strftime('%Y-%m-%d'),
        end_dt.strftime('%Y-%m-%d')
    )
    
    if not prices:
        return None
    
    sorted_dates = sorted(prices.keys())
    
    # 找到同意注册日和发行公告日附近的交易日
    reg_trading_day = None
    announce_trading_day = None
    
    for d in sorted_dates:
        if d >= reg_date and reg_trading_day is None:
            reg_trading_day = d
        if d >= announce_date and announce_trading_day is None:
            announce_trading_day = d
    
    if not reg_trading_day or not announce_trading_day:
        return None
    
    reg_price = prices[reg_trading_day]['close']
    announce_price = prices[announce_trading_day]['close']
    
    # 计算期间涨跌幅
    change_pct = ((announce_price - reg_price) / reg_price) * 100 if reg_price > 0 else 0
    
    # 找到期间最高/最低价
    period_prices = [prices[d]['close'] for d in sorted_dates if reg_trading_day <= d <= announce_trading_day]
    
    if not period_prices:
        return None
    
    max_price = max(period_prices)
    min_price = min(period_prices)
    
    # 计算交易日天数
    trading_days = len([d for d in sorted_dates if reg_trading_day <= d <= announce_trading_day])
    
    return {
        'stock_code': stock_code,
        'reg_date': reg_date,
        'reg_trading_day': reg_trading_day,
        'reg_price': round(reg_price, 2),
        'announce_date': announce_date,
        'announce_trading_day': announce_trading_day,
        'announce_price': round(announce_price, 2),
        'change_pct': round(change_pct, 2),
        'max_price': round(max_price, 2),
        'max_change_pct': round(((max_price - reg_price) / reg_price) * 100, 2),
        'min_price': round(min_price, 2),
        'min_change_pct': round(((min_price - reg_price) / reg_price) * 100, 2),
        'trading_days': trading_days,
    }


def fetch_and_analyze(limit: int = 30, use_eastmoney: bool = True) -> list:
    """
    获取数据并分析
    
    Args:
        limit: 分析转债数量
        use_eastmoney: 是否同时使用东方财富数据 (已上市转债)
        
    Returns:
        分析结果列表
    """
    all_bonds = []
    
    # 1. 从集思录获取待发转债
    print("正在从集思录获取待发转债数据...")
    jsl = JisiluAPI(timeout=30)
    jsl_bonds = jsl.fetch_pending_bonds(limit=limit * 2)
    
    for bond in jsl_bonds:
        progress_full = bond.get('progress_full', '')
        dates = parse_progress_dates(progress_full)
        
        if '同意注册' in dates and bond.get('apply_date'):
            bond['reg_date'] = dates['同意注册']
            bond['announce_date'] = estimate_announcement_date(bond['apply_date'])
            bond['source'] = 'jisilu'
            all_bonds.append(bond)
    
    # 2. 从东方财富获取已上市转债 (有更准确的发行日期)
    if use_eastmoney:
        print("正在从东方财富获取已上市转债数据...")
        em = EastmoneyAPI(timeout=30)
        em_bonds = em.fetch_listed_bonds(limit=limit * 2)
        
        for bond in em_bonds:
            # 东方财富的 record_date 是股权登记日
            # 发行公告日通常在股权登记日前 1-2 天
            if bond.get('record_date') and bond.get('listing_date'):
                # 用股权登记日作为同意注册后的参考点 (简化)
                # 实际上同意注册日在股权登记日之前
                record_date = bond['record_date']
                
                # 估算同意注册日 (股权登记日前约 2-4 周)
                record_dt = datetime.strptime(record_date, '%Y-%m-%d')
                reg_dt = record_dt - timedelta(days=20)  # 平均 20 天
                bond['reg_date'] = reg_dt.strftime('%Y-%m-%d')
                
                # 发行公告日 (申购日前 1-2 天，申购日约等于上市日前 2 周)
                listing_dt = datetime.strptime(bond['listing_date'], '%Y-%m-%d')
                announce_dt = listing_dt - timedelta(days=14)
                bond['announce_date'] = announce_dt.strftime('%Y-%m-%d')
                bond['source'] = 'eastmoney'
                all_bonds.append(bond)
    
    # 筛选有效数据
    valid_bonds = [b for b in all_bonds if b.get('reg_date') and b.get('announce_date') and b.get('stock_code')]
    
    # 去重 (同一转债可能出现在两个数据源)
    seen = set()
    unique_bonds = []
    for b in valid_bonds:
        key = f"{b['bond_code']}_{b['source']}"
        if key not in seen:
            seen.add(key)
            unique_bonds.append(b)
    
    print(f"共找到 {len(unique_bonds)} 只有效转债")
    print(f"正在分析同意注册 → 发行公告期间的股价变化...")
    print()
    
    results = []
    for idx, bond in enumerate(valid_bonds[:limit], 1):
        stock_code = bond.get('stock_code', '')
        bond_name = bond.get('bond_name') or 'N/A'
        reg_date = bond.get('reg_date', '')
        announce_date = bond.get('announce_date', '')
        
        if not stock_code or not reg_date or not announce_date:
            continue
        
        # 确保 announce_date 在 reg_date 之后
        if announce_date < reg_date:
            print(f"[{idx}/{len(valid_bonds[:limit])}] {bond_name} - ⚠️ 公告日早于注册日，跳过")
            continue
        
        print(f"[{idx}/{len(valid_bonds[:limit])}] {bond_name} ({stock_code})", end="")
        print(f" 同意注册:{reg_date} → 公告:{announce_date}", end="")
        
        analysis = analyze_period(stock_code, reg_date, announce_date)
        
        if analysis:
            analysis['bond_name'] = bond_name
            analysis['bond_code'] = bond.get('bond_code', '')
            results.append(analysis)
            
            change = analysis['change_pct']
            days = analysis['trading_days']
            if change > 0:
                print(f" ✓ +{change:.2f}% ({days} 交易日)")
            else:
                print(f" ✓ {change:.2f}% ({days} 交易日)")
        else:
            print(" ⚠️ 无股价数据")
    
    return results


def print_summary(results: list):
    """打印统计摘要"""
    if not results:
        print("\n⚠️  没有分析结果")
        return
    
    print("\n" + "=" * 80)
    print("📊 同意注册 → 发行公告期间股价变化统计")
    print("=" * 80)
    
    # 统计涨跌
    up_count = sum(1 for r in results if r['change_pct'] > 0)
    down_count = sum(1 for r in results if r['change_pct'] <= 0)
    
    print(f"分析数量：{len(results)} 只")
    print(f"上涨：{up_count} 只 ({up_count/len(results)*100:.1f}%)")
    print(f"下跌：{down_count} 只 ({down_count/len(results)*100:.1f}%)")
    print()
    
    # 平均变化
    avg_change = sum(r['change_pct'] for r in results) / len(results)
    print(f"平均涨跌幅：{avg_change:+.2f}%")
    
    # 平均交易日天数
    avg_days = sum(r['trading_days'] for r in results) / len(results)
    print(f"平均时间跨度：{avg_days:.1f} 交易日")
    
    # 年化收益率 (简化)
    if avg_days > 0:
        annualized = (avg_change / avg_days) * 252  # 252 个交易日/年
        print(f"年化收益率：{annualized:+.2f}%")
    
    # 最大涨幅/跌幅
    max_up = max(results, key=lambda x: x['change_pct'])
    max_down = min(results, key=lambda x: x['change_pct'])
    
    print(f"\n最大涨幅：{max_up['bond_name']} ({max_up['change_pct']:+.2f}%, {max_up['trading_days']} 天)")
    print(f"最大跌幅：{max_down['bond_name']} ({max_down['change_pct']:+.2f}%, {max_down['trading_days']} 天)")
    print()
    
    # 波动统计
    avg_max = sum(r['max_change_pct'] for r in results) / len(results)
    avg_min = sum(r['min_change_pct'] for r in results) / len(results)
    
    print(f"平均最高涨幅：{avg_max:+.2f}%")
    print(f"平均最低跌幅：{avg_min:+.2f}%")
    print(f"平均波动幅度：{avg_max - avg_min:.2f}%")
    print("=" * 80)


def print_detailed_results(results: list):
    """打印详细结果"""
    print("\n" + "=" * 110)
    print("📋 详细数据")
    print("=" * 110)
    print(f"{'债券名称':<12} {'股票代码':<10} {'同意注册':<12} {'公告日':<12} {'注册价':<10} {'公告价':<10} {'涨跌':<10} {'天数':<6}")
    print("-" * 110)
    
    for r in results:
        bond_name = (r.get('bond_name') or 'N/A')[:12]
        print(f"{bond_name:<12} {r['stock_code']:<10} {r['reg_date']:<12} {r['announce_date']:<12} "
              f"{r['reg_price']:<10.2f} {r['announce_price']:<10.2f} {r['change_pct']:>+9.2f}% {r['trading_days']:<6}")
    
    print("=" * 110)


def main():
    parser = argparse.ArgumentParser(description='分析同意注册到发行公告期间的股价变化')
    
    parser.add_argument('--limit', '-n', type=int, default=30, help='分析转债数量 (默认：30)')
    parser.add_argument('--format', '-f', choices=['text', 'json'], default='text', help='输出格式')
    
    args = parser.parse_args()
    
    results = fetch_and_analyze(limit=args.limit, use_eastmoney=True)
    
    if not results:
        print("\n⚠️  没有分析结果")
        sys.exit(1)
    
    if args.format == 'json':
        import json
        output = []
        for r in results:
            r_copy = r.copy()
            output.append(r_copy)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_summary(results)
        print_detailed_results(results)


if __name__ == '__main__':
    main()
