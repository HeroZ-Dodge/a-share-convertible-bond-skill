# -*- coding: utf-8 -*-
"""
自我进化模块

基于历史监控数据，自动优化信号判断参数，提升监控准确性。

核心功能:
1. 分析历史信号的成功率
2. 自动调整信号阈值
3. 生成进化建议
4. 持续学习优化
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple


class SelfEvolution:
    """自我进化引擎"""
    
    def __init__(self, db=None):
        """
        初始化进化引擎
        
        Args:
            db: LocalDatabase 实例
        """
        from .local_database import LocalDatabase
        self.db = db if db else LocalDatabase()
        
        # 默认信号参数
        self.default_params = {
            # 潜伏策略参数
            'latent': {
                'min_days_since_tongguo': 25,
                'max_days_since_tongguo': 55,
                'min_price_change_2d': 2.0,  # 2 日涨跌幅阈值
                'min_price_change_5d': 3.0,  # 5 日涨跌幅阈值
                'min_volume_ratio': 1.5,     # 成交量比率阈值
                'min_quality_rating': 'B',   # 最低质量评级
            },
            # 入场时机策略参数
            'entry': {
                'min_quality_rating': 'B',
                'max_days_since_event': 3,
            },
        }
        
        # 加载已进化的参数
        self.evolved_params = self._load_evolved_params()
    
    def _load_evolved_params(self) -> Dict:
        """加载已进化的参数"""
        params_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'data', 'evolved_params.json'
        )
        
        if os.path.exists(params_file):
            try:
                with open(params_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        return self.default_params.copy()
    
    def _save_evolved_params(self):
        """保存进化后的参数"""
        params_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'data', 'evolved_params.json'
        )
        
        os.makedirs(os.path.dirname(params_file), exist_ok=True)
        
        with open(params_file, 'w', encoding='utf-8') as f:
            json.dump(self.evolved_params, f, ensure_ascii=False, indent=2)
    
    def analyze_signal_performance(self, signal_type: str = 'latent') -> Dict:
        """
        分析信号表现
        
        Args:
            signal_type: 信号类型 (latent/entry)
        
        Returns:
            性能分析结果
        """
        outcomes = self.db.get_outcomes_history(signal_type)
        
        if not outcomes:
            return {
                'total': 0,
                'success_rate': 0,
                'avg_return': 0,
                'message': '数据不足，需要更多监控案例',
            }
        
        # 计算统计
        total = len(outcomes)
        success_count = sum(1 for o in outcomes if o.get('success', False))
        returns = [o.get('return', 0) for o in outcomes]
        
        # 按参数分组分析
        param_analysis = self._analyze_by_params(outcomes, signal_type)
        
        return {
            'total': total,
            'success_count': success_count,
            'success_rate': success_count / total * 100,
            'avg_return': sum(returns) / total,
            'best_return': max(returns),
            'worst_return': min(returns),
            'param_analysis': param_analysis,
        }
    
    def _analyze_by_params(self, outcomes: List[Dict], signal_type: str) -> Dict:
        """按参数分组分析"""
        analysis = {}
        
        # 按股票质量分析
        quality_groups = {'A': [], 'B': [], 'C': [], 'D': []}
        for o in outcomes:
            rating = o.get('stock_quality', {}).get('rating', 'N/A')
            if rating in quality_groups:
                quality_groups[rating].append(o)
        
        analysis['by_quality'] = {}
        for rating, group in quality_groups.items():
            if group:
                success = sum(1 for o in group if o.get('success', False))
                returns = [o.get('return', 0) for o in group]
                analysis['by_quality'][rating] = {
                    'count': len(group),
                    'success_rate': success / len(group) * 100,
                    'avg_return': sum(returns) / len(returns),
                }
        
        # 按时间窗口分析
        window_groups = {'25-35': [], '36-45': [], '46-55': [], '56+': []}
        for o in outcomes:
            days = o.get('days_since_tongguo', 0)
            if 25 <= days <= 35:
                window_groups['25-35'].append(o)
            elif 36 <= days <= 45:
                window_groups['36-45'].append(o)
            elif 46 <= days <= 55:
                window_groups['46-55'].append(o)
            elif days > 55:
                window_groups['56+'].append(o)
        
        analysis['by_window'] = {}
        for window, group in window_groups.items():
            if group:
                success = sum(1 for o in group if o.get('success', False))
                returns = [o.get('return', 0) for o in group]
                analysis['by_window'][window] = {
                    'count': len(group),
                    'success_rate': success / len(group) * 100,
                    'avg_return': sum(returns) / len(returns),
                }
        
        # 按信号强度分析
        strength_groups = {'strong': [], 'medium': [], 'weak': []}
        for o in outcomes:
            signals = o.get('signal_count', 0)
            if signals >= 3:
                strength_groups['strong'].append(o)
            elif signals >= 2:
                strength_groups['medium'].append(o)
            else:
                strength_groups['weak'].append(o)
        
        analysis['by_strength'] = {}
        for strength, group in strength_groups.items():
            if group:
                success = sum(1 for o in group if o.get('success', False))
                returns = [o.get('return', 0) for o in group]
                analysis['by_strength'][strength] = {
                    'count': len(group),
                    'success_rate': success / len(group) * 100,
                    'avg_return': sum(returns) / len(returns),
                }
        
        return analysis
    
    def optimize_params(self, signal_type: str = 'latent') -> Dict:
        """
        优化信号参数
        
        Args:
            signal_type: 信号类型
        
        Returns:
            优化后的参数
        """
        analysis = self.analyze_signal_performance(signal_type)
        
        if analysis['total'] < 10:
            return {
                'message': f'数据不足 (当前{analysis["total"]}个案例，需要至少 10 个)',
                'params': self.evolved_params.get(signal_type, self.default_params.get(signal_type, {})),
            }
        
        current_params = self.evolved_params.get(signal_type, self.default_params.get(signal_type, {})).copy()
        param_analysis = analysis.get('param_analysis', {})
        
        # 优化时间窗口
        by_window = param_analysis.get('by_window', {})
        if by_window:
            best_window = max(by_window.items(), key=lambda x: x[1].get('success_rate', 0))
            if best_window[1].get('success_rate', 0) > 70:
                # 解析最佳窗口
                window_range = best_window[0].split('-')
                if len(window_range) == 2:
                    current_params['min_days_since_tongguo'] = int(window_range[0])
                    current_params['max_days_since_tongguo'] = int(window_range[1])
        
        # 优化质量评级要求
        by_quality = param_analysis.get('by_quality', {})
        if by_quality:
            # 找出成功率最高的评级
            best_quality = max(by_quality.items(), key=lambda x: x[1].get('success_rate', 0))
            if best_quality[1].get('success_rate', 0) > 75:
                current_params['min_quality_rating'] = best_quality[0]
        
        # 保存进化后的参数
        self.evolved_params[signal_type] = current_params
        self._save_evolved_params()
        
        return {
            'message': '参数已优化',
            'params': current_params,
            'improvements': self._get_improvement_suggestions(analysis),
        }
    
    def _get_improvement_suggestions(self, analysis: Dict) -> List[str]:
        """获取改进建议"""
        suggestions = []
        param_analysis = analysis.get('param_analysis', {})
        
        # 质量评级建议
        by_quality = param_analysis.get('by_quality', {})
        if by_quality.get('D', {}).get('success_rate', 0) < 40:
            suggestions.append('❌ D 级股票成功率低，建议回避')
        if by_quality.get('A', {}).get('success_rate', 0) > 80:
            suggestions.append('✅ A 级股票成功率高，建议优先')
        
        # 时间窗口建议
        by_window = param_analysis.get('by_window', {})
        if by_window:
            best_window = max(by_window.items(), key=lambda x: x[1].get('success_rate', 0))
            worst_window = min(by_window.items(), key=lambda x: x[1].get('success_rate', 0))
            if best_window[1].get('success_rate', 0) > 70:
                suggestions.append(f'✅ 时间窗口 {best_window[0]} 天表现最佳')
            if worst_window[1].get('success_rate', 0) < 50:
                suggestions.append(f'⚠️ 时间窗口 {worst_window[0]} 天表现较差')
        
        # 信号强度建议
        by_strength = param_analysis.get('by_strength', {})
        if by_strength.get('strong', {}).get('success_rate', 0) > 80:
            suggestions.append('✅ 强信号 (≥3 个) 成功率高，建议只参与强信号')
        
        return suggestions
    
    def get_evolution_report(self) -> str:
        """
        生成进化报告
        
        Returns:
            格式化的报告文本
        """
        lines = []
        lines.append('=' * 60)
        lines.append('🧬 自我进化报告')
        lines.append('=' * 60)
        lines.append(f'生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        lines.append('')
        
        # 潜伏策略
        lines.append('📊 潜伏策略')
        lines.append('-' * 60)
        latent_analysis = self.analyze_signal_performance('latent')
        lines.append(f'总信号数：{latent_analysis["total"]}')
        lines.append(f'成功率：{latent_analysis["success_rate"]:.1f}%')
        lines.append(f'平均收益：{latent_analysis["avg_return"]:+.2f}%')
        
        if latent_analysis.get('param_analysis'):
            lines.append('')
            lines.append('按股票质量:')
            for rating, stats in latent_analysis['param_analysis'].get('by_quality', {}).items():
                lines.append(f'  {rating}级：{stats["count"]}个，成功率{stats["success_rate"]:.1f}%, 平均收益{stats["avg_return"]:+.2f}%')
            
            lines.append('')
            lines.append('按时间窗口:')
            for window, stats in latent_analysis['param_analysis'].get('by_window', {}).items():
                lines.append(f'  {window}天：{stats["count"]}个，成功率{stats["success_rate"]:.1f}%, 平均收益{stats["avg_return"]:+.2f}%')
        
        lines.append('')
        
        # 进化建议
        lines.append('💡 进化建议')
        lines.append('-' * 60)
        suggestions = self.db.get_evolution_suggestions()
        for i, sug in enumerate(suggestions, 1):
            lines.append(f'{i}. {sug}')
        
        lines.append('')
        lines.append('=' * 60)
        
        return '\n'.join(lines)
    
    def auto_evolve(self):
        """
        自动进化（定期调用）
        
        执行所有进化步骤
        """
        # 更新统计
        self.db.update_evolution_stats()
        
        # 优化参数
        self.optimize_params('latent')
        self.optimize_params('entry')
        
        # 生成报告
        report = self.get_evolution_report()
        
        return report


# 全局进化引擎实例
evolution_engine = SelfEvolution()
