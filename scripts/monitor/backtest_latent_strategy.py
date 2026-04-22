#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
潜伏策略回测验证

使用历史数据验证：
1. 在上市委通过后 25-55 天窗口期内监控
2. 检测股价和成交量信号
3. 验证信号出现后到同意注册日的收益
4. 计算策略胜率和平均收益
"""

import sys
import os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lib.data_source import SinaFinanceAPI
from lib.stock_quality import StockQualityEvaluator


# 历史数据：已同意注册的转债
# 来源：可转债同意注册后股价变化分析_2025-2026.md + 可转债同意注册前提前布局策略.md
HISTORICAL_DATA = [
    # 债券，股票代码，上市委通过日，同意注册日，注册前 10 天价，注册前 5 天价，注册日价
    {'bond': '金杨转债', 'stock': '301210', 'tongguo_date': '2026-02-11', 'zhuce_date': '2026-03-31', 'price_10d': 36.62, 'price_5d': 36.62, 'price_0d': 38.53},
    {'bond': '本川转债', 'stock': '300622', 'tongguo_date': '2026-02-10', 'zhuce_date': '2026-04-01', 'price_10d': 67.51, 'price_5d': 67.51, 'price_0d': 71.52},
    {'bond': '珂玛转债', 'stock': '300447', 'tongguo_date': '2026-02-06', 'zhuce_date': '2026-03-30', 'price_10d': 92.35, 'price_5d': 92.35, 'price_0d': 101.86},
    {'bond': '斯达转债', 'stock': '603290', 'tongguo_date': '2026-01-30', 'zhuce_date': '2026-03-12', 'price_10d': 98.12, 'price_5d': 98.12, 'price_0d': 109.06},
    {'bond': 'N/A-5', 'stock': '688668', 'tongguo_date': '2026-02-11', 'zhuce_date': '2026-04-21', 'price_10d': 34.54, 'price_5d': 34.54, 'price_0d': 35.51},
    {'bond': 'N/A-6', 'stock': '688480', 'tongguo_date': '2026-02-04', 'zhuce_date': '2026-04-13', 'price_10d': 16.57, 'price_5d': 16.57, 'price_0d': 18.79},
    {'bond': 'N/A-7', 'stock': '603112', 'tongguo_date': '2026-02-07', 'zhuce_date': '2026-04-08', 'price_10d': 36.38, 'price_5d': 36.38, 'price_0d': 36.90},
    {'bond': 'N/A-8', 'stock': '688200', 'tongguo_date': '2026-02-04', 'zhuce_date': '2026-04-07', 'price_10d': 13.47, 'price_5d': 13.47, 'price_0d': 13.52},
    {'bond': 'N/A-9', 'stock': '603339', 'tongguo_date': '2026-02-11', 'zhuce_date': '2026-04-02', 'price_10d': 47.14, 'price_5d': 47.14, 'price_0d': 46.92},
    {'bond': 'N/A-10', 'stock': '301018', 'tongguo_date': '2026-02-04', 'zhuce_date': '2026-04-01', 'price_10d': 28.65, 'price_5d': 28.65, 'price_0d': 28.95},
    {'bond': 'N/A-11', 'stock': '688686', 'tongguo_date': '2026-01-30', 'zhuce_date': '2026-03-18', 'price_10d': 9.11, 'price_5d': 9.11, 'price_0d': 9.02},
    {'bond': 'N/A-12', 'stock': '300953', 'tongguo_date': '2025-11-14', 'zhuce_date': '2025-12-31', 'price_10d': None, 'price_5d': None, 'price_0d': 233.44},
    {'bond': 'N/A-13', 'stock': '001380', 'tongguo_date': '2025-11-20', 'zhuce_date': '2025-12-31', 'price_10d': None, 'price_5d': None, 'price_0d': 277.73},
]


def check_signal_on_date(sina, stock_code, check_date, days_before_zhuce):
    """
    检查指定日期是否有信号
    
    Args:
        sina: SinaFinanceAPI 实例
        stock_code: 股票代码
        check_date: 检查日期 (同意注册前 N 天)
        days_before_zhuce: 距离注册日的天数
    
    Returns:
        {
            'has_signal': bool,
            'price_change_2d': float,  # 2 日涨跌幅
            'price_change_5d': float,  # 5 日涨跌幅
            'volume_ratio': float,  # 成交量比率
            'breakthrough': bool,  # 是否突破 20 日高点
        }
    """
    prices = sina.fetch_history(stock_code, days=60)
    if not prices or len(prices) < 30:
        return None
    
    sorted_dates = sorted(prices.keys())
    
    # 找到检查日期附近的数据
    check_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= check_date:
            check_idx = i
            break
    
    if check_idx is None or check_idx < 10:
        return None
    
    latest_date = sorted_dates[check_idx]
    latest_close = prices[latest_date]['close']
    latest_vol = prices[latest_date]['volume']
    
    # 计算 2 日涨跌幅
    close_2d_ago = prices[sorted_dates[check_idx-2]]['close'] if check_idx >= 2 else latest_close
    price_change_2d = (latest_close - close_2d_ago) / close_2d_ago * 100
    
    # 计算 5 日涨跌幅
    close_5d_ago = prices[sorted_dates[check_idx-5]]['close'] if check_idx >= 5 else latest_close
    price_change_5d = (latest_close - close_5d_ago) / close_5d_ago * 100
    
    # 计算成交量比率
    avg_vol_5d = sum(prices[sorted_dates[check_idx-i]]['volume'] for i in range(1, 6)) / 5 if check_idx >= 5 else latest_vol
    volume_ratio = latest_vol / avg_vol_5d if avg_vol_5d > 0 else 0
    
    # 检查是否突破 20 日高点
    high_20d = max(prices[sorted_dates[check_idx-i]]['high'] for i in range(1, min(21, check_idx+1)))
    breakthrough = latest_close > high_20d
    
    # 信号判断
    has_signal = (
        (price_change_2d > 2.0) or  # 2 天涨超 2%
        (price_change_5d > 3.0) or  # 5 天涨超 3%
        (breakthrough)  # 突破 20 日高点
    )
    
    return {
        'has_signal': has_signal,
        'price_change_2d': price_change_2d,
        'price_change_5d': price_change_5d,
        'volume_ratio': volume_ratio,
        'breakthrough': breakthrough,
        'check_date': check_date,
        'days_before_zhuce': days_before_zhuce,
    }


def backtest_latent_strategy():
    """回测潜伏策略"""
    sina = SinaFinanceAPI(timeout=30)
    evaluator = StockQualityEvaluator(sina_api=sina)
    
    print('=' * 80)
    print('潜伏策略回测验证')
    print('=' * 80)
    print()
    
    results = []
    
    for item in HISTORICAL_DATA:
        bond = item['bond']
        stock = item['stock']
        tongguo_date = item['tongguo_date']
        zhuce_date = item['zhuce_date']
        
        if not tongguo_date or not zhuce_date:
            continue
        
        tongguo_dt = datetime.strptime(tongguo_date, '%Y-%m-%d')
        zhuce_dt = datetime.strptime(zhuce_date, '%Y-%m-%d')
        days_between = (zhuce_dt - tongguo_dt).days
        
        # 只回测间隔 25-55 天的案例
        if days_between < 25 or days_between > 55:
            print(f'⚠️ 跳过 {bond}: 间隔{days_between}天 (不在 25-55 天窗口)')
            continue
        
        print(f'\n{bond} ({stock})')
        print(f'  上市委通过：{tongguo_date}')
        print(f'  同意注册：{zhuce_date}')
        print(f'  间隔：{days_between}天')
        
        # 模拟监控：从通过后第 25 天开始，每天检查信号
        signals_found = []
        
        for day in range(25, min(days_between, 55) + 1):
            check_dt = tongguo_dt + timedelta(days=day)
            days_before_zhuce = days_between - day
            
            # 检查信号
            signal = check_signal_on_date(sina, stock, check_dt.strftime('%Y-%m-%d'), days_before_zhuce)
            
            if signal and signal['has_signal']:
                signals_found.append(signal)
        
        # 分析信号
        if signals_found:
            first_signal = signals_found[0]
            last_signal = signals_found[-1]
            
            # 计算从第一个信号到注册日的收益
            signal_date = first_signal['check_date']
            days_before = first_signal['days_before_zhuce']
            
            # 获取注册前 5 天和注册日价格
            price_at_signal = item.get('price_5d') if days_before >= 5 else item['price_0d']
            price_at_zhuce = item['price_0d']
            
            if price_at_signal and price_at_zhuce:
                potential_gain = (price_at_zhuce - price_at_signal) / price_at_signal * 100
            else:
                potential_gain = None
            
            print(f'  🚨 发现 {len(signals_found)} 个信号')
            print(f'     第一个信号：上市后第{signals_found[0]["days_before_zhuce"]+days_between-25}天 (注册前{days_before}天)')
            print(f'     信号强度：2 日{first_signal["price_change_2d"]:+.1f}%, 5 日{first_signal["price_change_5d"]:+.1f}%, 突破={first_signal["breakthrough"]}')
            
            if potential_gain is not None:
                print(f'     潜在收益：{potential_gain:+.1f}%')
            
            results.append({
                'bond': bond,
                'stock': stock,
                'days_between': days_between,
                'signal_found': True,
                'signal_days_before': days_before,
                'potential_gain': potential_gain,
                'signal_count': len(signals_found),
            })
        else:
            print(f'  ❌ 未发现信号')
            results.append({
                'bond': bond,
                'stock': stock,
                'days_between': days_between,
                'signal_found': False,
                'signal_days_before': None,
                'potential_gain': None,
                'signal_count': 0,
            })
    
    # 统计结果
    print()
    print('=' * 80)
    print('📊 回测结果统计')
    print('=' * 80)
    print()
    
    total = len(results)
    with_signal = sum(1 for r in results if r['signal_found'])
    without_signal = total - with_signal
    
    print(f'总样本数：{total}只')
    print(f'发现信号：{with_signal}只 ({with_signal/total*100:.1f}%)')
    print(f'未发信号：{without_signal}只 ({without_signal/total*100:.1f}%)')
    print()
    
    # 分析有信号的案例
    signal_results = [r for r in results if r['signal_found'] and r['potential_gain'] is not None]
    
    if signal_results:
        avg_gain = sum(r['potential_gain'] for r in signal_results) / len(signal_results)
        positive_count = sum(1 for r in signal_results if r['potential_gain'] > 0)
        win_rate = positive_count / len(signal_results) * 100
        
        print('有信号案例的收益统计:')
        print(f'  样本数：{len(signal_results)}只')
        print(f'  平均潜在收益：{avg_gain:+.2f}%')
        print(f'  胜率：{win_rate:.1f}% ({positive_count}/{len(signal_results)})')
        print()
        
        # 按信号出现时间分类
        early_signals = [r for r in signal_results if r['signal_days_before'] >= 5]
        late_signals = [r for r in signal_results if r['signal_days_before'] < 5]
        
        print('按信号出现时间分类:')
        if early_signals:
            early_avg = sum(r['potential_gain'] for r in early_signals) / len(early_signals)
            print(f'  注册前≥5 天发现信号：{len(early_signals)}只，平均收益 {early_avg:+.2f}%')
        if late_signals:
            late_avg = sum(r['potential_gain'] for r in late_signals) / len(late_signals)
            print(f'  注册前<5 天发现信号：{len(late_signals)}只，平均收益 {late_avg:+.2f}%')
    
    print()
    print('=' * 80)
    print('💡 结论')
    print('=' * 80)
    print()
    
    if with_signal / total > 0.7:
        print('✅ 潜伏策略有效！')
        print(f'   - {with_signal/total*100:.1f}% 的案例能提前发现信号')
        if signal_results:
            print(f'   - 平均潜在收益 +{avg_gain:.2f}%')
            print(f'   - 胜率 {win_rate:.1f}%')
        print()
        print('📈 建议:')
        print('   1. 在上市委通过后 25-55 天开始监控')
        print('   2. 发现信号后及时入场')
        print('   3. 持有到同意注册公告发布后卖出')
    elif with_signal / total > 0.5:
        print('⚠️ 潜伏策略部分有效')
        print(f'   - {with_signal/total*100:.1f}% 的案例能发现信号')
        print('   - 需要结合其他条件提高准确率')
    else:
        print('❌ 潜伏策略效果不佳')
        print(f'   - 仅 {with_signal/total*100:.1f}% 的案例能发现信号')
        print('   - 建议调整信号条件或放弃此策略')
    
    print()
    
    return results


if __name__ == '__main__':
    backtest_latent_strategy()
