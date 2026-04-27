#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册策略信号监控脚本

每次从集思录 API 实时获取待发转债数据，应用 4 个策略检测信号，
支持策略组合。当策略 1 或策略 2 命中时，D0-D3 窗口持续提醒。

用法：
    python3 scripts/strategy_signal_monitor.py                    # 检测所有注册日当天信号
    python3 scripts/strategy_signal_monitor.py --combine          # 同时展示组合结果
    python3 scripts/strategy_signal_monitor.py --lookback 3       # 同时检查过去3天注册的是否仍在提醒窗口
    python3 scripts/strategy_signal_monitor.py --all-bonds        # 显示全部注册转债（含无信号）
"""
import sys
import os
import re
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lib.backtest_cache import BacktestCache
from lib.data_source import JisiluAPI


STRATEGIES = [
    ('策略1: pre3≤2% + mom10<5% + rc>0%',
     lambda f: f['pre3'] <= 2 and f['mom10'] < 5 and f['rc'] > 0),
    ('策略2: pre3≤2% + mom10<5%',
     lambda f: f['pre3'] <= 2 and f['mom10'] < 5),
    ('策略3: rc<-2%',
     lambda f: f['rc'] < -2),
    ('策略4: pre7<0%',
     lambda f: f['pre7'] < 0),
]

COMBO_CONDITIONS = [
    ('任一触发', lambda v: v.get('_s1', False) or v.get('_s2', False) or v.get('_s3', False) or v.get('_s4', False)),
    ('至少2个', lambda v: sum([v.get('_s1', False), v.get('_s2', False), v.get('_s3', False), v.get('_s4', False)]) >= 2),
    ('全部触发', lambda v: v.get('_s1', False) and v.get('_s2', False) and v.get('_s3', False) and v.get('_s4', False)),
]


def find_idx(sorted_dates, target):
    """找 <= target 的最后一个交易日（处理周末/节假日注册日）"""
    result = 0
    for i, d in enumerate(sorted_dates):
        if d <= target:
            result = i
        else:
            break
    return result


def calc_factors(prices, sorted_dates, ri):
    """以 ri 日为锚点，计算 pre3/pre7/rc/mom10"""
    anchor_price = prices[sorted_dates[ri]]['close']

    pre3 = 0
    if ri >= 3:
        p3 = prices[sorted_dates[ri - 3]]['close']
        if p3 > 0:
            pre3 = ((anchor_price - p3) / p3) * 100

    pre7 = 0
    if ri >= 7:
        p7 = prices[sorted_dates[ri - 7]]['close']
        if p7 > 0:
            pre7 = ((anchor_price - p7) / p7) * 100

    rc = 0
    if ri > 0:
        prev = prices[sorted_dates[ri - 1]]['close']
        if prev > 0:
            rc = ((anchor_price - prev) / prev) * 100

    mom10 = 0
    if ri >= 10:
        p10 = prices[sorted_dates[ri - 10]]['close']
        if p10 > 0:
            mom10 = ((anchor_price - p10) / p10) * 100

    return {
        'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
        'anchor_price': anchor_price,
    }


def evaluate_strategies(factors):
    """返回触发策略的索引列表"""
    triggered = []
    for i, (_, fn) in enumerate(STRATEGIES):
        if fn(factors):
            triggered.append(i)
    return triggered


def get_day_label(anchor_date, offset, today_str):
    """返回 D+N 标签，如果超过今天则标注 [待]"""
    label = f"D+{offset}"
    # 计算 D+offset 日期
    sorted_dates = None  # caller will handle
    return label


def fetch_and_filter_registered(bonds):
    """从集思录数据中提取已同意注册的转债，返回 (stock_code, anchor_date, bond_info) 列表"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    results = []
    for b in bonds:
        sc = b.get('stock_code') or b.get('stock_id', '')
        if not sc:
            continue
        pf = b.get('progress_full', '')
        if not pf:
            continue
        anchor = ''
        for line in pf.replace('<br>', '\n').split('\n'):
            if '同意注册' in line:
                m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                if m:
                    anchor = m.group(1)
                    break
        if not anchor or anchor > today_str:
            continue
        results.append((sc, anchor, b))
    return results


def check_bond_at_date(sc, anchor_date, check_date, cache):
    """
    检查某转债在指定日期（check_date）的信号因子。
    以 anchor_date 为 D+0，check_date 对应 D+N。
    在 check_date 当天计算因子（用 check_date 的收盘价作为锚定价）。

    Returns:
        dict or None
    """
    prices = cache.get_kline_as_dict(sc, days=1500)
    if not prices:
        return None

    sd = sorted(prices.keys())
    anchor_idx = find_idx(sd, anchor_date)

    # 找 check_date 的索引
    check_idx = find_idx(sd, check_date)
    if check_idx > anchor_idx + 3:
        check_idx = anchor_idx + 3  # 限制在 D+3 内

    if check_idx >= len(sd):
        return None

    actual_date = sd[check_idx]
    factors = calc_factors(prices, sd, check_idx)
    factors['check_date'] = actual_date
    factors['day_offset'] = check_idx - anchor_idx

    # 计算 D+1 买入价和 D+9 目标价
    buy_idx = check_idx + 1
    buy_price = None
    if buy_idx < len(sd):
        buy_price = prices[sd[buy_idx]]['open']

    sell_idx = check_idx + 8  # D+9
    sell_price = None
    if sell_idx < len(sd):
        sell_price = prices[sd[sell_idx]]['close']

    if buy_price and buy_price > 0 and sell_price:
        factors['projected_ret'] = ((sell_price - buy_price) / buy_price) * 100
    else:
        factors['projected_ret'] = 0

    factors['buy_price'] = buy_price
    factors['sell_price'] = sell_price

    triggered = evaluate_strategies(factors)
    factors['triggered'] = triggered

    return factors


def monitor(cache, jisilu, show_all=False, enable_combine=False, lookback_days=0):
    """
    主监控逻辑

    Args:
        cache: BacktestCache
        jisilu: JisiluAPI
        show_all: 显示全部注册转债（含无信号）
        enable_combine: 启用策略组合展示
        lookback_days: 回溯过去N天注册的转债，检查是否仍在 D0-D3 提醒窗口
    """
    today_str = datetime.now().strftime('%Y-%m-%d')

    print("=" * 90)
    print(f"注册策略信号监控 — {today_str}")
    print("=" * 90)

    # 1. 从集思录 API 实时获取
    print("\n正在从集思录 API 获取数据...")
    bonds = jisilu.fetch_pending_bonds(limit=200)
    if not bonds:
        print("  未获取到数据")
        return
    print(f"  获取到 {len(bonds)} 只待发转债")

    # 2. 筛选已注册
    registered = fetch_and_filter_registered(bonds)
    print(f"  已同意注册: {len(registered)} 只")

    if not registered:
        print("\n  当前无已注册转债")
        return

    # 3. 按注册日期排序
    registered.sort(key=lambda x: x[1], reverse=True)

    # 4. 判断需要检查哪些转债 + 日期
    #    - 今天注册的：检查 D+0
    #    - 过去N天注册的：如果到今天 <= 3 个交易日，检查今天是否为 D+N 窗口
    alerts = []  # {bond_info, anchor, check_result, is_alert}

    registered_today = []
    registered_pending = []  # 注册了但仍在 D0-D3 窗口的

    for sc, anchor, bond_info in registered:
        bond_name = (bond_info.get('bond_name') or bond_info.get('stock_name', '?'))[:12]

        # 计算注册日距今天数（交易日）
        prices = cache.get_kline_as_dict(sc, days=1500)
        if not prices:
            continue

        sd = sorted(prices.keys())
        anchor_idx = find_idx(sd, anchor)
        today_idx = find_idx(sd, today_str)

        # 确保 today_idx 是实际今天或之前最近的交易日
        if today_str not in prices:
            # 今天还没收盘或没数据，用最后一条
            today_idx = len(sd) - 1
            if sd[today_idx] > today_str:
                today_idx = today_idx - 1
                if today_idx < 0:
                    continue

        day_offset = today_idx - anchor_idx

        # 只关心 D-1 到 D+3 的转债
        if day_offset < -1 or day_offset > 3:
            continue

        # 检查当天的因子
        factors = check_bond_at_date(sc, anchor, today_str, cache)
        if factors is None:
            continue

        # 判断是否在提醒窗口
        in_alert_window = (0 <= day_offset <= 3)

        triggered = factors.get('triggered', [])

        if day_offset == 0:
            # 今天刚注册
            status_tag = "[D+0 注册当天]"
            if triggered:
                alert_level = "!!"
            else:
                alert_level = "  "
            registered_today.append({
                'sc': sc, 'anchor': anchor, 'bond_name': bond_name,
                'bond_info': bond_info, 'factors': factors,
                'triggered': triggered, 'day_offset': day_offset,
                'status_tag': status_tag, 'alert_level': alert_level,
                'in_alert_window': in_alert_window,
            })
        elif day_offset <= 3:
            # 过去N天注册，仍在提醒窗口
            status_tag = f"[D+{day_offset} 提醒窗口]"
            if triggered:
                alert_level = "!!"
            else:
                alert_level = "  "
            registered_pending.append({
                'sc': sc, 'anchor': anchor, 'bond_name': bond_name,
                'bond_info': bond_info, 'factors': factors,
                'triggered': triggered, 'day_offset': day_offset,
                'status_tag': status_tag, 'alert_level': alert_level,
                'in_alert_window': in_alert_window,
            })
        # else: day_offset < 0，注册日还没到（未来），忽略

    # ========== 输出 ==========

    # --- 今日注册 ---
    print("\n" + "─" * 90)
    print(f"今日注册 (D+0): {len(registered_today)} 只")
    print("─" * 90)

    if registered_today:
        for item in registered_today:
            f = item['factors']
            t = item['triggered']
            tag = item['status_tag']
            name = item['bond_name']
            sc = item['sc']
            anchor = item['anchor']

            if t:
                tags_str = '/'.join([f"S{i+1}" for i in t])
                buy = f.get('buy_price')
                sell = f.get('sell_price')
                proj = f.get('projected_ret', 0)
                buy_str = f"{buy:.2f}" if buy and buy > 0 else "N/A"
                sell_str = f"{sell:.2f}" if sell and sell > 0 else "N/A"
                proj_str = f"{proj:+.1f}%" if buy and buy > 0 and sell and sell > 0 else "N/A"

                print(f"\n  {item['alert_level']} {name} ({sc}) {tag}")
                print(f"      注册日: {anchor} | 因子: pre3={f['pre3']:+.1f}% mom10={f['mom10']:+.1f}% rc={f['rc']:+.1f}% pre7={f['pre7']:+.1f}%")
                print(f"      >>> 触发: {tags_str}")
                print(f"      D+{offset+1}开盘买入价: {buy_str} → D+{offset+8}收盘目标价: {sell_str}  预期收益: {proj_str}")
            else:
                if show_all:
                    print(f"\n  {item['alert_level']} {name} ({sc}) {tag}")
                    print(f"      注册日: {anchor} | 因子: pre3={f['pre3']:+.1f}% mom10={f['mom10']:+.1f}% rc={f['rc']:+.1f}% pre7={f['pre7']:+.1f}%")
                    print(f"      无策略触发")

    # --- 提醒窗口内（D+1 ~ D+3）---
    if registered_pending:
        print("\n" + "─" * 90)
        print(f"提醒窗口内 (D+1~D+3): {len(registered_pending)} 只")
        print("─" * 90)

        for item in registered_pending:
            f = item['factors']
            t = item['triggered']
            tag = item['status_tag']
            name = item['bond_name']
            sc = item['sc']
            anchor = item['anchor']
            offset = item['day_offset']

            if t:
                tags_str = '/'.join([f"S{i+1}" for i in t])
                buy = f.get('buy_price')
                sell = f.get('sell_price')
                proj = f.get('projected_ret', 0)
                buy_str = f"{buy:.2f}" if buy and buy > 0 else "N/A"
                sell_str = f"{sell:.2f}" if sell and sell > 0 else "N/A"
                proj_str = f"{proj:+.1f}%" if buy and buy > 0 and sell and sell > 0 else "N/A"

                # S1/S2 的 D0-D3 窗口特别说明
                s1s2_active = any(ti in [0, 1] for ti in t)
                window_note = ""
                if s1s2_active:
                    remaining = 3 - offset
                    if remaining > 0:
                        window_note = f" (S1/S2提醒窗口，剩余{remaining}天)"
                    else:
                        window_note = " (S1/S2提醒窗口，今日最后1天!)"

                print(f"\n  {item['alert_level']} {name} ({sc}) {tag}{window_note}")
                print(f"      注册日: {anchor} | D+{offset} | 因子: pre3={f['pre3']:+.1f}% mom10={f['mom10']:+.1f}% rc={f['rc']:+.1f}% pre7={f['pre7']:+.1f}%")
                print(f"      >>> 触发: {tags_str}")
                print(f"      D+{offset+1}开盘买入价: {buy_str} → D+{offset+8}收盘目标价: {sell_str}  预期收益: {proj_str}")
            else:
                if show_all:
                    print(f"\n  {item['alert_level']} {name} ({sc}) {tag}")
                    print(f"      注册日: {anchor} | D+{offset} | 因子: pre3={f['pre3']:+.1f}% mom10={f['mom10']:+.1f}% rc={f['rc']:+.1f}% pre7={f['pre7']:+.1f}%")
                    print(f"      当前无策略触发")

    # --- 注册但超出窗口 ---
    out_of_window = [
        (sc, anchor, bond_info)
        for sc, anchor, bond_info in registered
        if prices and sd
    ]
    # 只统计真正超出的
    out_count = 0
    for sc, anchor, bond_info in registered:
        p = cache.get_kline_as_dict(sc, days=1500)
        if not p:
            continue
        s = sorted(p.keys())
        ai = find_idx(s, anchor)
        ti = find_idx(s, today_str)
        if today_str not in p:
            ti = len(s) - 1
            if s[ti] > today_str:
                ti -= 1
        if ti - ai > 3:
            out_count += 1

    if out_count > 0 and show_all:
        print(f"\n  已超出提醒窗口: {out_count} 只")

    # --- 组合模式 ---
    if enable_combine:
        print("\n" + "=" * 90)
        print("策略组合")
        print("=" * 90)

        # 收集所有在 D0-D3 窗口的
        window_bonds = registered_today + registered_pending
        if not window_bonds:
            print("  当前无窗口内转债，跳过组合分析")
        else:
            for cname, cfn in COMBO_CONDITIONS:
                triggered_combo = [
                    item for item in window_bonds
                    if cfn({
                        '_s1': 0 in item['triggered'],
                        '_s2': 1 in item['triggered'],
                        '_s3': 2 in item['triggered'],
                        '_s4': 3 in item['triggered'],
                    })
                ]
                if triggered_combo:
                    print(f"\n  {cname}: {len(triggered_combo)} 只")
                    for item in triggered_combo:
                        f = item['factors']
                        t = item['triggered']
                        tags_str = '/'.join([f"S{i+1}" for i in t])
                        offset = item['day_offset']
                        proj = f.get('projected_ret', 0)
                        buy = f.get('buy_price')
                        buy_str = f"{buy:.2f}" if buy and buy > 0 else "N/A"
                        proj_str = f"{proj:+.1f}%" if buy and buy > 0 else "N/A"
                        print(f"    {item['bond_name']} ({item['sc']}) D+{offset} [{tags_str}] "
                              f"买入:{buy_str} 预期:{proj_str}")

    # --- 汇总 ---
    print("\n" + "=" * 90)
    total_alerts = sum(1 for item in registered_today + registered_pending if item['triggered'])
    print(f"汇总: 已注册 {len(registered)} 只 | "
          f"窗口内 {len(registered_today) + len(registered_pending)} 只 | "
          f"有信号 {total_alerts} 只")
    print("=" * 90)

    # 操作建议
    active_alerts = [item for item in (registered_today + registered_pending) if item['triggered']]
    if active_alerts:
        print("\n操作建议:")
        for item in active_alerts:
            f = item['factors']
            t = item['triggered']
            offset = item['day_offset']
            tags_str = '/'.join([f"S{i+1}" for i in t])

            # S1/S2 特殊说明
            buy_p = f.get('buy_price')
            buy_p_str = f"{buy_p:.2f}" if buy_p and buy_p > 0 else "N/A"
            if any(ti in [0, 1] for ti in t):
                if offset <= 3:
                    remaining = 3 - offset
                    print(f"  ★ {item['bond_name']} ({item['sc']}): "
                          f"触发{tags_str}，D0-D3 买入窗口 (剩余{remaining}天)，"
                          f"D+{offset+1}开盘价 {buy_p_str} 可关注")
            else:
                print(f"  ★ {item['bond_name']} ({item['sc']}): "
                      f"触发{tags_str}，D+{offset+1}开盘价 {buy_p_str} 可关注")


def main():
    show_all = False
    enable_combine = False
    lookback_days = 0

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--all-bonds':
            show_all = True
            i += 1
        elif args[i] == '--combine':
            enable_combine = True
            i += 1
        elif args[i] == '--lookback' and i + 1 < len(args):
            lookback_days = int(args[i + 1])
            i += 2
        else:
            i += 1

    cache = BacktestCache()
    jisilu = JisiluAPI()

    monitor(cache, jisilu, show_all=show_all, enable_combine=enable_combine,
            lookback_days=lookback_days)


if __name__ == '__main__':
    main()
