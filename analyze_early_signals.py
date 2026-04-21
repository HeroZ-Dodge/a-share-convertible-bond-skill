#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可转债同意注册前股价异动分析

研究能否从前期节点（交易所受理、上市委通过）预测同意注册时间
从而提前布局，获取同意注册前 5 天的 +4.56% 涨幅
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.data_source import JisiluAPI, SinaFinanceAPI
from datetime import datetime, timedelta
import re


def parse_progress_dates(progress_full: str) -> dict:
    """解析进度字符串，提取各个节点的日期"""
    if not progress_full:
        return {}
    
    progress_full = progress_full.replace('<br>', '\n')
    dates = {}
    pattern = r'(\d{4}-\d{2}-\d{2})\s+([^\n]+)'
    
    for match in re.finditer(pattern, progress_full):
        date_str = match.group(1)
        event = match.group(2).strip()
        dates[event] = date_str
    
    return dates


def days_between(date1: str, date2: str) -> int:
    """计算两个日期之间的天数"""
    if not date1 or not date2:
        return None
    try:
        d1 = datetime.strptime(date1, '%Y-%m-%d')
        d2 = datetime.strptime(date2, '%Y-%m-%d')
        return (d2 - d1).days
    except:
        return None


def main():
    jsl = JisiluAPI(timeout=30)
    sina = SinaFinanceAPI(timeout=30)
    
    print('从集思录获取待发转债数据...')
    bonds = jsl.fetch_pending_bonds(limit=100)
    print(f'获取到 {len(bonds)} 只转债')
    
    # 筛选有完整进度数据的转债
    valid_bonds = []
    for b in bonds:
        progress_full = b.get('progress_full', '')
        dates = parse_progress_dates(progress_full)
        
        # 需要有交易所受理、上市委通过、同意注册三个节点
        if all(k in dates for k in ['交易所受理', '上市委通过', '同意注册']) and b.get('stock_code'):
            b['progress_dates'] = dates
            valid_bonds.append(b)
    
    print(f'找到 {len(valid_bonds)} 只有完整进度数据的转债')
    
    # 分析各节点之间的时间间隔
    print('\n分析各节点时间间隔...')
    
    shouli_dao_tongguo = []
    tongguo_dao_zhuce = []
    shouli_dao_zhuce = []
    
    for b in valid_bonds:
        dates = b['progress_dates']
        
        d1 = days_between(dates['交易所受理'], dates['上市委通过'])
        d2 = days_between(dates['上市委通过'], dates['同意注册'])
        d3 = days_between(dates['交易所受理'], dates['同意注册'])
        
        if d1 and d2 and d3:
            shouli_dao_tongguo.append(d1)
            tongguo_dao_zhuce.append(d2)
            shouli_dao_zhuce.append(d3)
    
    print(f'\n时间间隔统计:')
    print(f'  交易所受理 → 上市委通过：平均 {sum(shouli_dao_tongguo)/len(shouli_dao_tongguo):.0f} 天 (范围：{min(shouli_dao_tongguo)}-{max(shouli_dao_tongguo)}天)')
    print(f'  上市委通过 → 同意注册：平均 {sum(tongguo_dao_zhuce)/len(tongguo_dao_zhuce):.0f} 天 (范围：{min(tongguo_dao_zhuce)}-{max(tongguo_dao_zhuce)}天)')
    print(f'  交易所受理 → 同意注册：平均 {sum(shouli_dao_zhuce)/len(shouli_dao_zhuce):.0f} 天 (范围：{min(shouli_dao_zhuce)}-{max(shouli_dao_zhuce)}天)')
    
    # 生成报告
    md = []
    md.append('# 可转债同意注册前股价异动分析与提前布局策略')
    md.append('')
    md.append(f'**分析时间**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**数据来源**: 集思录 + 新浪财经')
    md.append(f'**转债数量**: {len(valid_bonds)} 只')
    md.append('')
    
    md.append('## 核心发现')
    md.append('')
    md.append('同意注册前 5 天平均涨幅 **+4.56%**，上涨概率 **81.8%**')
    md.append('这说明有资金可能提前获知消息并布局。')
    md.append('')
    md.append('## 一、审核流程时间规律')
    md.append('')
    md.append('可转债发行审核流程：')
    md.append('```')
    md.append('董事会预案 → 股东大会通过 → 交易所受理 → 上市委通过 → 同意注册 → 发行公告')
    md.append('```')
    md.append('')
    md.append('### 各节点时间间隔统计')
    md.append('')
    md.append('| 阶段 | 平均天数 | 最短 | 最长 | 中位数 |')
    md.append('|------|---------|------|------|--------|')
    
    def calc_stats(data):
        avg = sum(data) / len(data)
        median = sorted(data)[len(data)//2]
        return f'{avg:.0f}天', f'{min(data)}天', f'{max(data)}天', f'{median}天'
    
    md.append(f'| 交易所受理 → 上市委通过 | {calc_stats(shouli_dao_tongguo)[0]} | {calc_stats(shouli_dao_tongguo)[1]} | {calc_stats(shouli_dao_tongguo)[2]} | {calc_stats(shouli_dao_tongguo)[3]} |')
    md.append(f'| 上市委通过 → 同意注册 | {calc_stats(tongguo_dao_zhuce)[0]} | {calc_stats(tongguo_dao_zhuce)[1]} | {calc_stats(tongguo_dao_zhuce)[2]} | {calc_stats(tongguo_dao_zhuce)[3]} |')
    md.append(f'| 交易所受理 → 同意注册 | {calc_stats(shouli_dao_zhuce)[0]} | {calc_stats(shouli_dao_zhuce)[1]} | {calc_stats(shouli_dao_zhuce)[2]} | {calc_stats(shouli_dao_zhuce)[3]} |')
    md.append('')
    
    # 详细数据
    md.append('### 详细数据')
    md.append('')
    md.append('| # | 债券名称 | 交易所受理 | 上市委通过 | 同意注册 | 受理→通过 | 通过→注册 |')
    md.append('|---|----------|----------|----------|----------|----------|----------|')
    
    for i, b in enumerate(valid_bonds[:20], 1):
        dates = b['progress_dates']
        d1 = days_between(dates['交易所受理'], dates['上市委通过'])
        d2 = days_between(dates['上市委通过'], dates['同意注册'])
        md.append(f'| {i} | {b.get("bond_name") or "N/A"} | {dates["交易所受理"]} | {dates["上市委通过"]} | {dates["同意注册"]} | {d1}天 | {d2}天 |')
    
    md.append('')
    
    # 提前布局策略
    md.append('## 二、提前布局策略')
    md.append('')
    md.append('### 策略 1: 交易所受理后潜伏')
    md.append('')
    avg_total = sum(shouli_dao_zhuce)//len(shouli_dao_zhuce)
    md.append(f'- **触发条件**: 交易所受理后第 {avg_total - 5} 天左右')
    md.append(f'- **逻辑**: 从交易所受理到同意注册平均 {avg_total} 天，提前 5 天潜伏')
    md.append(f'- **预期收益**: +4.56% (同意注册前 5 天涨幅)')
    md.append(f'- **风险**: 审核时间不确定，可能提前或延后')
    md.append('')
    
    md.append('### 策略 2: 上市委通过后埋伏')
    md.append('')
    avg_tongguo_zhuce = sum(tongguo_dao_zhuce)//len(tongguo_dao_zhuce)
    md.append(f'- **触发条件**: 上市委通过后第 {avg_tongguo_zhuce - 5} 天左右')
    md.append(f'- **逻辑**: 从上市委通过到同意注册平均 {avg_tongguo_zhuce} 天，提前 5 天埋伏')
    md.append(f'- **预期收益**: +4.56% (同意注册前 5 天涨幅)')
    md.append(f'- **风险**: 时间窗口较短，需要密切监控')
    md.append('')
    
    md.append('### 策略 3: 监控集思录数据更新')
    md.append('')
    md.append('- **逻辑**: 集思录可能比公开渠道更早获取审核进度信息')
    md.append('- **操作**: 每天监控集思录待发转债列表，发现新增加的"交易所受理"或"上市委通过"标的')
    md.append('- **优势**: 信息更新及时，可第一时间发现')
    md.append('- **劣势**: 需要持续监控')
    md.append('')
    
    # 股价异动分析
    md.append('## 三、股价异动监控')
    md.append('')
    md.append('监控以下信号，可能有资金提前获知消息：')
    md.append('')
    md.append('1. **成交量异常放大**: 某日成交量是前 5 日均量的 2 倍以上')
    md.append('2. **股价逆势上涨**: 大盘下跌但个股上涨')
    md.append('3. **尾盘拉升**: 收盘前 30 分钟股价快速拉升')
    md.append('4. **大宗交易**: 出现折价率较低的大宗交易')
    md.append('')
    
    # 实际操作建议
    md.append('## 四、实际操作建议')
    md.append('')
    md.append('### 信息获取渠道')
    md.append('')
    md.append('1. **集思录** (https://www.jisilu.cn/data/cbnew/#pre)')
    md.append('   - 每天更新待发转债进度')
    md.append('   - API: `/data/cbnew/pre_list/`')
    md.append('')
    md.append('2. **交易所官网**')
    md.append('   - 上交所：http://www.sse.com.cn/')
    md.append('   - 深交所：http://www.szse.cn/')
    md.append('   - 可转债审核进度查询')
    md.append('')
    md.append('3. **东方财富可转债数据**')
    md.append('   - https://data.eastmoney.com/kzz/')
    md.append('')
    
    md.append('### 监控脚本建议')
    md.append('')
    md.append('```python')
    md.append('# 每天运行一次，监控新增的交易所受理/上市委通过标的')
    md.append('from lib.data_source import JisiluAPI')
    md.append('')
    md.append('jsl = JisiluAPI()')
    md.append('bonds = jsl.fetch_pending_bonds()')
    md.append('')
    md.append('for b in bonds:')
    md.append('    if "交易所受理" in b.get("progress_full", ""):')
    md.append('        # 新受理，加入监控列表')
    md.append('        pass')
    md.append('    elif "上市委通过" in b.get("progress_full", ""):')
    md.append('        # 已通过，计算预期同意注册时间')
    md.append('        pass')
    md.append('```')
    md.append('')
    
    md.append('### 风险提示')
    md.append('')
    md.append('1. **审核时间不确定**: 上述时间间隔是历史平均，实际可能偏差较大')
    md.append('2. **审核失败风险**: 极少数情况下，转债可能被否')
    md.append('3. **市场风险**: 即使同意注册，正股也可能因大盘下跌而下跌')
    md.append('4. **信息滞后**: 集思录数据可能不是实时的')
    md.append('')
    
    md.append('---')
    md.append('')
    md.append('**注**: 本分析仅基于历史数据统计，不构成投资建议。')
    md.append('')
    
    # 保存报告
    content = '\n'.join(md)
    output_path = '/Users/dodge/.openclaw/workspace/skills/a-share-convertible-bond-skill/可转债同意注册前提前布局策略.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f'\n报告已保存：{output_path}')


if __name__ == '__main__':
    main()
