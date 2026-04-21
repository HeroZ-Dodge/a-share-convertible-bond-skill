#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上帝视角回测：已知同意注册日期，模拟不同策略的收益
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.data_source import JisiluAPI, SinaFinanceAPI
from datetime import datetime, timedelta
import re


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


def find_trading_day(prices: dict, base_date: str, offset: int) -> str:
    """查找偏移后的交易日"""
    sorted_dates = sorted(prices.keys())
    base_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= base_date:
            base_idx = i
            break
    
    if base_idx is None:
        return None
    
    target_idx = base_idx + offset
    if 0 <= target_idx < len(sorted_dates):
        return sorted_dates[target_idx]
    return None


def main():
    jsl = JisiluAPI(timeout=30)
    sina = SinaFinanceAPI(timeout=30)
    
    print('从集思录获取待发转债数据...')
    bonds = jsl.fetch_pending_bonds(limit=100)
    print(f'获取到 {len(bonds)} 只转债')
    
    # 筛选有上市委通过和同意注册日期的转债
    valid_bonds = []
    for b in bonds:
        progress_full = b.get('progress_full', '')
        dates = parse_progress_dates(progress_full)
        
        if all(k in dates for k in ['上市委通过', '同意注册']) and b.get('stock_code'):
            b['progress_dates'] = dates
            valid_bonds.append(b)
    
    print(f'找到 {len(valid_bonds)} 只有完整进度数据的转债')
    
    # 上帝视角回测多种策略
    print('\n上帝视角回测多种策略')
    print('=' * 80)
    
    strategies = {
        '策略 A: 上市委通过当日入场 → 同意注册后 1 天卖出': 0,
        '策略 B: 上市委通过后 20 天入场 → 同意注册后 1 天卖出': 20,
        '策略 C: 上市委通过后 30 天入场 → 同意注册后 1 天卖出': 30,
        '策略 D: 上市委通过后 35 天入场 → 同意注册后 1 天卖出': 35,
        '策略 E: 同意注册当日入场 → 同意注册后 1 天卖出': 'reg',
        '策略 F: 同意注册前 5 天入场 → 同意注册后 1 天卖出': -5,
    }
    
    all_results = {name: [] for name in strategies.keys()}
    
    for b in valid_bonds:
        stock_code = b['stock_code']
        tongguo_date = b['progress_dates']['上市委通过']
        zhuce_date = b['progress_dates']['同意注册']
        bond_name = b.get('bond_name') or 'N/A'
        
        # 计算从上市委通过到同意注册的实际天数
        actual_days = (datetime.strptime(zhuce_date, '%Y-%m-%d') - 
                      datetime.strptime(tongguo_date, '%Y-%m-%d')).days
        
        # 获取股价数据
        prices = sina.fetch_history(stock_code, days=90)
        if not prices:
            continue
        
        # 找到同意注册日的交易日
        zhuce_trading = find_trading_day(prices, zhuce_date, 0)
        if not zhuce_trading:
            continue
        
        # 同意注册后 1 天的交易日（统一卖出日）
        exit_day = find_trading_day(prices, zhuce_date, 1)
        if not exit_day:
            exit_day = zhuce_trading
        
        exit_price = prices.get(exit_day, {}).get('close', 0)
        if exit_price <= 0:
            continue
        
        # 测试各个策略
        for strategy_name, entry_offset in strategies.items():
            if entry_offset == 'reg':
                # 同意注册当日入场
                entry_day = zhuce_trading
            elif entry_offset < 0:
                # 同意注册前 N 天入场
                entry_day = find_trading_day(prices, zhuce_date, entry_offset)
            else:
                # 上市委通过后 N 天入场
                entry_day = find_trading_day(prices, tongguo_date, entry_offset)
            
            if not entry_day:
                continue
            
            entry_price = prices.get(entry_day, {}).get('close', 0)
            if entry_price <= 0:
                continue
            
            # 计算收益
            stock_return = (exit_price - entry_price) / entry_price * 100
            hold_days = (datetime.strptime(exit_day, '%Y-%m-%d') - 
                        datetime.strptime(entry_day, '%Y-%m-%d')).days
            
            all_results[strategy_name].append({
                'bond_name': bond_name,
                'entry_day': entry_day,
                'exit_day': exit_day,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'return': stock_return,
                'hold_days': hold_days,
                'actual_days': actual_days,
            })
    
    # 生成报告
    md = []
    md.append('# 上帝视角回测：同意注册前后不同策略收益对比')
    md.append('')
    md.append(f'**分析时间**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**样本数量**: {len(valid_bonds)} 只转债')
    md.append('')
    
    md.append('## 策略对比')
    md.append('')
    md.append('| 策略 | 平均收益 | 胜率 | 平均持有天数 | 最佳 | 最差 |')
    md.append('|------|----------|------|-------------|------|------|')
    
    strategy_stats = []
    for strategy_name, results in all_results.items():
        if not results:
            continue
        
        avg_return = sum(r['return'] for r in results) / len(results)
        win_count = sum(1 for r in results if r['return'] > 0)
        win_ratio = win_count / len(results) * 100
        avg_hold = sum(r['hold_days'] for r in results) / len(results)
        best = max(results, key=lambda x: x['return'])
        worst = min(results, key=lambda x: x['return'])
        
        strategy_stats.append({
            'name': strategy_name,
            'avg_return': avg_return,
            'win_ratio': win_ratio,
            'avg_hold': avg_hold,
            'best': best,
            'worst': worst,
            'count': len(results),
        })
        
        md.append(f'| {strategy_name} | {avg_return:+.2f}% | {win_ratio:.1f}% | {avg_hold:.0f}天 | {best["bond_name"]}({best["return"]:+.1f}%) | {worst["bond_name"]}({worst["return"]:+.1f}%) |')
    
    md.append('')
    
    # 排序找出最佳策略
    strategy_stats.sort(key=lambda x: x['avg_return'], reverse=True)
    
    md.append('## 策略排名')
    md.append('')
    for i, s in enumerate(strategy_stats, 1):
        medal = '🥇' if i == 1 else ('🥈' if i == 2 else ('🥉' if i == 3 else ''))
        md.append(f'{i}. {medal} **{s["name"]}**')
        md.append(f'   - 平均收益：{s["avg_return"]:+.2f}% | 胜率：{s["win_ratio"]:.1f}% | 持有：{s["avg_hold"]:.0f}天')
        md.append('')
    
    # 详细数据
    md.append('## 详细数据（按最佳策略）')
    md.append('')
    
    best_strategy = strategy_stats[0]['name'] if strategy_stats else None
    if best_strategy:
        md.append(f'**{best_strategy}**')
        md.append('')
        md.append('| # | 债券名称 | 入场日 | 卖出日 | 入场价 | 卖出价 | 收益率 | 持有天数 |')
        md.append('|---|----------|--------|--------|--------|--------|--------|----------|')
        
        for i, r in enumerate(all_results[best_strategy], 1):
            marker = '✅' if r['return'] > 0 else '❌'
            md.append(f'| {i} | {r["bond_name"]} | {r["entry_day"]} | {r["exit_day"]} | '
                     f'{r["entry_price"]:.2f} | {r["exit_price"]:.2f} | {r["return"]:+.2f}% {marker} | {r["hold_days"]}天 |')
    
    md.append('')
    
    # 结论
    md.append('## 结论')
    md.append('')
    if strategy_stats:
        best = strategy_stats[0]
        md.append(f'🏆 **最佳策略**: {best["name"]}')
        md.append(f'   - 平均收益：{best["avg_return"]:+.2f}%')
        md.append(f'   - 胜率：{best["win_ratio"]:.1f}%')
        md.append('')
        
        if best['avg_return'] > 4:
            md.append('✅ 该策略历史表现优秀，值得采用')
        elif best['avg_return'] > 2:
            md.append('⚠️ 该策略有一定收益，但需结合其他因素')
        else:
            md.append('⚠️ 该策略收益有限，建议优化')
    
    md.append('')
    md.append('---')
    md.append('')
    md.append('**注**: 本回测以上帝视角进行，实际投资中无法预知同意注册日期。')
    md.append('')
    
    # 保存报告
    content = '\n'.join(md)
    output_path = '/Users/dodge/.openclaw/workspace/skills/a-share-convertible-bond-skill/上帝视角回测_同意注册前后策略对比.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f'\n报告已保存：{output_path}')
    
    # 打印排名
    print('\n策略排名:')
    for i, s in enumerate(strategy_stats[:5], 1):
        print(f'{i}. {s["name"]}: {s["avg_return"]:+.2f}% (胜率{s["win_ratio"]:.1f}%)')


if __name__ == '__main__':
    main()
