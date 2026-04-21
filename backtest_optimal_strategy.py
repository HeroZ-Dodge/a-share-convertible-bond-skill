#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最优策略回测：上市委通过后 35 天监控 + 同意注册后卖出

以上帝视角回测历史数据，验证策略收益
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
    
    # 回测策略
    print('\n回测策略：上市委通过后 35 天监控 → 同意注册后卖出')
    print('=' * 70)
    
    results = []
    
    for b in valid_bonds:
        stock_code = b['stock_code']
        tongguo_date = b['progress_dates']['上市委通过']
        zhuce_date = b['progress_dates']['同意注册']
        bond_name = b.get('bond_name') or 'N/A'
        
        # 计算从上市委通过到同意注册的实际天数
        actual_days = (datetime.strptime(zhuce_date, '%Y-%m-%d') - 
                      datetime.strptime(tongguo_date, '%Y-%m-%d')).days
        
        # 如果实际天数小于 35 天，说明监控开始晚于同意注册，跳过
        if actual_days < 35:
            print(f'  ⚠️  {bond_name}: 通过到注册仅{actual_days}天，跳过')
            continue
        
        # 获取股价数据
        prices = sina.fetch_history(stock_code, days=90)
        if not prices:
            continue
        
        # 计算监控开始日期（上市后 35 天）
        monitor_start = find_trading_day(prices, tongguo_date, 35)
        if not monitor_start:
            continue
        
        # 找到同意注册日的交易日
        zhuce_trading = find_trading_day(prices, zhuce_date, 0)
        if not zhuce_trading:
            continue
        
        # 同意注册后 1 天的交易日（卖出日）
        zhuce_exit = find_trading_day(prices, zhuce_date, 1)
        if not zhuce_exit:
            zhuce_exit = zhuce_trading  # 如果找不到，就用同意注册日当天
        
        # 获取价格
        monitor_price = prices.get(monitor_start, {}).get('close', 0)
        zhuce_price = prices.get(zhuce_trading, {}).get('close', 0)
        exit_price = prices.get(zhuce_exit, {}).get('close', 0)
        
        if monitor_price > 0 and exit_price > 0:
            # 计算收益
            stock_return = (exit_price - monitor_price) / monitor_price * 100
            
            # 计算监控期天数
            monitor_days = (datetime.strptime(zhuce_trading, '%Y-%m-%d') - 
                          datetime.strptime(monitor_start, '%Y-%m-%d')).days
            
            results.append({
                'bond_name': bond_name,
                'stock_code': stock_code,
                'tongguo_date': tongguo_date,
                'zhuce_date': zhuce_date,
                'monitor_start': monitor_start,
                'monitor_price': monitor_price,
                'zhuce_price': zhuce_price,
                'exit_price': exit_price,
                'exit_date': zhuce_exit,
                'stock_return': stock_return,
                'monitor_days': monitor_days,
                'actual_days': actual_days,
            })
    
    print(f'完成 {len(results)} 只转债回测')
    
    # 生成报告
    md = []
    md.append('# 最优策略回测报告：上市委通过后 35 天监控 → 同意注册后卖出')
    md.append('')
    md.append(f'**分析时间**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**策略**: 上市委通过后第 35 天开始监控，同意注册公告后第 1 天卖出')
    md.append(f'**样本数量**: {len(results)} 只转债')
    md.append('')
    
    # 总体统计
    md.append('## 总体收益统计')
    md.append('')
    
    if results:
        avg_return = sum(r['stock_return'] for r in results) / len(results)
        win_count = sum(1 for r in results if r['stock_return'] > 0)
        win_ratio = win_count / len(results) * 100
        best = max(results, key=lambda x: x['stock_return'])
        worst = min(results, key=lambda x: x['stock_return'])
        
        avg_monitor_days = sum(r['monitor_days'] for r in results) / len(results)
        
        md.append('| 指标 | 数值 |')
        md.append('|------|------|')
        md.append(f'| 样本数量 | {len(results)} 只 |')
        md.append(f'| 平均收益率 | {avg_return:+.2f}% |')
        md.append(f'| 平均监控天数 | {avg_monitor_days:.0f} 天 |')
        md.append(f'| 胜率 | {win_count}/{len(results)} ({win_ratio:.1f}%) |')
        md.append(f'| 最佳收益 | {best["bond_name"]} ({best["stock_return"]:+.2f}%) |')
        md.append(f'| 最差收益 | {worst["bond_name"]} ({worst["stock_return"]:+.2f}%) |')
        md.append('')
        
        # 收益分布
        md.append('### 收益分布')
        md.append('')
        md.append('| 收益区间 | 数量 | 占比 |')
        md.append('|----------|------|------|')
        
        ranges = [
            ('+10% 以上', lambda x: x['stock_return'] >= 10),
            ('+5% ~ +10%', lambda x: 5 <= x['stock_return'] < 10),
            ('0% ~ +5%', lambda x: 0 <= x['stock_return'] < 5),
            ('-5% ~ 0%', lambda x: -5 <= x['stock_return'] < 0),
            ('-5% 以下', lambda x: x['stock_return'] < -5),
        ]
        
        for label, func in ranges:
            count = sum(1 for r in results if func(r))
            pct = count / len(results) * 100
            md.append(f'| {label} | {count} | {pct:.1f}% |')
        
        md.append('')
    
    # 详细数据
    md.append('## 详细回测数据')
    md.append('')
    md.append('| # | 债券名称 | 上市委通过 | 监控开始 | 同意注册 | 监控价 | 卖出价 | 收益率 | 监控天数 |')
    md.append('|---|----------|----------|----------|----------|--------|--------|--------|----------|')
    
    for i, r in enumerate(results, 1):
        marker = '✅' if r['stock_return'] > 0 else '❌'
        md.append(f'| {i} | {r["bond_name"]} | {r["tongguo_date"]} | {r["monitor_start"]} | {r["zhuce_date"]} | '
                 f'{r["monitor_price"]:.2f} | {r["exit_price"]:.2f} | {r["stock_return"]:+.2f}% {marker} | {r["monitor_days"]}天 |')
    
    md.append('')
    
    # 策略评估
    md.append('## 策略评估')
    md.append('')
    
    if results:
        if avg_return > 5:
            md.append('✅ **策略优秀**: 平均收益 +{:.2f}%，值得采用'.format(avg_return))
        elif avg_return > 2:
            md.append('⚠️ **策略可行**: 平均收益 +{:.2f}%，但需结合其他因素'.format(avg_return))
        elif avg_return > 0:
            md.append('⚠️ **策略一般**: 平均收益 +{:.2f}%，收益有限'.format(avg_return))
        else:
            md.append('❌ **策略不佳**: 平均收益 {:.2f}%，不建议采用'.format(avg_return))
        
        md.append('')
        md.append('### 策略优缺点')
        md.append('')
        md.append('**优点**:')
        md.append('- 有明确的触发条件（上市委通过后 35 天）')
        md.append('- 监控期相对较短（平均{:.0f}天）'.format(avg_monitor_days))
        md.append('- 信息透明，容易获取')
        md.append('')
        md.append('**缺点**:')
        md.append('- 审核时间不确定，可能提前或延后')
        md.append('- 需要持续监控集思录数据')
        md.append('- 收益率波动大（{:.2f}% ~ {:+.2f}%）'.format(worst['stock_return'], best['stock_return']))
        md.append('')
        
        # 改进建议
        md.append('### 改进建议')
        md.append('')
        md.append('1. **结合成交量监控**: 监控期内发现成交量异动时提前入场')
        md.append('2. **分批建仓**: 上市后 35 天开始分批买入，降低时点风险')
        md.append('3. **设置止损**: 亏损 -5% 时止损离场')
        md.append('4. **优选标的**: 选择正股基本面好、行业景气的转债')
        md.append('')
    
    # 保存报告
    content = '\n'.join(md)
    output_path = '/Users/dodge/.openclaw/workspace/skills/a-share-convertible-bond-skill/最优策略回测报告_上市委通过监控.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f'\n报告已保存：{output_path}')
    
    # 打印统计
    if results:
        print(f'\n回测结果:')
        print(f'  平均收益率：{avg_return:+.2f}%')
        print(f'  胜率：{win_ratio:.1f}%')
        print(f'  平均监控期：{avg_monitor_days:.0f} 天')
        print(f'  最佳：{best["bond_name"]} ({best["stock_return"]:+.2f}%)')
        print(f'  最差：{worst["bond_name"]} ({worst["stock_return"]:+.2f}%)')


if __name__ == '__main__':
    main()
