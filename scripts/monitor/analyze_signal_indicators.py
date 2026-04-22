#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号指标深度分析

目标：找到能预判"同意注册即将临近"的技术指标
核心思路：我们无法知道注册日，但需要找到注册前 0-8 天才会出现的信号

分析维度：
1. 成交量异动（量比、换手率突增）
2. 均线系统（MA5 上穿 MA20、MA60）
3. 相对强度（跑赢大盘/行业）
4. 价格形态（突破平台、加速上涨）
5. MACD 金叉/零轴上方
6. 布林带突破上轨
7. 筹码集中度
"""

import sys
import os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lib.data_source import SinaFinanceAPI


# 历史数据
HISTORICAL_DATA = [
    {'bond': '金杨转债', 'stock': '301210', 'stock_name': '金杨精密', 'tongguo_date': '2026-02-11', 'zhuce_date': '2026-03-31'},
    {'bond': '本川转债', 'stock': '300622', 'stock_name': '博士眼镜', 'tongguo_date': '2026-02-10', 'zhuce_date': '2026-04-01'},
    {'bond': '珂玛转债', 'stock': '300447', 'stock_name': '珂玛科技', 'tongguo_date': '2026-02-06', 'zhuce_date': '2026-03-30'},
    {'bond': '斯达转债', 'stock': '603290', 'stock_name': '斯达半导', 'tongguo_date': '2026-01-30', 'zhuce_date': '2026-03-12'},
    {'bond': '四方转债', 'stock': '603339', 'stock_name': '四方科技', 'tongguo_date': '2026-02-11', 'zhuce_date': '2026-04-02'},
    {'bond': '奥普转债', 'stock': '688686', 'stock_name': '奥普特', 'tongguo_date': '2026-01-30', 'zhuce_date': '2026-03-18'},
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


def calculate_volume_ratio(prices, date, window=10):
    """计算量比（当日成交量 / 过去 N 日平均）"""
    sorted_dates = sorted(prices.keys())
    idx = None
    for i, d in enumerate(sorted_dates):
        if d >= date:
            idx = i
            break
    if idx is None or idx < window:
        return None
    
    current_vol = prices[sorted_dates[idx]]['volume']
    avg_vol = sum(prices[sorted_dates[idx-j]]['volume'] for j in range(1, window + 1)) / window
    return current_vol / avg_vol if avg_vol > 0 else None


def calculate_turnover(prices, date):
    """计算换手率（简化版：用成交量/平均成交量近似）"""
    sorted_dates = sorted(prices.keys())
    idx = None
    for i, d in enumerate(sorted_dates):
        if d >= date:
            idx = i
            break
    if idx is None or idx < 20:
        return None
    
    current_vol = prices[sorted_dates[idx]]['volume']
    avg_vol = sum(prices[sorted_dates[idx-j]]['volume'] for j in range(1, 21)) / 20
    return current_vol / avg_vol


def calculate_macd(prices):
    """计算 MACD"""
    sorted_dates = sorted(prices.keys())
    closes = [prices[d]['close'] for d in sorted_dates]
    
    if len(closes) < 26:
        return {}
    
    # EMA12
    ema12 = [closes[0]]
    for i in range(1, len(closes)):
        ema12.append(closes[i] * 2/13 + ema12[-1] * 11/13)
    
    # EMA26
    ema26 = [closes[0]]
    for i in range(1, len(closes)):
        ema26.append(closes[i] * 2/27 + ema26[-1] * 25/27)
    
    # DIF
    dif = [ema12[i] - ema26[i] for i in range(len(closes))]
    
    # DEA (EMA9 of DIF)
    dea = [dif[0]]
    for i in range(1, len(dif)):
        dea.append(dif[i] * 2/10 + dea[-1] * 8/10)
    
    # MACD histogram
    macd_hist = [(dif[i] - dea[i]) * 2 for i in range(len(dif))]
    
    result = {}
    for i, date in enumerate(sorted_dates):
        result[date] = {
            'dif': dif[i],
            'dea': dea[i],
            'macd': macd_hist[i],
        }
    return result


def analyze_stock_indicators(sina, item):
    """分析单只股票的各项指标"""
    stock = item['stock']
    bond = item['bond']
    stock_name = item['stock_name']
    zhuce_date = item['zhuce_date']
    
    prices = sina.fetch_history(stock, days=120)
    if not prices or len(prices) < 40:
        return None
    
    sorted_dates = sorted(prices.keys())
    
    # 找到注册日索引
    zhuce_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= zhuce_date:
            zhuce_idx = i
            break
    
    if zhuce_idx is None or zhuce_idx < 30:
        return None
    
    # 计算各项指标
    ma5 = calculate_ma(prices, 5)
    ma10 = calculate_ma(prices, 10)
    ma20 = calculate_ma(prices, 20)
    macd_data = calculate_macd(prices)
    
    # 分析注册前 0-30 天的指标变化
    analysis = []
    
    for days_before in range(30, -1, -1):
        target_idx = zhuce_idx - days_before
        if target_idx < 0 or target_idx >= len(sorted_dates):
            continue
        
        date = sorted_dates[target_idx]
        close = prices[date]['close']
        volume = prices[date]['volume']
        
        # 量比
        vol_ratio = calculate_volume_ratio(prices, date, 10)
        
        # MA 关系
        ma5_val = ma5.get(date)
        ma20_val = ma20.get(date)
        ma_above_20 = (close > ma20_val) if ma20_val else None
        ma5_above_20 = (ma5_val > ma20_val) if ma5_val and ma20_val else None
        
        # MACD
        macd_info = macd_data.get(date, {})
        macd_positive = macd_info.get('macd', 0) > 0 if macd_info else None
        dif_above_dea = macd_info.get('dif', 0) > macd_info.get('dea', 0) if macd_info else None
        
        # 2 日涨跌幅
        if target_idx >= 2:
            close_2d = prices[sorted_dates[target_idx - 2]]['close']
            change_2d = (close - close_2d) / close_2d * 100
        else:
            change_2d = None
        
        # 5 日涨跌幅
        if target_idx >= 5:
            close_5d = prices[sorted_dates[target_idx - 5]]['close']
            change_5d = (close - close_5d) / close_5d * 100
        else:
            change_5d = None
        
        # 20 日高点
        if target_idx >= 20:
            high_20d = max(prices[sorted_dates[target_idx - j]]['high'] for j in range(20))
            breakthrough = close > high_20d
        else:
            breakthrough = None
        
        # 注册日收益
        price_at_zhuce = prices[sorted_dates[zhuce_idx]]['close']
        gain_to_zhuce = (price_at_zhuce - close) / close * 100
        
        analysis.append({
            'date': date,
            'days_before': days_before,
            'close': close,
            'vol_ratio': vol_ratio,
            'change_2d': change_2d,
            'change_5d': change_5d,
            'ma_above_20': ma_above_20,
            'ma5_above_20': ma5_above_20,
            'macd_positive': macd_positive,
            'dif_above_dea': dif_above_dea,
            'breakthrough': breakthrough,
            'gain_to_zhuce': gain_to_zhuce,
        })
    
    return {
        'bond': bond,
        'stock': stock,
        'stock_name': stock_name,
        'zhuce_date': zhuce_date,
        'analysis': analysis,
    }


def find_optimal_signals(all_results):
    """寻找最优信号组合"""
    print('=' * 80)
    print('🔍 信号指标深度分析')
    print('=' * 80)
    print()
    
    # 按天数分组统计
    from collections import defaultdict
    
    days_stats = defaultdict(lambda: {
        'count': 0,
        'positive_count': 0,
        'total_gain': 0,
        'vol_ratio_sum': 0,
        'vol_ratio_count': 0,
        'change_2d_sum': 0,
        'change_2d_count': 0,
        'change_5d_sum': 0,
        'change_5d_count': 0,
        'ma_above_20_count': 0,
        'ma5_above_20_count': 0,
        'macd_positive_count': 0,
        'dif_above_dea_count': 0,
        'breakthrough_count': 0,
    })
    
    for result in all_results:
        if not result or 'analysis' not in result:
            continue
        
        for entry in result['analysis']:
            days = entry['days_before']
            stats = days_stats[days]
            stats['count'] += 1
            
            if entry['gain_to_zhuce'] > 0:
                stats['positive_count'] += 1
            stats['total_gain'] += entry['gain_to_zhuce']
            
            if entry['vol_ratio'] is not None:
                stats['vol_ratio_sum'] += entry['vol_ratio']
                stats['vol_ratio_count'] += 1
            
            if entry['change_2d'] is not None:
                stats['change_2d_sum'] += entry['change_2d']
                stats['change_2d_count'] += 1
            
            if entry['change_5d'] is not None:
                stats['change_5d_sum'] += entry['change_5d']
                stats['change_5d_count'] += 1
            
            if entry['ma_above_20'] is True:
                stats['ma_above_20_count'] += 1
            if entry['ma5_above_20'] is True:
                stats['ma5_above_20_count'] += 1
            if entry['macd_positive'] is True:
                stats['macd_positive_count'] += 1
            if entry['dif_above_dea'] is True:
                stats['dif_above_dea_count'] += 1
            if entry['breakthrough'] is True:
                stats['breakthrough_count'] += 1
    
    # 输出统计
    print('📊 各天数指标统计（注册前 N 天）')
    print('-' * 80)
    print(f'{"天数":>4} | {"胜率":>6} | {"平均收益":>8} | {"量比":>5} | {"2日涨跌":>7} | {"5日涨跌":>7} | {"MA>20":>5} | {"MA5>20":>6} | {"MACD+":>5} | {"突破":>5}')
    print('-' * 80)
    
    for days in sorted(days_stats.keys()):
        stats = days_stats[days]
        if stats['count'] < 3:
            continue
        
        win_rate = stats['positive_count'] / stats['count'] * 100
        avg_gain = stats['total_gain'] / stats['count']
        avg_vol = stats['vol_ratio_sum'] / stats['vol_ratio_count'] if stats['vol_ratio_count'] > 0 else 0
        avg_2d = stats['change_2d_sum'] / stats['change_2d_count'] if stats['change_2d_count'] > 0 else 0
        avg_5d = stats['change_5d_sum'] / stats['change_5d_count'] if stats['change_5d_count'] > 0 else 0
        ma_rate = stats['ma_above_20_count'] / stats['count'] * 100
        ma5_rate = stats['ma5_above_20_count'] / stats['count'] * 100
        macd_rate = stats['macd_positive_count'] / stats['count'] * 100
        bt_rate = stats['breakthrough_count'] / stats['count'] * 100
        
        print(f'{days:>4} | {win_rate:>5.1f}% | {avg_gain:>+7.1f}% | {avg_vol:>5.2f} | {avg_2d:>+6.1f}% | {avg_5d:>+6.1f}% | {ma_rate:>4.0f}% | {ma5_rate:>5.0f}% | {macd_rate:>4.0f}% | {bt_rate:>4.0f}%')
    
    print()
    
    # 寻找最优信号组合
    print('=' * 80)
    print('🎯 信号组合回测')
    print('=' * 80)
    print()
    
    # 定义多种信号组合
    signal_combos = {
        '量比>1.5 + 2日涨>1%': lambda e: e['vol_ratio'] and e['vol_ratio'] > 1.5 and e['change_2d'] and e['change_2d'] > 1,
        '量比>1.8 + MA>MA20': lambda e: e['vol_ratio'] and e['vol_ratio'] > 1.8 and e['ma_above_20'],
        'MACD 金叉 + 量比>1.3': lambda e: e['dif_above_dea'] and e['vol_ratio'] and e['vol_ratio'] > 1.3,
        '突破 20 日高点 + 量比>1.5': lambda e: e['breakthrough'] and e['vol_ratio'] and e['vol_ratio'] > 1.5,
        '2 日涨>2% + 5 日涨>3%': lambda e: e['change_2d'] and e['change_2d'] > 2 and e['change_5d'] and e['change_5d'] > 3,
        '量比>2.0': lambda e: e['vol_ratio'] and e['vol_ratio'] > 2.0,
        'MA5>MA20 + MACD+': lambda e: e['ma5_above_20'] and e['macd_positive'],
        '量比>1.5 + MACD+': lambda e: e['vol_ratio'] and e['vol_ratio'] > 1.5 and e['macd_positive'],
        '突破 20 日高点': lambda e: e['breakthrough'],
        '2 日涨>1.5%': lambda e: e['change_2d'] and e['change_2d'] > 1.5,
    }
    
    combo_results = {}
    
    for combo_name, combo_func in signal_combos.items():
        signals_found = []
        
        for result in all_results:
            if not result or 'analysis' not in result:
                continue
            
            for entry in result['analysis']:
                if combo_func(entry):
                    signals_found.append({
                        'bond': result['bond'],
                        'days_before': entry['days_before'],
                        'gain': entry['gain_to_zhuce'],
                    })
        
        if signals_found:
            # 每只转债只取第一个信号
            first_signals = {}
            for s in signals_found:
                if s['bond'] not in first_signals or s['days_before'] < first_signals[s['bond']]['days_before']:
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
    print(f'{"信号组合":<35} | {"样本":>4} | {"胜率":>6} | {"平均收益":>8}')
    print('-' * 65)
    
    for name, res in sorted(combo_results.items(), key=lambda x: x[1]['win_rate'], reverse=True):
        print(f'{name:<35} | {res["count"]:>4} | {res["win_rate"]:>5.1f}% | {res["avg_gain"]:>+7.1f}%')
    
    print()
    
    # 详细分析最优组合
    if combo_results:
        best_combo = max(combo_results.items(), key=lambda x: x[1]['win_rate'])
        print('=' * 80)
        print(f'🏆 最优信号组合：{best_combo[0]}')
        print('=' * 80)
        print(f'样本数：{best_combo[1]["count"]}')
        print(f'胜率：{best_combo[1]["win_rate"]:.1f}%')
        print(f'平均收益：{best_combo[1]["avg_gain"]:+.1f}%')
        print()
        
        for bond, sig in sorted(best_combo[1]['signals'].items(), key=lambda x: x[1]['gain'], reverse=True):
            icon = '✅' if sig['gain'] > 0 else '❌'
            print(f'  {bond}: 注册前{sig["days_before"]}天信号, 收益{sig["gain"]:+.1f}% {icon}')
    
    print()


def main():
    sina = SinaFinanceAPI(timeout=30)
    
    all_results = []
    
    for item in HISTORICAL_DATA:
        bond = item['bond']
        stock = item['stock']
        print(f'分析 {bond} ({stock})...')
        
        result = analyze_stock_indicators(sina, item)
        if result:
            all_results.append(result)
    
    if all_results:
        find_optimal_signals(all_results)


if __name__ == '__main__':
    main()
