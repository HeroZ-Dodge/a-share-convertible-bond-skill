#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度分析：注册前股价运行规律

核心发现：
1. 注册前 1-7 天：胜率 83%，平均收益 +2-3%（如果此时入场）
2. 注册前 10-30 天：胜率 0-17%，平均收益 -4% 到 -12%

规律：股价在注册前经历三个阶段
- 早期（注册前 20-30 天）：资金建仓，股价上涨
- 中期（注册前 7-15 天）：洗盘回调，股价下跌
- 晚期（注册前 0-7 天）：重新拉升，股价上涨

关键问题：如何识别"洗盘结束、即将拉升"的拐点？

分析维度：
1. 回调深度（从高点回撤多少）
2. 回调时长（跌了多少天）
3. 缩量程度（回调时成交量萎缩）
4. 企稳信号（缩量十字星、长下影线）
5. 均线支撑（是否触及 MA20/MA60）
6. 动量恢复（5 日跌幅收窄、由跌转涨）
"""

import sys
import os
from datetime import datetime, timedelta
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lib.data_source import SinaFinanceAPI


HISTORICAL_DATA = [
    {'bond': '金杨转债', 'stock': '301210', 'stock_name': '金杨精密', 'zhuce_date': '2026-03-31'},
    {'bond': '本川转债', 'stock': '300622', 'stock_name': '博士眼镜', 'zhuce_date': '2026-04-01'},
    {'bond': '珂玛转债', 'stock': '300447', 'stock_name': '珂玛科技', 'zhuce_date': '2026-03-30'},
    {'bond': '斯达转债', 'stock': '603290', 'stock_name': '斯达半导', 'zhuce_date': '2026-03-12'},
    {'bond': '四方转债', 'stock': '603339', 'stock_name': '四方科技', 'zhuce_date': '2026-04-02'},
    {'bond': '奥普转债', 'stock': '688686', 'stock_name': '奥普特', 'zhuce_date': '2026-03-18'},
]


def calculate_ma(prices, period):
    """计算移动平均线"""
    sorted_dates = sorted(prices.keys())
    ma = {}
    for i, date in enumerate(sorted_dates):
        if i < period - 1:
            continue
        window = [prices[sorted_dates[i-j]]['close'] for j in range(period)]
        ma[date] = sum(window) / period
    return ma


def find_pullback_and_recovery(prices, zhuce_date):
    """
    分析每只股票在注册前的完整走势
    识别：高点、回调低点、恢复点
    """
    sorted_dates = sorted(prices.keys())
    
    zhuce_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= zhuce_date:
            zhuce_idx = i
            break
    
    if zhuce_idx is None or zhuce_idx < 30:
        return None
    
    price_at_zhuce = prices[sorted_dates[zhuce_idx]]['close']
    ma20 = calculate_ma(prices, 20)
    
    # 从注册前 30 天到注册日，逐日分析
    analysis = []
    
    # 跟踪最高点（用于计算回撤）
    running_high = None
    running_high_date = None
    
    for offset in range(30, 0, -1):
        idx = zhuce_idx - offset
        if idx < 20:
            continue
        
        date = sorted_dates[idx]
        close = prices[date]['close']
        low = prices[date]['low']
        high = prices[date]['high']
        volume = prices[date]['volume']
        
        # 更新最高点
        if running_high is None or close > running_high:
            running_high = close
            running_high_date = date
        
        # 从最高点的回撤
        drawdown = (close - running_high) / running_high * 100
        
        # 2 日涨跌幅
        close_2d = prices[sorted_dates[idx-2]]['close'] if idx >= 2 else close
        change_2d = (close - close_2d) / close_2d * 100
        
        # 5 日涨跌幅
        close_5d = prices[sorted_dates[idx-5]]['close'] if idx >= 5 else close
        change_5d = (close - close_5d) / close_5d * 100
        
        # 10 日涨跌幅（趋势）
        close_10d = prices[sorted_dates[idx-10]]['close'] if idx >= 10 else close
        change_10d = (close - close_10d) / close_10d * 100
        
        # 量比（vs 10 日均量）
        avg_vol_10 = sum(prices[sorted_dates[idx-j]]['volume'] for j in range(1, 11)) / 10
        vol_ratio = volume / avg_vol_10 if avg_vol_10 > 0 else 1
        
        # 成交量趋势（5 日均量 vs 20 日均量）
        avg_vol_5 = sum(prices[sorted_dates[idx-j]]['volume'] for j in range(1, 6)) / 5 if idx >= 5 else avg_vol_10
        avg_vol_20 = sum(prices[sorted_dates[idx-j]]['volume'] for j in range(1, 21)) / 20 if idx >= 20 else avg_vol_10
        vol_trend = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1
        
        # MA20 位置
        ma20_val = ma20.get(date)
        price_vs_ma20 = (close - ma20_val) / ma20_val * 100 if ma20_val else 0
        
        # 下影线（低点相对收盘）
        lower_shadow = (close - low) / close * 100 if close > 0 else 0
        
        # 注册日收益
        gain_to_zhuce = (price_at_zhuce - close) / close * 100
        
        analysis.append({
            'date': date,
            'days_before': offset,
            'close': close,
            'running_high': running_high,
            'drawdown': drawdown,
            'change_2d': change_2d,
            'change_5d': change_5d,
            'change_10d': change_10d,
            'vol_ratio': vol_ratio,
            'vol_trend': vol_trend,
            'price_vs_ma20': price_vs_ma20,
            'lower_shadow': lower_shadow,
            'gain_to_zhuce': gain_to_zhuce,
        })
    
    return analysis


def analyze_phase_transition(all_analyses):
    """
    分析阶段转换信号
    重点：识别回调结束、即将上涨的拐点
    """
    print('=' * 80)
    print('🔍 阶段转换信号分析')
    print('=' * 80)
    print()
    
    # 按天数统计
    days_stats = defaultdict(lambda: {
        'count': 0,
        'positive_count': 0,
        'total_gain': 0,
        'drawdown_sum': 0,
        'vol_ratio_sum': 0,
        'vol_trend_sum': 0,
        'change_2d_sum': 0,
        'change_5d_sum': 0,
        'change_10d_sum': 0,
        'ma20_above_count': 0,
        'lower_shadow_sum': 0,
        # 拐点信号计数
        'drawdown_recovering': 0,  # 回撤开始收窄
        'vol_shrinking': 0,  # 缩量
        'vol_trend_turning': 0,  # 量趋势转正
        'change_5d_turning': 0,  # 5 日涨幅由负转正
        'lower_shadow_long': 0,  # 长下影线
    })
    
    for analysis in all_analyses:
        if not analysis:
            continue
        
        for entry in analysis:
            days = entry['days_before']
            stats = days_stats[days]
            stats['count'] += 1
            
            if entry['gain_to_zhuce'] > 0:
                stats['positive_count'] += 1
            stats['total_gain'] += entry['gain_to_zhuce']
            stats['drawdown_sum'] += entry['drawdown']
            stats['vol_ratio_sum'] += entry['vol_ratio']
            stats['vol_trend_sum'] += entry['vol_trend']
            stats['change_2d_sum'] += entry['change_2d']
            stats['change_5d_sum'] += entry['change_5d']
            stats['change_10d_sum'] += entry['change_10d']
            
            if entry['price_vs_ma20'] > 0:
                stats['ma20_above_count'] += 1
            stats['lower_shadow_sum'] += entry['lower_shadow']
    
    # 输出统计
    print('📊 注册前各天数统计')
    print('-' * 100)
    print(f'{"天数":>4} | {"胜率":>6} | {"收益":>7} | {"回撤":>6} | {"量比":>5} | {"量趋势":>6} | {"2日":>6} | {"5日":>6} | {"10日":>6} | {"MA20+":>5}')
    print('-' * 100)
    
    for days in sorted(days_stats.keys(), reverse=True):
        stats = days_stats[days]
        if stats['count'] < 3:
            continue
        
        win_rate = stats['positive_count'] / stats['count'] * 100
        avg_gain = stats['total_gain'] / stats['count']
        avg_drawdown = stats['drawdown_sum'] / stats['count']
        avg_vol_ratio = stats['vol_ratio_sum'] / stats['count']
        avg_vol_trend = stats['vol_trend_sum'] / stats['count']
        avg_2d = stats['change_2d_sum'] / stats['count']
        avg_5d = stats['change_5d_sum'] / stats['count']
        avg_10d = stats['change_10d_sum'] / stats['count']
        ma20_rate = stats['ma20_above_count'] / stats['count'] * 100
        
        print(f'{days:>4} | {win_rate:>5.0f}% | {avg_gain:>+6.1f}% | {avg_drawdown:>+5.1f}% | {avg_vol_ratio:>5.2f} | {avg_vol_trend:>5.2f} | {avg_2d:>+5.1f}% | {avg_5d:>+5.1f}% | {avg_10d:>+5.1f}% | {ma20_rate:>4.0f}%')
    
    print()
    
    # 分析拐点特征
    print('=' * 80)
    print('🎯 拐点信号分析（寻找"洗盘结束"的特征）')
    print('=' * 80)
    print()
    
    # 对于每只股票，找出"最佳入场点"（收益最大的点）
    print('各股票最佳入场点分析:')
    print('-' * 80)
    
    for analysis in all_analyses:
        if not analysis:
            continue
        
        bond = analysis[0].get('bond', 'N/A') if 'bond' in analysis[0] else 'N/A'
        
        # 找最佳入场点（收益最大的那天）
        best_entry = max(analysis, key=lambda x: x['gain_to_zhuce'])
        
        # 找第一个盈利点
        first_profit = None
        for entry in analysis:
            if entry['gain_to_zhuce'] > 0:
                first_profit = entry
                break
        
        # 找最大回撤点
        max_dd = min(analysis, key=lambda x: x['drawdown'])
        
        print(f'\n{bond}:')
        print(f'  最佳入场：注册前{best_entry["days_before"]}天 ({best_entry["date"]}), 收益{best_entry["gain_to_zhuce"]:+.1f}%')
        print(f'    当日特征：回撤{best_entry["drawdown"]:+.1f}%, 量比{best_entry["vol_ratio"]:.2f}, 5日{best_entry["change_5d"]:+.1f}%, 10日{best_entry["change_10d"]:+.1f}%')
        
        if first_profit:
            print(f'  首个盈利：注册前{first_profit["days_before"]}天 ({first_profit["date"]}), 收益{first_profit["gain_to_zhuce"]:+.1f}%')
            print(f'    当日特征：回撤{first_profit["drawdown"]:+.1f}%, 量比{first_profit["vol_ratio"]:.2f}, 5日{first_profit["change_5d"]:+.1f}%')
        
        print(f'  最大回撤：注册前{max_dd["days_before"]}天 ({max_dd["date"]}), 回撤{max_dd["drawdown"]:+.1f}%')
        print(f'    当日特征：量比{max_dd["vol_ratio"]:.2f}, 5日{max_dd["change_5d"]:+.1f}%, 10日{max_dd["change_10d"]:+.1f}%')
    
    print()
    print()
    
    # 信号组合回测（基于新发现的特征）
    print('=' * 80)
    print('🎯 新信号组合回测')
    print('=' * 80)
    print()
    
    # 基于分析设计新信号
    signal_combos = {
        # 缩量回调信号
        '缩量(量比<0.8) + 回调>5%': lambda e: e['vol_ratio'] < 0.8 and e['drawdown'] < -5,
        '缩量(量比<0.7) + 回调>8%': lambda e: e['vol_ratio'] < 0.7 and e['drawdown'] < -8,
        
        # 动量恢复信号
        '5日跌幅收窄(>-3%) + 10日涨>0': lambda e: e['change_5d'] > -3 and e['change_10d'] > 0,
        '2日转正 + 5日仍负': lambda e: e['change_2d'] > 0 and e['change_5d'] < 0,
        
        # 组合信号
        '缩量(量比<1.0) + 2日转正': lambda e: e['vol_ratio'] < 1.0 and e['change_2d'] > 0,
        '缩量(量比<0.9) + 5日跌幅>-5%': lambda e: e['vol_ratio'] < 0.9 and e['change_5d'] > -5,
        
        # 均线支撑
        '触及 MA20(+/-2%) + 缩量': lambda e: abs(e['price_vs_ma20']) < 2 and e['vol_ratio'] < 1.0,
        'MA20 上方 + 量比>1.2': lambda e: e['price_vs_ma20'] > 0 and e['vol_ratio'] > 1.2,
        
        # 长下影线
        '长下影线(>2%) + 缩量': lambda e: e['lower_shadow'] > 2 and e['vol_ratio'] < 1.0,
        
        # 综合信号
        '缩量 + 2日转正 + MA20 上方': lambda e: e['vol_ratio'] < 1.0 and e['change_2d'] > 0 and e['price_vs_ma20'] > 0,
        '量比 0.7-1.0 + 5日>-5% + 10日>0': lambda e: 0.7 < e['vol_ratio'] < 1.0 and e['change_5d'] > -5 and e['change_10d'] > 0,
    }
    
    combo_results = {}
    
    for combo_name, combo_func in signal_combos.items():
        signals_found = []
        
        for analysis in all_analyses:
            if not analysis:
                continue
            
            bond_name = None
            for entry in analysis:
                if 'bond_name' in entry:
                    bond_name = entry['bond_name']
                    break
            
            for entry in analysis:
                if combo_func(entry):
                    signals_found.append({
                        'bond': bond_name or 'N/A',
                        'days_before': entry['days_before'],
                        'gain': entry['gain_to_zhuce'],
                        'date': entry['date'],
                    })
        
        if signals_found:
            # 每只转债只取第一个信号
            first_signals = {}
            for s in signals_found:
                if s['bond'] not in first_signals or s['days_before'] > first_signals[s['bond']]['days_before']:
                    # 取最早出现的信号（days_before 最大的）
                    first_signals[s['bond']] = s
            
            gains = [s['gain'] for s in first_signals.values()]
            avg_gain = sum(gains) / len(gains)
            win_rate = sum(1 for g in gains if g > 0) / len(gains) * 100
            
            combo_results[combo_name] = {
                'count': len(first_signals),
                'avg_gain': avg_gain,
                'win_rate': win_rate,
                'signals': first_signals,
            }
    
    # 输出结果
    print(f'{"信号组合":<40} | {"样本":>4} | {"胜率":>6} | {"平均收益":>8}')
    print('-' * 70)
    
    for name, res in sorted(combo_results.items(), key=lambda x: x[1]['win_rate'], reverse=True):
        print(f'{name:<40} | {res["count"]:>4} | {res["win_rate"]:>5.1f}% | {res["avg_gain"]:>+7.1f}%')
    
    print()
    
    # 详细分析每个信号
    for name, res in sorted(combo_results.items(), key=lambda x: x[1]['win_rate'], reverse=True)[:3]:
        print(f'--- {name} ---')
        for bond, sig in sorted(res['signals'].items(), key=lambda x: x[1]['gain'], reverse=True):
            icon = '✅' if sig['gain'] > 0 else '❌'
            print(f'  {bond}: 注册前{sig["days_before"]}天 ({sig["date"]}), 收益{sig["gain"]:+.1f}% {icon}')
        print()


def main():
    sina = SinaFinanceAPI(timeout=30)
    
    all_analyses = []
    
    for item in HISTORICAL_DATA:
        bond = item['bond']
        stock = item['stock']
        stock_name = item['stock_name']
        zhuce_date = item['zhuce_date']
        
        print(f'分析 {bond} ({stock_name}, {stock})...')
        
        prices = sina.fetch_history(stock, days=120)
        if not prices or len(prices) < 40:
            print(f'  数据不足，跳过')
            continue
        
        analysis = find_pullback_and_recovery(prices, zhuce_date)
        if analysis:
            # 添加债券名称到每个条目
            for entry in analysis:
                entry['bond_name'] = bond
                entry['stock_name'] = stock_name
            all_analyses.append(analysis)
    
    if all_analyses:
        analyze_phase_transition(all_analyses)


if __name__ == '__main__':
    main()
