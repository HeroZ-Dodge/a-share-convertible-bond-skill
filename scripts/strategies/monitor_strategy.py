#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册+3天入场，持有7天卖出 — 每日监控脚本

策略逻辑:
1. 每天读取集思录待发转债数据
2. 发现新"同意注册"的转债 → 计算买入/卖出日期
3. 买入日 = 注册日 + 3个交易日（需正股质量 B 级以上）
4. 卖出日 = 买入日 + 7个交易日（支持止损/止盈）

Usage:
    python3 scripts/monitor_strategy.py --once          # 日常运行
    python3 scripts/monitor_strategy.py --status         # 查看状态
    python3 scripts/monitor_strategy.py --init-backfill  # 首次回填
    python3 scripts/monitor_strategy.py --once --dry-run # 模拟运行
"""

import argparse
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Optional, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lib.backtest_cache import BacktestCache
from lib.monitor_db import MonitorDB
from lib.stock_quality import StockQualityEvaluator


def parse_progress_dates(progress_full: str) -> Dict[str, str]:
    """从进度字符串提取各节点日期"""
    if not progress_full:
        return {}
    progress_full = progress_full.replace('<br>', '\n')
    dates = {}
    pattern = r'(\d{4}-\d{2}-\d{2})\s+([^\n]+)'
    for match in re.finditer(pattern, progress_full):
        dates[match.group(2).strip()] = match.group(1)
    return dates


def get_bond_display_name(bond: Dict) -> str:
    """获取债券显示名称，优先使用转债名称，fallback 到股票名称"""
    return bond.get('bond_name') or bond.get('bond_code') or bond.get('stock_name', '')


def find_trading_day_offset(kline_dict: Dict[str, Dict], base_date: str,
                             offset: int) -> Optional[str]:
    """
    在K线数据中从 base_date 起偏移 offset 个交易日

    Args:
        kline_dict: {date: {open, close, ...}}
        base_date: 基准日期 'YYYY-MM-DD'
        offset: 偏移天数（正数=向后）

    Returns:
        目标日期字符串，找不到返回 None
    """
    sorted_dates = sorted(kline_dict.keys())
    base_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= base_date:
            base_idx = i
            break
    if base_idx is None or base_idx + offset >= len(sorted_dates):
        return None
    return sorted_dates[base_idx + offset]


def detect_new_registrations(cache: BacktestCache, monitor_db: MonitorDB,
                              today: str) -> List[Dict]:
    """
    对比集思录快照和 monitor_db，发现新注册的转债

    Returns:
        新注册事件列表
    """
    bonds = cache.get_latest_jisilu_data()
    if not bonds:
        return []

    new_regs = []
    for bond in bonds:
        stock_code = bond.get('stock_code', '')
        if not stock_code:
            continue

        dates = parse_progress_dates(bond.get('progress_full', ''))
        if '同意注册' not in dates:
            continue

        registration_date = dates['同意注册']
        tongguo_date = dates.get('上市委通过', '')

        # 计算通过→注册天数
        days_tongguo_to_reg = None
        if tongguo_date:
            try:
                d1 = datetime.strptime(tongguo_date, '%Y-%m-%d')
                d2 = datetime.strptime(registration_date, '%Y-%m-%d')
                days_tongguo_to_reg = (d2 - d1).days
            except ValueError:
                pass

        # 检查是否已记录
        existing = monitor_db.get_registration_by_stock(stock_code)
        if existing and existing['registration_date'] == registration_date:
            continue  # 已存在

        new_regs.append({
            'stock_code': stock_code,
            'stock_name': bond.get('stock_name', ''),
            'bond_code': bond.get('bond_code', ''),
            'bond_name': bond.get('bond_name') or bond.get('stock_name', ''),
            'registration_date': registration_date,
            'tongguo_date': tongguo_date,
            'days_tongguo_to_reg': days_tongguo_to_reg,
        })

    return new_regs


def create_positions_for_registrations(new_regs: List[Dict],
                                        cache: BacktestCache,
                                        monitor_db: MonitorDB,
                                        source: str = 'real',
                                        dry_run: bool = False) -> List[Dict]:
    """
    为新注册的转债创建持仓计划

    Args:
        source: 'real'（真实监控）或 'backfill'（历史回填）

    Returns:
        创建的持仓列表
    """
    created = []
    for reg in new_regs:
        stock_code = reg['stock_code']
        registration_date = reg['registration_date']

        kline = cache.get_kline_as_dict(stock_code, days=60)
        if not kline or len(kline) < 10:
            print(f'  ⚠️  {reg["bond_name"]} ({stock_code}): K线数据不足，跳过')
            continue

        buy_date = find_trading_day_offset(kline, registration_date, 3)
        if not buy_date:
            print(f'  ⚠️  {reg["bond_name"]} ({stock_code}): 无法计算买入日期，跳过')
            continue

        sell_date = find_trading_day_offset(kline, buy_date, 7)
        if not sell_date:
            print(f'  ⚠️  {reg["bond_name"]} ({stock_code}): 无法计算卖出日期，跳过')
            continue

        position_id = f'{stock_code}_{registration_date.replace("-", "")}'

        if not dry_run:
            monitor_db.create_position({
                'position_id': position_id,
                'stock_code': stock_code,
                'stock_name': reg['stock_name'],
                'bond_code': reg['bond_code'],
                'bond_name': reg['bond_name'],
                'registration_date': registration_date,
                'planned_buy_date': buy_date,
                'planned_sell_date': sell_date,
            }, source=source)

        created.append({
            'position_id': position_id,
            'stock_code': stock_code,
            'stock_name': reg['stock_name'],
            'bond_name': reg['bond_name'],
            'registration_date': registration_date,
            'planned_buy_date': buy_date,
            'planned_sell_date': sell_date,
        })

    return created


def process_buy_signals(monitor_db: MonitorDB, cache: BacktestCache,
                        today: str, quality_evaluator: StockQualityEvaluator,
                        min_rating: str = 'B', dry_run: bool = False) -> Dict:
    """
    处理今日到期的买入信号

    Returns:
        {executed: [...], missed: [...]}
    """
    due = monitor_db.get_positions_due_to_buy(today)
    executed = []
    missed = []

    for pos in due:
        stock_code = pos['stock_code']
        position_id = pos['position_id']

        kline = cache.get_kline_as_dict(stock_code, days=90)
        if not kline:
            if not dry_run:
                monitor_db.mark_missed(position_id, 'no_kline_data')
            missed.append({
                'position_id': position_id,
                'bond_name': pos['bond_name'],
                'stock_code': stock_code,
                'reason': 'K线数据不可用',
            })
            continue

        latest_date = sorted(kline.keys())[-1]
        buy_price = kline[latest_date]['close']
        if buy_price <= 0:
            missed.append({
                'position_id': position_id,
                'bond_name': pos['bond_name'],
                'stock_code': stock_code,
                'reason': '价格无效',
            })
            continue

        quality = quality_evaluator.evaluate(stock_code, kline)
        rating = quality.get('rating', 'D')
        score = quality.get('total_score', 0)

        rating_order = {'A': 4, 'B': 3, 'C': 2, 'D': 1}
        min_rating_value = rating_order.get(min_rating, 3)

        if rating_order.get(rating, 0) < min_rating_value:
            if not dry_run:
                monitor_db.mark_missed(
                    position_id, f'quality_filter: {rating}({score}分)')
            missed.append({
                'position_id': position_id,
                'bond_name': pos['bond_name'],
                'stock_code': stock_code,
                'reason': f'正股质量 {rating}({score}分) < {min_rating}',
                'rating': rating,
                'score': score,
            })
            continue

        if not dry_run:
            monitor_db.execute_buy(
                position_id, latest_date, buy_price, rating, score)

        executed.append({
            'position_id': position_id,
            'bond_name': pos['bond_name'],
            'stock_code': stock_code,
            'buy_date': latest_date,
            'buy_price': buy_price,
            'quality_rating': rating,
            'quality_score': score,
            'planned_sell_date': pos['planned_sell_date'],
        })

    return {'executed': executed, 'missed': missed}


def process_sell_signals(monitor_db: MonitorDB, cache: BacktestCache,
                         today: str,
                         stop_loss_pct: float = -5.0,
                         take_profit_pct: float = 15.0,
                         dry_run: bool = False) -> List[Dict]:
    """
    处理卖出信号：
    1. 持有到期（计划卖出日 <= today）
    2. 止损（收益 <= stop_loss_pct）
    3. 止盈（收益 >= take_profit_pct）

    Returns:
        卖出结果列表
    """
    sold = []

    active = monitor_db.get_active_positions()
    for pos in active:
        stock_code = pos['stock_code']
        position_id = pos['position_id']
        buy_price = pos['actual_buy_price']
        if not buy_price or buy_price <= 0:
            continue

        kline = cache.get_kline_as_dict(stock_code, days=10)
        if not kline:
            continue

        latest_date = sorted(kline.keys())[-1]
        current_price = kline[latest_date]['close']
        return_pct = ((current_price - buy_price) / buy_price) * 100

        sell_reason = None
        notes = ''

        # 检查卖出条件（优先顺序：到期 > 止盈 > 止损）
        if pos['planned_sell_date'] and today >= pos['planned_sell_date']:
            sell_reason = 'hold_7d'
            notes = '持有7天到期'
        elif return_pct >= take_profit_pct:
            sell_reason = 'take_profit'
            notes = f'止盈触发 (+{return_pct:.1f}%)'
        elif return_pct <= stop_loss_pct:
            sell_reason = 'stop_loss'
            notes = f'止损触发 ({return_pct:.1f}%)'

        if not sell_reason:
            continue

        if not dry_run:
            result = monitor_db.execute_sell(
                position_id, latest_date, current_price, sell_reason, notes)
        else:
            result = {**pos, 'actual_sell_date': latest_date,
                      'actual_sell_price': current_price,
                      'sell_reason': sell_reason,
                      'return_pct': round(return_pct, 2),
                      'success': 1 if return_pct > 0 else 0,
                      'notes': notes}

        sold.append({
            'position_id': position_id,
            'bond_name': pos['bond_name'],
            'stock_code': stock_code,
            'buy_price': buy_price,
            'sell_price': current_price,
            'sell_date': latest_date,
            'return_pct': round(return_pct, 2),
            'sell_reason': sell_reason,
            'notes': notes,
            'success': result.get('success', 0),
        })

    return sold


def init_backfill(cache: BacktestCache, monitor_db: MonitorDB,
                   quality_evaluator: StockQualityEvaluator,
                   min_rating: str = 'B') -> Dict:
    """
    首次运行：回填所有已有"同意注册"的转债

    Returns:
        统计信息
    """
    bonds = cache.get_latest_jisilu_data()
    if not bonds:
        print('⚠️  无法获取集思录数据，请先运行缓存快照')
        return {'error': 'no_data'}

    today = datetime.now().strftime('%Y-%m-%d')

    # 检测新注册
    new_regs = []
    for bond in bonds:
        stock_code = bond.get('stock_code', '')
        if not stock_code:
            continue

        dates = parse_progress_dates(bond.get('progress_full', ''))
        if '同意注册' not in dates:
            continue

        registration_date = dates['同意注册']
        tongguo_date = dates.get('上市委通过', '')

        existing = monitor_db.get_registration_by_stock(stock_code)
        if existing and existing['registration_date'] == registration_date:
            continue

        days_tongguo_to_reg = None
        if tongguo_date:
            try:
                d1 = datetime.strptime(tongguo_date, '%Y-%m-%d')
                d2 = datetime.strptime(registration_date, '%Y-%m-%d')
                days_tongguo_to_reg = (d2 - d1).days
            except ValueError:
                pass

        new_regs.append({
            'stock_code': stock_code,
            'stock_name': bond.get('stock_name', ''),
            'bond_code': bond.get('bond_code', ''),
            'bond_name': bond.get('bond_name') or bond.get('stock_name', ''),
            'registration_date': registration_date,
            'tongguo_date': tongguo_date,
            'days_tongguo_to_reg': days_tongguo_to_reg,
        })

    if not new_regs:
        print('✅ 没有新注册数据需要回填')
        return {'new_registrations': 0, 'positions_created': 0}

    # 注册事件
    for reg in new_regs:
        monitor_db.record_registration(reg)

    # 创建持仓（标记为 backfill，不影响真实监控数据）
    positions = create_positions_for_registrations(
        new_regs, cache, monitor_db, source='backfill')

    return {
        'new_registrations': len(new_regs),
        'positions_created': len(positions),
    }


def show_status(monitor_db: MonitorDB, cache: BacktestCache = None) -> None:
    """显示当前监控状态"""
    stats = monitor_db.get_position_stats()

    print('=' * 70)
    print('📊 注册+3天入场策略 — 当前状态')
    print('=' * 70)
    print()

    # 注册统计
    regs = monitor_db.get_registration_events()
    print(f'📌 注册事件: {len(regs)} 只')
    if regs:
        latest = regs[0]
        display_name = get_bond_display_name(latest)
        print(f'   最新: {display_name} ({latest["stock_code"]}) | '
              f'注册日: {latest["registration_date"]}')
    print()

    # Backfill 持仓（历史回填，不参与统计）
    backfill = monitor_db.get_backfill_positions()
    if backfill:
        statuses = {}
        for p in backfill:
            s = p.get('status', 'unknown')
            statuses[s] = statuses.get(s, 0) + 1
        status_str = ', '.join(f'{k}: {v}' for k, v in statuses.items())
        print(f'📋 回填持仓 ({len(backfill)} 个, source=backfill): {status_str}')
        print()

    # 计划持仓
    scheduled = monitor_db.get_scheduled_positions()
    if scheduled:
        print(f'📋 计划买入 ({len(scheduled)} 只):')
        for pos in scheduled:
            display_name = pos['bond_name'] or pos.get('stock_name') or pos['stock_code']
            print(f'  {display_name} ({pos["stock_code"]}) | '
                  f'注册日: {pos["registration_date"]} | '
                  f'计划买入: {pos["planned_buy_date"]} | '
                  f'计划卖出: {pos["planned_sell_date"]}')
        print()

    # 活跃持仓
    active = monitor_db.get_active_positions()
    if active:
        print(f'💰 活跃持仓 ({len(active)} 只):')
        for pos in active:
            buy_price = pos['actual_buy_price']
            current_price = buy_price
            return_pct = 0
            if cache and pos['stock_code']:
                kline = cache.get_kline_as_dict(pos['stock_code'], days=5)
                if kline:
                    latest_date = sorted(kline.keys())[-1]
                    current_price = kline[latest_date]['close']
                    if buy_price > 0:
                        return_pct = ((current_price - buy_price) / buy_price) * 100

            status_icon = '✅' if return_pct > 0 else '⚠️' if return_pct < 0 else '➖'
            print(f'  {pos["bond_name"]} ({pos["stock_code"]}) | '
                  f'买入: {buy_price:.2f} | '
                  f'当前: {current_price:.2f} | '
                  f'浮动: {return_pct:+.1f}% {status_icon} | '
                  f'计划卖出: {pos["planned_sell_date"]}')
        print()

    # 已平仓
    if stats['total'] > 0:
        print(f'📈 历史统计 (已平仓 {stats["total"]} 笔):')
        print(f'   胜率: {stats["win_rate"]:.0f}% ({stats["wins"]}/{stats["total"]}) | '
              f'平均收益: {stats["avg_return"]:+.1f}% | '
              f'最佳: {stats["best"]:+.1f}% | '
              f'最差: {stats["worst"]:+.1f}%')
        print(f'   平均持仓: {stats["avg_hold_days"]:.0f} 交易日')
    else:
        print('📈 暂无已平仓记录')

    print()
    print('=' * 70)


def generate_daily_report(today: str, cache_stats: Dict,
                           new_regs: List[Dict], created_positions: List[Dict],
                           buy_result: Dict, sells: List[Dict],
                           active: List[Dict], closed_today: List[Dict],
                           stats: Dict) -> None:
    """生成并打印每日监控报告"""
    print('=' * 70)
    print(f'📊 注册+3天入场策略 — 每日监控报告')
    print(f'📅 {today}')
    print('=' * 70)
    print()

    # 数据获取
    print('📥 数据获取')
    print(f'  集思录: 总计 {cache_stats.get("total_registered", 0)} 只待发转债')
    print(f'  新增注册: {len(new_regs)} 只')
    print()

    # 新注册
    if new_regs:
        print(f'📌 新注册 (同意注册):')
        for i, reg in enumerate(new_regs, 1):
            pos_info = ''
            for p in created_positions:
                if p['stock_code'] == reg['stock_code']:
                    pos_info = (f' | 计划买入: {p["planned_buy_date"]} | '
                               f'计划卖出: {p["planned_sell_date"]}')
                    break

            tg_info = ''
            if reg.get('tongguo_date'):
                days = reg.get('days_tongguo_to_reg', '?')
                tg_info = f' | 上市委通过: {reg["tongguo_date"]} ({days}天前)'

            print(f'  {i}. {reg["bond_name"]} ({reg["stock_code"]}) | '
                  f'注册日: {reg["registration_date"]}{tg_info}{pos_info}')
        print()

    # 买入信号
    executed_buys = buy_result.get('executed', [])
    if executed_buys:
        print(f'💰 买入信号 (今日执行, {len(executed_buys)} 只):')
        for i, b in enumerate(executed_buys, 1):
            print(f'  {i}. {b["bond_name"]} ({b["stock_code"]}) | '
                  f'买入价: {b["buy_price"]:.2f} | '
                  f'正股评级: {b["quality_rating"]} ({b["quality_score"]:.0f}分) | '
                  f'计划卖出: {b["planned_sell_date"]}')
        print()

    missed_buys = buy_result.get('missed', [])
    if missed_buys:
        print(f'⏭️  跳过买入 ({len(missed_buys)} 只):')
        for i, m in enumerate(missed_buys, 1):
            print(f'  {i}. {m["bond_name"]} ({m["stock_code"]}) | '
                  f'原因: {m["reason"]}')
        print()

    # 卖出信号
    if sells:
        print(f'💸 卖出信号 ({len(sells)} 只):')
        for i, s in enumerate(sells, 1):
            icon = '✅' if s['success'] else '❌'
            reason_map = {
                'hold_7d': '持有7天到期',
                'stop_loss': '止损',
                'take_profit': '止盈',
            }
            reason_str = reason_map.get(s['sell_reason'], s['sell_reason'])
            print(f'  {i}. {s["bond_name"]} ({s["stock_code"]}) | '
                  f'买入价: {s["buy_price"]:.2f} | '
                  f'卖出价: {s["sell_price"]:.2f} | '
                  f'收益: {s["return_pct"]:+.1f}% {icon} | '
                  f'原因: {reason_str}')
        print()

    # 活跃持仓
    if active:
        print(f'📋 活跃持仓 ({len(active)} 只):')
        for i, pos in enumerate(active, 1):
            buy_price = pos['actual_buy_price']
            print(f'  {i}. {pos["bond_name"]} ({pos["stock_code"]}) | '
                  f'买入日: {pos["actual_buy_date"]} | '
                  f'买入价: {buy_price:.2f}')
        print()

    # 历史统计
    if stats['total'] > 0:
        print(f'📈 历史统计 (已平仓 {stats["total"]} 笔)')
        print(f'   胜率: {stats["win_rate"]:.0f}% ({stats["wins"]}/{stats["total"]}) | '
              f'平均收益: {stats["avg_return"]:+.1f}% | '
              f'最佳: {stats["best"]:+.1f}% | '
              f'最差: {stats["worst"]:+.1f}%')
        print(f'   平均持仓: {stats["avg_hold_days"]:.0f} 交易日')
        print()

    print('=' * 70)


def run_daily_monitor(monitor_db: MonitorDB, cache: BacktestCache,
                       quality_evaluator: StockQualityEvaluator,
                       today: str,
                       stop_loss_pct: float,
                       take_profit_pct: float,
                       min_rating: str,
                       dry_run: bool) -> None:
    """执行每日监控流程"""
    print(f'🔄 开始每日监控 | {today} | dry_run={dry_run}')
    print()

    # 1. 获取集思录快照
    snapshot_stats = cache.save_jisilu_snapshot()

    # 2. 检测新注册
    new_regs = detect_new_registrations(cache, monitor_db, today)
    if new_regs:
        for reg in new_regs:
            monitor_db.record_registration(reg)
        print(f'✅ 发现 {len(new_regs)} 只新注册转债')
    else:
        print('✅ 无新注册转债')
    print()

    # 3. 创建持仓计划
    created_positions = []
    if new_regs:
        created_positions = create_positions_for_registrations(
            new_regs, cache, monitor_db, dry_run)
        if created_positions:
            print(f'✅ 创建 {len(created_positions)} 个持仓计划')
        print()

    # 4. 处理买入信号
    buy_result = process_buy_signals(
        monitor_db, cache, today, quality_evaluator, min_rating, dry_run)
    total_buys = len(buy_result['executed']) + len(buy_result['missed'])
    if total_buys:
        print(f'💰 买入处理: 执行 {len(buy_result["executed"])} 只, '
              f'跳过 {len(buy_result["missed"])} 只')
        print()

    # 5. 处理卖出信号
    sells = process_sell_signals(
        monitor_db, cache, today, stop_loss_pct, take_profit_pct, dry_run)
    if sells:
        print(f'💸 卖出处理: {len(sells)} 只')
        print()

    # 6. 获取当前状态
    active = monitor_db.get_active_positions()
    stats = monitor_db.get_position_stats()
    all_regs = monitor_db.get_registration_events()

    # 7. 保存每日快照
    if not dry_run:
        monitor_db.save_daily_snapshot({
            'snapshot_date': today,
            'total_registered': len(all_regs),
            'new_registrations': len(new_regs),
            'buy_signals': len(buy_result['executed']),
            'sell_signals': len(sells),
            'active_positions': len(active),
            'closed_positions': len(sells),
            'data': {
                'new_regs': new_regs,
                'created_positions': created_positions,
                'buys': buy_result,
                'sells': sells,
            },
        })

    # 8. 生成报告
    generate_daily_report(
        today=today,
        cache_stats={'total_registered': len(all_regs)},
        new_regs=new_regs,
        created_positions=created_positions,
        buy_result=buy_result,
        sells=sells,
        active=active,
        closed_today=sells,
        stats=stats,
    )


def main():
    parser = argparse.ArgumentParser(
        description='注册+3天入场，持有7天卖出 — 每日监控脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--once', action='store_true',
                        help='只运行一次（日常监控）')
    parser.add_argument('--status', action='store_true',
                        help='显示当前监控状态（不获取新数据）')
    parser.add_argument('--init-backfill', action='store_true',
                        help='首次运行：回填所有已有"同意注册"的转债')
    parser.add_argument('--date', type=str, default=None,
                        help='指定交易日期 (YYYY-MM-DD)，默认今天')
    parser.add_argument('--stop-loss', type=float, default=-5.0,
                        help='止损阈值（百分比，默认-5.0）')
    parser.add_argument('--take-profit', type=float, default=15.0,
                        help='止盈阈值（百分比，默认+15.0）')
    parser.add_argument('--quality-min', type=str, default='B',
                        help='最低正股质量评级（默认B）')
    parser.add_argument('--dry-run', action='store_true',
                        help='模拟运行：只计算信号，不写入数据库')

    args = parser.parse_args()

    today = args.date or datetime.now().strftime('%Y-%m-%d')
    if not args.date:
        args.date = today

    cache = BacktestCache()
    monitor_db = MonitorDB()
    quality_evaluator = StockQualityEvaluator(kline_cache=cache)

    if args.status:
        show_status(monitor_db, cache)
        return

    if args.init_backfill:
        print('🔄 开始回填历史数据...')
        result = init_backfill(cache, monitor_db, quality_evaluator, args.quality_min)
        print(f'\n✅ 回填完成 (source=backfill, 不影响真实统计):')
        print(f'   新注册: {result.get("new_registrations", 0)} 只')
        print(f'   持仓创建: {result.get("positions_created", 0)} 个')
        return

    if args.once:
        run_daily_monitor(
            monitor_db=monitor_db,
            cache=cache,
            quality_evaluator=quality_evaluator,
            today=today,
            stop_loss_pct=args.stop_loss,
            take_profit_pct=args.take_profit,
            min_rating=args.quality_min,
            dry_run=args.dry_run,
        )
        return

    # 无参数时显示帮助
    parser.print_help()


if __name__ == '__main__':
    main()
