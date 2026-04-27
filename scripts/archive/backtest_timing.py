#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测：从回测数据库直接提取数据，灵活设置买卖窗口

支持通过 --phase 参数筛选不同阶段的转债（默认=注册），
回测数据库直接提供 progress_full 含注册日期的数据。

示例：

  # 默认：查询"注册"阶段，30只转债，注册前10~1天买，注册当天卖
  python3 backtest_timing.py

  # 查询"上市委"阶段
  python3 backtest_timing.py --phase 注册

  # 指定数量50只
  python3 backtest_timing.py --limit 50

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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

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


def get_bonds_with_registration(cache: BacktestCache, phase: str = '注册'):
    """从回测数据库直接提取指定阶段的转债，提取锚定日期"""
    bonds = cache.get_jisilu_bonds(phase=phase)
    if not bonds:
        print(f'数据库无"{phase}"阶段数据，请先运行 cache.save_jisilu_data() 导入数据')
        return []

    valid = []
    for b in bonds:
        if not b.get('stock_code'):
            continue
        dates = parse_progress_dates(b.get('progress_full', ''))
        # 根据 phase 选择对应的锚定日期字段
        anchor_key = {
            '注册': '同意注册',
            '上市委': '上市委通过',
            '预案': '董事会预案',
            '股东大会': '股东大会通过',
            '受理': '受理',
            '申购': '申购日',
        }.get(phase, '同意注册')

        if anchor_key in dates:
            b['anchor_date'] = dates[anchor_key]
            b['progress_dates'] = dates
            valid.append(b)

    return valid


def offset_to_label(off: int, anchor_short: str = '注册') -> str:
    """将偏移量转为可读标签"""
    if off == 0:
        return anchor_short + '日'
    elif off > 0:
        return f'{anchor_short}+{off}天'
    else:
        return f'{anchor_short}{off}天'


def get_stock_daily_data(stock_code: str, reg_date: str,
                         buy_offsets: list, sell_offsets: list,
                         cache: BacktestCache, verbose: bool = False):
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

    # 请求600天K线，确保锚定日前10+天的数据可用
    kline_days = max(max_lookback + max_lookforward + 5, 600)
    prices = cache.get_kline_as_dict(stock_code, days=kline_days)
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
                 limit: int, cache: BacktestCache, anchor_short: str = '注册'):
    """对全部转债运行回测

    Returns:
        (stock_details, scenario_stats, skip_stats)
    """
    stock_details = []
    skip_stats = {'no_kline': 0, 'no_reg_in_kline': 0, 'no_results': 0, 'future': 0}

    # 预先拉取所有标的的 K 线数据（确保有足够历史）
    print('正在预取 K 线数据...')
    kline_days = 600
    pre_fetched = 0
    for bond in bonds[:limit]:
        sc = bond['stock_code']
        # 检查缓存是否足够
        prices = cache.get_kline_as_dict(sc, days=kline_days)
        if not prices or len(prices) < 200:
            cache.fetch_and_save_kline(sc, days=kline_days)
            pre_fetched += 1
    if pre_fetched:
        print(f'  从 API 补充 {pre_fetched}/{limit} 只 K 线数据')

    for bond in bonds[:limit]:
        stock_code = bond['stock_code']
        anchor_date = bond.get('anchor_date', '')
        bond_name = bond.get('bond_name') or bond.get('stock_name') or ''

        if not anchor_date:
            continue

        # 检查锚定日期是否在未来
        today = datetime.now().strftime('%Y-%m-%d')
        if anchor_date > today:
            skip_stats['future'] += 1
            continue

        result = get_stock_daily_data(stock_code, anchor_date, buy_offsets, sell_offsets, cache)
        if not result:
            skip_stats['no_kline'] += 1
            continue
        if not result['results']:
            skip_stats['no_results'] += 1
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
        buy_label = offset_to_label(boff, anchor_short)
        sell_label = offset_to_label(soff, anchor_short)
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

    return stock_details, scenario_stats, skip_stats


def offset_label_short(off: int, anchor_short: str = '注册') -> str:
    """短标签用于表头"""
    if off == 0:
        return anchor_short + '日'
    elif off > 0:
        return f'+{off}天'
    else:
        return f'{off}天'


def print_detail_report(stock_details: list, scenario_stats: list,
                        buy_offsets: list, sell_offsets: list,
                        anchor_label: str = '同意注册', anchor_short: str = '注册'):
    """按股票打印每日价格详情，末尾加跨股汇总"""
    if not stock_details:
        print('\n没有回测结果')
        return

    sell_labels = {s: offset_label_short(s, anchor_short) for s in sell_offsets}

    for sd in stock_details:
        bond_name = (sd['bond_name'] or 'N/A')[:12]
        print(f'\n{"=" * 80}')
        print(f'{bond_name} ({sd["stock_code"]})  {anchor_label}: {sd["reg_date"]}  锚定价: {sd["reg_price"]:.2f}')
        print(f'{"=" * 80}')

        # 每日价格表
        header = f'  {"日期":>10} {"偏移":>5} {"收盘价":>8} {"日涨跌":>7}'
        for boff in buy_offsets:
            header += f' 累计{offset_label_short(boff, anchor_short):>6}'
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
                        markers.append(f'买{offset_label_short(boff, anchor_short)}')
                else:
                    line += f' {"-":>6}'

            if offset == 0:
                markers.append(anchor_short)

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
            row = f'  {offset_label_short(boff, anchor_short):>6}  '
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
    sell_range_str = ', '.join(offset_label_short(s, anchor_short) for s in sell_offsets)
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
                b_label = offset_label_short(boff, anchor_short)
                s_label = offset_label_short(soff, anchor_short)
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
                       buy_offsets: list, sell_offsets: list,
                       anchor_label: str = '同意注册', anchor_short: str = '注册'):
    """批量汇总模式：按买入日分组，显示所有股票"""
    if not stock_details:
        print('\n没有回测结果')
        return

    sell_labels = {s: offset_label_short(s, anchor_short) for s in sell_offsets}

    # 第一部分：逐日明细
    for boff in buy_offsets:
        print(f'\n{"=" * 90}')
        print(f'买入: {offset_to_label(boff, anchor_short)}')
        print(f'{"=" * 90}')

        date_label = anchor_label
        price_label = '锚定价'
        print(f'  {"债券名称":>12} {"代码":>8} {date_label:>12} {price_label:>8}', end='')
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
    sell_range_str = ', '.join(offset_label_short(s, anchor_short) for s in sell_offsets)
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
                b_label = offset_label_short(boff, anchor_short)
                s_label = offset_label_short(soff, anchor_short)
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
        description='回测：从回测数据库直接提取数据，灵活设置买卖窗口',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--phase', type=str, default='注册',
                        choices=['待发', '已上市', '预案', '股东大会', '受理', '上市委', '注册', '申购'],
                        help='查询阶段（默认=注册），对应 get_jisilu_bonds() 的 phase 参数')
    parser.add_argument('--limit', '-n', type=int, default=30, help='回测转债数量（默认30）')
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
    print(f'正在从回测数据库查询"{args.phase}"阶段数据...')
    bonds = get_bonds_with_registration(cache, phase=args.phase)
    anchor_label = {
        '注册': '同意注册',
        '上市委': '上市委通过',
        '预案': '董事会预案',
        '股东大会': '股东大会通过',
        '受理': '受理',
        '申购': '申购日',
    }.get(args.phase, '锚定日期')
    # 短标签用于偏移量显示
    anchor_short = {
        '注册': '注册', '上市委': '上市委', '预案': '预案',
        '股东大会': '大会', '受理': '受理', '申购': '申购',
    }.get(args.phase, '锚定')
    print(f'找到 {len(bonds)} 只有"{anchor_label}"日期的转债')

    buy_range_str = ', '.join(offset_to_label(o, anchor_short) for o in sorted(set(buy_offsets)))
    sell_range_str = ', '.join(offset_to_label(o, anchor_short) for o in sorted(set(sell_offsets)))
    print(f'买入: {buy_range_str}')
    print(f'卖出: {sell_range_str}')

    stock_details, scenario_stats, skip_stats = run_backtest(
        bonds, buy_offsets, sell_offsets, args.limit, cache, anchor_short)

    # 跳过统计
    total_skipped = sum(skip_stats.values())
    if total_skipped > 0:
        reasons = []
        if skip_stats['future']:
            reasons.append(f'未来锚定{skip_stats["future"]}')
        if skip_stats['no_kline']:
            reasons.append(f'缺K线{skip_stats["no_kline"]}')
        if skip_stats['no_results']:
            reasons.append(f'K线范围不足{skip_stats["no_results"]}')
        print(f'⚠️ 跳过 {total_skipped}/{args.limit} 只: {", ".join(reasons)}')

    if args.format == 'json':
        print_json(stock_details, scenario_stats, buy_offsets, sell_offsets)
    elif args.detail:
        print_detail_report(stock_details, scenario_stats, buy_offsets, sell_offsets, anchor_label, anchor_short)
    else:
        print_batch_report(stock_details, scenario_stats, buy_offsets, sell_offsets, anchor_label, anchor_short)


if __name__ == '__main__':
    main()
