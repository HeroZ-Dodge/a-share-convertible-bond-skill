#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册后策略回测 — 基于数据驱动的策略定义

策略A：注册日入场 + 条件确认
  买入：注册日(D+0)
  条件：D+1必须涨（涨幅>0），否则放弃
  卖出：D+9
  持有：8~9天

策略B：注册日入场 + 无筛选
  买入：注册日(D+0)
  卖出：D+9
  持有：9天

策略C：延后入场 + 条件确认
  买入：D+3
  条件：D+1涨 且 注册前7天涨幅<=2%
  卖出：D+11
  持有：8天

策略D：激进短线
  买入：注册日(D+0)
  条件：D+1涨 且 pre7<=2%
  卖出：D+7
  持有：7天
"""
import sys
import os
import re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.backtest_cache import BacktestCache


def parse_anchor_date(bond: dict) -> str:
    pf = bond.get('progress_full', '')
    if not pf:
        return ''
    pf = pf.replace('<br>', '\n')
    for line in pf.split('\n'):
        if '同意注册' in line:
            m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
            if m:
                return m.group(1)
    return ''


def find_reg_idx(sorted_dates, target):
    for i, d in enumerate(sorted_dates):
        if d >= target:
            return i
    return len(sorted_dates) - 1


def run_backtest(cache, valid, strategy_name, buy_off, sell_off, filters=None):
    """回测单个策略

    Args:
        valid: 有效样本列表
        buy_off: 买入偏移(D+X)
        sell_off: 卖出偏移(D+X)
        filters: [(name, lambda)] 筛选条件列表
    """
    today = datetime.now().strftime('%Y-%m-%d')
    hold = sell_off - buy_off

    if filters is None:
        filters = [('无筛选', lambda v: True)]

    print(f"\n{'=' * 90}")
    print(f"策略: {strategy_name}")
    print(f"买入: D+{buy_off} | 卖出: D+{sell_off} | 持有: {hold}天")
    print(f"{'=' * 90}")

    all_pcts = []
    for fname, ffunc in filters:
        subset = [v for v in valid if ffunc(v)]
        pcts = []
        details = []

        for v in subset:
            b_ret = v['post_returns'].get(buy_off)
            s_ret = v['post_returns'].get(sell_off)
            if b_ret is None and buy_off == 0:
                b_ret = 0
            if b_ret is None or s_ret is None:
                continue

            entry_price = v['reg_price'] * (1 + b_ret / 100)
            if entry_price <= 0:
                continue
            exit_price = v['reg_price'] * (1 + s_ret / 100)
            pct = ((exit_price - entry_price) / entry_price) * 100
            pcts.append(pct)
            details.append({
                'code': v['code'],
                'name': v['name'],
                'reg_date': v['reg_date'],
                'reg_price': v['reg_price'],
                'entry_price': round(entry_price, 2),
                'exit_price': round(exit_price, 2),
                'pct': round(pct, 2),
            })

        all_pcts.append((fname, pcts, details, subset))

        if not pcts:
            print(f"\n  {fname}: 无样本")
            continue

        s = sorted(pcts)
        n = len(s)
        avg = sum(s) / n
        med = s[n // 2]
        win_n = sum(1 for x in s if x > 0)
        win_rate = win_n / n * 100
        std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
        sharpe = avg / std if std > 0 else 0
        best = max(s)
        worst = min(s)

        # 去极均值（trim 10%）
        trim_n = max(1, n // 10)
        trimmed = s[trim_n:n - trim_n] if n > 20 else s
        trimmed_avg = sum(trimmed) / len(trimmed)

        # 盈亏比
        wins = [x for x in s if x > 0]
        losses = [x for x in s if x < 0]
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0
        pl_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')

        # 最大连续亏损（模拟）
        # 年化效率 = avg_return / hold_days * 245
        annual_eff = (avg / hold) * 245 if hold > 0 else 0

        print(f"\n  [{fname}] 样本: {n}只")
        print(f"    平均收益: {avg:>+6.2f}%    中位数: {med:>+6.2f}%    去极均值: {trimmed_avg:>+6.2f}%")
        print(f"    胜率:     {win_rate:>5.1f}%  ({win_n}/{n})  "
              f"盈利均: +{avg_win:.2f}%  亏损均: -{avg_loss:.2f}%")
        print(f"    标准差:   {std:>6.2f}%    夏普比率: {sharpe:>+5.2f}    盈亏比: {pl_ratio:.2f}")
        print(f"    最佳:     +{best:.2f}%    最差: {worst:.2f}%")
        print(f"    年化效率: {annual_eff:>+6.2f}%")

        # 每只股票明细
        details_sorted = sorted(details, key=lambda x: x['pct'], reverse=True)
        print(f"\n    逐只收益 (Top 10 / Bottom 5):")
        print(f"    {'股票':>10} {'注册日':>12} {'锚定价':>8} {'买入价':>8} {'卖出价':>8} {'收益':>7}")
        print("    " + "-" * 65)
        for d in details_sorted[:10]:
            print(f"    {d['name']:>10} {d['reg_date']:>12} {d['reg_price']:>8.2f} "
                  f"{d['entry_price']:>8.2f} {d['exit_price']:>8.2f} {d['pct']:>+6.1f}%  ←Top")
        if n > 15:
            print("    ...")
        for d in details_sorted[-5:]:
            print(f"    {d['name']:>10} {d['reg_date']:>12} {d['reg_price']:>8.2f} "
                  f"{d['entry_price']:>8.2f} {d['exit_price']:>8.2f} {d['pct']:>+6.1f}%  ←Bot")

    return all_pcts


def main():
    cache = BacktestCache()
    today = datetime.now().strftime('%Y-%m-%d')

    # ============================================================
    # 数据准备
    # ============================================================
    all_bonds = cache.get_jisilu_bonds(phase='注册', status_cd='OK', limit=0)
    print(f"数据库: {len(all_bonds)} 只已上市+有注册信息转债")

    valid = []
    for b in all_bonds:
        sc = b.get('stock_code')
        if not sc:
            continue
        reg_date = parse_anchor_date(b)
        if not reg_date or reg_date > today:
            continue

        prices = cache.get_kline_as_dict(sc, days=600)
        if not prices or len(prices) < 100:
            continue

        sd = sorted(prices.keys())
        reg_idx = find_reg_idx(sd, reg_date)
        if reg_idx is None or reg_idx < 0:
            continue

        post_days = len(sd) - 1 - reg_idx
        if post_days < 12:
            continue

        reg_price = prices[sd[reg_idx]]['close']
        if reg_price <= 0:
            continue

        # 注册日后收益
        post_returns = {}
        for off in range(1, 31):
            idx = reg_idx + off
            if idx >= len(sd) or sd[idx] > today:
                continue
            p = prices[sd[idx]]['close']
            ret = ((p - reg_price) / reg_price) * 100
            post_returns[off] = round(ret, 2)

        # 注册前收益
        pre7_ret = 0
        pre7_idx = reg_idx - 7
        if pre7_idx >= 0:
            pre7_price = prices[sd[pre7_idx]]['close']
            if pre7_price > 0:
                pre7_ret = ((reg_price - pre7_price) / pre7_price) * 100

        # 注册日涨跌
        reg_day_chg = 0
        if reg_idx > 0:
            prev = prices[sd[reg_idx - 1]]['close']
            if prev > 0:
                reg_day_chg = ((reg_price - prev) / prev) * 100

        valid.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'reg_date': reg_date,
            'reg_price': round(reg_price, 2),
            'reg_idx': reg_idx,
            'post_days': post_days,
            'post_returns': post_returns,
            'pre7_ret': round(pre7_ret, 2),
            'reg_day_chg': round(reg_day_chg, 2),
            'prices': prices,
            'sorted_dates': sd,
        })

    print(f"有效样本: {len(valid)} 只\n")

    # ============================================================
    # 策略定义
    # ============================================================

    filters_common = [
        ('无筛选', lambda v: True),
        ('D+1涨', lambda v: v['post_returns'].get(1, 0) > 0),
        ('pre7<=2%', lambda v: v['pre7_ret'] <= 2),
        ('D+1涨+pre7<=2%', lambda v: v['post_returns'].get(1, 0) > 0 and v['pre7_ret'] <= 2),
        ('D+1涨+pre7<=2%+rc>0', lambda v: v['post_returns'].get(1, 0) > 0 and v['pre7_ret'] <= 2 and v['reg_day_chg'] > 0),
    ]

    # ============================================================
    # 策略A: D+0→D+9 (注册日买, D+9卖) — 主策略
    # ============================================================
    run_backtest(cache, valid, 'A: D+0→D+9 (注册日买 D+9卖)', 0, 9, filters_common)

    # ============================================================
    # 策略B: D+0→D+7 (注册日买, D+7卖) — 短线
    # ============================================================
    run_backtest(cache, valid, 'B: D+0→D+7 (注册日买 D+7卖)', 0, 7, filters_common)

    # ============================================================
    # 策略C: D+0→D+12 (注册日买, D+12卖) — 长持
    # ============================================================
    run_backtest(cache, valid, 'C: D+0→D+12 (注册日买 D+12卖)', 0, 12, filters_common)

    # ============================================================
    # 策略D: D+1→D+9 (D+1买, D+9卖) — 延迟入场
    # ============================================================
    run_backtest(cache, valid, 'D: D+1→D+9 (D+1买 D+9卖)', 1, 9, filters_common)

    # ============================================================
    # 策略E: D+3→D+11 (D+3买, D+11卖) — 确认入场
    # ============================================================
    run_backtest(cache, valid, 'E: D+3→D+11 (D+3买 D+11卖)', 3, 11, filters_common)

    # ============================================================
    # 策略F: D+1→D+8 (D+1买, D+8卖) — 超短
    # ============================================================
    run_backtest(cache, valid, 'F: D+1→D+8 (D+1买 D+8卖)', 1, 8, filters_common)

    # ============================================================
    # 汇总对比表
    # ============================================================
    print(f"\n{'=' * 100}")
    print("全策略对比 (最佳筛选条件)")
    print(f"{'=' * 100}")

    strategies = [
        ('A: D+0→D+9', 0, 9),
        ('B: D+0→D+7', 0, 7),
        ('C: D+0→D+12', 0, 12),
        ('D: D+1→D+9', 1, 9),
        ('E: D+3→D+11', 3, 11),
        ('F: D+1→D+8', 1, 8),
    ]

    filter_names = ['无筛选', 'D+1涨', 'pre7<=2%', 'D+1涨+pre7<=2%', 'D+1涨+pre7<=2%+rc>0']

    print(f"\n  {'策略':<15}", end='')
    for fn in filter_names:
        print(f" {fn:>20}", end='')
    print()

    for sname, boff, soff in strategies:
        hold = soff - boff
        print(f"  {sname:<15}", end='')
        for fn in filter_names:
            pcts = []
            for v in valid:
                # 检查筛选
                if fn == '无筛选':
                    pass
                elif fn == 'D+1涨':
                    if v['post_returns'].get(1, 0) <= 0:
                        continue
                elif fn == 'pre7<=2%':
                    if v['pre7_ret'] > 2:
                        continue
                elif fn == 'D+1涨+pre7<=2%':
                    if v['post_returns'].get(1, 0) <= 0 or v['pre7_ret'] > 2:
                        continue
                elif fn == 'D+1涨+pre7<=2%+rc>0':
                    if v['post_returns'].get(1, 0) <= 0 or v['pre7_ret'] > 2 or v['reg_day_chg'] <= 0:
                        continue

                b_ret = v['post_returns'].get(boff)
                s_ret = v['post_returns'].get(soff)
                if b_ret is None or s_ret is None:
                    # D+0 买入直接用锚定价
                    if boff == 0:
                        entry = v['reg_price']
                    else:
                        continue
                else:
                    entry = v['reg_price'] * (1 + b_ret / 100)
                if entry <= 0:
                    continue
                exit_price = v['reg_price'] * (1 + s_ret / 100)
                pct = ((exit_price - entry) / entry) * 100
                pcts.append(pct)

            if pcts:
                s = sorted(pcts)
                n = len(s)
                avg = sum(s) / n
                win_n = sum(1 for x in s if x > 0)
                win_rate = win_n / n * 100
                std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
                sharpe = avg / std if std > 0 else 0
                # 显示 平均/胜率/夏普
                print(f" {avg:>+4.1f}%/{win_rate:.0f}%/{sharpe:+.2f}", end='')
            else:
                print(f" {'N/A':>20}", end='')
        print()


if __name__ == '__main__':
    main()
