#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测：基于同意注册日，灵活设置买卖窗口

买入/卖出均相对于注册日指定交易日偏移范围（负数=注册前，正数=注册后），
支持任意组合，例如：

  # 默认: 注册前 10~1 天买入，注册当天卖出
  python3 backtest_timing.py

  # 注册+1天买入，持有到注册+7天卖出
  python3 backtest_timing.py --buy-range 1 1 --sell-range 7 7

  # 注册前 5~7 天买入，注册后 5~7 天卖出
  python3 backtest_timing.py --buy-range 5 7 --sell-range 5 7

  # 注册前 10 天 ~ 注册后 5 天，任意天买入，注册后 3~10 天任意天卖出
  python3 backtest_timing.py --buy-range -10 5 --sell-range 3 10

  # 按股输出每日价格详情
  python3 backtest_timing.py --detail

  # 输出 JSON
  python3 backtest_timing.py --format json
"""

import argparse
import sys
import os
import re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.backtest_cache import BacktestCache


def parse_progress_dates(progress_full: str) -> dict:
    """解析进度字符串，提取日期"""
    if not progress_full:
        return {}
    progress_full = progress_full.replace('<br>', '\n')
    dates = {}
    pattern = r'(\d{4}-\d{2}-\d{2})\s+([^\n]+)'
    for match in re.finditer(pattern, progress_full):
        dates[match.group(2).strip()] = match.group(1)
    return dates


def get_bonds_with_registration(cache: BacktestCache):
    """获取有同意注册日期的转债列表"""
    bonds = cache.get_latest_jisilu_data()
    if not bonds:
        cache.save_jisilu_snapshot()
        bonds = cache.get_latest_jisilu_data()

    valid = []
    for b in bonds:
        if not b.get('stock_code'):
            continue
        dates = parse_progress_dates(b.get('progress_full', ''))
        if '同意注册' in dates:
            b['registration_date'] = dates['同意注册']
            b['progress_dates'] = dates
            valid.append(b)
    return valid


def offset_to_label(off: int) -> str:
    """将偏移量转为可读标签"""
    if off == 0:
        return '注册日'
    elif off > 0:
        return f'注册+{off}天'
    else:
        return f'注册{off}天'


def get_stock_daily_data(stock_code: str, reg_date: str,
                         buy_offsets: list, sell_offsets: list,
                         cache: BacktestCache):
    """
    获取单只股票从注册前到注册后的每日数据

    Returns:
        {
            'stock_code': ..., 'bond_name': ..., 'reg_date': ..., 'reg_idx': ...,
            'reg_price': ...,
            'prices': [{date, close, change_pct, offset}, ...],
            'results': [...],
        }
    """
    max_lookback = max(abs(o) for o in buy_offsets + sell_offsets) if (buy_offsets or sell_offsets) else 10
    max_lookforward = max((o for o in buy_offsets + sell_offsets if o > 0), default=0)

    prices = cache.get_kline_as_dict(stock_code, days=max(max_lookback + max_lookforward + 5, 60))
    if not prices:
        return None

    sorted_dates = sorted(prices.keys())
    if len(sorted_dates) < 10:
        return None

    # 找到注册日对应的交易日索引
    reg_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= reg_date:
            reg_idx = i
            break

    if reg_idx is None:
        return None

    # 跳过注册日为未来的数据（避免用未发生的数据回测）
    today = datetime.now().strftime('%Y-%m-%d')
    if reg_date > today:
        return None

    reg_price = prices[sorted_dates[reg_idx]]['close']

    # 确定显示范围
    start_idx = max(0, reg_idx - max_lookback)
    end_idx = min(len(sorted_dates) - 1, reg_idx + max_lookforward)

    daily = []
    for i in range(start_idx, end_idx + 1):
        d = sorted_dates[i]
        close = prices[d]['close']
        offset = i - reg_idx
        change_pct = 0
        if i > start_idx:
            prev_close = prices[sorted_dates[i - 1]]['close']
            change_pct = ((close - prev_close) / prev_close) * 100 if prev_close > 0 else 0
        daily.append({
            'date': d,
            'close': round(close, 2),
            'change_pct': round(change_pct, 2),
            'offset': offset,
        })

    # 计算各买入/卖出组合收益
    results = []
    for boff in buy_offsets:
        for soff in sell_offsets:
            if boff >= soff:
                continue  # 买入必须在卖出之前

            buy_idx = reg_idx + boff
            sell_idx = reg_idx + soff
            if buy_idx < 0 or sell_idx >= len(sorted_dates):
                continue

            entry_date = sorted_dates[buy_idx]
            exit_date = sorted_dates[sell_idx]

            # 跳过买入/卖出日期在未来的情况
            if entry_date > today or exit_date > today:
                continue

            entry_price = prices[entry_date]['close']
            exit_price = prices[exit_date]['close']
            if entry_price <= 0:
                continue

            pct = ((exit_price - entry_price) / entry_price) * 100
            results.append({
                'buy_offset': boff,
                'sell_offset': soff,
                'buy_date': entry_date,
                'sell_date': exit_date,
                'buy_price': round(entry_price, 2),
                'sell_price': round(exit_price, 2),
                'pct': round(pct, 2),
                'holding_days': sell_idx - buy_idx,
            })

    return {
        'stock_code': stock_code,
        'reg_date': reg_date,
        'reg_price': round(reg_price, 2),
        'reg_idx': reg_idx,
        'prices': daily,
        'results': results,
    }


def run_backtest(bonds: list, buy_offsets: list, sell_offsets: list,
                 limit: int, cache: BacktestCache):
    """对全部转债运行回测

    Returns:
        (stock_details, scenario_stats)
    """
    stock_details = []

    for bond in bonds[:limit]:
        stock_code = bond['stock_code']
        reg_date = bond['registration_date']
        bond_name = bond.get('bond_name') or bond.get('stock_name') or ''

        result = get_stock_daily_data(stock_code, reg_date, buy_offsets, sell_offsets, cache)
        if not result or not result['results']:
            continue

        result['bond_name'] = bond_name
        stock_details.append(result)

    # 聚合场景统计
    all_scenarios = {}
    for boff in buy_offsets:
        for soff in sell_offsets:
            all_scenarios[(boff, soff)] = {'pcts': [], 'holdings': [], 'up': 0, 'down': 0}

    for sd in stock_details:
        for r in sd['results']:
            key = (r['buy_offset'], r['sell_offset'])
            all_scenarios[key]['pcts'].append(r['pct'])
            all_scenarios[key]['holdings'].append(r['holding_days'])
            if r['pct'] > 0:
                all_scenarios[key]['up'] += 1
            else:
                all_scenarios[key]['down'] += 1

    scenario_stats = []
    for (boff, soff), data in all_scenarios.items():
        if not data['pcts']:
            continue
        n = len(data['pcts'])
        buy_label = offset_to_label(boff)
        sell_label = offset_to_label(soff)
        scenario_stats.append({
            'buy_offset': boff,
            'sell_offset': soff,
            'label': f'{buy_label} → {sell_label}',
            'count': n,
            'avg_pct': round(sum(data['pcts']) / n, 2),
            'up_rate': round(data['up'] / n * 100, 1),
            'avg_holding': round(sum(data['holdings']) / n, 1),
            'best': round(max(data['pcts']), 2),
            'worst': round(min(data['pcts']), 2),
            'total_return': round(sum(data['pcts']), 2),
        })

    return stock_details, scenario_stats


def offset_label_short(off: int) -> str:
    """短标签用于表头"""
    if off == 0:
        return '注册日'
    elif off > 0:
        return f'+{off}天'
    else:
        return f'{off}天'


def print_detail_report(stock_details: list, scenario_stats: list,
                        buy_offsets: list, sell_offsets: list):
    """按股票打印每日价格详情，末尾加跨股汇总"""
    if not stock_details:
        print('\n没有回测结果')
        return

    sell_labels = {s: offset_label_short(s) for s in sell_offsets}

    for sd in stock_details:
        bond_name = (sd['bond_name'] or 'N/A')[:12]
        print(f'\n{"=" * 80}')
        print(f'{bond_name} ({sd["stock_code"]})  同意注册: {sd["reg_date"]}  注册价: {sd["reg_price"]:.2f}')
        print(f'{"=" * 80}')

        # 每日价格表
        header = f'  {"日期":>10} {"偏移":>5} {"收盘价":>8} {"日涨跌":>7}'
        for boff in buy_offsets:
            header += f' 累计{offset_label_short(boff):>6}'
        header += f'  {"标记":>8}'
        print(header)
        print('  ' + '-' * 78)

        offset_price = {}
        for p in sd['prices']:
            offset_price[p['offset']] = p['close']

        for p in sd['prices']:
            offset = p['offset']
            date = p['date']
            close = p['close']
            chg = p['change_pct']

            line = f'  {date:>10} ({offset:+}d) {close:>8.2f} {chg:>+6.2f}%'

            markers = []
            for boff in buy_offsets:
                bprice = offset_price.get(boff)
                if bprice and bprice > 0:
                    cum_pct = ((close - bprice) / bprice) * 100
                    line += f' {cum_pct:>+6.2f}%'
                    if offset == boff:
                        markers.append(f'买{offset_label_short(boff)}')
                else:
                    line += f' {"-":>6}'

            if offset == 0:
                markers.append('注册')

            marker_str = ' '.join(markers) if markers else ''
            if marker_str:
                line += f'  {marker_str}'
            print(line)

        # 底部汇总：买入→卖出收益矩阵
        print()
        col_header = f'  {"买入→":>8}'
        for soff in sell_offsets:
            col_header += f' {sell_labels[soff]:>8}'
        col_header += f' {"平均":>8}'
        print(col_header)
        print('  ' + '-' * 78)

        for boff in buy_offsets:
            row = f'  {offset_label_short(boff):>6}  '
            total = 0
            count = 0
            for soff in sell_offsets:
                matched = [r for r in sd['results']
                          if r['buy_offset'] == boff and r['sell_offset'] == soff]
                if matched:
                    r = matched[0]
                    row += f' {r["pct"]:>+7.2f}%'
                    total += r['pct']
                    count += 1
                else:
                    row += f' {"-":>8}'
            if count > 0:
                row += f' {total/count:>+7.2f}%'
            print(row)

    # 跨股汇总统计
    print(f'\n{"=" * 80}')
    sell_range_str = ', '.join(offset_label_short(s) for s in sell_offsets)
    print(f'汇总统计 ({len(stock_details)} 只转债，卖出: {sell_range_str})')
    print(f'{"=" * 80}')
    print()
    print(f'  {"买入":>10} {"卖出":>10} {"平均收益":>8} {"上涨率":>6} {"持仓":>6} {"最佳":>8} {"最差":>8} {"样本":>6}')
    print('  ' + '-' * 88)

    for boff in buy_offsets:
        for soff in sell_offsets:
            matched = [s for s in scenario_stats
                      if s['buy_offset'] == boff and s['sell_offset'] == soff]
            if matched:
                s = matched[0]
                b_label = offset_label_short(boff)
                s_label = offset_label_short(soff)
                print(f'  {b_label:>10} {s_label:>10} {s["avg_pct"]:>+7.2f}% {s["up_rate"]:>5.1f}% '
                      f'{s["avg_holding"]:>4.0f}天 {s["best"]:>+7.2f}% {s["worst"]:>+7.2f}% {s["count"]:>4}')

    sorted_stats = sorted(scenario_stats, key=lambda x: x['avg_pct'], reverse=True)
    if sorted_stats:
        print()
        print('  Top 5 策略 (按平均收益):')
        for i, s in enumerate(sorted_stats[:5], 1):
            emoji = '+' if s['avg_pct'] > 0 else '-'
            print(f'    {i}. [{emoji}] {s["label"]} | 平均 {s["avg_pct"]:+.2f}%, '
                  f'上涨率 {s["up_rate"]:.0f}%, 样本 {s["count"]}')

    print(f'{"=" * 80}')


def print_batch_report(stock_details: list, scenario_stats: list,
                       buy_offsets: list, sell_offsets: list):
    """批量汇总模式：按买入日分组，显示所有股票"""
    if not stock_details:
        print('\n没有回测结果')
        return

    sell_labels = {s: offset_label_short(s) for s in sell_offsets}

    # 第一部分：逐日明细
    for boff in buy_offsets:
        print(f'\n{"=" * 90}')
        print(f'买入: {offset_to_label(boff)}')
        print(f'{"=" * 90}')

        print(f'  {"债券名称":>12} {"代码":>8} {"注册日":>12} {"注册价":>8}', end='')
        for soff in sell_offsets:
            print(f' {"收益":>8} {"持仓":>6}', end='')
        print()
        print('  ' + '-' * 88, end='')

        for sd in stock_details:
            bond_name = (sd['bond_name'] or 'N/A')[:12]
            print(f'\n  {bond_name:>12} {sd["stock_code"]:>8} {sd["reg_date"]:>12} {sd["reg_price"]:>8.2f}', end='')

            results_by_sell = {}
            for r in sd['results']:
                if r['buy_offset'] == boff:
                    results_by_sell[r['sell_offset']] = r

            for soff in sell_offsets:
                r = results_by_sell.get(soff)
                if r:
                    print(f' {r["pct"]:>+7.2f}% {r["holding_days"]:>4}天', end='')
                else:
                    print(f' {"-":>8} {"-":>4}', end='')

        print()
        print()

    # 第二部分：汇总统计
    print('=' * 90)
    sell_range_str = ', '.join(offset_label_short(s) for s in sell_offsets)
    print(f'汇总统计 ({len(stock_details)} 只转债，卖出: {sell_range_str})')
    print('=' * 90)
    print()
    print(f'  {"买入":>10} {"卖出":>10} {"平均收益":>8} {"上涨率":>6} {"持仓":>6} {"最佳":>8} {"最差":>8} {"样本":>6}')
    print('  ' + '-' * 88)

    for boff in buy_offsets:
        for soff in sell_offsets:
            matched = [s for s in scenario_stats
                      if s['buy_offset'] == boff and s['sell_offset'] == soff]
            if matched:
                s = matched[0]
                b_label = offset_label_short(boff)
                s_label = offset_label_short(soff)
                print(f'  {b_label:>10} {s_label:>10} {s["avg_pct"]:>+7.2f}% {s["up_rate"]:>5.1f}% '
                      f'{s["avg_holding"]:>4.0f}天 {s["best"]:>+7.2f}% {s["worst"]:>+7.2f}% {s["count"]:>4}')

    scenario_stats.sort(key=lambda x: x['avg_pct'], reverse=True)
    print()
    print('  Top 5 策略 (按平均收益):')
    for i, s in enumerate(scenario_stats[:5], 1):
        emoji = '+' if s['avg_pct'] > 0 else '-'
        print(f'    {i}. [{emoji}] {s["label"]} | 平均 {s["avg_pct"]:+.2f}%, '
              f'上涨率 {s["up_rate"]:.0f}%, 样本 {s["count"]}')

    print('=' * 90)


def print_json(stock_details: list, scenario_stats: list,
               buy_offsets: list, sell_offsets: list):
    import json
    output = {
        'stock_details': stock_details,
        'scenarios': scenario_stats,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def expand_range(spec):
    """
    将 [max, min] 展开为 range 列表
    max 和 min 都可以是负数（注册前）或正数（注册后）
    如果 max > min，说明是 [远, 近]，正常展开
    如果 max == min，返回单元素
    """
    if len(spec) == 2:
        a, b = spec
        if a == b:
            return [a]
        elif a < b:
            return list(range(a, b + 1))
        else:
            # 兼容旧格式: --buy-range 10 1 表示 -10 到 -1
            if a > 0 and b > 0:
                return list(range(-a, -b + 1))
            else:
                return list(range(min(a, b), max(a, b) + 1))
    return spec


def main():
    parser = argparse.ArgumentParser(
        description='回测：基于同意注册日，灵活设置买卖窗口',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--limit', '-n', type=int, default=20, help='分析转债数量')
    parser.add_argument(
        '--buy-range', type=int, nargs=2, default=[10, 1],
        help='买入窗口 [最大偏移, 最小偏移] (默认: 10 1，即注册前10天到前1天)'
             '\n       也支持指定偏移范围: --buy-range -7 -5'
             '\n       也支持正数: --buy-range 1 1 表示注册+1天买入',
    )
    parser.add_argument(
        '--sell-range', type=int, nargs=2, default=[0, 0],
        help='卖出窗口 [最大偏移, 最小偏移] (默认: 0 0，即注册当天)'
             '\n       也支持范围: --sell-range 5 7 表示注册+5天到+7天'
             '\n       也支持负数: --sell-range -1 -1 表示注册前1天卖出',
    )
    parser.add_argument(
        '--detail', action='store_true',
        help='按股票输出每日价格详情（包含累计涨跌）',
    )
    parser.add_argument('--format', '-f', choices=['text', 'json'], default='text')
    args = parser.parse_args()

    buy_offsets = expand_range(args.buy_range)
    sell_offsets = expand_range(args.sell_range)

    cache = BacktestCache()
    print('正在获取待发转债数据...')
    bonds = get_bonds_with_registration(cache)
    print(f'找到 {len(bonds)} 只有"同意注册"日期的转债')

    buy_range_str = ', '.join(offset_to_label(o) for o in sorted(set(buy_offsets)))
    sell_range_str = ', '.join(offset_to_label(o) for o in sorted(set(sell_offsets)))
    print(f'买入: {buy_range_str}')
    print(f'卖出: {sell_range_str}')

    stock_details, scenario_stats = run_backtest(
        bonds, buy_offsets, sell_offsets, args.limit, cache)

    if args.format == 'json':
        print_json(stock_details, scenario_stats, buy_offsets, sell_offsets)
    elif args.detail:
        print_detail_report(stock_details, scenario_stats, buy_offsets, sell_offsets)
    else:
        print_batch_report(stock_details, scenario_stats, buy_offsets, sell_offsets)


if __name__ == '__main__':
    main()
