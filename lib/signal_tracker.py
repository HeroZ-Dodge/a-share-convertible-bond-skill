# -*- coding: utf-8 -*-
"""
信号跟踪模块

自动跟踪已触发信号的后续表现，用于：
1. 验证信号准确性
2. 计算实际收益
3. 为自我进化提供数据
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


class SignalTracker:
    """信号跟踪器"""
    
    def __init__(self, db=None, sina_api=None):
        """
        初始化跟踪器
        
        Args:
            db: LocalDatabase 实例
            sina_api: SinaFinanceAPI 实例
        """
        if db is None:
            from lib.local_database import LocalDatabase
            self.db = LocalDatabase()
        else:
            self.db = db
        
        if sina_api is None:
            from lib.data_source import SinaFinanceAPI
            self.sina_api = SinaFinanceAPI(timeout=15)
        else:
            self.sina_api = sina_api
    
    def get_active_signals(self) -> List[Dict]:
        """
        获取活跃信号（已触发但未结束）
        
        Returns:
            活跃信号列表
        """
        signals = self.db.get_signals_history()
        outcomes = self.db.get_outcomes_history()
        
        # 已结束的信号 ID 列表（使用 signal_id 而不是 bond_code）
        ended_signal_ids = set(o.get('signal_id') for o in outcomes if o.get('signal_id') and o.get('exit_date'))
        
        # 过滤出活跃信号
        active = []
        for s in signals:
            # 为每个信号生成唯一 ID
            signal_id = s.get('signal_id', f"{s['bond_code']}_{s.get('date', '')}")
            s['signal_id'] = signal_id  # 确保有 signal_id
            
            if signal_id not in ended_signal_ids:
                active.append(s)
        
        return active
    
    def check_signal_status(self, signal: Dict) -> Dict:
        """
        检查单个信号的状态
        
        Args:
            signal: 信号数据
        
        Returns:
            状态信息
        """
        bond_code = signal['bond_code']
        stock_code = signal['stock_code']
        signal_date = signal.get('date', '')
        
        # 获取当前股价
        prices = self.sina_api.fetch_history(stock_code, days=10)
        if not prices:
            return {
                'bond_code': bond_code,
                'status': 'error',
                'message': '无法获取股价数据',
            }
        
        sorted_dates = sorted(prices.keys())
        latest_date = sorted_dates[-1]
        latest_close = prices[latest_date]['close']
        
        # 计算持有天数
        signal_dt = datetime.strptime(signal_date, '%Y-%m-%d')
        today_dt = datetime.now()
        hold_days = (today_dt - signal_dt).days
        
        # 获取信号时的价格（近似）
        signal_price = prices.get(signal_date, {}).get('close', 0)
        if signal_price == 0 and len(sorted_dates) > 1:
            # 如果找不到信号日期的价格，使用最近的价格
            for d in sorted_dates:
                if d >= signal_date:
                    signal_price = prices[d]['close']
                    break
        
        if signal_price == 0:
            return {
                'bond_code': bond_code,
                'status': 'error',
                'message': '无法获取信号价格',
            }
        
        # 计算收益
        current_return = (latest_close - signal_price) / signal_price * 100
        
        # 判断是否结束
        status = 'active'
        exit_reason = None
        exit_price = None
        exit_date = None
        final_return = None
        
        # 结束条件
        if hold_days > 30:
            # 持有超过 30 天，自动结束
            status = 'ended'
            exit_reason = '持有超过 30 天'
            exit_price = latest_close
            exit_date = latest_date
            final_return = current_return
        
        elif current_return <= -5:
            # 止损 -5%
            status = 'ended'
            exit_reason = '止损 -5%'
            exit_price = latest_close
            exit_date = latest_date
            final_return = current_return
        
        elif current_return >= 10:
            # 止盈 +10%
            status = 'ended'
            exit_reason = '止盈 +10%'
            exit_price = latest_close
            exit_date = latest_date
            final_return = current_return
        
        # 检查是否已同意注册
        from lib.data_source import JisiluAPI
        jsl = JisiluAPI(timeout=15)
        bonds = jsl.fetch_pending_bonds(limit=100)
        
        for b in bonds:
            if b.get('bond_code') == bond_code:
                progress_full = b.get('progress_full', '')
                if '同意注册' in progress_full:
                    # 已同意注册，持有 2 天后结束
                    if hold_days >= 2:
                        status = 'ended'
                        exit_reason = '同意注册后卖出'
                        exit_price = latest_close
                        exit_date = latest_date
                        final_return = current_return
                break
        
        return {
            'bond_code': bond_code,
            'bond_name': signal.get('bond_name', ''),
            'stock_code': stock_code,
            'signal_date': signal_date,
            'signal_price': signal_price,
            'current_price': latest_close,
            'current_return': current_return,
            'hold_days': hold_days,
            'status': status,
            'exit_reason': exit_reason,
            'exit_price': exit_price,
            'exit_date': exit_date,
            'final_return': final_return,
        }
    
    def update_all_signals(self) -> List[Dict]:
        """
        更新所有活跃信号的状态
        
        Returns:
            更新结果列表
        """
        active_signals = self.get_active_signals()
        results = []
        
        for signal in active_signals:
            status = self.check_signal_status(signal)
            results.append(status)
            
            # 如果信号结束，保存结果
            if status['status'] == 'ended' and status.get('final_return') is not None:
                outcome = {
                    'bond_code': status['bond_code'],
                    'bond_name': status.get('bond_name', ''),
                    'stock_code': status['stock_code'],
                    'signal_date': status['signal_date'],
                    'signal_type': 'latent',
                    'entry_price': status['signal_price'],
                    'exit_price': status['exit_price'],
                    'exit_date': status['exit_date'],
                    'return': status['final_return'],
                    'success': status['final_return'] > 0,
                    'hold_days': status['hold_days'],
                    'exit_reason': status['exit_reason'],
                    'stock_quality': signal.get('stock_quality', {}),
                    'days_since_tongguo': signal.get('days_since_tongguo', 0),
                    'notes': f"自动跟踪 - {status['exit_reason']}",
                    'signal_id': signal.get('signal_id', ''),  # 唯一信号 ID
                }
                
                self.db.save_outcome(outcome)
        
        return results
    
    def get_tracking_report(self) -> str:
        """
        生成跟踪报告
        
        Returns:
            格式化的报告文本
        """
        lines = []
        lines.append('=' * 60)
        lines.append('📊 信号跟踪报告')
        lines.append('=' * 60)
        lines.append(f'生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        lines.append('')
        
        # 活跃信号
        active = self.get_active_signals()
        lines.append(f'活跃信号：{len(active)}个')
        lines.append('')
        
        if active:
            lines.append('📋 活跃信号列表:')
            lines.append('-' * 60)
            
            for s in active:
                status = self.check_signal_status(s)
                
                if status['status'] == 'active':
                    ret = status.get('current_return', 0)
                    ret_str = f'{ret:+.1f}%'
                    ret_icon = '✅' if ret > 0 else '❌'
                    
                    lines.append(f'  {s.get("bond_name", "")} ({s["bond_code"]})')
                    lines.append(f'    信号日期：{s.get("date", "")}')
                    lines.append(f'    信号价格：{status["signal_price"]:.2f}')
                    lines.append(f'    当前价格：{status["current_price"]:.2f}')
                    lines.append(f'    当前收益：{ret_str} {ret_icon}')
                    lines.append(f'    持有天数：{status["hold_days"]}天')
                    lines.append('')
        
        # 已结束信号
        outcomes = self.db.get_outcomes_history('latent')
        if outcomes:
            lines.append(f'已结束信号：{len(outcomes)}个')
            lines.append('-' * 60)
            
            success_count = sum(1 for o in outcomes if o.get('success', False))
            returns = [o.get('return', 0) for o in outcomes]
            avg_return = sum(returns) / len(returns)
            
            lines.append(f'  成功率：{success_count}/{len(outcomes)} ({success_count/len(outcomes)*100:.1f}%)')
            lines.append(f'  平均收益：{avg_return:+.2f}%')
            lines.append(f'  最佳收益：{max(returns):+.2f}%')
            lines.append(f'  最差收益：{min(returns):+.2f}%')
            lines.append('')
            
            lines.append('  详细记录:')
            for o in outcomes[-10:]:  # 显示最近 10 个
                ret = o.get('return', 0)
                ret_str = f'{ret:+.1f}%'
                ret_icon = '✅' if ret > 0 else '❌'
                
                lines.append(f'    {o.get("bond_name", "")} ({o["bond_code"]})')
                lines.append(f'      信号日期：{o.get("signal_date", "")}')
                lines.append(f'      入场价格：{o.get("entry_price", 0):.2f}')
                lines.append(f'      退出价格：{o.get("exit_price", 0):.2f}')
                lines.append(f'      收益：{ret_str} {ret_icon}')
                lines.append(f'      持有天数：{o.get("hold_days", 0)}天')
                lines.append(f'      退出原因：{o.get("exit_reason", "")}')
                lines.append('')
        
        lines.append('=' * 60)
        
        return '\n'.join(lines)


# 全局跟踪器实例
tracker = SignalTracker()
