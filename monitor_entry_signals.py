#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可转债入场时机监控脚本

监控策略：
1. 同意注册当日入场 → 持有 10 天
2. 上市委通过后 10 天入场 → 持有 20 天

当发现入场窗口时提醒用户
"""

import sys
import os
import json
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.data_source import JisiluAPI, SinaFinanceAPI
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


def load_history():
    """加载历史记录"""
    history_path = os.path.join(os.path.dirname(__file__), 'monitor_history.json')
    if os.path.exists(history_path):
        with open(history_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'bonds': {}, 'alerts': []}


def save_history(data):
    """保存历史记录"""
    history_path = os.path.join(os.path.dirname(__file__), 'monitor_history.json')
    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def check_entry_signals():
    """检查入场信号"""
    jsl = JisiluAPI(timeout=30)
    sina = SinaFinanceAPI(timeout=30)
    
    print('=' * 80)
    print(f'可转债入场时机监控')
    print(f'检查时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 80)
    print()
    
    # 获取历史记录
    history = load_history()
    
    # 获取最新数据
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
        
        # 策略 1: 同意注册当日入场
        if '同意注册' in dates:
            zhuce_date = dates['同意注册']
            
            # 检查是否是今天或最近 3 天内（考虑到周末）
            zhuce_dt = datetime.strptime(zhuce_date, '%Y-%m-%d')
            days_diff = (datetime.now() - zhuce_dt).days
            
            if 0 <= days_diff <= 3:
                # 检查是否已经提醒过
                alert_key = f'{bond_code}_zhuce'
                if alert_key not in history.get('bonds', {}):
                    # 获取当前股价
                    prices = sina.fetch_history(stock_code, days=10)
                    current_price = 0
                    if prices:
                        latest_date = max(prices.keys())
                        current_price = prices[latest_date].get('close', 0)
                    
                    alert = {
                        'type': '同意注册当日入场',
                        'bond_name': bond_name,
                        'bond_code': bond_code,
                        'stock_name': stock_name,
                        'stock_code': stock_code,
                        'trigger_date': zhuce_date,
                        'current_price': current_price,
                        'strategy': '同意注册当日入场 → 持有 10 天',
                        'expected_return': '+3.12%',
                        'win_rate': '60.0%',
                        'hold_days': 10,
                        'exit_date': calculate_exit_date(zhuce_date, 10),
                    }
                    alerts.append(alert)
                    history['bonds'][alert_key] = today
        
        # 策略 2: 上市委通过后 10 天入场
        if '上市委通过' in dates:
            tongguo_date = dates['上市委通过']
            
            # 计算通过后第 10 天
            tongguo_dt = datetime.strptime(tongguo_date, '%Y-%m-%d')
            entry_dt = tongguo_dt + timedelta(days=10)
            entry_date = entry_dt.strftime('%Y-%m-%d')
            
            # 检查是否是今天或最近 3 天内
            days_diff = (datetime.now() - entry_dt).days
            
            if 0 <= days_diff <= 3:
                # 检查是否已经提醒过
                alert_key = f'{bond_code}_tongguo'
                if alert_key not in history.get('bonds', {}):
                    # 获取当前股价
                    prices = sina.fetch_history(stock_code, days=10)
                    current_price = 0
                    if prices:
                        latest_date = max(prices.keys())
                        current_price = prices[latest_date].get('close', 0)
                    
                    alert = {
                        'type': '上市委通过后 10 天入场',
                        'bond_name': bond_name,
                        'bond_code': bond_code,
                        'stock_name': stock_name,
                        'stock_code': stock_code,
                        'trigger_date': tongguo_date,
                        'entry_date': entry_date,
                        'current_price': current_price,
                        'strategy': '上市委通过后 10 天入场 → 持有 20 天',
                        'expected_return': '+3.78%',
                        'win_rate': '62.5%',
                        'hold_days': 20,
                        'exit_date': calculate_exit_date(entry_date, 20),
                    }
                    alerts.append(alert)
                    history['bonds'][alert_key] = today
        
        # 监控即将同意注册的（通过后 35-40 天）
        if '上市委通过' in dates and '同意注册' not in dates:
            tongguo_date = dates['上市委通过']
            tongguo_dt = datetime.strptime(tongguo_date, '%Y-%m-%d')
            
            # 计算通过后 35 天（开始监控）
            monitor_dt = tongguo_dt + timedelta(days=35)
            days_until_monitor = (monitor_dt - datetime.now()).days
            
            if 0 <= days_until_monitor <= 5:
                alert_key = f'{bond_code}_monitor'
                if alert_key not in history.get('bonds', {}):
                    alert = {
                        'type': '即将进入监控期',
                        'bond_name': bond_name,
                        'bond_code': bond_code,
                        'stock_name': stock_name,
                        'stock_code': stock_code,
                        'tongguo_date': tongguo_date,
                        'monitor_start': monitor_dt.strftime('%Y-%m-%d'),
                        'days_until_monitor': days_until_monitor,
                        'note': f'{days_until_monitor} 天后开始监控，预计同意后 41 天左右同意注册',
                    }
                    alerts.append(alert)
                    history['bonds'][alert_key] = today
    
    # 保存历史记录
    save_history(history)
    
    # 输出提醒
    if alerts:
        print(f'🚨 发现 {len(alerts)} 个入场机会！')
        print()
        
        for i, alert in enumerate(alerts, 1):
            print(f'【{i}】{alert["type"]}')
            print(f'  债券：{alert["bond_name"]} ({alert["bond_code"]})')
            print(f'  正股：{alert["stock_name"]} ({alert["stock_code"]})')
            
            if alert['type'] == '同意注册当日入场':
                print(f'  同意注册日期：{alert["trigger_date"]}')
                print(f'  当前股价：{alert["current_price"]:.2f}元')
                print(f'  策略：{alert["strategy"]}')
                print(f'  预期收益：{alert["expected_return"]} (胜率{alert["win_rate"]})')
                print(f'  持有时间：{alert["hold_days"]}天')
                print(f'  预计卖出：{alert["exit_date"]}')
            
            elif alert['type'] == '上市委通过后 10 天入场':
                print(f'  上市委通过：{alert["trigger_date"]}')
                print(f'  入场日期：{alert["entry_date"]}')
                print(f'  当前股价：{alert["current_price"]:.2f}元')
                print(f'  策略：{alert["strategy"]}')
                print(f'  预期收益：{alert["expected_return"]} (胜率{alert["win_rate"]})')
                print(f'  持有时间：{alert["hold_days"]}天')
                print(f'  预计卖出：{alert["exit_date"]}')
            
            elif alert['type'] == '即将进入监控期':
                print(f'  上市委通过：{alert["tongguo_date"]}')
                print(f'  监控开始：{alert["monitor_start"]} ({alert["days_until_monitor"]}天后)')
                print(f'  备注：{alert["note"]}')
            
            print()
            print('-' * 60)
            print()
    else:
        print('✅ 暂无新的入场机会')
        print()
    
    # 显示持仓跟踪（已入场但未卖出的）
    print('📊 持仓跟踪:')
    print('-' * 60)
    show_holdings(history)
    
    return alerts


def calculate_exit_date(entry_date: str, hold_days: int) -> str:
    """计算卖出日期（考虑周末）"""
    entry_dt = datetime.strptime(entry_date, '%Y-%m-%d')
    exit_dt = entry_dt + timedelta(days=hold_days)
    
    # 如果卖出日是周末，顺延到周一
    while exit_dt.weekday() >= 5:
        exit_dt += timedelta(days=1)
    
    return exit_dt.strftime('%Y-%m-%d')


def show_holdings(history):
    """显示持仓跟踪"""
    today = datetime.now()
    
    # 读取已入场记录
    holdings = []
    for key, date_str in history.get('bonds', {}).items():
        if '_zhuce' in key or '_tongguo' in key:
            bond_code = key.split('_')[0]
            entry_date = datetime.strptime(date_str, '%Y-%m-%d')
            days_held = (today - entry_date).days
            
            # 根据策略类型确定持有天数
            if '_zhuce' in key:
                hold_period = 10
                strategy = '同意注册入场'
            else:
                hold_period = 20
                strategy = '上市后入场'
            
            days_remaining = hold_period - days_held
            
            if days_remaining > 0:
                holdings.append({
                    'bond_code': bond_code,
                    'entry_date': date_str,
                    'days_held': days_held,
                    'days_remaining': days_remaining,
                    'strategy': strategy,
                })
    
    if holdings:
        for h in sorted(holdings, key=lambda x: x['days_remaining']):
            status = '⏰' if h['days_remaining'] <= 3 else '📈'
            print(f'{status} {h["bond_code"]} | {h["strategy"]} | 入场：{h["entry_date"]} | '
                  f'已持有：{h["days_held"]}天 | 剩余：{h["days_remaining"]}天')
    else:
        print('暂无持仓')
    
    print()


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='可转债入场时机监控')
    parser.add_argument('--once', action='store_true', help='只运行一次')
    parser.add_argument('--interval', type=int, default=60, help='监控间隔（分钟），默认 60')
    args = parser.parse_args()
    
    if args.once:
        # 只运行一次
        check_entry_signals()
    else:
        # 持续监控
        import time
        print(f'开始监控，每{args.interval}分钟检查一次...')
        print('按 Ctrl+C 停止监控')
        print()
        
        try:
            while True:
                check_entry_signals()
                print(f'下次检查：{args.interval}分钟后')
                print()
                time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            print('\n监控已停止')


if __name__ == '__main__':
    main()
