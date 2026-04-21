#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可转债同意注册后股价变化分析

从集思录获取同意注册日期，分析同意注册后不同买入和卖出时点的收益
寻找最佳入场时机和卖出策略
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
    
    # 筛选有上市委通过日期的转债
    valid_bonds = []
    for b in bonds:
        progress_full = b.get('progress_full', '')
        dates = parse_progress_dates(progress_full)
        
        if '上市委通过' in dates and b.get('stock_code'):
            b['reg_date'] = dates['上市委通过']
            valid_bonds.append(b)
    
    print(f'找到 {len(valid_bonds)} 只有上市委通过日期的转债')
    
    # 获取股价数据
    print('获取股价数据...')
    results = []
    for b in valid_bonds:
        stock_code = b['stock_code']
        reg_date = b['reg_date']
        
        # 获取同意注册日前后共 60 天的股价
        prices = sina.fetch_history(stock_code, days=60)
        if not prices:
            continue
        
        # 找到同意注册日附近的交易日
        reg_trading = find_trading_day(prices, reg_date, 0)
        if not reg_trading:
            continue
        
        # 提取关键时点的股价
        reg_price = prices.get(reg_trading, {}).get('close', 0)
        
        # T+5, T+10, T+15, T+20 的股价（同意注册后）
        t5 = find_trading_day(prices, reg_date, 5)
        t10 = find_trading_day(prices, reg_date, 10)
        t15 = find_trading_day(prices, reg_date, 15)
        t20 = find_trading_day(prices, reg_date, 20)
        
        # 同意注册前的股价（T-5, T-10）
        tm5 = find_trading_day(prices, reg_date, -5)
        tm10 = find_trading_day(prices, reg_date, -10)
        
        if reg_price > 0:
            results.append({
                'bond_name': b.get('bond_name') or 'N/A',
                'bond_code': b.get('bond_code', ''),
                'stock_code': stock_code,
                'reg_date': reg_date,
                'reg_price': reg_price,
                'pre_5_price': prices.get(tm5, {}).get('close', 0) if tm5 else 0,
                'pre_10_price': prices.get(tm10, {}).get('close', 0) if tm10 else 0,
                't5_price': prices.get(t5, {}).get('close', 0) if t5 else 0,
                't10_price': prices.get(t10, {}).get('close', 0) if t10 else 0,
                't15_price': prices.get(t15, {}).get('close', 0) if t15 else 0,
                't20_price': prices.get(t20, {}).get('close', 0) if t20 else 0,
                't5_day': t5,
                't10_day': t10,
                't15_day': t15,
                't20_day': t20,
            })
    
    print(f'完成 {len(results)} 只转债分析')
    
    # 生成报告
    md = []
    md.append('# 可转债上市委通过后股价变化分析')
    md.append('')
    md.append(f'**分析时间**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**数据来源**: 集思录 + 新浪财经')
    md.append(f'**转债数量**: {len(results)} 只')
    md.append('')
    md.append('## 分析目的')
    md.append('')
    md.append('分析**上市委通过公告后**的股价变化规律，寻找：')
    md.append('1. 上市委通过后是否适合入场')
    md.append('2. 最佳买入时点（上市委通过前/后）')
    md.append('3. 最佳卖出时点（持有几天卖出）')
    md.append('')
    
    # 总体统计
    md.append('## 总体统计')
    md.append('')
    
    # 同意注册前后的涨跌幅统计
    pre5_changes = []
    pre10_changes = []
    t5_changes = []
    t10_changes = []
    t15_changes = []
    t20_changes = []
    
    for r in results:
        if r['pre_5_price'] > 0:
            change = (r['reg_price'] - r['pre_5_price']) / r['pre_5_price'] * 100
            pre5_changes.append(change)
        
        if r['pre_10_price'] > 0:
            change = (r['reg_price'] - r['pre_10_price']) / r['pre_10_price'] * 100
            pre10_changes.append(change)
        
        if r['t5_price'] > 0:
            change = (r['t5_price'] - r['reg_price']) / r['reg_price'] * 100
            t5_changes.append(change)
        
        if r['t10_price'] > 0:
            change = (r['t10_price'] - r['reg_price']) / r['reg_price'] * 100
            t10_changes.append(change)
        
        if r['t15_price'] > 0:
            change = (r['t15_price'] - r['reg_price']) / r['reg_price'] * 100
            t15_changes.append(change)
        
        if r['t20_price'] > 0:
            change = (r['t20_price'] - r['reg_price']) / r['reg_price'] * 100
            t20_changes.append(change)
    
    md.append('### 上市委通过前后股价涨跌幅统计')
    md.append('')
    md.append('| 时点 | 样本数 | 平均涨跌幅 | 上涨比例 | 平均最高 | 平均最低 |')
    md.append('|------|--------|------------|----------|----------|----------|')
    
    def calc_stats(changes):
        if not changes:
            return 'N/A', 'N/A', 'N/A', 'N/A'
        avg = sum(changes) / len(changes)
        up_ratio = sum(1 for c in changes if c > 0) / len(changes) * 100
        max_c = max(changes)
        min_c = min(changes)
        return f'{avg:+.2f}%', f'{up_ratio:.1f}%', f'{max_c:+.2f}%', f'{min_c:+.2f}%'
    
    md.append(f'| 上市委通过前 10 天 | {len(pre10_changes)} | {calc_stats(pre10_changes)[0]} | {calc_stats(pre10_changes)[1]} | {calc_stats(pre10_changes)[2]} | {calc_stats(pre10_changes)[3]} |')
    md.append(f'| 上市委通过前 5 天 | {len(pre5_changes)} | {calc_stats(pre5_changes)[0]} | {calc_stats(pre5_changes)[1]} | {calc_stats(pre5_changes)[2]} | {calc_stats(pre5_changes)[3]} |')
    md.append(f'| **上市委通过日** | {len(results)} | **0.00%** | - | - | - |')
    md.append(f'| 上市委通过后 5 天 | {len(t5_changes)} | {calc_stats(t5_changes)[0]} | {calc_stats(t5_changes)[1]} | {calc_stats(t5_changes)[2]} | {calc_stats(t5_changes)[3]} |')
    md.append(f'| 上市委通过后 10 天 | {len(t10_changes)} | {calc_stats(t10_changes)[0]} | {calc_stats(t10_changes)[1]} | {calc_stats(t10_changes)[2]} | {calc_stats(t10_changes)[3]} |')
    md.append(f'| 上市委通过后 15 天 | {len(t15_changes)} | {calc_stats(t15_changes)[0]} | {calc_stats(t15_changes)[1]} | {calc_stats(t15_changes)[2]} | {calc_stats(t15_changes)[3]} |')
    md.append(f'| 上市委通过后 20 天 | {len(t20_changes)} | {calc_stats(t20_changes)[0]} | {calc_stats(t20_changes)[1]} | {calc_stats(t20_changes)[2]} | {calc_stats(t20_changes)[3]} |')
    md.append('')
    
    # 详细数据
    md.append('## 详细数据')
    md.append('')
    md.append('| # | 债券名称 | 上市委通过日 | 通过前 5 天 | 通过日 | 通过后 5 天 | 通过后 10 天 | 通过后 20 天 |')
    md.append('|---|----------|----------|----------|--------|----------|-----------|-----------|')
    
    for i, r in enumerate(results, 1):
        pre5 = f"{r['pre_5_price']:.2f}" if r['pre_5_price'] > 0 else 'N/A'
        t5 = f"{r['t5_price']:.2f}" if r['t5_price'] > 0 else 'N/A'
        t10 = f"{r['t10_price']:.2f}" if r['t10_price'] > 0 else 'N/A'
        t20 = f"{r['t20_price']:.2f}" if r['t20_price'] > 0 else 'N/A'
        md.append(f'| {i} | {r["bond_name"]} | {r["reg_date"]} | {pre5} | **{r["reg_price"]:.2f}** | {t5} | {t10} | {t20} |')
    
    md.append('')
    
    # 策略分析
    md.append('## 策略分析')
    md.append('')
    
    # 上市委通过后买入的收益
    md.append('### 上市委通过后不同天数买入的收益')
    md.append('')
    md.append('假设在上市委通过后第 N 天买入，持有到第 20 天卖出：')
    md.append('')
    md.append('| 买入时点 | 平均收益率 | 胜率 | 建议 |')
    md.append('|----------|------------|------|------|')
    
    # 计算不同买入时点的收益
    entry_strategies = []
    for entry_day in [0, 5, 10, 15]:
        profits = []
        for r in results:
            entry_price = r['reg_price'] if entry_day == 0 else (
                r['t5_price'] if entry_day == 5 else (
                r['t10_price'] if entry_day == 10 else r['t15_price']))
            exit_price = r['t20_price']
            
            if entry_price > 0 and exit_price > 0:
                profit = (exit_price - entry_price) / entry_price * 100
                profits.append(profit)
        
        if profits:
            avg_profit = sum(profits) / len(profits)
            win_ratio = sum(1 for p in profits if p > 0) / len(profits) * 100
            suggestion = '✅ 推荐' if avg_profit > 2 else '⚠️ 观望' if avg_profit > 0 else '❌ 不推荐'
            entry_strategies.append((entry_day, avg_profit, win_ratio, suggestion))
            md.append(f'| 通过后第{entry_day}天 | {avg_profit:+.2f}% | {win_ratio:.1f}% | {suggestion} |')
    
    md.append('')
    
    # 最佳策略
    md.append('### 最佳买卖策略')
    md.append('')
    
    if entry_strategies:
        best = max(entry_strategies, key=lambda x: x[1])
        worst = min(entry_strategies, key=lambda x: x[1])
        
        md.append(f'- 🏆 **最佳买入时点**: 上市委通过后第{best[0]}天，平均收益 {best[1]:+.2f}%，胜率 {best[2]:.1f}%')
        md.append(f'- 💀 **最差买入时点**: 上市委通过后第{worst[0]}天，平均收益 {worst[1]:+.2f}%，胜率 {worst[2]:.1f}%')
        md.append('')
    
    # 结论
    md.append('## 结论与建议')
    md.append('')
    
    avg_t5 = sum(t5_changes) / len(t5_changes) if t5_changes else 0
    avg_t10 = sum(t10_changes) / len(t10_changes) if t10_changes else 0
    avg_t20 = sum(t20_changes) / len(t20_changes) if t20_changes else 0
    
    if avg_t5 > 0 and avg_t10 > 0:
        md.append('✅ **上市委通过后股价整体呈上涨趋势**，适合入场')
    else:
        md.append('⚠️ **上市委通过后股价无明显上涨趋势**，需谨慎参与')
    
    md.append('')
    md.append('### 操作建议')
    md.append('')
    md.append('1. **入场时机**:')
    if avg_t5 > 2:
        md.append('   - 上市委通过后**立即入场**（前 5 天平均涨幅较好）')
    else:
        md.append('   - 建议**观望 5-10 天**后再决定是否入场')
    
    md.append('')
    md.append('2. **持有时间**:')
    if avg_t10 > avg_t20:
        md.append('   - 建议持有**10 天左右**卖出（后期涨幅收窄）')
    else:
        md.append('   - 可持有**20 天或更长**（上涨趋势持续）')
    
    md.append('')
    md.append('3. **风险控制**:')
    md.append('   - 设置止损位：-5% 止损')
    md.append('   - 设置止盈位：+10% 止盈')
    md.append('   - 关注正股基本面，避免问题股')
    
    md.append('')
    md.append('---')
    md.append('')
    md.append('**注**: 本分析仅基于历史数据统计，不构成投资建议。实际投资需结合市场环境和个人风险承受能力。')
    md.append('')
    
    # 保存报告
    content = '\n'.join(md)
    output_path = '/Users/dodge/.openclaw/workspace/skills/a-share-convertible-bond-skill/可转债上市委通过后股价变化分析_2025-2026.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f'\n报告已保存：{output_path}')
    print(f'\n上市委通过后股价变化:')
    print(f'  后 5 天平均：{avg_t5:+.2f}%')
    print(f'  后 10 天平均：{avg_t10:+.2f}%')
    print(f'  后 20 天平均：{avg_t20:+.2f}%')


if __name__ == '__main__':
    main()
