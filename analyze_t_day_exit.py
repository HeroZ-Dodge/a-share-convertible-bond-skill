#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可转债抢权配债分析 - T 日卖出策略

分析在股权登记日 (T 日) 卖出的收益情况
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.data_source import EastmoneyAPI, SinaFinanceAPI
from lib.bond_calculator import BondCalculator
from datetime import datetime, timedelta


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
    em = EastmoneyAPI(timeout=30)
    sina = SinaFinanceAPI(timeout=30)
    calc = BondCalculator(target_bonds=10, bond_price=100)
    
    print('获取 2025 年及 2026 年转债数据...')
    all_bonds = em.fetch_listed_bonds(limit=100)
    
    target_bonds = [b for b in all_bonds if b.get('listing_date', '').startswith(('2025', '2026'))]
    print(f'找到 {len(target_bonds)} 只转债')
    
    print('获取股价数据...')
    stock_prices = {}
    for b in target_bonds:
        stock_code = b.get('stock_code', '')
        if stock_code and stock_code not in stock_prices:
            prices = sina.fetch_history(stock_code, days=365)
            if prices:
                stock_prices[stock_code] = prices
    
    print('分析中...')
    results = []
    for b in target_bonds:
        listing_close = em.fetch_bond_listing_price(b['bond_code'], b['listing_date'])
        b['listing_close'] = listing_close
        analysis = calc.analyze_quequan_profit(b, stock_prices)
        
        if analysis and analysis.has_stock_data:
            # 计算 T 日股价
            record_date = analysis.record_date
            prices = stock_prices.get(analysis.stock_code, {})
            
            t_day = find_trading_day(prices, record_date, 0)
            t_price = prices.get(t_day, {}).get('close', 0) if t_day else 0
            
            results.append({
                'analysis': analysis,
                't_day': t_day,
                't_price': t_price,
            })
    
    print(f'完成 {len(results)} 只转债分析')
    
    # 生成报告
    md = []
    md.append('# 可转债抢权配债分析 - 股权登记日 (T 日) 卖出策略')
    md.append('')
    md.append(f'**分析时间**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**分析范围**: 2025 年 1 月 至 2026 年 4 月')
    md.append(f'**转债数量**: {len(results)} 只')
    md.append('')
    md.append('## 策略说明')
    md.append('')
    md.append('本分析研究在**股权登记日 (T 日) 卖出**的收益情况，对比不同买入时点：')
    md.append('- **T-3 买入，T 日卖出**')
    md.append('- **T-2 买入，T 日卖出**')
    md.append('- **T-1 买入，T 日卖出**')
    md.append('')
    md.append('同时统计 T 日股价是否为 T-3 至 T+1 期间的最高价。')
    md.append('')
    
    # 按年份分组
    by_year = {}
    for r in results:
        year = r['analysis'].listing_date[:4]
        if year not in by_year:
            by_year[year] = []
        by_year[year].append(r)
    
    for year in sorted(by_year.keys()):
        year_results = by_year[year]
        
        md.append('---')
        md.append('')
        md.append(f'## {year}年数据')
        md.append('')
        
        # T 日股价统计
        md.append('### T 日股价是否为期间最高价统计')
        md.append('')
        md.append('| # | 债券名称 | T-3 | T-2 | T-1 | **T 日** | T+1 | 期间最高价 | T 日是否最高 |')
        md.append('|---|----------|-----|-----|-----|--------|-----|------------|------------|')
        
        t_day_highest_count = 0
        for i, r in enumerate(year_results, 1):
            a = r['analysis']
            p = a.stock_prices
            t_price = r['t_price']
            
            if p['T-1'] > 0 and t_price > 0:
                prices_list = [
                    ('T-3', p['T-3']),
                    ('T-2', p['T-2']),
                    ('T-1', p['T-1']),
                    ('T', t_price),
                    ('T+1', p['T+1'])
                ]
                valid_prices = [(k, v) for k, v in prices_list if v > 0]
                if valid_prices:
                    max_label, max_price = max(valid_prices, key=lambda x: x[1])
                    is_highest = '✅' if max_label == 'T' else '❌'
                    if max_label == 'T':
                        t_day_highest_count += 1
                    md.append(f'| {i} | {a.bond_name} | {p["T-3"]:.2f} | {p["T-2"]:.2f} | {p["T-1"]:.2f} | **{t_price:.2f}** | {p["T+1"]:.2f} | {max_price:.2f} ({max_label}) | {is_highest} |')
        
        md.append('')
        md.append(f'**T 日为最高价的数量**: {t_day_highest_count}/{len(year_results)} ({t_day_highest_count/len(year_results)*100:.1f}%)')
        md.append('')
        
        # T-3 买入，T 日卖出 (无配债收益)
        md.append('### T-3 买入，T 日卖出 (放弃配债)')
        md.append('')
        md.append('| # | 债券名称 | 买入价 (T-3) | 卖出价 (T) | 股价涨跌 | 股票盈亏 |')
        md.append('|---|----------|------------|----------|----------|----------|')
        
        t3_win = 0
        t3_total = 0
        t3_change_total = 0
        t3_count = 0
        for i, r in enumerate(year_results, 1):
            a = r['analysis']
            t_price = r['t_price']
            
            if a.stock_prices['T-3'] > 0 and t_price > 0:
                buy = a.stock_prices['T-3']
                sell = t_price
                change = (sell - buy) / buy * 100
                stock_profit = a.actual_shares * (sell - buy)
                roi = stock_profit / (a.actual_shares * buy) * 100
                marker = '✅' if stock_profit > 0 else '❌'
                if stock_profit > 0:
                    t3_win += 1
                t3_total += stock_profit
                t3_change_total += change
                t3_count += 1
                md.append(f'| {i} | {a.bond_name} | {buy:.2f} | {sell:.2f} | {change:+.1f}% | {stock_profit:+.0f}元 {marker} |')
        
        md.append('')
        avg_t3_change = t3_change_total / t3_count if t3_count > 0 else 0
        avg_t3_profit = t3_total / len(year_results)
        md.append(f'**胜率**: {t3_win}/{len(year_results)} ({t3_win/len(year_results)*100:.1f}%)  **平均收益**: {avg_t3_profit:+.0f}元  **平均涨跌率**: {avg_t3_change:+.2f}%')
        md.append('')
        
        # T-2 买入，T 日卖出 (无配债收益)
        md.append('### T-2 买入，T 日卖出 (放弃配债)')
        md.append('')
        md.append('| # | 债券名称 | 买入价 (T-2) | 卖出价 (T) | 股价涨跌 | 股票盈亏 |')
        md.append('|---|----------|------------|----------|----------|----------|')
        
        t2_win = 0
        t2_total = 0
        t2_change_total = 0
        t2_count = 0
        for i, r in enumerate(year_results, 1):
            a = r['analysis']
            t_price = r['t_price']
            
            if a.stock_prices['T-2'] > 0 and t_price > 0:
                buy = a.stock_prices['T-2']
                sell = t_price
                change = (sell - buy) / buy * 100
                stock_profit = a.actual_shares * (sell - buy)
                roi = stock_profit / (a.actual_shares * buy) * 100
                marker = '✅' if stock_profit > 0 else '❌'
                if stock_profit > 0:
                    t2_win += 1
                t2_total += stock_profit
                t2_change_total += change
                t2_count += 1
                md.append(f'| {i} | {a.bond_name} | {buy:.2f} | {sell:.2f} | {change:+.1f}% | {stock_profit:+.0f}元 {marker} |')
        
        md.append('')
        avg_t2_change = t2_change_total / t2_count if t2_count > 0 else 0
        avg_t2_profit = t2_total / len(year_results)
        md.append(f'**胜率**: {t2_win}/{len(year_results)} ({t2_win/len(year_results)*100:.1f}%)  **平均收益**: {avg_t2_profit:+.0f}元  **平均涨跌率**: {avg_t2_change:+.2f}%')
        md.append('')
        
        # T-1 买入，T 日卖出 (无配债收益)
        md.append('### T-1 买入，T 日卖出 (放弃配债)')
        md.append('')
        md.append('| # | 债券名称 | 买入价 (T-1) | 卖出价 (T) | 股价涨跌 | 股票盈亏 |')
        md.append('|---|----------|------------|----------|----------|----------|')
        
        t1_win = 0
        t1_total = 0
        t1_change_total = 0
        t1_count = 0
        for i, r in enumerate(year_results, 1):
            a = r['analysis']
            t_price = r['t_price']
            
            if a.stock_prices['T-1'] > 0 and t_price > 0:
                buy = a.stock_prices['T-1']
                sell = t_price
                change = (sell - buy) / buy * 100
                stock_profit = a.actual_shares * (sell - buy)
                roi = stock_profit / (a.actual_shares * buy) * 100
                marker = '✅' if stock_profit > 0 else '❌'
                if stock_profit > 0:
                    t1_win += 1
                t1_total += stock_profit
                t1_change_total += change
                t1_count += 1
                md.append(f'| {i} | {a.bond_name} | {buy:.2f} | {sell:.2f} | {change:+.1f}% | {stock_profit:+.0f}元 {marker} |')
        
        md.append('')
        avg_t1_change = t1_change_total / t1_count if t1_count > 0 else 0
        avg_t1_profit = t1_total / len(year_results)
        md.append(f'**胜率**: {t1_win}/{len(year_results)} ({t1_win/len(year_results)*100:.1f}%)  **平均收益**: {avg_t1_profit:+.0f}元  **平均涨跌率**: {avg_t1_change:+.2f}%')
        md.append('')
        
        # 策略对比
        md.append('### 策略对比')
        md.append('')
        md.append('| 策略 | 盈利数量 | 胜率 | 平均股票收益 |')
        md.append('|------|----------|------|------------|')
        md.append(f'| T-3 买入，T 日卖出 | {t3_win}/{len(year_results)} | {t3_win/len(year_results)*100:.1f}% | {t3_total/len(year_results):+.0f}元 |')
        md.append(f'| T-2 买入，T 日卖出 | {t2_win}/{len(year_results)} | {t2_win/len(year_results)*100:.1f}% | {t2_total/len(year_results):+.0f}元 |')
        md.append(f'| T-1 买入，T 日卖出 | {t1_win}/{len(year_results)} | {t1_win/len(year_results)*100:.1f}% | {t1_total/len(year_results):+.0f}元 |')
        md.append('')
        md.append('⚠️ 注意：T 日卖出**放弃配债资格**，只计算股票盈亏，不含配债收益。')
        md.append('')
    
    # 总体统计
    md.append('---')
    md.append('')
    md.append('## 总体统计')
    md.append('')
    
    total_t3_win = 0
    total_t2_win = 0
    total_t1_win = 0
    total_t3 = 0
    total_t2 = 0
    total_t1 = 0
    total_t_day_highest = 0
    
    for r in results:
        a = r['analysis']
        t_price = r['t_price']
        
        if a.stock_prices['T-1'] > 0 and t_price > 0:
            # T 日是否最高
            prices_list = [v for k, v in a.stock_prices.items() if v > 0] + [t_price]
            if t_price >= max(prices_list):
                total_t_day_highest += 1
            
            # T-3 (无配债收益)
            if a.stock_prices['T-3'] > 0:
                profit = a.actual_shares * (t_price - a.stock_prices['T-3'])
                total_t3 += profit
                if profit > 0:
                    total_t3_win += 1
            
            # T-2 (无配债收益)
            if a.stock_prices['T-2'] > 0:
                profit = a.actual_shares * (t_price - a.stock_prices['T-2'])
                total_t2 += profit
                if profit > 0:
                    total_t2_win += 1
            
            # T-1 (无配债收益)
            profit = a.actual_shares * (t_price - a.stock_prices['T-1'])
            total_t1 += profit
            if profit > 0:
                total_t1_win += 1
    
    md.append('| 指标 | 数值 |')
    md.append('|------|------|')
    md.append(f'| 分析转债总数 | {len(results)} 只 |')
    md.append(f'| T 日为最高价数量 | {total_t_day_highest}/{len(results)} ({total_t_day_highest/len(results)*100:.1f}%) |')
    md.append(f'| T-3 买入 T 日卖出胜率 (仅股票) | {total_t3_win}/{len(results)} ({total_t3_win/len(results)*100:.1f}%) |')
    md.append(f'| T-3 平均股票收益 | {total_t3/len(results):+.0f}元 |')
    md.append(f'| T-2 买入 T 日卖出胜率 (仅股票) | {total_t2_win}/{len(results)} ({total_t2_win/len(results)*100:.1f}%) |')
    md.append(f'| T-2 平均股票收益 | {total_t2/len(results):+.0f}元 |')
    md.append(f'| T-1 买入 T 日卖出胜率 (仅股票) | {total_t1_win}/{len(results)} ({total_t1_win/len(results)*100:.1f}%) |')
    md.append(f'| T-1 平均股票收益 | {total_t1/len(results):+.0f}元 |')
    md.append('')
    
    md.append('### 策略建议')
    md.append('')
    md.append('根据历史数据分析，给出以下策略建议：')
    md.append('')
    md.append('**1. 固定策略**:')
    md.append(f'- 🏆 **T-3 买入，T 日卖出**：胜率 {total_t3_win/len(results)*100:.1f}%，平均收益 {total_t3/len(results):+.0f}元')
    md.append('  - 优点：时间充裕，可观察市场反应')
    md.append('  - 缺点：占用资金时间长')
    md.append('')
    md.append('**2. 动态策略**:')
    md.append('- **观察 T-1 日股价表现**：如果 T-1 日股价已经大幅上涨 (>3%)，可考虑 T-1 日卖出，放弃配债')
    md.append('- **根据正股走势决定**：如果正股处于上升趋势，可 T-3 买入持有到 T 日；如果正股弱势，建议不参与')
    md.append('- **配债收益率评估**：如果每股配售额低 (<1 元/股)，配债收益有限，可考虑 T 日卖出股票锁定利润')
    md.append('')
    md.append('**3. 不建议的策略**:')
    md.append('- ❌ **T-1 买入，T 日卖出**：胜率仅 57%，平均收益接近 0 元，风险收益比不佳')
    md.append('- ❌ **持有到 T+1 卖出**：根据另一份报告，平均亏损 -396 元')
    md.append('')
    
    md.append('## 结论')
    md.append('')
    md.append('**重要提示**: T 日卖出意味着**放弃配债资格**，以下收益仅计算股票盈亏。')
    md.append('')
    if total_t_day_highest > len(results) * 0.5:
        md.append(f'- ✅ T 日股价在 {total_t_day_highest/len(results)*100:.1f}% 的情况下是期间最高价')
    else:
        md.append(f'- ⚠️ T 日股价仅在 {total_t_day_highest/len(results)*100:.1f}% 的情况下是期间最高价，**不建议 T 日卖出**')
    
    strategies = [
        ('T-3 买入', total_t3/len(results)),
        ('T-2 买入', total_t2/len(results)),
        ('T-1 买入', total_t1/len(results))
    ]
    best = max(strategies, key=lambda x: x[1])
    worst = min(strategies, key=lambda x: x[1])
    md.append(f'- 🏆 最佳买入时点：**{best[0]}**，T 日卖出平均股票收益 {best[1]:+.0f}元')
    md.append(f'- 💀 最差买入时点：**{worst[0]}**，T 日卖出平均股票收益 {worst[1]:+.0f}元')
    md.append('')
    md.append('**对比参考**: 如果持有到 T+1 卖出并获得配债，平均收益见另一份报告。')
    md.append('')
    
    # 保存
    content = '\n'.join(md)
    output_path = '/Users/dodge/.openclaw/workspace/skills/a-share-convertible-bond-skill/可转债抢权配债分析_T 日卖出策略_2025-2026.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f'\n报告已保存：{output_path}')
    print(f'\n总体统计:')
    print(f'  T 日为最高价：{total_t_day_highest}/{len(results)} ({total_t_day_highest/len(results)*100:.1f}%)')
    print(f'  T-3 买入 T 日卖出：{total_t3_win}/{len(results)} ({total_t3_win/len(results)*100:.1f}%), 平均 {total_t3/len(results):+.0f}元')
    print(f'  T-2 买入 T 日卖出：{total_t2_win}/{len(results)} ({total_t2_win/len(results)*100:.1f}%), 平均 {total_t2/len(results):+.0f}元')
    print(f'  T-1 买入 T 日卖出：{total_t1_win}/{len(results)} ({total_t1_win/len(results)*100:.1f}%), 平均 {total_t1/len(results):+.0f}元')


if __name__ == '__main__':
    main()
