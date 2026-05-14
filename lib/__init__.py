# -*- coding: utf-8 -*-
"""
A 股可转债分析工具库

模块说明:
- data_source: 数据源接口 (集思录/东方财富)
- bond_calculator: 配债额度、盈亏计算
- report: 报告生成器
- stock_quality: 股票质量评估
- signal_tracker: 信号跟踪
- self_evolution: 自我进化
- sqlite_database: SQLite 数据库
- local_database: 本地数据存储
- monitor_db: 监控数据库
- backtest_cache: 回测缓存数据库
"""

__version__ = '1.0.0'

from .data_source import EastmoneyAPI, BaoStockAPI
from .bond_calculator import BondCalculator, QuequanAnalysis
from .report import ReportGenerator
from .backtest_cache import BacktestCache
from .monitor_db import MonitorDB

__all__ = [
    'EastmoneyAPI',
    'BaoStockAPI',
    'BondCalculator',
    'QuequanAnalysis',
    'ReportGenerator',
    'BacktestCache',
    'MonitorDB',
]
