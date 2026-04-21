#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可转债抢权配债完整收益分析 (上帝视角)

基于模块化设计，动态获取数据并生成分析报告。

功能:
- 从东方财富 API 获取已上市转债列表
- 从新浪财经 API 获取股票历史价格
- 计算 T-3/T-2/T-1 买入，T+1 卖出的完整盈亏
- 生成文本/JSON/Markdown格式报告

Usage:
    # 实时分析 (默认 2026 年全部上市转债)
    python analyze_quequan_profit.py
    
    # 指定分析数量
    python analyze_quequan_profit.py --limit 5
    
    # 指定年份
    python analyze_quequan_profit.py --year 2025
    
    # 离线测试 (使用内置数据)
    python analyze_quequan_profit.py --offline
    
    # 输出 JSON 格式
    python analyze_quequan_profit.py --format json
    
    # 输出 Markdown格式
    python analyze_quequan_profit.py --format markdown
"""

import argparse
import sys
import os

# 添加 lib 目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.data_source import EastmoneyAPI, SinaFinanceAPI
from lib.bond_calculator import BondCalculator, QuequanAnalysis
from lib.report import ReportGenerator


# ==================== 离线测试数据 ====================

OFFLINE_TEST_DATA = [
    {
        'bond_name': '上 26 转债',
        'bond_code': '118050',
        'stock_code': '688533',
        'stock_name': '上声电子',
        'listing_date': '2026-04-14',
        'record_date': '2026-03-17',
        'credit_rating': 'A+',
        'per_share_amount': 1.9680,
        'first_profit': 523.01,
        'listing_close': 147.546,
    },
    {
        'bond_name': '博士转债',
        'bond_code': '123240',
        'stock_code': '300622',
        'stock_name': '博士眼镜',
        'listing_date': '2026-04-07',
        'record_date': '2026-03-17',
        'credit_rating': 'AA',
        'per_share_amount': 1.6457,
        'first_profit': 422.70,
        'listing_close': 138.427,
    },
    {
        'bond_name': '长高转债',
        'bond_code': '127103',
        'stock_code': '002452',
        'stock_name': '长高电新',
        'listing_date': '2026-03-30',
        'record_date': '2026-03-06',
        'credit_rating': 'AA-',
        'per_share_amount': 1.2228,
        'first_profit': 433.89,
        'listing_close': 139.445,
    },
    {
        'bond_name': '祥和转债',
        'bond_code': '111026',
        'stock_code': '603500',
        'stock_name': '祥和实业',
        'listing_date': '2026-03-26',
        'record_date': '2026-03-02',
        'credit_rating': 'A+',
        'per_share_amount': 1.2010,
        'first_profit': 547.44,
        'listing_close': 154.744,
    },
    {
        'bond_name': '统联转债',
        'bond_code': '118049',
        'stock_code': '688210',
        'stock_name': '统联精密',
        'listing_date': '2026-03-20',
        'record_date': '2026-02-27',
        'credit_rating': 'AA-',
        'per_share_amount': 3.6120,
        'first_profit': 337.54,
        'listing_close': 133.754,
    },
]

OFFLINE_STOCK_PRICES = {
    '688533': {
        '2026-03-12': {'close': 32.48},
        '2026-03-13': {'close': 32.36},
        '2026-03-16': {'close': 31.29},
        '2026-03-17': {'close': 29.66},
        '2026-03-18': {'close': 27.89},
    },
    '300622': {
        '2026-03-12': {'close': 30.10},
        '2026-03-13': {'close': 29.50},
        '2026-03-16': {'close': 28.80},
        '2026-03-17': {'close': 28.56},
        '2026-03-18': {'close': 24.16},
    },
    '002452': {
        '2026-03-03': {'close': 10.80},
        '2026-03-04': {'close': 10.98},
        '2026-03-05': {'close': 11.10},
        '2026-03-06': {'close': 11.28},
        '2026-03-07': {'close': 10.21},
    },
    '603500': {
        '2026-02-25': {'close': 15.20},
        '2026-02-26': {'close': 15.00},
        '2026-02-27': {'close': 14.80},
        '2026-02-28': {'close': 14.50},
        '2026-03-01': {'close': 14.78},
        '2026-03-02': {'close': 14.50},
    },
    '688210': {
        '2026-02-24': {'close': 55.89},
        '2026-02-25': {'close': 56.94},
        '2026-02-26': {'close': 58.00},
        '2026-02-27': {'close': 61.32},
        '2026-02-28': {'close': 39.87},
    },
}


def run_offline(limit: int = 5) -> list:
    """
    离线模式：使用内置测试数据
    
    Args:
        limit: 分析数量
        
    Returns:
        分析结果列表
    """
    print("模式：离线测试 (使用内置数据)")
    print()
    
    calc = BondCalculator(target_bonds=10, bond_price=100.0)
    analyses = []
    
    for bond_info in OFFLINE_TEST_DATA[:limit]:
        analysis = calc.analyze_quequan_profit(bond_info, OFFLINE_STOCK_PRICES)
        analyses.append(analysis)
    
    return analyses


def run_online(limit: int = 0, year: int = 0, month: int = 0, from_month: int = 0) -> list:
    """
    在线模式：从 API 获取实时数据
    
    Args:
        limit: 分析数量 (0=全部)
        year: 筛选年份 (默认 2026)
        month: 指定月份 (0=全年)
        from_month: 从该月份开始 (用于分析 X 月至今)
        
    Returns:
        分析结果列表
    """
    print("数据来源：东方财富 + 新浪财经")
    if from_month > 0:
        print(f"筛选条件：{year}年{from_month}月至今")
    elif month > 0:
        print(f"筛选条件：{year}年{month}月")
    else:
        print(f"筛选条件：{year}年上市")
    print()
    
    # 初始化数据源
    em = EastmoneyAPI()
    sina = SinaFinanceAPI()
    calc = BondCalculator(target_bonds=10, bond_price=100)
    
    # 默认分析 2026 年
    if year == 0:
        year = 2026
    
    # 获取转债列表 (获取足够多的数据)
    fetch_limit = limit if limit > 0 else 200
    print(f"正在获取已上市转债数据...")
    all_bonds = em.fetch_listed_bonds(limit=fetch_limit)
    
    # 筛选指定年份/月份上市的转债
    bonds = []
    for b in all_bonds:
        listing_date = b.get('listing_date', '')
        if not listing_date:
            continue
        
        # 年份筛选
        if not listing_date.startswith(str(year)):
            continue
        
        # 月份筛选
        date_parts = listing_date.split('-')
        if len(date_parts) >= 2:
            bond_month = int(date_parts[1])
            
            # 如果指定了 from_month，筛选该月及之后
            if from_month > 0:
                if bond_month < from_month:
                    continue
            # 如果指定了 month，只筛选该月
            elif month > 0:
                if bond_month != month:
                    continue
        
        bonds.append(b)
    
    # 如果指定了数量限制，取前 N 只
    if limit > 0:
        bonds = bonds[:limit]
    
    if not bonds:
        if month > 0:
            print(f"未找到 {year}年{month}月上市的转债数据")
        else:
            print(f"未找到 {year}年上市的转债数据")
        return []
    
    if month > 0:
        print(f"获取到 {len(bonds)} 只 {year}年{month}月上市的转债")
    else:
        print(f"获取到 {len(bonds)} 只 {year}年上市的转债")
    print()
    
    # 获取股票价格
    print("正在获取股票历史价格...")
    stock_prices = {}
    stock_codes = set(b['stock_code'] for b in bonds if b.get('stock_code'))
    
    # 计算需要的日期范围 (从最早登记日往前 10 天，到最晚上市日后 15 天)
    min_date = None
    max_date = None
    for b in bonds:
        record_date = b.get('record_date', '')
        listing_date = b.get('listing_date', '')
        if record_date:
            if min_date is None or record_date < min_date:
                min_date = record_date
        if listing_date:
            if max_date is None or listing_date > max_date:
                max_date = listing_date
    
    # 计算天数 (从最早登记日到现在)
    from datetime import datetime
    if min_date:
        days_needed = (datetime.now() - datetime.strptime(min_date, '%Y-%m-%d')).days + 15
        days_needed = min(days_needed, 365)  # 最多获取 365 天
    else:
        days_needed = 90
    
    print(f"  日期范围：{min_date or 'N/A'} ~ {max_date or 'N/A'} (获取 {days_needed} 天数据)")
    
    for idx, stock_code in enumerate(sorted(stock_codes), 1):
        print(f"  [{idx}/{len(stock_codes)}] {stock_code}...", end="", flush=True)
        prices = sina.fetch_history(stock_code, days=days_needed)
        if prices:
            stock_prices[stock_code] = prices
            print(f" ✓ ({len(prices)} 天)")
        else:
            print(" ⚠️")
    
    print()
    
    # 获取上市价格并计算分析
    print("正在计算抢权配债收益...")
    for bond in bonds:
        # 获取上市价格
        listing_close = em.fetch_bond_listing_price(
            bond['bond_code'], 
            bond['listing_date']
        )
        bond['listing_close'] = listing_close  # 可以是 None
        
        # 进行分析
        analysis = calc.analyze_quequan_profit(bond, stock_prices)
        yield analysis


def main():
    parser = argparse.ArgumentParser(
        description='可转债抢权配债完整收益分析',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                    # 分析 2026 年全部上市转债 (完整报告)
  %(prog)s --limit 5          # 分析 2026 年最近 5 只
  %(prog)s --year 2025        # 分析 2025 年上市转债
  %(prog)s --year 2025 --month 12  # 分析 2025 年 12 月上市转债
  %(prog)s --compact          # 紧凑摘要模式 (适合聊天界面)
  %(prog)s --offline          # 离线测试模式
  %(prog)s --format json      # 输出 JSON 格式
  %(prog)s --format markdown  # 输出 Markdown格式
  %(prog)s --output report.txt # 保存到文件
        """
    )
    
    parser.add_argument(
        '--compact',
        action='store_true',
        help='使用紧凑摘要模式 (适合聊天界面，不会截断)'
    )
    
    parser.add_argument(
        '--limit', '-n',
        type=int,
        default=0,
        help='分析转债数量 (默认：0=全部)'
    )
    
    parser.add_argument(
        '--year',
        type=int,
        default=0,
        help='分析指定年份上市的转债 (默认：0=2026 年)'
    )
    
    parser.add_argument(
        '--month',
        type=int,
        default=0,
        help='分析指定月份上市的转债 (默认：0=全年)'
    )
    
    parser.add_argument(
        '--from-month',
        type=int,
        default=0,
        help='分析指定月份及之后上市的转债 (默认：0=全年)'
    )
    
    parser.add_argument(
        '--offline',
        action='store_true',
        help='使用离线测试数据 (不调用 API)'
    )
    
    parser.add_argument(
        '--format', '-f',
        choices=['text', 'json', 'markdown'],
        default='text',
        help='输出格式 (默认：text)'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        help='输出文件路径 (默认：stdout)'
    )
    
    args = parser.parse_args()
    
    # 紧凑模式：直接调用紧凑脚本
    if args.compact:
        import subprocess
        cmd = [sys.executable, os.path.join(os.path.dirname(__file__), 'analyze_compact.py')]
        if args.limit > 0:
            cmd.extend(['--limit', str(args.limit)])
        if args.year != 0:
            cmd.extend(['--year', str(args.year)])
        if args.month > 0:
            cmd.extend(['--month', str(args.month)])
        if args.offline:
            cmd.append('--offline')
        subprocess.run(cmd)
        return
    
    # 运行分析
    if args.offline:
        analyses = run_offline(limit=args.limit if args.limit > 0 else 5)
    else:
        analyses = list(run_online(limit=args.limit, year=args.year, month=args.month, from_month=args.from_month))
    
    if not analyses:
        print("没有分析结果")
        sys.exit(1)
    
    # 生成报告
    gen = ReportGenerator(width=120)
    
    if args.format == 'json':
        output = gen.generate_json_report(analyses)
        content = __import__('json').dumps(output, ensure_ascii=False, indent=2)
    elif args.format == 'markdown':
        content = gen.generate_markdown_report(analyses)
    else:
        content = gen.generate_text_report(analyses)
    
    # 输出
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"报告已保存到：{args.output}")
    else:
        # 检测输出长度，如果太长提示使用紧凑模式
        lines = content.split('\n')
        if len(lines) > 200 and not args.output:
            # 先输出完整报告
            print(content)
            # 添加提示
            print("\n" + "="*60)
            print("💡 提示：报告较长，聊天界面可能显示不完整")
            print("   查看紧凑摘要：python analyze_quequan_profit.py --compact")
            print("   保存到文件：python analyze_quequan_profit.py --output report.txt")
            print("="*60)
        else:
            print(content)


if __name__ == '__main__':
    main()
