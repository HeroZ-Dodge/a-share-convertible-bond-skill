# -*- coding: utf-8 -*-
"""
本地数据存储模块

用于保存集思录接口获取的待发转债历史数据，支持：
1. 数据持久化存储
2. 历史数据查询
3. 数据统计分析
4. 自我进化学习
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


class LocalDatabase:
    """本地数据库管理类"""
    
    def __init__(self, data_dir: str = None):
        """
        初始化数据库
        
        Args:
            data_dir: 数据目录，默认为脚本所在目录的 data 文件夹
        """
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
        
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        
        # 数据文件路径
        self.pending_bonds_file = os.path.join(data_dir, 'pending_bonds_history.json')
        self.signals_file = os.path.join(data_dir, 'signals_history.json')
        self.outcomes_file = os.path.join(data_dir, 'outcomes_history.json')
        self.stats_file = os.path.join(data_dir, 'evolution_stats.json')
    
    # ==================== 待发转债历史数据 ====================
    
    def save_pending_bonds(self, bonds: List[Dict], source: str = 'jisilu'):
        """
        保存待发转债数据
        
        Args:
            bonds: 转债列表
            source: 数据来源
        """
        data = self._load_json(self.pending_bonds_file, {'records': []})
        
        record = {
            'timestamp': datetime.now().isoformat(),
            'date': datetime.now().strftime('%Y-%m-%d'),
            'source': source,
            'count': len(bonds),
            'bonds': bonds,
        }
        
        data['records'].append(record)
        self._save_json(self.pending_bonds_file, data)
    
    def get_pending_bonds_history(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """
        获取待发转债历史数据
        
        Args:
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
        
        Returns:
            历史记录列表
        """
        data = self._load_json(self.pending_bonds_file, {'records': []})
        records = data.get('records', [])
        
        if start_date:
            records = [r for r in records if r['date'] >= start_date]
        if end_date:
            records = [r for r in records if r['date'] <= end_date]
        
        return records
    
    def get_bond_progress(self, bond_code: str) -> Dict:
        """
        获取单只转债的进度变化历史
        
        Args:
            bond_code: 转债代码
        
        Returns:
            进度历史记录
        """
        records = self.get_pending_bonds_history()
        progress_history = []
        
        for record in records:
            for bond in record.get('bonds', []):
                if bond.get('bond_code') == bond_code:
                    progress_history.append({
                        'date': record['date'],
                        'timestamp': record['timestamp'],
                        'progress': bond.get('progress', ''),
                        'progress_full': bond.get('progress_full', ''),
                    })
        
        return {
            'bond_code': bond_code,
            'history': progress_history,
        }
    
    # ==================== 信号历史数据 ====================
    
    def save_signal(self, signal: Dict):
        """
        保存监控信号
        
        Args:
            signal: 信号数据
        """
        data = self._load_json(self.signals_file, {'signals': []})
        
        signal_record = {
            'timestamp': datetime.now().isoformat(),
            'date': datetime.now().strftime('%Y-%m-%d'),
            **signal,
        }
        
        data['signals'].append(signal_record)
        self._save_json(self.signals_file, data)
    
    def get_signals_history(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """
        获取信号历史数据
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            信号历史记录
        """
        data = self._load_json(self.signals_file, {'signals': []})
        signals = data.get('signals', [])
        
        if start_date:
            signals = [s for s in signals if s['date'] >= start_date]
        if end_date:
            signals = [s for s in signals if s['date'] <= end_date]
        
        return signals
    
    # ==================== 结果跟踪数据 ====================
    
    def save_outcome(self, outcome: Dict):
        """
        保存信号结果（用于自我进化）
        
        Args:
            outcome: 结果数据
            {
                'bond_code': '123456',
                'signal_date': '2026-04-22',
                'signal_type': 'latent',
                'entry_price': 45.80,
                'exit_price': 48.50,
                'exit_date': '2026-04-25',
                'return': 5.9,
                'success': True,
                'hold_days': 3,
            }
        """
        data = self._load_json(self.outcomes_file, {'outcomes': []})
        data['outcomes'].append(outcome)
        self._save_json(self.outcomes_file, data)
    
    def get_outcomes_history(self, signal_type: str = None) -> List[Dict]:
        """
        获取结果历史数据
        
        Args:
            signal_type: 信号类型 (latent/entry)
        
        Returns:
            结果历史记录
        """
        data = self._load_json(self.outcomes_file, {'outcomes': []})
        outcomes = data.get('outcomes', [])
        
        if signal_type:
            outcomes = [o for o in outcomes if o.get('signal_type') == signal_type]
        
        return outcomes
    
    # ==================== 进化统计 ====================
    
    def update_evolution_stats(self):
        """
        更新进化统计（基于历史结果）
        
        Returns:
            统计结果
        """
        outcomes = self.get_outcomes_history()
        
        if not outcomes:
            stats = {
                'total_signals': 0,
                'success_rate': 0,
                'avg_return': 0,
                'avg_hold_days': 0,
                'best_return': 0,
                'worst_return': 0,
                'last_updated': datetime.now().isoformat(),
            }
        else:
            success_count = sum(1 for o in outcomes if o.get('success', False))
            returns = [o.get('return', 0) for o in outcomes]
            hold_days = [o.get('hold_days', 0) for o in outcomes]
            
            stats = {
                'total_signals': len(outcomes),
                'success_rate': success_count / len(outcomes) * 100,
                'avg_return': sum(returns) / len(returns),
                'avg_hold_days': sum(hold_days) / len(hold_days) if hold_days else 0,
                'best_return': max(returns),
                'worst_return': min(returns),
                'last_updated': datetime.now().isoformat(),
                
                # 按信号类型统计
                'by_type': self._calc_stats_by_type(outcomes),
                
                # 按股票质量统计
                'by_quality': self._calc_stats_by_quality(outcomes),
                
                # 按时间窗口统计
                'by_window': self._calc_stats_by_window(outcomes),
            }
        
        self._save_json(self.stats_file, stats)
        return stats
    
    def _calc_stats_by_type(self, outcomes: List[Dict]) -> Dict:
        """按信号类型统计"""
        types = {}
        for o in outcomes:
            sig_type = o.get('signal_type', 'unknown')
            if sig_type not in types:
                types[sig_type] = {'count': 0, 'success': 0, 'total_return': 0}
            types[sig_type]['count'] += 1
            if o.get('success', False):
                types[sig_type]['success'] += 1
            types[sig_type]['total_return'] += o.get('return', 0)
        
        for t in types.values():
            t['success_rate'] = t['success'] / t['count'] * 100 if t['count'] > 0 else 0
            t['avg_return'] = t['total_return'] / t['count'] if t['count'] > 0 else 0
        
        return types
    
    def _calc_stats_by_quality(self, outcomes: List[Dict]) -> Dict:
        """按股票质量统计"""
        quality_stats = {'A': [], 'B': [], 'C': [], 'D': []}
        
        for o in outcomes:
            rating = o.get('stock_quality', {}).get('rating', 'N/A')
            if rating in quality_stats:
                quality_stats[rating].append(o)
        
        result = {}
        for rating, outcomes_list in quality_stats.items():
            if outcomes_list:
                success = sum(1 for o in outcomes_list if o.get('success', False))
                returns = [o.get('return', 0) for o in outcomes_list]
                result[rating] = {
                    'count': len(outcomes_list),
                    'success_rate': success / len(outcomes_list) * 100,
                    'avg_return': sum(returns) / len(returns),
                }
        
        return result
    
    def _calc_stats_by_window(self, outcomes: List[Dict]) -> Dict:
        """按时间窗口统计（上市后天数）"""
        windows = {
            '25-35': [],
            '36-45': [],
            '46-55': [],
            '56+': [],
        }
        
        for o in outcomes:
            days = o.get('days_since_tongguo', 0)
            if 25 <= days <= 35:
                windows['25-35'].append(o)
            elif 36 <= days <= 45:
                windows['36-45'].append(o)
            elif 46 <= days <= 55:
                windows['46-55'].append(o)
            elif days > 55:
                windows['56+'].append(o)
        
        result = {}
        for window, outcomes_list in windows.items():
            if outcomes_list:
                success = sum(1 for o in outcomes_list if o.get('success', False))
                returns = [o.get('return', 0) for o in outcomes_list]
                result[window] = {
                    'count': len(outcomes_list),
                    'success_rate': success / len(outcomes_list) * 100,
                    'avg_return': sum(returns) / len(returns),
                }
        
        return result
    
    def get_evolution_stats(self) -> Dict:
        """获取进化统计"""
        return self._load_json(self.stats_file, {})
    
    # ==================== 自我进化建议 ====================
    
    def get_evolution_suggestions(self) -> List[str]:
        """
        基于历史数据生成进化建议
        
        Returns:
            建议列表
        """
        stats = self.update_evolution_stats()
        suggestions = []
        
        if not stats:
            return ['数据不足，需要更多监控案例']
        
        # 按质量评级建议
        by_quality = stats.get('by_quality', {})
        if by_quality.get('D', {}).get('success_rate', 0) < 30:
            suggestions.append('D 级股票成功率低于 30%，建议回避 D 级股票')
        
        if by_quality.get('A', {}).get('success_rate', 0) > 80:
            suggestions.append('A 级股票成功率超过 80%，建议优先参与 A 级')
        
        # 按时间窗口建议
        by_window = stats.get('by_window', {})
        best_window = max(by_window.items(), key=lambda x: x[1].get('success_rate', 0), default=None)
        if best_window and best_window[1].get('success_rate', 0) > 70:
            suggestions.append(f'时间窗口 {best_window[0]} 天成功率最高 ({best_window[1]["success_rate"]:.1f}%)，建议重点关注')
        
        # 总体成功率
        if stats.get('success_rate', 0) > 70:
            suggestions.append(f'总体成功率 {stats["success_rate"]:.1f}%，策略表现优秀！')
        elif stats.get('success_rate', 0) < 50:
            suggestions.append(f'总体成功率 {stats["success_rate"]:.1f}%，建议优化信号条件')
        
        # 平均收益
        if stats.get('avg_return', 0) > 5:
            suggestions.append(f'平均收益 +{stats["avg_return"]:.1f}%，收益表现良好')
        
        return suggestions
    
    # ==================== 工具函数 ====================
    
    def _load_json(self, filepath: str, default: Any = None) -> Any:
        """加载 JSON 文件"""
        if not os.path.exists(filepath):
            return default if default is not None else {}
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return default if default is not None else {}
    
    def _save_json(self, filepath: str, data: Any):
        """保存 JSON 文件"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def export_data(self, output_file: str = None):
        """
        导出数据到文件
        
        Args:
            output_file: 输出文件路径
        """
        if output_file is None:
            output_file = os.path.join(self.data_dir, f'export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
        
        export_data = {
            'export_time': datetime.now().isoformat(),
            'pending_bonds': self.get_pending_bonds_history(),
            'signals': self.get_signals_history(),
            'outcomes': self.get_outcomes_history(),
            'stats': self.get_evolution_stats(),
        }
        
        self._save_json(output_file, export_data)
        print(f'数据已导出到：{output_file}')
        return output_file


# 全局数据库实例
db = LocalDatabase()
