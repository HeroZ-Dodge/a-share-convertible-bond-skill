#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
混合策略监控脚本

策略：买跌策略（混合窗口）
- 上市后 10 天后计算 10 日涨跌
- 根据 10 日涨跌选择监控窗口：
  - 10 日涨跌 > 10% → 长间隔 → 上市后 35-45 天监控
  - 10 日涨跌 < -5% → 短间隔 → 上市后 15-25 天监控
  - 其他 → 固定 → 上市后 25-35 天监控
- 2 日跌幅 < 0（股价在跌）
- 5 日跌幅 < 0（中期趋势向下）
- 5 日跌幅 > -20%（回调未过度）
- 量比 0.5-1.5（成交量适中）
- 持有到注册日卖出

回测结果：
- 发现率：53.8%
- 胜率：71.4%
- 平均收益：+4.67%
"""

import sys
import os
import json
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lib.data_source import JisiluAPI, SinaFinanceAPI
import re


def parse_progress_dates(progress_full: str) -> dict:
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


def get_monitor_window(change_10d: float) -> tuple:
    """根据上市后 10 日涨跌确定监控窗口"""
    if change_10d > 10:
        return 35, 45, '长间隔 (35-45 天)'
    elif change_10d < -5:
        return 15, 25, '短间隔 (15-25 天)'
    else:
        return 25, 35, '固定 (25-35 天)'


def check_buy_dip_signal(sina, stock_code, tongguo_date):
    prices = sina.fetch_history(stock_code, days=90)
    if not prices or len(prices) < 40:
        return None
    
    sorted_dates = sorted(prices.keys())
    
    tongguo_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= tongguo_date:
            tongguo_idx = i
            break
    
    if tongguo_idx is None or tongguo_idx + 10 >= len(sorted_dates):
        return None
    
    # 上市后 10 日涨跌
    price_at_tongguo = prices[sorted_dates[tongguo_idx]]['close']
    price_10d = prices[sorted_dates[tongguo_idx + 10]]['close']
    change_10d = (price_10d - price_at_tongguo) / price_at_tongguo * 100
    
    # 确定监控窗口
    start_day, end_day, window_type = get_monitor_window(change_10d)
    
    days_since_tongguo = len(sorted_dates) - 1 - tongguo_idx
    
    # 检查是否在监控窗口内
    if days_since_tongguo < start_day or days_since_tongguo > end_day:
        return None
    
    latest_date = sorted_dates[-1]
    latest_close = prices[latest_date]['close']
    latest_vol = prices[latest_date]['volume']
    
    avg_vol_10 = sum(prices[sorted_dates[-1-i]]['volume'] for i in range(1, 11)) / 10
    vol_ratio = latest_vol / avg_vol_10 if avg_vol_10 > 0 else 1
    
    close_2d = prices[sorted_dates[-3]]['close'] if len(sorted_dates) >= 3 else latest_close
    change_2d = (latest_close - close_2d) / close_2d * 100
    
    close_5d = prices[sorted_dates[-6]]['close'] if len(sorted_dates) >= 6 else latest_close
    change_5d = (latest_close - close_5d) / close_5d * 100
    
    has_signal = (
        change_2d < 0 and
        change_5d < 0 and
        change_5d > -20 and
        vol_ratio > 0.5 and vol_ratio < 1.5
    )
    
    return {
        'has_signal': has_signal,
        'change_2d': change_2d,
        'change_5d': change_5d,
        'vol_ratio': vol_ratio,
        'days_since_tongguo': days_since_tongguo,
        'signal_date': latest_date,
        'current_price': latest_close,
        'change_10d': change_10d,
        'window_type': window_type,
        'window_start': start_day,
        'window_end': end_day,
    }


def load_history():
    history_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'monitor_history.json')
    if os.path.exists(history_path):
        with open(history_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'bonds': {}, 'alerts': []}


def save_history(data):
    history_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'monitor_history.json')
    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def check_signals():
    jsl = JisiluAPI(timeout=30)
    sina = SinaFinanceAPI(timeout=30)
    
    print('=' * 80)
    print(f'混合策略监控（基于上市后 10 日涨跌选择窗口）')
    print(f'检查时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 80)
    print()
    
    history = load_history()
    
    print('从集思录获取待发转债数据...')
    bonds = jsl.fetch_pending_bonds(limit=100)
    print(f'获取到 {len(bonds)} 只转债')
    print()
    
    alerts = []
    today = datetime.now().strftime('%Y-%m-%d')
    
    for b in bonds:
        bond_name = b.get('bond_name') or 'N/A'
        bond_code = b.get('bond_code', '')
        stock_code = b.get('stock_code', '')
        stock_name = b.get('stock_name') or 'N/A'
        progress_full = b.get('progress_full', '')
        dates = parse_progress_dates(progress_full)
        
        if '上市委通过' not in dates or '同意注册' in dates:
            continue
        
        tongguo_date = dates['上市委通过']
        
        signal = check_buy_dip_signal(sina, stock_code, tongguo_date)
        
        if signal and signal['has_signal']:
            alert_key = f'{stock_code}_mixed_strategy'
            if alert_key not in history.get('bonds', {}):
                alert = {
                    'type': '混合策略买跌信号',
                    'bond_name': bond_name,
                    'bond_code': bond_code,
                    'stock_name': stock_name,
                    'stock_code': stock_code,
                    'tongguo_date': tongguo_date,
                    'signal_date': signal['signal_date'],
                    'current_price': signal['current_price'],
                    'vol_ratio': signal['vol_ratio'],
                    'change_2d': signal['change_2d'],
                    'change_5d': signal['change_5d'],
                    'days_since_tongguo': signal['days_since_tongguo'],
                    'change_10d': signal['change_10d'],
                    'window_type': signal['window_type'],
                    'window_start': signal['window_start'],
                    'window_end': signal['window_end'],
                    'strategy': '混合策略 → 持有到注册日',
                    'expected_return': '+4.67%',
                    'win_rate': '71.4%',
                    'hold_days': '到注册日',
                }
                alerts.append(alert)
                history['bonds'][alert_key] = today
    
    save_history(history)
    
    if alerts:
        print(f'🚨 发现 {len(alerts)} 个买跌信号！')
        print()
        
        for i, alert in enumerate(alerts, 1):
            print(f'【{i}】{alert["type"]}')
            print(f'  债券：{alert["bond_name"]} ({alert["bond_code"]})')
            print(f'  正股：{alert["stock_name"]} ({alert["stock_code"]})')
            print(f'  上市委通过：{alert["tongguo_date"]}')
            print(f'  信号日期：{alert["signal_date"]}')
            print(f'  当前股价：{alert["current_price"]:.2f}元')
            print(f'  上市后 10 日涨跌：{alert["change_10d"]:+.1f}%')
            print(f'  窗口类型：{alert["window_type"]}')
            print(f'  监控窗口：上市后{alert["window_start"]:.0f}-{alert["window_end"]:.0f}天')
            print(f'  量比：{alert["vol_ratio"]:.2f}')
            print(f'  2 日涨跌：{alert["change_2d"]:+.1f}%')
            print(f'  5 日涨跌：{alert["change_5d"]:+.1f}%')
            print(f'  上市后天数：{alert["days_since_tongguo"]}天')
            print(f'  策略：{alert["strategy"]}')
            print(f'  预期收益：{alert["expected_return"]} (胜率{alert["win_rate"]})')
            print()
            print('-' * 60)
            print()
    else:
        print('✅ 暂无新的买跌信号')
        print()
    
    print('📊 监控列表（上市委通过但未同意注册）:')
    print('-' * 60)
    
    for b in bonds:
        stock_code = b.get('stock_code', '')
        stock_name = b.get('stock_name') or 'N/A'
        progress_full = b.get('progress_full', '')
        dates = parse_progress_dates(progress_full)
        
        if '上市委通过' not in dates or '同意注册' in dates:
            continue
        
        tongguo_date = dates['上市委通过']
        tongguo_dt = datetime.strptime(tongguo_date, '%Y-%m-%d')
        days_since = (datetime.now() - tongguo_dt).days
        
        # 获取 10 日涨跌（如果有数据）
        prices = sina.fetch_history(stock_code, days=90)
        if prices and len(prices) >= 40:
            sorted_dates = sorted(prices.keys())
            tongguo_idx = None
            for idx, d in enumerate(sorted_dates):
                if d >= tongguo_date:
                    tongguo_idx = idx
                    break
            
            if tongguo_idx is not None and tongguo_idx + 10 < len(sorted_dates):
                price_at_tongguo = prices[sorted_dates[tongguo_idx]]['close']
                price_10d = prices[sorted_dates[tongguo_idx + 10]]['close']
                change_10d = (price_10d - price_at_tongguo) / price_at_tongguo * 100
                start_day, end_day, window_type = get_monitor_window(change_10d)
                
                if start_day <= days_since <= end_day:
                    status = '⏰'
                else:
                    status = '📋'
                
                print(f'{status} {stock_name} ({stock_code}) | 上市后{days_since}天 | 10日{change_10d:+.1f}% | {window_type} | 通过：{tongguo_date}')
            else:
                print(f'📋 {stock_name} ({stock_code}) | 上市后{days_since}天 | 10日数据不足 | 通过：{tongguo_date}')
        else:
            print(f'📋 {stock_name} ({stock_code}) | 上市后{days_since}天 | 数据不足 | 通过：{tongguo_date}')
    
    print()
    
    return alerts


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='混合策略监控')
    parser.add_argument('--once', action='store_true', help='只运行一次')
    parser.add_argument('--interval', type=int, default=60, help='监控间隔（分钟），默认 60')
    args = parser.parse_args()
    
    if args.once:
        check_signals()
    else:
        import time
        print(f'开始监控，每{args.interval}分钟检查一次...')
        print('按 Ctrl+C 停止监控')
        print()
        
        try:
            while True:
                check_signals()
                print(f'下次检查：{args.interval}分钟后')
                print()
                time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            print('\n监控已停止')


if __name__ == '__main__':
    main()
