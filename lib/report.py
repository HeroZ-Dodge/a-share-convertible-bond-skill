# -*- coding: utf-8 -*-
"""
报告生成模块

提供多种格式的报告输出 (文本、JSON、Markdown)。

Usage:
    from lib.report import ReportGenerator
    
    gen = ReportGenerator()
    
    # 生成文本报告
    text = gen.generate_text_report(analyses)
    print(text)
    
    # 生成 JSON 报告
    json_data = gen.generate_json_report(analyses)
    
    # 生成 Markdown 报告
    md = gen.generate_markdown_report(analyses)
"""

import json
from typing import List, Dict, Any
from datetime import datetime

from .bond_calculator import QuequanAnalysis


class ReportGenerator:
    """报告生成器"""
    
    def __init__(self, width: int = 120, compact: bool = False):
        """
        初始化报告生成器
        
        Args:
            width: 输出宽度 (字符数)
            compact: 紧凑模式 (缩短表格，适合聊天输出)
        """
        self.width = width
        self.compact = compact
    
    def _separator(self, char: str = '=') -> str:
        """生成分隔线"""
        return char * self.width
    
    def _header(self, title: str) -> str:
        """生成标题"""
        padding = (self.width - len(title)) // 2
        return ' ' * padding + title + '\n'
    
    def _format_table(self, headers: List[str], rows: List[List[str]], widths: List[int] = None) -> str:
        """
        格式化表格
        
        Args:
            headers: 表头
            rows: 数据行
            widths: 每列宽度 (可选)
        """
        if not widths:
            widths = [max(len(str(h)), max(len(str(row[i])) for row in rows) if rows else 0) + 2 
                     for i, h in enumerate(headers)]
        
        # 表头
        header_line = ''.join(str(h).ljust(w) for h, w in zip(headers, widths))
        
        # 分隔线
        sep_line = '-' * sum(widths)
        
        # 数据行
        data_lines = []
        for row in rows:
            line = ''.join(str(cell).ljust(w) for cell, w in zip(row, widths))
            data_lines.append(line)
        
        return header_line + '\n' + sep_line + '\n' + '\n'.join(data_lines)
    
    def generate_text_report(
        self,
        analyses: List[QuequanAnalysis],
        show_header: bool = True,
        show_summary: bool = True
    ) -> str:
        """
        生成文本格式报告
        
        Args:
            analyses: 分析结果列表
            show_header: 是否显示头部信息
            show_summary: 是否显示统计汇总
            
        Returns:
            文本报告字符串
        """
        lines = []
        
        # 头部
        if show_header:
            lines.append(self._separator())
            lines.append(self._header("可转债抢权配债完整收益分析 (上帝视角)"))
            lines.append(self._separator())
            lines.append(f"分析时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
            lines.append("")
            lines.append("分析说明:")
            lines.append("  • 股权登记日 = T")
            lines.append("  • 买入时点：T-3、T-2、T-1 (登记日前)")
            lines.append("  • 卖出时点：T+1 (登记日后 1 个交易日)")
            lines.append("  • 目标：获得 10 张配债 (1 手)")
            lines.append("  • 完整盈亏 = 股票盈亏 + 配债收益")
            lines.append("")
        
        # 基本信息表
        lines.append(self._separator('='))
        lines.append("【一、转债基本信息】")
        lines.append(self._separator('='))
        lines.append("")
        
        headers = ['序号', '债券名称', '股票代码', '上市日期', '登记日期', '评级', '每股配售', '每签获利']
        rows = []
        for i, a in enumerate(analyses, 1):
            rows.append([
                str(i),
                a.bond_name,
                a.stock_code,
                a.listing_date,
                a.record_date,
                a.credit_rating,
                f"{a.per_share_amount:.4f}",
                f"{a.first_profit:.2f}"
            ])
        lines.append(self._format_table(headers, rows))
        lines.append("")
        
        # 抢权成本
        lines.append(self._separator('='))
        lines.append("【二、抢权成本分析 (获得 10 张配债)】")
        lines.append(self._separator('='))
        lines.append("")
        
        headers = ['序号', '债券名称', '理论股数', '实际买入', '配债张数', '配债资金']
        rows = []
        for i, a in enumerate(analyses, 1):
            rows.append([
                str(i),
                a.bond_name,
                f"{a.theoretical_shares:.2f}",
                str(a.actual_shares),
                str(a.actual_bonds),
                f"{a.bond_cost:,.0f} 元"
            ])
        lines.append(self._format_table(headers, rows))
        lines.append("")
        
        # 股价走势
        lines.append(self._separator())
        lines.append("【三、股价走势 (T-3 → T+1)】")
        lines.append(self._separator())
        lines.append("")
        
        headers = ['序号', '债券名称', 'T-3', 'T-2', 'T-1', 'T+1', 'T-1→T+1 涨跌']
        rows = []
        for i, a in enumerate(analyses, 1):
            p = a.stock_prices
            d = a.stock_dates
            if p['T-1'] > 0 and p['T+1'] > 0:
                change = p['T+1'] - p['T-1']
                change_pct = change / p['T-1'] * 100
                arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
                rows.append([
                    str(i),
                    a.bond_name,
                    f"{p['T-3']:.2f}\n({d.get('T-3', '-')})" if p['T-3'] > 0 else 'N/A',
                    f"{p['T-2']:.2f}\n({d.get('T-2', '-')})" if p['T-2'] > 0 else 'N/A',
                    f"{p['T-1']:.2f}\n({d.get('T-1', '-')})",
                    f"{p['T+1']:.2f}\n({d.get('T+1', '-')})",
                    f"{change:+.2f} {arrow} {change_pct:+.1f}%"
                ])
            else:
                rows.append([str(i), a.bond_name, '数据不足', '-', '-', '-', '-'])
        lines.append(self._format_table(headers, rows))
        lines.append("")
        
        # 转债上市收益
        lines.append(self._separator())
        lines.append("【四、转债上市收益】")
        lines.append(self._separator())
        lines.append("")
        
        headers = ['序号', '债券名称', '上市收盘价', '每张收益', '配债总收益', 'API 每签获利']
        rows = []
        for i, a in enumerate(analyses, 1):
            profit_per_bond = a.listing_close - 100 if a.listing_close > 0 else 0
            rows.append([
                str(i),
                a.bond_name,
                f"{a.listing_close:.3f}",
                f"{profit_per_bond:+.2f}",
                f"{a.bond_profit:+.0f} 元",
                f"{a.first_profit:+.2f} 元"
            ])
        lines.append(self._format_table(headers, rows))
        lines.append("")
        
        # 完整盈亏分析
        lines.append(self._separator())
        lines.append("【五、完整盈亏分析 (股票 + 配债) - 上帝视角】")
        lines.append(self._separator())
        lines.append("")
        
        has_stock_data = any(a.has_stock_data for a in analyses)
        
        for strategy, key in [('T-3 买入，T+1 卖出', 'T-3'), ('T-2 买入，T+1 卖出', 'T-2'), ('T-1 买入，T+1 卖出', 'T-1')]:
            lines.append(f"【策略：{strategy}】")
            lines.append(self._separator('-'))
            
            if has_stock_data:
                headers = ['序号', '债券名称', '配债成本', '股票成本', '股票盈亏', '配债收益', '总盈亏', '收益率', '结果']
                rows = []
                for i, a in enumerate(analyses, 1):
                    if a.total_costs[key] > 0:
                        status = "✅" if a.total_profits[key] > 0 else "❌"
                        rows.append([
                            str(i),
                            a.bond_name,
                            f"{a.bond_cost:,.0f} 元",
                            f"{a.total_costs[key]:,.0f}",
                            f"{a.stock_profits[key]:+.0f} 元",
                            f"{a.bond_profit:+.0f} 元",
                            f"{a.total_profits[key]:+.0f} 元",
                            f"{a.rois[key]:+.1f}%",
                            status
                        ])
                lines.append(self._format_table(headers, rows))
            else:
                lines.append("  ⚠️  股票价格数据不足，无法计算完整盈亏")
            lines.append("")
        
        # 统计汇总
        if show_summary and analyses:
            lines.append(self._separator())
            lines.append("【六、统计汇总】")
            lines.append(self._separator())
            lines.append("")
            
            # 平均数据
            avg_per_share = sum(a.per_share_amount for a in analyses) / len(analyses)
            avg_first_profit = sum(a.first_profit for a in analyses) / len(analyses)
            avg_listing = sum(a.listing_close for a in analyses) / len(analyses)
            avg_bond_profit = sum(a.bond_profit for a in analyses) / len(analyses)
            
            lines.append("  📊 平均数据:")
            lines.append(f"     平均每股配售：{avg_per_share:.4f} 元/股")
            lines.append(f"     平均每签获利：{avg_first_profit:.2f} 元")
            lines.append(f"     平均上市价格：{avg_listing:.3f} 元")
            lines.append(f"     平均配债收益：{avg_bond_profit:.0f} 元")
            lines.append("")
            
            # 策略胜率
            if has_stock_data:
                lines.append("  📊 策略对比:")
                for key in ['T-3', 'T-2', 'T-1']:
                    profitable = sum(1 for a in analyses if a.total_profits[key] > 0)
                    avg_profit = sum(a.total_profits[key] for a in analyses) / len(analyses)
                    pct = profitable / len(analyses) * 100
                    lines.append(f"     {key} 买入胜率：{profitable}/{len(analyses)} ({pct:.1f}%) 平均收益：{avg_profit:+.0f} 元")
                lines.append("")
            
            # 最佳和最差
            best = max(analyses, key=lambda x: x.first_profit)
            worst = min(analyses, key=lambda x: x.first_profit)
            lines.append(f"  🏆 最高每签获利：{best.bond_name} - {best.first_profit:.2f} 元")
            lines.append(f"  💀 最低每签获利：{worst.bond_name} - {worst.first_profit:.2f} 元")
            lines.append("")
        
        # 数据说明
        lines.append(self._separator())
        lines.append("【七、数据说明】")
        lines.append(self._separator())
        lines.append("")
        lines.append("  数据来源:")
        lines.append("    • 转债发行信息：东方财富 datacenter-web.eastmoney.com")
        lines.append("    • 上市价格：东方财富 push2his.eastmoney.com")
        lines.append("    • 股票历史价格：新浪财经 money.finance.sina.com.cn")
        lines.append("")
        lines.append("  时间定义:")
        lines.append("    • T-3: 股权登记日前 3 个交易日")
        lines.append("    • T-2: 股权登记日前 2 个交易日")
        lines.append("    • T-1: 股权登记日前 1 个交易日 (最后买入时机)")
        lines.append("    • T+1: 股权登记日后 1 个交易日 (卖出时机)")
        lines.append("")
        
        return '\n'.join(lines)
    
    def generate_json_report(self, analyses: List[QuequanAnalysis]) -> Dict[str, Any]:
        """
        生成 JSON 格式报告
        
        Args:
            analyses: 分析结果列表
            
        Returns:
            JSON 字典
        """
        return {
            'generated_at': datetime.now().isoformat(),
            'count': len(analyses),
            'analyses': [
                {
                    'bond_info': {
                        'bond_name': a.bond_name,
                        'bond_code': a.bond_code,
                        'stock_name': a.stock_name,
                        'stock_code': a.stock_code,
                        'listing_date': a.listing_date,
                        'record_date': a.record_date,
                        'credit_rating': a.credit_rating,
                    },
                    'allocation': {
                        'theoretical_shares': a.theoretical_shares,
                        'actual_shares': a.actual_shares,
                        'actual_bonds': a.actual_bonds,
                        'bond_cost': a.bond_cost,
                    },
                    'stock_prices': a.stock_prices,
                    'stock_dates': a.stock_dates,
                    'listing_close': a.listing_close,
                    'profits': {
                        'bond_cost': a.bond_cost,
                        'stock_profits': a.stock_profits,
                        'bond_profit': a.bond_profit,
                        'total_profits': a.total_profits,
                        'rois': a.rois,
                    },
                    'has_stock_data': a.has_stock_data,
                }
                for a in analyses
            ],
            'summary': {
                'avg_per_share': sum(a.per_share_amount for a in analyses) / len(analyses) if analyses else 0,
                'avg_first_profit': sum(a.first_profit for a in analyses) / len(analyses) if analyses else 0,
                'avg_listing': sum(a.listing_close for a in analyses) / len(analyses) if analyses else 0,
            }
        }
    
    def generate_markdown_report(self, analyses: List[QuequanAnalysis]) -> str:
        """
        生成 Markdown 格式报告
        
        Args:
            analyses: 分析结果列表
            
        Returns:
            Markdown 字符串
        """
        lines = []
        
        lines.append("# 可转债抢权配债完整收益分析")
        lines.append("")
        lines.append(f"**分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        
        # 基本信息
        lines.append("## 转债基本信息")
        lines.append("")
        lines.append("| 序号 | 债券名称 | 股票代码 | 上市日期 | 登记日期 | 评级 | 每股配售 | 每签获利 |")
        lines.append("|------|----------|----------|----------|----------|------|----------|----------|")
        for i, a in enumerate(analyses, 1):
            lines.append(f"| {i} | {a.bond_name} | {a.stock_code} | {a.listing_date} | {a.record_date} | {a.credit_rating} | {a.per_share_amount:.4f} | {a.first_profit:.2f} |")
        lines.append("")
        
        # 股价走势
        lines.append("## 股价走势")
        lines.append("")
        lines.append("| 债券名称 | T-3 (日期) | T-2 (日期) | T-1 (日期) | T+1 (日期) | 涨跌 |")
        lines.append("|----------|------------|------------|------------|------------|------|")
        for a in analyses:
            p = a.stock_prices
            d = a.stock_dates
            if p['T-1'] > 0 and p['T+1'] > 0:
                change = p['T+1'] - p['T-1']
                change_pct = change / p['T-1'] * 100
                t3 = f"{p['T-3']:.2f}" if p['T-3'] > 0 else '-'
                t2 = f"{p['T-2']:.2f}" if p['T-2'] > 0 else '-'
                lines.append(f"| {a.bond_name} | {t3} ({d.get('T-3', '-')}) | {t2} ({d.get('T-2', '-')}) | {p['T-1']:.2f} ({d.get('T-1', '-')}) | {p['T+1']:.2f} ({d.get('T+1', '-')}) | {change_pct:+.1f}% |")
            else:
                lines.append(f"| {a.bond_name} | - | - | {p['T-1']:.2f} | {p['T+1']:.2f} | 数据不足 |")
        lines.append("")
        
        # 完整盈亏
        lines.append("## 完整盈亏分析")
        lines.append("")
        lines.append("| 债券名称 | 配债成本 | 配债收益 | T-3 总盈亏 | T-2 总盈亏 | T-1 总盈亏 |")
        lines.append("|----------|----------|----------|------------|------------|------------|")
        for a in analyses:
            t3 = f"{a.total_profits['T-3']:+.0f}" if a.total_costs['T-3'] > 0 else "N/A"
            t2 = f"{a.total_profits['T-2']:+.0f}" if a.total_costs['T-2'] > 0 else "N/A"
            t1 = f"{a.total_profits['T-1']:+.0f}" if a.total_costs['T-1'] > 0 else "N/A"
            lines.append(f"| {a.bond_name} | {a.bond_cost:,.0f} 元 | {a.bond_profit:+.0f} 元 | {t3} 元 | {t2} 元 | {t1} 元 |")
        lines.append("")
        
        return '\n'.join(lines)
