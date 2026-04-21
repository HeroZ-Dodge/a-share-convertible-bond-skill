# -*- coding: utf-8 -*-
"""
A 股可转债分析工具库

模块说明:
- data_source: 数据源接口 (东方财富、新浪财经 API)
- bond_calculator: 配债额度、盈亏计算
- report: 报告生成器
"""

__version__ = '1.0.0'

from .data_source import EastmoneyAPI, SinaFinanceAPI
from .bond_calculator import BondCalculator, QuequanAnalysis
from .report import ReportGenerator

__all__ = [
    'EastmoneyAPI',
    'SinaFinanceAPI', 
    'BondCalculator',
    'QuequanAnalysis',
    'ReportGenerator',
]
