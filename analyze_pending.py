#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
待发转债分析 (公告前即可获取)

从集思录 API 获取待发转债信息，在公告发布前发现配债机会。

优势:
- 比东方财富公告提前获取信息
- 包含申购代码、配售代码、股权登记日、每股配售额
- 可提前计算配债额度和所需资金

Usage:
    # 查看待发转债列表
    python analyze_pending.py
    
    # 紧凑摘要模式 (适合聊天)
    python analyze_pending.py --compact
    
    # 分析前 N 只
    python analyze_pending.py --limit 5
    
    # 输出 JSON 格式
    python analyze_pending.py --format json
    
    # 保存到文件
    python analyze_pending.py --output pending.txt
"""

import argparse
import sys
import os
from datetime import datetime

# 添加 lib 目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.data_source import BondDataSource, JisiluAPI
from lib.bond_calculator import BondCalculator


def fetch_pending_bonds(limit: int = 50, use_fallback: bool = True) -> tuple:
    """
    获取待发转债列表 (优先集思录，失败降级东方财富)
    
    Args:
        limit: 返回数量限制
        use_fallback: 是否启用降级
        
    Returns:
        (bonds_list, source_name) 元组
        source_name: 'jisilu' | 'eastmoney' | 'none'
    """
    if use_fallback:
        # 使用统一数据源 (带降级)
        ds = BondDataSource()
        bonds = ds.fetch_bonds(limit=limit, pending_only=True)
        return bonds, ds.last_source
    else:
        # 直接使用集思录
        jsl = JisiluAPI()
        bonds = jsl.fetch_pending_bonds(limit=limit)
        source = 'jisilu' if bonds else 'none'
        return bonds, source


def print_pending_list(bonds: list, source: str = 'jisilu', compact: bool = False):
    """
    打印待发转债列表
    
    Args:
        bonds: 转债列表
        source: 数据来源 ('jisilu' | 'eastmoney')
        compact: 紧凑模式
    """
    if not bonds:
        print("⚠️  未获取到待发转债数据")
        return
    
    source_name = '集思录' if source == 'jisilu' else '东方财富'
    print(f"📊 {source_name}待发转债列表 (共 {len(bonds)} 只)")
    print(f"数据时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    if compact:
        # 紧凑模式：只显示关键信息
        print(f"{'债券名称':<10} {'股票代码':<10} {'申购日期':<12} {'每股配售':<10} {'发行规模':<10} {'进度'}")
        print("-" * 80)
        
        for bond in bonds:
            bond_name = (str(bond.get('bond_name') or '') or 'N/A')[:10]
            stock_code = str(bond.get('stock_code') or '')
            apply_date = str(bond.get('apply_date') or '') or '待公布'
            
            # 适配不同数据源的字段名
            ration_str = str(bond.get('per_share_amount') or bond.get('ration') or '') if (bond.get('per_share_amount') or bond.get('ration')) else 'N/A'
            amount_str = str(bond.get('issue_amount') or bond.get('amount') or '') if (bond.get('issue_amount') or bond.get('amount')) else 'N/A'
            
            progress = str(bond.get('progress') or '')[:20]
            
            print(f"{bond_name:<10} {stock_code:<10} {apply_date:<12} {ration_str:<10} {amount_str:<10} {progress}")
    else:
        # 完整模式
        for idx, bond in enumerate(bonds, 1):
            # 适配不同数据源的字段名
            bond_name = bond.get('bond_name') or 'N/A'
            bond_code = bond.get('bond_code') or 'N/A'
            stock_name = bond.get('stock_name') or 'N/A'
            stock_code = bond.get('stock_code') or 'N/A'
            apply_date = bond.get('apply_date') or '待公布'
            apply_code = bond.get('apply_code') or bond.get('ration_code') or '待公布'
            ration_code = bond.get('ration_code') or '待公布'
            record_date = bond.get('record_date') or '待公布'
            
            # 每股配售额 (适配不同数据源)
            per_share = bond.get('per_share_amount') or bond.get('ration')
            per_share_str = f"{per_share} 元/股" if per_share else 'N/A'
            
            # 发行规模 (适配不同数据源)
            issue_amt = bond.get('issue_amount') or bond.get('amount')
            issue_str = f"{issue_amt} 亿元" if issue_amt else 'N/A'
            
            convert_price = bond.get('convert_price') or 'N/A'
            if convert_price and convert_price != 'N/A':
                convert_price = f"{convert_price} 元"
            
            rating = bond.get('credit_rating') or bond.get('rating') or 'N/A'
            progress = bond.get('progress') or 'N/A'
            progress_full = bond.get('progress_full', '')
            
            print(f"[{idx}] {bond_name} ({bond_code})")
            print(f"    股票：{stock_name} ({stock_code})")
            print(f"    申购日期：{apply_date}")
            print(f"    申购代码：{apply_code}")
            print(f"    配售代码：{ration_code}")
            print(f"    股权登记日：{record_date}")
            print(f"    每股配售额：{per_share_str}")
            print(f"    转股价：{convert_price}")
            print(f"    发行规模：{issue_str}")
            print(f"    信用评级：{rating}")
            print(f"    当前进度：{progress}")
            if progress_full:
                print(f"    完整进度：{progress_full.replace(chr(10), ' → ')}")
            print()


def calculate_allocation_example(bond: dict, target_bonds: int = 10):
    """
    计算配债额度示例
    
    Args:
        bond: 转债信息
        target_bonds: 目标配债张数
    """
    # 适配不同数据源的字段名
    ration = bond.get('per_share_amount') or bond.get('ration')
    if not ration:
        print("⚠️  每股配售额数据缺失，无法计算")
        return
    
    # 假设当前股价
    current_price = bond.get('record_price', 0)
    if not current_price:
        print("⚠️  股价数据缺失，无法计算")
        return
    
    try:
        ration = float(ration)
        current_price = float(current_price)
    except (ValueError, TypeError):
        print("⚠️  数据格式错误，无法计算")
        return
    
    # 计算配债额度
    # 公式：配债额度 = 持股数 × 每股配售额
    # 可配张数 = floor(配债额度 / 100)
    
    # 目标配债额度
    target_allocation = target_bonds * 100  # 10 张 = 1000 元额度
    
    # 所需持股数
    shares_needed = int(target_allocation / ration) + 1
    
    # 所需资金
    capital_needed = shares_needed * current_price
    
    print(f"💰 配债额度计算示例 (目标：{target_bonds} 张)")
    print(f"    每股配售额：{ration} 元/股")
    print(f"    参考股价：{current_price} 元")
    print(f"    所需持股数：{shares_needed} 股")
    print(f"    所需资金：{capital_needed:,.0f} 元")
    print(f"    预计配债额度：{shares_needed * ration:.2f} 元 → 可配 {int(shares_needed * ration / 100)} 张")
    print()


def main():
    parser = argparse.ArgumentParser(
        description='待发转债分析 (公告前即可获取)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                    # 查看待发转债完整列表
  %(prog)s --limit 5          # 查看前 5 只
  %(prog)s --compact          # 紧凑摘要模式
  %(prog)s --format json      # 输出 JSON 格式
  %(prog)s --output out.txt   # 保存到文件
        """
    )
    
    parser.add_argument(
        '--limit', '-n',
        type=int,
        default=50,
        help='获取数量 (默认：50)'
    )
    
    parser.add_argument(
        '--compact',
        action='store_true',
        help='紧凑摘要模式 (适合聊天界面)'
    )
    
    parser.add_argument(
        '--format', '-f',
        choices=['text', 'json'],
        default='text',
        help='输出格式 (默认：text)'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        help='输出文件路径'
    )
    
    parser.add_argument(
        '--calc',
        type=int,
        default=0,
        help='为第 N 只转债计算配债额度 (默认：不计算)'
    )
    
    args = parser.parse_args()
    
    # 获取数据 (优先集思录，失败降级东方财富)
    print("正在获取待发转债数据 (优先集思录)...", flush=True)
    bonds, source = fetch_pending_bonds(limit=args.limit, use_fallback=True)
    
    if not bonds:
        print("⚠️  获取数据失败，请稍后重试")
        sys.exit(1)
    
    # 显示数据来源
    if source == 'jisilu':
        print(f"✅ 数据来源：集思录 (公告前即可获取)")
    elif source == 'eastmoney':
        print(f"⚠️  集思录不可用，已降级到东方财富")
    print()
    
    # 计算示例 (如果指定)
    if args.calc > 0 and args.calc <= len(bonds):
        print()
        calculate_allocation_example(bonds[args.calc - 1])
    
    # 输出
    if args.format == 'json':
        import json
        content = json.dumps(bonds, ensure_ascii=False, indent=2)
    else:
        import io
        from contextlib import redirect_stdout
        
        f = io.StringIO()
        with redirect_stdout(f):
            print_pending_list(bonds, source=source, compact=args.compact)
        content = f.getvalue()
    
    # 保存或打印
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ 报告已保存到：{args.output}")
    else:
        print(content)


if __name__ == '__main__':
    main()
