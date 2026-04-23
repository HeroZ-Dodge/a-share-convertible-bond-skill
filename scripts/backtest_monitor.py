#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测：注册+3天入场，持有7天卖出策略

精确模拟 monitor_strategy.py 的行为：
1. 发现新"同意注册"转债
2. 注册日 + 3个交易日 = 买入日
3. 买入日 + 7个交易日 = 卖出日
4. 买入时质量过滤（可选）
5. 持有7天到期卖出（可选止损/止盈）

Usage:
    # 默认策略：+3天买入，+7天卖出，质量过滤B级以上
    python3 scripts/backtest_monitor.py

    # 关闭质量过滤
    python3 scripts/backtest_monitor.py --no-quality-filter

    # 启用止损/止盈
    python3 scripts/backtest_monitor.py --stop-loss -5 --take-profit 15

    # 测试不同买卖偏移
    python3 scripts/backtest_monitor.py --buy-offset 1 --sell-offset 10

    # 按股票打印每日详情
    python3 scripts/backtest_monitor.py --detail

    # 输出 JSON
    python3 scripts/backtest_monitor.py --format json
"""

import argparse
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.backtest_cache import BacktestCache
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


def get_bonds_with_registration(cache: BacktestCache) -> List[Dict]:
    """获取有同意注册日期的转债列表"""
    bonds = cache.get_latest_jisilu_data()
    if not bonds:
        cache.save_jisilu_snapshot()
        bonds = cache.get_latest_jisilu_data()

    valid = []
    for b in bonds:
        sc = b.get('stock_code', '')
        if not sc:
            continue
        dates = parse_progress_dates(b.get('progress_full', ''))
        if '同意注册' in dates:
            b['stock_code'] = sc
            b['registration_date'] = dates['同意注册']
            b['progress_dates'] = dates
            b['bond_name'] = b.get('bond_name') or b.get('stock_name', '')
            valid.append(b)
    return valid


def find_trading_day(kline: Dict[str, Dict], base_date: str,
                     offset: int) -> Optional[Tuple[str, float, int]]:
    """
    在K线数据中从 base_date 起偏移 offset 个交易日

    Returns:
        (date, close, index) 或 None
    """
    sorted_dates = sorted(kline.keys())
    base_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= base_date:
            base_idx = i
            break
    if base_idx is None or base_idx + offset >= len(sorted_dates):
        return None
    target_date = sorted_dates[base_idx + offset]
    target_price = kline[target_date]['close']
    return (target_date, target_price, base_idx + offset)


def evaluate_quality_at_buy(kline: Dict[str, Dict], buy_idx: int,
                            evaluator: StockQualityEvaluator) -> Optional[Dict]:
    """
    在买入日评估正股质量
    使用买入日及之前的数据（模拟真实情况）
    """
    # 只用买入日及之前的K线数据
    sorted_dates = sorted(kline.keys())
    available_dates = sorted_dates[:buy_idx + 1]
    if len(available_dates) < 20:
        return None

    filtered_kline = {d: kline[d] for d in available_dates}
    return evaluator.evaluate('dummy', filtered_kline)


def run_backtest_for_bond(bond: Dict, buy_offset: int, sell_offset: int,
                           stop_loss: float, take_profit: float,
                           use_quality_filter: bool,
                           min_rating: str,
                           cache: BacktestCache,
                           evaluator: StockQualityEvaluator) -> Optional[Dict]:
    """
    对单只转债运行回测

    Returns:
        {stock_code, bond_name, reg_date, reg_price,
         buy_date, buy_price, sell_date, sell_price,
         hold_days, return_pct, quality_rating, exit_reason,
         daily_prices} 或 None
    """
    stock_code = bond['stock_code']
    reg_date = bond['registration_date']
    bond_name = bond['bond_name']

    # 获取足够长的K线数据
    lookback = 60
    lookforward = max(sell_offset, 20)
    kline = cache.get_kline_as_dict(stock_code, days=lookback + lookforward)
    if not kline or len(kline) < 10:
        return None

    # 找到注册日对应的交易日
    sorted_dates = sorted(kline.keys())
    reg_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= reg_date:
            reg_idx = i
            break
    if reg_idx is None:
        return None

    reg_price = kline[sorted_dates[reg_idx]]['close']

    # 跳过未来注册
    today = datetime.now().strftime('%Y-%m-%d')
    if reg_date > today:
        return None

    # 计算买入日
    buy_result = find_trading_day(kline, reg_date, buy_offset)
    if not buy_result:
        return None
    buy_date, buy_price, buy_idx = buy_result

    if buy_price <= 0:
        return None

    # 质量过滤
    quality_rating = None
    quality_score = None
    if use_quality_filter:
        quality = evaluate_quality_at_buy(kline, buy_idx, evaluator)
        if quality:
            quality_rating = quality.get('rating', 'D')
            quality_score = quality.get('total_score', 0)
            rating_order = {'A': 4, 'B': 3, 'C': 2, 'D': 1}
            min_value = rating_order.get(min_rating, 3)
            if rating_order.get(quality_rating, 0) < min_value:
                return None
        else:
            # 无法评估质量，跳过
            return None

    # 计算卖出日
    sell_result = find_trading_day(kline, buy_date, sell_offset)
    if not sell_result:
        return None
    sell_date, planned_sell_price, sell_idx = sell_result

    # 模拟逐日持仓，检查止损/止盈
    exit_date = None
    exit_price = None
    exit_reason = None

    for i in range(buy_idx + 1, min(sell_idx + 1, len(sorted_dates))):
        d = sorted_dates[i]
        p = kline[d]['close']
        ret = ((p - buy_price) / buy_price) * 100

        if stop_loss and ret <= stop_loss:
            exit_date = d
            exit_price = p
            exit_reason = 'stop_loss'
            break
        elif take_profit and ret >= take_profit:
            exit_date = d
            exit_price = p
            exit_reason = 'take_profit'
            break

    if not exit_date:
        # 持有到期
        exit_date = sell_date
        exit_price = planned_sell_price
        exit_reason = 'hold_7d'

    return_pct = ((exit_price - buy_price) / buy_price) * 100
    hold_days = sell_idx - buy_idx if sell_idx > buy_idx else 0

    return {
        'stock_code': stock_code,
        'bond_name': bond_name,
        'reg_date': reg_date,
        'reg_price': round(reg_price, 2),
        'buy_date': buy_date,
        'buy_price': round(buy_price, 2),
        'sell_date': exit_date,
        'sell_price': round(exit_price, 2),
        'planned_sell_date': sell_date,
        'hold_days': hold_days,
        'return_pct': round(return_pct, 2),
        'quality_rating': quality_rating,
        'quality_score': quality_score,
        'exit_reason': exit_reason,
    }


def print_table(results: List[Dict], show_quality: bool) -> None:
    """打印汇总表格"""
    if not results:
        print('\n⚠️  没有回测结果')
        return

    n = len(results)
    wins = sum(1 for r in results if r['return_pct'] > 0)
    avg_ret = sum(r['return_pct'] for r in results) / n
    avg_hold = sum(r['hold_days'] for r in results) / n
    best = max(r['return_pct'] for r in results)
    worst = min(r['return_pct'] for r in results)
    total_ret = sum(r['return_pct'] for r in results)

    print()
    print('=' * 70)
    print('📊 注册+3天入场策略回测汇总')
    print('=' * 70)
    print()
    print(f'回测数量：{n} 只')
    print(f'上涨：{wins} 只 ({wins/n*100:.1f}%)')
    print(f'下跌：{n - wins} 只 ({(n-wins)/n*100:.1f}%)')
    print()
    print(f'平均收益：{avg_ret:+.2f}%')
    print(f'累计收益：{total_ret:+.2f}%')
    print(f'最佳收益：{best:+.2f}%')
    print(f'最差收益：{worst:+.2f}%')
    print(f'平均持仓：{avg_hold:.0f} 交易日')
    print()

    # 按退出原因统计
    reasons = {}
    for r in results:
        reason = r['exit_reason']
        if reason not in reasons:
            reasons[reason] = []
        reasons[reason].append(r['return_pct'])

    if len(reasons) > 1:
        print('退出原因统计:')
        reason_map = {
            'hold_7d': '持有7天到期',
            'stop_loss': '止损',
            'take_profit': '止盈',
        }
        for reason, rets in reasons.items():
            avg = sum(rets) / len(rets)
            print(f'  {reason_map.get(reason, reason)}: {len(rets)} 只, 平均 {avg:+.2f}%')
        print()

    # 详细表格
    print('-' * 70)
    header = f'  {"债券名称":>10} {"代码":>8} {"注册日":>12} {"买入价":>8} {"卖出价":>8} {"收益":>8} {"持仓":>6}'
    if show_quality:
        header += f' {"评级":>4}'
    print(header)
    print('  ' + '-' * 66)

    for r in sorted(results, key=lambda x: x['reg_date']):
        line = (f'  {r["bond_name"]:>10} {r["stock_code"]:>8} '
                f'{r["reg_date"]:>12} {r["buy_price"]:>8.2f} '
                f'{r["sell_price"]:>8.2f} {r["return_pct"]:>+7.2f}% '
                f'{r["hold_days"]:>4}天')
        if show_quality and r.get('quality_rating'):
            line += f' {r["quality_rating"]:>4}'
        print(line)

    print('=' * 70)


def print_detail_report(results: List[Dict], cache: BacktestCache) -> None:
    """按股票打印每日详情"""
    for r in results:
        stock_code = r['stock_code']
        kline = cache.get_kline_as_dict(stock_code, days=60)
        if not kline:
            continue

        sorted_dates = sorted(kline.keys())

        # 找到注册日索引
        reg_idx = None
        for i, d in enumerate(sorted_dates):
            if d >= r['reg_date']:
                reg_idx = i
                break

        if reg_idx is None:
            continue

        print()
        print('=' * 70)
        print(f'{r["bond_name"]} ({stock_code})  注册日: {r["reg_date"]}  注册价: {r["reg_price"]:.2f}')
        print('=' * 70)

        # 打印注册日前后各10个交易日的价格
        start_idx = max(0, reg_idx - 5)
        end_idx = min(len(sorted_dates) - 1, reg_idx + 15)

        header = f'  {"日期":>10} {"偏移":>5} {"收盘价":>8} {"累计涨跌":>8} {"标记":>12}'
        print(header)
        print('  ' + '-' * 48)

        reg_price = kline[sorted_dates[reg_idx]]['close']
        buy_price = r['buy_price']

        for i in range(start_idx, end_idx + 1):
            d = sorted_dates[i]
            close = kline[d]['close']
            offset = i - reg_idx
            cum_pct = ((close - reg_price) / reg_price) * 100

            markers = []
            if d == r['buy_date']:
                markers.append('买入')
            if d == r['sell_date']:
                markers.append('卖出')
            if offset == 0:
                markers.append('注册')

            marker_str = ','.join(markers) if markers else ''
            print(f'  {d:>10} ({offset:+}d) {close:>8.2f} {cum_pct:>+7.2f}%  {marker_str}')

    # 底部汇总
    print()
    print_table(results, show_quality=True)


def print_json(results: List[Dict]) -> None:
    import json
    n = len(results)
    if n == 0:
        print(json.dumps({'results': [], 'summary': {}}, ensure_ascii=False, indent=2))
        return

    wins = sum(1 for r in results if r['return_pct'] > 0)
    summary = {
        'count': n,
        'wins': wins,
        'win_rate': round(wins / n * 100, 1),
        'avg_return': round(sum(r['return_pct'] for r in results) / n, 2),
        'total_return': round(sum(r['return_pct'] for r in results), 2),
        'best': round(max(r['return_pct'] for r in results), 2),
        'worst': round(min(r['return_pct'] for r in results), 2),
        'avg_hold_days': round(sum(r['hold_days'] for r in results) / n, 1),
    }
    output = {'summary': summary, 'results': results}
    print(json.dumps(output, ensure_ascii=False, indent=2))


def run_scenarios(cache: BacktestCache, args: argparse.Namespace) -> List[List[Dict]]:
    """运行多组参数对比"""
    all_results = []
    evaluator = StockQualityEvaluator(kline_cache=cache)

    bonds = get_bonds_with_registration(cache)
    print(f'找到 {len(bonds)} 只有"同意注册"日期的转债')
    print()

    # 参数组合
    buy_offsets = [args.buy_offset]
    sell_offsets = [args.sell_offset]

    # 如果有 --all-scenarios，测试多组偏移
    if args.all_scenarios:
        buy_offsets = list(range(1, 8))
        sell_offsets = list(range(5, 16))

    for boff in buy_offsets:
        for soff in sell_offsets:
            results = []
            for bond in bonds:
                result = run_backtest_for_bond(
                    bond, boff, soff,
                    args.stop_loss if args.stop_loss else None,
                    args.take_profit if args.take_profit else None,
                    not args.no_quality_filter,
                    args.quality_min,
                    cache, evaluator,
                )
                if result:
                    results.append(result)

            if results:
                all_results.append((boff, soff, results))

    return all_results


def main():
    parser = argparse.ArgumentParser(
        description='注册+3天入场策略回测',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--buy-offset', type=int, default=3,
                        help='注册日后第N个交易日买入（默认3）')
    parser.add_argument('--sell-offset', type=int, default=7,
                        help='买入日后第N个交易日卖出（默认7）')
    parser.add_argument('--stop-loss', type=float, default=None,
                        help='止损阈值（百分比，如 -5）')
    parser.add_argument('--take-profit', type=float, default=None,
                        help='止盈阈值（百分比，如 15）')
    parser.add_argument('--no-quality-filter', action='store_true',
                        help='关闭正股质量过滤')
    parser.add_argument('--quality-min', type=str, default='B',
                        help='最低正股质量评级（默认B）')
    parser.add_argument('--all-scenarios', action='store_true',
                        help='测试多组买卖偏移组合')
    parser.add_argument('--detail', action='store_true',
                        help='按股票打印每日价格详情')
    parser.add_argument('--format', '-f', choices=['text', 'json'], default='text')

    args = parser.parse_args()

    cache = BacktestCache()

    # 先获取最新快照
    bonds = get_bonds_with_registration(cache)
    if not bonds:
        print('⚠️  没有可用的注册数据')
        return

    # 策略标签
    qf = '质量过滤' if not args.no_quality_filter else '无质量过滤'
    sl = f'止损{args.stop_loss}%' if args.stop_loss else '无止损'
    tp = f'止盈{args.take_profit}%' if args.take_profit else '无止盈'
    print(f'策略: 注册+{args.buy_offset}天买入 → 买入+{args.sell_offset}天卖出 | {qf} | {sl} | {tp}')
    print()

    # 单场景回测（默认）
    evaluator = StockQualityEvaluator(kline_cache=cache)
    results = []

    for bond in bonds:
        result = run_backtest_for_bond(
            bond, args.buy_offset, args.sell_offset,
            args.stop_loss if args.stop_loss else None,
            args.take_profit if args.take_profit else None,
            not args.no_quality_filter,
            args.quality_min,
            cache, evaluator,
        )
        if result:
            results.append(result)

    if not results:
        print('⚠️  没有回测结果（可能全部被质量过滤或数据不足）')
        return

    if args.format == 'json':
        print_json(results)
    elif args.detail:
        print_detail_report(results, cache)
    else:
        print_table(results, show_quality=not args.no_quality_filter)

    # 如果指定 --all-scenarios，额外输出矩阵
    if args.all_scenarios:
        print()
        print('=' * 70)
        print('📊 多场景对比')
        print('=' * 70)
        print()

        # 重新运行多场景
        all_results = run_scenarios(cache, args)

        # 打印对比表
        print(f'  {"买入":>10} {"卖出":>10} {"样本":>6} {"平均收益":>8} {"胜率":>6} {"最佳":>8} {"最差":>8}')
        print('  ' + '-' * 62)
        for boff, soff, res in sorted(all_results, key=lambda x: x[2][0]['return_pct'] if x[2] else 0, reverse=True):
            if not res:
                continue
            n = len(res)
            wins = sum(1 for r in res if r['return_pct'] > 0)
            avg = sum(r['return_pct'] for r in res) / n
            best = max(r['return_pct'] for r in res)
            worst = min(r['return_pct'] for r in res)
            print(f'  +{boff}天{">":>6} +{soff}天{">":>5} {n:>4}只 '
                  f'{avg:>+7.2f}% {wins/n*100:>5.1f}% '
                  f'{best:>+7.2f}% {worst:>+7.2f}%')

        print('=' * 70)


if __name__ == '__main__':
    main()
