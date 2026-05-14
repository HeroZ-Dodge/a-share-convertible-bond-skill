# -*- coding: utf-8 -*-
"""
股票质量评估模块

基于技术面指标评估正股质量，用于优化可转债抢权配债策略的选股。

评估维度:
1. 趋势评分 (40 分): 均线系统、价格趋势
2. 动量评分 (30 分): 近期涨跌幅、相对强度
3. 成交量评分 (20 分): 量价关系、成交量趋势
4. 波动性评分 (10 分): 价格稳定性

总分 100 分，评级:
- A 级 (80-100): 优质股，强烈推荐
- B 级 (60-79): 良好股，可以参与
- C 级 (40-59): 一般股，谨慎参与
- D 级 (0-39): 差股，建议回避
"""

import math
from typing import Dict, List, Optional, Any


class StockQualityEvaluator:
    """股票质量评估器"""
    
    def __init__(self, kline_cache=None):
        """
        初始化评估器

        Args:
            kline_cache: BacktestCache 实例，用于获取K线数据
        """
        self.kline_cache = kline_cache
    
    def evaluate(self, stock_code: str, prices: Optional[Dict] = None) -> Dict[str, Any]:
        """
        评估股票质量
        
        Args:
            stock_code: 股票代码
            prices: 可选的股价数据字典 {date: {open, close, high, low, volume}}
                   如果不提供，会优先从传入的 kline_cache 读取
            
        Returns:
            评估结果字典:
            - stock_code: 股票代码
            - total_score: 总分 (0-100)
            - rating: 评级 (A/B/C/D)
            - trend_score: 趋势评分 (0-40)
            - momentum_score: 动量评分 (0-30)
            - volume_score: 成交量评分 (0-20)
            - volatility_score: 波动性评分 (0-10)
            - signals: 信号列表 (利好/利空)
            - recommendation: 推荐意见
        """
        # 获取股价数据
        if prices is None and self.kline_cache:
            prices = self.kline_cache.get_kline_as_dict(stock_code, days=90)
        
        if not prices or len(prices) < 20:
            return {
                'stock_code': stock_code,
                'total_score': 0,
                'rating': 'N/A',
                'trend_score': 0,
                'momentum_score': 0,
                'volume_score': 0,
                'volatility_score': 0,
                'signals': ['数据不足，无法评估'],
                'recommendation': '数据不足，建议回避',
            }
        
        # 计算各项评分
        trend_score = self._calc_trend_score(prices)
        momentum_score = self._calc_momentum_score(prices)
        volume_score = self._calc_volume_score(prices)
        volatility_score = self._calc_volatility_score(prices)
        
        total_score = trend_score + momentum_score + volume_score + volatility_score
        
        # 确定评级
        rating = self._get_rating(total_score)
        
        # 生成信号和建议
        signals = self._generate_signals(prices, trend_score, momentum_score, volume_score)
        recommendation = self._get_recommendation(rating, signals)
        
        return {
            'stock_code': stock_code,
            'total_score': total_score,
            'rating': rating,
            'trend_score': trend_score,
            'momentum_score': momentum_score,
            'volume_score': volume_score,
            'volatility_score': volatility_score,
            'signals': signals,
            'recommendation': recommendation,
        }
    
    def _calc_trend_score(self, prices: Dict) -> float:
        """
        计算趋势评分 (0-40 分)
        
        评估指标:
        - 均线排列 (20 分): 短期均线在长期均线上方为多头排列
        - 价格趋势 (20 分): 当前价格在 60 日/30 日/10 日均线上方
        """
        score = 0
        sorted_dates = sorted(prices.keys())
        latest_date = sorted_dates[-1]
        latest_close = prices[latest_date]['close']
        
        # 计算均线
        ma5 = self._calc_ma(prices, 5)
        ma10 = self._calc_ma(prices, 10)
        ma20 = self._calc_ma(prices, 20)
        ma60 = self._calc_ma(prices, 60)
        
        # 均线排列评分 (20 分)
        if ma5 and ma10 and ma20 and ma60:
            if ma5 > ma10 > ma20 > ma60:
                # 完美多头排列
                score += 20
            elif ma5 > ma10 > ma20:
                # 短期多头排列
                score += 15
            elif ma5 > ma10:
                # 超短期多头
                score += 10
            elif ma10 > ma20:
                # 弱多头
                score += 5
            elif ma60 > ma20 > ma10 > ma5:
                # 完美空头排列 (扣分)
                score += 0
            else:
                # 震荡
                score += 8
        
        # 价格趋势评分 (20 分)
        if ma60 and latest_close > ma60:
            score += 10  # 在 60 日均线上方
        if ma20 and latest_close > ma20:
            score += 7   # 在 20 日均线上方
        if ma10 and latest_close > ma10:
            score += 3   # 在 10 日均线上方
        
        return min(40, score)
    
    def _calc_momentum_score(self, prices: Dict) -> float:
        """
        计算动量评分 (0-30 分)
        
        评估指标:
        - 5 日涨跌幅 (10 分)
        - 10 日涨跌幅 (10 分)
        - 20 日涨跌幅 (10 分)
        """
        score = 0
        sorted_dates = sorted(prices.keys())
        latest_close = prices[sorted_dates[-1]]['close']
        
        # 5 日涨跌幅
        if len(sorted_dates) >= 5:
            close_5d_ago = prices[sorted_dates[-5]]['close']
            change_5d = (latest_close - close_5d_ago) / close_5d_ago * 100
            if change_5d > 5:
                score += 10
            elif change_5d > 2:
                score += 8
            elif change_5d > 0:
                score += 5
            elif change_5d > -5:
                score += 3
            else:
                score += 0
        
        # 10 日涨跌幅
        if len(sorted_dates) >= 10:
            close_10d_ago = prices[sorted_dates[-10]]['close']
            change_10d = (latest_close - close_10d_ago) / close_10d_ago * 100
            if change_10d > 10:
                score += 10
            elif change_10d > 5:
                score += 8
            elif change_10d > 0:
                score += 5
            elif change_10d > -5:
                score += 3
            else:
                score += 0
        
        # 20 日涨跌幅
        if len(sorted_dates) >= 20:
            close_20d_ago = prices[sorted_dates[-20]]['close']
            change_20d = (latest_close - close_20d_ago) / close_20d_ago * 100
            if change_20d > 15:
                score += 10
            elif change_20d > 8:
                score += 8
            elif change_20d > 0:
                score += 5
            elif change_20d > -10:
                score += 3
            else:
                score += 0
        
        return min(30, score)
    
    def _calc_volume_score(self, prices: Dict) -> float:
        """
        计算成交量评分 (0-20 分)
        
        评估指标:
        - 量价配合 (10 分): 上涨时放量、下跌时缩量为佳
        - 成交量趋势 (10 分): 近期成交量是否温和放大
        """
        score = 0
        sorted_dates = sorted(prices.keys())
        
        if len(sorted_dates) < 10:
            return score
        
        # 量价配合评分 (10 分)
        recent_days = sorted_dates[-10:]
        up_volume_days = 0
        down_volume_days = 0
        total_change_days = 0
        
        avg_volume = sum(prices[d]['volume'] for d in recent_days) / len(recent_days)
        
        for i in range(1, len(recent_days)):
            prev_close = prices[recent_days[i-1]]['close']
            curr_close = prices[recent_days[i]]['close']
            curr_volume = prices[recent_days[i]]['volume']
            
            if curr_close > prev_close:
                total_change_days += 1
                if curr_volume > avg_volume:
                    up_volume_days += 1  # 上涨放量 - 好
            elif curr_close < prev_close:
                total_change_days += 1
                if curr_volume < avg_volume:
                    down_volume_days += 1  # 下跌缩量 - 好
        
        if total_change_days > 0:
            volume_ratio = (up_volume_days + down_volume_days) / total_change_days
            score += int(volume_ratio * 10)
        
        # 成交量趋势评分 (10 分)
        if len(sorted_dates) >= 20:
            recent_5d_vol = sum(prices[sorted_dates[-i]]['volume'] for i in range(1, 6)) / 5
            prev_5d_vol = sum(prices[sorted_dates[-i]]['volume'] for i in range(6, 11)) / 5
            
            if recent_5d_vol > prev_5d_vol * 1.2:
                score += 10  # 明显放量
            elif recent_5d_vol > prev_5d_vol:
                score += 7   # 温和放量
            elif recent_5d_vol > prev_5d_vol * 0.8:
                score += 5   # 持平
            else:
                score += 3   # 缩量
        
        return min(20, score)
    
    def _calc_volatility_score(self, prices: Dict) -> float:
        """
        计算波动性评分 (0-10 分)
        
        评估指标:
        - 价格稳定性：波动率适中为佳 (过高或过低都扣分)
        """
        score = 5  # 基础分
        sorted_dates = sorted(prices.keys())
        
        if len(sorted_dates) < 20:
            return score
        
        # 计算 20 日波动率
        daily_returns = []
        for i in range(1, min(20, len(sorted_dates))):
            prev_close = prices[sorted_dates[-i-1]]['close']
            curr_close = prices[sorted_dates[-i]]['close']
            daily_return = (curr_close - prev_close) / prev_close
            daily_returns.append(daily_return)
        
        if daily_returns:
            # 计算标准差
            avg_return = sum(daily_returns) / len(daily_returns)
            variance = sum((r - avg_return) ** 2 for r in daily_returns) / len(daily_returns)
            std_dev = math.sqrt(variance)
            
            # 年化波动率
            annual_vol = std_dev * math.sqrt(252) * 100
            
            # 波动率评分
            if 15 <= annual_vol <= 40:
                score += 5  # 适中
            elif 10 <= annual_vol < 15 or 40 < annual_vol <= 60:
                score += 3  # 偏低或偏高
            elif annual_vol < 10:
                score += 1  # 过低，缺乏弹性
            else:
                score += 0  # 过高，风险大
        
        return min(10, score)
    
    def _calc_ma(self, prices: Dict, period: int) -> Optional[float]:
        """计算移动平均线"""
        sorted_dates = sorted(prices.keys())
        if len(sorted_dates) < period:
            return None
        
        recent_closes = [prices[sorted_dates[-i]]['close'] for i in range(1, period + 1)]
        return sum(recent_closes) / period
    
    def _get_rating(self, total_score: float) -> str:
        """根据总分确定评级"""
        if total_score >= 80:
            return 'A'
        elif total_score >= 60:
            return 'B'
        elif total_score >= 40:
            return 'C'
        else:
            return 'D'
    
    def _generate_signals(self, prices: Dict, trend_score: float, momentum_score: float, volume_score: float) -> List[str]:
        """生成利好/利空信号"""
        signals = []
        sorted_dates = sorted(prices.keys())
        latest_close = prices[sorted_dates[-1]]['close']
        
        # 趋势信号
        ma20 = self._calc_ma(prices, 20)
        ma60 = self._calc_ma(prices, 60)
        if ma20 and latest_close > ma20:
            signals.append('✅ 价格在 20 日均线上方')
        elif ma20:
            signals.append('⚠️ 价格在 20 日均线下方')
        
        if ma60 and latest_close > ma60:
            signals.append('✅ 价格在 60 日均线上方')
        elif ma60:
            signals.append('⚠️ 价格在 60 日均线下方')
        
        # 动量信号
        if len(sorted_dates) >= 10:
            close_10d_ago = prices[sorted_dates[-10]]['close']
            change_10d = (latest_close - close_10d_ago) / close_10d_ago * 100
            if change_10d > 5:
                signals.append(f'✅ 10 日涨幅 +{change_10d:.1f}%')
            elif change_10d < -5:
                signals.append(f'❌ 10 日跌幅 {change_10d:.1f}%')
            else:
                signals.append(f'➖ 10 日涨跌 {change_10d:+.1f}%')
        
        # 成交量信号
        if volume_score >= 15:
            signals.append('✅ 成交量配合良好')
        elif volume_score >= 10:
            signals.append('➖ 成交量一般')
        else:
            signals.append('⚠️ 成交量配合较差')
        
        return signals
    
    def _get_recommendation(self, rating: str, signals: List[str]) -> str:
        """根据评级和信号生成推荐意见"""
        positive_signals = sum(1 for s in signals if s.startswith('✅'))
        negative_signals = sum(1 for s in signals if s.startswith('❌') or s.startswith('⚠️'))
        
        if rating == 'A':
            return '🟢 优质股，强烈推荐参与'
        elif rating == 'B':
            if positive_signals > negative_signals:
                return '🟢 良好股，推荐参与'
            else:
                return '🟡 良好股，可谨慎参与'
        elif rating == 'C':
            return '🟡 一般股，建议观望或轻仓'
        else:
            return '🔴 差股，建议回避'
    
    def filter_bonds_by_stock_quality(
        self,
        bonds: List[Dict[str, Any]],
        min_rating: str = 'B',
        min_score: float = 60
    ) -> List[Dict[str, Any]]:
        """
        根据股票质量筛选转债
        
        Args:
            bonds: 转债列表 (包含 stock_code 字段)
            min_rating: 最低评级要求 ('A'/'B'/'C'/'D')
            min_score: 最低分数要求
            
        Returns:
            符合条件的转债列表 (添加了 stock_quality 字段)
        """
        rating_order = {'A': 4, 'B': 3, 'C': 2, 'D': 1}
        min_rating_value = rating_order.get(min_rating, 3)
        
        filtered = []
        for bond in bonds:
            stock_code = bond.get('stock_code', '')
            if not stock_code:
                continue
            
            quality = self.evaluate(stock_code)
            bond_with_quality = bond.copy()
            bond_with_quality['stock_quality'] = quality
            
            # 筛选
            if quality['total_score'] >= min_score and rating_order.get(quality['rating'], 0) >= min_rating_value:
                filtered.append(bond_with_quality)
        
        return filtered


def print_quality_report(quality: Dict[str, Any]) -> str:
    """
    格式化输出股票质量评估报告
    
    Args:
        quality: 评估结果字典
        
    Returns:
        格式化的报告字符串
    """
    lines = []
    lines.append(f"📊 股票质量评估：{quality['stock_code']}")
    lines.append(f"   总分：{quality['total_score']:.1f}/100 | 评级：{quality['rating']}")
    lines.append(f"   ── 趋势：{quality['trend_score']:.1f}/40 | 动量：{quality['momentum_score']:.1f}/30 | 成交量：{quality['volume_score']:.1f}/20 | 波动性：{quality['volatility_score']:.1f}/10")
    lines.append(f"   推荐：{quality['recommendation']}")
    
    if quality.get('signals'):
        lines.append("   信号:")
        for signal in quality['signals'][:5]:  # 最多显示 5 个信号
            lines.append(f"     {signal}")
    
    return '\n'.join(lines)
