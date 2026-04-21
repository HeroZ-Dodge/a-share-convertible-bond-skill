# -*- coding: utf-8 -*-
"""
可转债配债计算模块

提供配债额度计算、盈亏分析等功能。

Usage:
    from lib.bond_calculator import BondCalculator, QuequanAnalysis
    
    calc = BondCalculator()
    
    # 计算配债额度
    allocation = calc.calculate_allocation(
        stock_code='300622',
        shares=1500,
        per_share_amount=1.6457,
        bond_price=100
    )
    
    # 进行抢权配债分析
    analysis = calc.analyze_quequan_profit(bond_info, stock_prices)
"""

import math
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AllocationResult:
    """配债额度计算结果"""
    stock_code: str
    stock_name: str = ''
    current_shares: int = 0
    per_share_amount: float = 0.0
    bond_price: float = 100.0
    
    # 计算结果
    theoretical_shares: float = 0.0  # 理论所需股数
    actual_shares: int = 0  # 实际需买入股数 (向上取整到 100)
    actual_bonds: int = 0  # 实际可配债张数
    actual_amount: float = 0.0  # 实际配债金额
    bond_cost: float = 0.0  # 配债所需资金


@dataclass
class QuequanAnalysis:
    """抢权配债完整分析结果"""
    # 债券信息
    bond_name: str = ''
    bond_code: str = ''
    stock_name: str = ''
    stock_code: str = ''
    listing_date: str = ''
    record_date: str = ''
    credit_rating: str = ''
    
    # 配债信息
    per_share_amount: float = 0.0
    issue_amount: float = 0.0
    first_profit: float = 0.0
    
    # 计算结果
    theoretical_shares: float = 0.0
    actual_shares: int = 0
    actual_bonds: int = 0
    actual_amount: float = 0.0
    bond_cost: float = 0.0
    
    # 股价数据
    stock_prices: Dict[str, float] = field(default_factory=lambda: {
        'T-3': 0, 'T-2': 0, 'T-1': 0, 'T+1': 0
    })
    
    # 对应日期
    stock_dates: Dict[str, str] = field(default_factory=lambda: {
        'T-3': '', 'T-2': '', 'T-1': '', 'T+1': ''
    })
    
    # 上市价格
    listing_close: float = 0.0
    
    # 成本计算
    stock_costs: Dict[str, float] = field(default_factory=lambda: {
        'T-3': 0, 'T-2': 0, 'T-1': 0
    })
    
    # 股票盈亏
    stock_profits: Dict[str, float] = field(default_factory=lambda: {
        'T-3': 0, 'T-2': 0, 'T-1': 0
    })
    
    # 配债收益
    bond_profit: float = 0.0
    
    # 总盈亏
    total_costs: Dict[str, float] = field(default_factory=lambda: {
        'T-3': 0, 'T-2': 0, 'T-1': 0
    })
    total_profits: Dict[str, float] = field(default_factory=lambda: {
        'T-3': 0, 'T-2': 0, 'T-1': 0
    })
    
    # 收益率
    rois: Dict[str, float] = field(default_factory=lambda: {
        'T-3': 0, 'T-2': 0, 'T-1': 0
    })
    
    # 是否有股票数据
    has_stock_data: bool = False


class BondCalculator:
    """可转债配债计算器"""
    
    def __init__(self, target_bonds: int = 10, bond_price: float = 100.0):
        """
        初始化计算器
        
        Args:
            target_bonds: 目标配债张数 (默认 10 张=1 手)
            bond_price: 转债发行价格 (默认 100 元)
        """
        self.target_bonds = target_bonds
        self.bond_price = bond_price
    
    def calculate_allocation(
        self,
        stock_code: str,
        shares: int,
        per_share_amount: float,
        stock_name: str = ''
    ) -> AllocationResult:
        """
        计算配债额度
        
        Args:
            stock_code: 股票代码
            shares: 当前持股数
            per_share_amount: 每股配售额 (元/股)
            stock_name: 股票名称
            
        Returns:
            AllocationResult: 配债额度计算结果
        """
        result = AllocationResult(
            stock_code=stock_code,
            stock_name=stock_name,
            current_shares=shares,
            per_share_amount=per_share_amount,
            bond_price=self.bond_price
        )
        
        if per_share_amount <= 0:
            return result
        
        # 计算理论所需股数
        target_amount = self.target_bonds * 100  # 10 张 = 1000 元
        result.theoretical_shares = target_amount / per_share_amount
        
        # 向上取整到 100 股的整数倍
        result.actual_shares = math.ceil(result.theoretical_shares / 100) * 100
        
        # 计算实际可配债数量
        result.actual_amount = result.actual_shares * per_share_amount
        result.actual_bonds = int(result.actual_amount / 100)
        result.bond_cost = result.actual_bonds * self.bond_price
        
        return result
    
    def analyze_quequan_profit(
        self,
        bond_info: Dict[str, Any],
        stock_prices: Dict[str, Dict[str, float]]
    ) -> QuequanAnalysis:
        """
        进行抢权配债完整收益分析
        
        Args:
            bond_info: 债券信息 (来自 EastmoneyAPI.fetch_listed_bonds)
            stock_prices: 股价数据 {stock_code: {date: {close, ...}}}
            
        Returns:
            QuequanAnalysis: 分析结果
        """
        analysis = QuequanAnalysis(
            bond_name=bond_info.get('bond_name', ''),
            bond_code=bond_info.get('bond_code', ''),
            stock_name=bond_info.get('stock_name', ''),
            stock_code=bond_info.get('stock_code', ''),
            listing_date=bond_info.get('listing_date', ''),
            record_date=bond_info.get('record_date', ''),
            credit_rating=bond_info.get('credit_rating', ''),
            per_share_amount=bond_info.get('per_share_amount', 0),
            issue_amount=bond_info.get('issue_amount', 0),
            first_profit=bond_info.get('first_profit', 0),
        )
        
        if not analysis.record_date or not analysis.listing_date:
            return analysis
        
        # 计算配债额度
        target_amount = self.target_bonds * 100
        analysis.theoretical_shares = target_amount / analysis.per_share_amount if analysis.per_share_amount > 0 else 0
        analysis.actual_shares = math.ceil(analysis.theoretical_shares / 100) * 100
        analysis.actual_amount = analysis.actual_shares * analysis.per_share_amount
        analysis.actual_bonds = int(analysis.actual_amount / 100)
        analysis.bond_cost = analysis.actual_bonds * self.bond_price
        
        # 获取股价数据
        stock_code = analysis.stock_code
        if stock_code in stock_prices:
            prices = stock_prices[stock_code]
            analysis.has_stock_data = True
            
            # 查找交易日价格
            sorted_dates = sorted(prices.keys())
            record_idx = None
            for i, d in enumerate(sorted_dates):
                if d >= analysis.record_date:
                    record_idx = i
                    break
            
            if record_idx is not None and record_idx > 0:
                # T-1, T-2, T-3
                if record_idx - 1 >= 0:
                    analysis.stock_prices['T-1'] = prices[sorted_dates[record_idx - 1]]['close']
                    analysis.stock_dates['T-1'] = sorted_dates[record_idx - 1]
                if record_idx - 2 >= 0:
                    analysis.stock_prices['T-2'] = prices[sorted_dates[record_idx - 2]]['close']
                    analysis.stock_dates['T-2'] = sorted_dates[record_idx - 2]
                if record_idx - 3 >= 0:
                    analysis.stock_prices['T-3'] = prices[sorted_dates[record_idx - 3]]['close']
                    analysis.stock_dates['T-3'] = sorted_dates[record_idx - 3]
            
            # T+1
            if record_idx is not None and record_idx + 1 < len(sorted_dates):
                analysis.stock_prices['T+1'] = prices[sorted_dates[record_idx + 1]]['close']
                analysis.stock_dates['T+1'] = sorted_dates[record_idx + 1]
        
        # 获取上市价格
        listing_close = bond_info.get('listing_close')
        if listing_close is None or listing_close == 0:
            # 使用 FIRST_PROFIT 反推
            if analysis.first_profit > 0 and analysis.actual_bonds > 0:
                analysis.listing_close = analysis.first_profit / analysis.actual_bonds + 100
            else:
                analysis.listing_close = 100.0  # 默认发行价
        else:
            analysis.listing_close = float(listing_close)
        
        # 计算股票成本
        analysis.stock_costs['T-3'] = analysis.actual_shares * analysis.stock_prices['T-3'] if analysis.stock_prices['T-3'] > 0 else 0
        analysis.stock_costs['T-2'] = analysis.actual_shares * analysis.stock_prices['T-2'] if analysis.stock_prices['T-2'] > 0 else 0
        analysis.stock_costs['T-1'] = analysis.actual_shares * analysis.stock_prices['T-1'] if analysis.stock_prices['T-1'] > 0 else 0
        
        # 卖出价值 (T+1 价格)
        sell_price = analysis.stock_prices['T+1'] if analysis.stock_prices['T+1'] > 0 else 0
        stock_sell_value = analysis.actual_shares * sell_price if sell_price > 0 else 0
        
        # 股票盈亏
        analysis.stock_profits['T-3'] = stock_sell_value - analysis.stock_costs['T-3'] if analysis.stock_costs['T-3'] > 0 else 0
        analysis.stock_profits['T-2'] = stock_sell_value - analysis.stock_costs['T-2'] if analysis.stock_costs['T-2'] > 0 else 0
        analysis.stock_profits['T-1'] = stock_sell_value - analysis.stock_costs['T-1'] if analysis.stock_costs['T-1'] > 0 else 0
        
        # 配债收益
        bond_sell_value = analysis.actual_bonds * analysis.listing_close if analysis.listing_close > 0 else 0
        analysis.bond_profit = bond_sell_value - analysis.bond_cost if analysis.bond_cost > 0 else 0
        
        # 总盈亏
        for key in ['T-3', 'T-2', 'T-1']:
            analysis.total_costs[key] = analysis.stock_costs[key] + analysis.bond_cost
            analysis.total_profits[key] = analysis.stock_profits[key] + analysis.bond_profit
            if analysis.total_costs[key] > 0:
                analysis.rois[key] = analysis.total_profits[key] / analysis.total_costs[key] * 100
        
        return analysis
    
    def calculate_min_shares_for_profit(
        self,
        per_share_amount: float,
        expected_stock_drop_pct: float,
        bond_expected_price: float = 140.0
    ) -> Dict[str, Any]:
        """
        计算在预期股价下跌情况下的最小持股要求
        
        Args:
            per_share_amount: 每股配售额
            expected_stock_drop_pct: 预期股价下跌百分比 (正数)
            bond_expected_price: 预期转债上市价格
            
        Returns:
            计算结果字典
        """
        # 配债收益
        bond_profit_per_share = (bond_expected_price - 100) * per_share_amount / 100
        
        # 盈亏平衡点：配债收益 = 股票亏损
        # bond_profit_per_share = current_price * drop_pct
        # 所以只要配债收益 > 0，就值得参与 (短期持有)
        
        return {
            'per_share_amount': per_share_amount,
            'expected_drop_pct': expected_stock_drop_pct,
            'bond_profit_per_share': bond_profit_per_share,
            'break_even_drop_pct': bond_profit_per_share / 100 * 100 if bond_profit_per_share > 0 else 0,
            'recommendation': '值得参与' if bond_profit_per_share > 0 else '不建议参与'
        }
