#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票质量评估测试脚本

测试股票质量评估模块的功能
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.data_source import SinaFinanceAPI
from lib.stock_quality import StockQualityEvaluator, print_quality_report


def test_stock_quality():
    """测试股票质量评估"""
    sina = SinaFinanceAPI(timeout=30)
    evaluator = StockQualityEvaluator(sina_api=sina)
    
    # 测试股票代码列表（可以修改）
    test_stocks = [
        '300622',  # 博士眼镜
        '688001',  # 华兴源创
        '002475',  # 立讯精密
    ]
    
    print('=' * 80)
    print('股票质量评估测试')
    print('=' * 80)
    print()
    
    for stock_code in test_stocks:
        print(f'评估股票：{stock_code}')
        print('-' * 60)
        
        quality = evaluator.evaluate(stock_code)
        
        print(print_quality_report(quality))
        print()
        print()
    
    # 显示评级统计
    print('=' * 80)
    print('评估总结')
    print('=' * 80)
    
    ratings = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'N/A': 0}
    for stock_code in test_stocks:
        quality = evaluator.evaluate(stock_code)
        rating = quality.get('rating', 'N/A')
        if rating in ratings:
            ratings[rating] += 1
    
    print(f'A 级 (优质): {ratings["A"]} 只')
    print(f'B 级 (良好): {ratings["B"]} 只')
    print(f'C 级 (一般): {ratings["C"]} 只')
    print(f'D 级 (差): {ratings["D"]} 只')
    print(f'N/A (数据不足): {ratings["N/A"]} 只')


if __name__ == '__main__':
    test_stock_quality()
