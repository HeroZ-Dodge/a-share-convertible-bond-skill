#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
洗盘结束信号监控脚本

监控策略：洗盘结束信号入场
- 上市委通过后 15 天开始监控
- 从近期高点回撤 > 10%
- 量比 < 1.0（缩量）
- 2 日涨幅 > 0（企稳）
- 5 日跌幅 > -15%（回调未过度）

当发现洗盘结束信号时提醒用户
"""

import sys
import os
import json
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

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


def check_washout_end_signal(sina, stock_code, tongguo_date):
    """
    检测洗盘结束信号
    
    Args:
        sina: SinaFinanceAPI 实例
        stock_code: 股票代码
        tongguo_date: 上市委通过日期
    
    Returns:
        {
            'has_signal': bool,
            'drawdown': float,  # 从近期高点回撤
            'vol_ratio': float,  # 量比
            'change_2d': float,  # 2 日涨跌幅
            'change_5d': float,  # 5 日涨跌幅
            'days_since_tongguo': int,  # 上市后天数
            'signal_date': str,  # 信号日期
        }
    """
    prices = sina.fetch_history(stock_code, days=60)
    if not prices or len(prices) < 30:
        return None
    
    sorted_dates = sorted(prices.keys())
    
    # 找到上市委通过日期索引
    tongguo_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= tongguo_date:
            tongguo_idx = i
            break
    
    if tongguo_idx is None:
        return None
    
    # 上市后天数
    days_since_tongguo = len(sorted_dates) - 1 - tongguo_idx
    
    # 上市后不足 15 天，不监控
    if days_since_tongguo < 15:
        return None
    
    # 获取最新数据
    latest_date = sorted_dates[-1]
    latest_close = prices[latest_date]['close']
    latest_vol = prices[latest_date]['volume']
    
    # 计算从近期高点（上市后）的回撤
    recent_high = max(prices[sorted_dates[tongguo_idx + i]]['high'] 
                      for i in range(min(20, len(sorted_dates) - tongguo_idx)))
    drawdown = (latest_close - recent_high) / recent_high * 100
    
    # 计算量比（vs 10 日均量）
    avg_vol_10 = sum(prices[sorted_dates[-1-i]]['volume'] for i in range(1, 11)) / 10
    vol_ratio = latest_vol / avg_vol_10 if avg_vol_10 > 0 else 1
    
    # 计算 2 日涨跌幅
    close_2d = prices[sorted_dates[-3]]['close'] if len(sorted_dates) >= 3 else latest_close
    change_2d = (latest_close - close_2d) / close_2d * 100
    
    # 计算 5 日涨跌幅
    close_5d = prices[sorted_dates[-6]]['close'] if len(sorted_dates) >= 6 else latest_close
    change_5d = (latest_close - close_5d) / close_5d * 100
    
    # 信号判断
    has_signal = (
        drawdown < -10 and  # 回撤超过 10%
        vol_ratio < 1.0 and  # 缩量
        change_2d > 0 and  # 2 日转正
        change_5d > -15  # 5 日跌幅未超过 15%
    )
    
    return {
        'has_signal': has_signal,
        'drawdown': drawdown,
        'vol_ratio': vol_ratio,
        'change_2d': change_2d,
        'change_5d': change_5d,
        'days_since_tongguo': days_since_tongguo,
        'signal_date': latest_date,
        'current_price': latest_close,
        'recent_high': recent_high,
    }


def load_history():
    """加载历史记录"""
    history_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'monitor_history.json')
    if os.path.exists(history_path):
        with open(history_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'bonds': {}, 'alerts': []}


def save_history(data):
    """保存历史记录"""
    history_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'monitor_history.json')
    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def check_signals():
    """检查洗盘结束信号"""
    jsl = JisiluAPI(timeout=30)
    sina = SinaFinanceAPI(timeout=30)
    
    print('=' * 80)
    print(f'洗盘结束信号监控')
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
        
        # 只监控已上市委通过但未同意注册的
        if '上市委通过' not in dates or '同意注册' in dates:
            continue
        
        tongguo_date = dates['上市委通过']
        
        # 检测信号
        signal = check_washout_end_signal(sina, stock_code, tongguo_date)
        
        if signal and signal['has_signal']:
            # 检查是否已经提醒过
            alert_key = f'{stock_code}_washout_end'
            if alert_key not in history.get('bonds', {}):
                alert = {
                    'type': '洗盘结束信号',
                    'bond_name': bond_name,
                    'bond_code': bond_code,
                    'stock_name': stock_name,
                    'stock_code': stock_code,
                    'tongguo_date': tongguo_date,
                    'signal_date': signal['signal_date'],
                    'current_price': signal['current_price'],
                    'recent_high': signal['recent_high'],
                    'drawdown': signal['drawdown'],
                    'vol_ratio': signal['vol_ratio'],
                    'change_2d': signal['change_2d'],
                    'change_5d': signal['change_5d'],
                    'days_since_tongguo': signal['days_since_tongguo'],
                    'strategy': '洗盘结束信号入场 → 持有 10 天',
                    'expected_return': '+3.4%',
                    'win_rate': '83%',
                    'hold_days': 10,
                }
                alerts.append(alert)
                history['bonds'][alert_key] = today
    
    # 保存历史记录
    save_history(history)
    
    # 输出提醒
    if alerts:
        print(f'🚨 发现 {len(alerts)} 个洗盘结束信号！')
        print()
        
        for i, alert in enumerate(alerts, 1):
            print(f'【{i}】{alert["type"]}')
            print(f'  债券：{alert["bond_name"]} ({alert["bond_code"]})')
            print(f'  正股：{alert["stock_name"]} ({alert["stock_code"]})')
            print(f'  上市委通过：{alert["tongguo_date"]}')
            print(f'  信号日期：{alert["signal_date"]}')
            print(f'  当前股价：{alert["current_price"]:.2f}元')
            print(f'  近期高点：{alert["recent_high"]:.2f}元')
            print(f'  回撤幅度：{alert["drawdown"]:.1f}%')
            print(f'  量比：{alert["vol_ratio"]:.2f}')
            print(f'  2 日涨跌：{alert["change_2d"]:+.1f}%')
            print(f'  5 日涨跌：{alert["change_5d"]:+.1f}%')
            print(f'  上市后天数：{alert["days_since_tongguo"]}天')
            print(f'  策略：{alert["strategy"]}')
            print(f'  预期收益：{alert["expected_return"]} (胜率{alert["win_rate"]})')
            print(f'  持有时间：{alert["hold_days"]}天')
            print()
            print('-' * 60)
            print()
    else:
        print('✅ 暂无新的洗盘结束信号')
        print()
    
    # 显示监控列表
    print('📊 监控列表（上市委通过但未同意注册）:')
    print('-' * 60)
    
    monitored = 0
    for b in bonds:
        bond_name = b.get('bond_name') or 'N/A'
        stock_code = b.get('stock_code', '')
        stock_name = b.get('stock_name') or 'N/A'
        progress_full = b.get('progress_full', '')
        dates = parse_progress_dates(progress_full)
        
        if '上市委通过' not in dates or '同意注册' in dates:
            continue
        
        tongguo_date = dates['上市委通过']
        tongguo_dt = datetime.strptime(tongguo_date, '%Y-%m-%d')
        days_since = (datetime.now() - tongguo_dt).days
        
        status = '⏰' if days_since >= 15 else '📋'
        print(f'{status} {stock_name} ({stock_code}) | 上市后{days_since}天 | 通过：{tongguo_date}')
        monitored += 1
    
    if monitored == 0:
        print('暂无监控标的')
    
    print()
    
    return alerts


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='洗盘结束信号监控')
    parser.add_argument('--once', action='store_true', help='只运行一次')
    parser.add_argument('--interval', type=int, default=60, help='监控间隔（分钟），默认 60')
    args = parser.parse_args()
    
    if args.once:
        # 只运行一次
        check_signals()
    else:
        # 持续监控
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
