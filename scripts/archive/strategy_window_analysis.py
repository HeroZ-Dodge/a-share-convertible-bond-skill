#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略窗口分析 — 每个策略从注册日到各卖出的逐日收益
回答：注册日后的收益何时兑现？何时见顶？
"""
import sys, os, re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.backtest_cache import BacktestCache


def find_idx(sd, target):
    """找 <= target 的最后一个交易日（处理周末/节假日注册日）"""
    result = 0
    for i, d in enumerate(sd):
        if d <= target:
            result = i
        else:
            break
    return result


def main():
    cache = BacktestCache()
    today_str = datetime.now().strftime('%Y-%m-%d')

    # 定义策略
    strategies = {
        '基准(无筛选)': lambda v: True,
        '策略1: pre3≤2%+mom10<5%+rc>0%': lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0,
        '策略2: pre3≤2%+mom10<5%': lambda v: v['pre3'] <= 2 and v['mom10'] < 5,
        '策略3: rc<-2%': lambda v: v['rc'] < -2,
        '策略4: pre7<0%': lambda v: v['pre7'] < 0,
    }

    # 数据准备
    bonds = cache.get_jisilu_bonds(phase='注册', limit=0)
    pool = []
    for b in bonds:
        sc = b.get('stock_code')
        if not sc: continue
        pf = b.get('progress_full', '')
        if not pf: continue
        anchor = ''
        for line in pf.replace('<br>', '\n').split('\n'):
            if '同意注册' in line:
                m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                if m: anchor = m.group(1); break
        if not anchor or anchor > today_str: continue
        prices = cache.get_kline_as_dict(sc, days=1500)
        if not prices: continue
        sd = sorted(prices.keys())
        ri = find_idx(sd, anchor)
        reg_price = prices[sd[ri]]['close']
        if reg_price <= 0: continue

        # 计算各日偏移的收益
        post = {}
        for off in range(1, 16):
            idx = ri + off
            if idx >= len(sd) or sd[idx] > today_str: continue
            post[off] = ((prices[sd[idx]]['close'] - reg_price) / reg_price) * 100

        # 因子
        pre3 = 0
        if ri >= 3:
            p3 = prices[sd[ri-3]]['close']
            if p3 > 0: pre3 = ((reg_price - p3) / p3) * 100

        pre7 = 0
        if ri >= 7:
            p7 = prices[sd[ri-7]]['close']
            if p7 > 0: pre7 = ((reg_price - p7) / p7) * 100

        rc = 0
        if ri > 0:
            prev = prices[sd[ri-1]]['close']
            if prev > 0: rc = ((reg_price - prev) / prev) * 100

        mom10 = 0
        if ri >= 10:
            p10 = prices[sd[ri-10]]['close']
            if p10 > 0: mom10 = ((reg_price - p10) / p10) * 100

        pool.append({
            'code': sc, 'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor, 'reg_price': reg_price,
            'post': post, 'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    sample = pool[:100]

    # 逐日窗口分析
    print("=" * 100)
    print("注册日窗口分析 (limit=100)")
    print("展示每个策略在不同卖出日的平均收益 / 中位数 / 胜率 / 夏普")
    print("=" * 100)

    for sname, sfn in strategies.items():
        subset = [v for v in sample if sfn(v)]
        if len(subset) < 5:
            continue

        print(f"\n{sname} (样本 n={len(subset)})")
        print(f"  {'卖出日':>6} {'平均':>7} {'中位':>7} {'胜率':>6} {'夏普':>6} {'有效样本':>6}")
        print("  " + "-" * 50)

        for sell_off in range(1, 16):
            pcts = []
            for v in subset:
                r = v['post'].get(sell_off)
                if r is not None:
                    pcts.append(r)

            if len(pcts) < 5:
                continue

            s = sorted(pcts)
            n = len(s)
            avg = sum(s) / n
            med = s[n // 2]
            win = sum(1 for x in s if x > 0) / n * 100
            std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
            sharpe = avg / std if std > 0 else 0

            tag = ''
            if sname == '基准(无筛选)':
                tag = ' ←基准'
            else:
                beat = avg - 2.2  # 基准均值约2.2%
                if beat > 1.5:
                    tag = f' <<<强{beat:+.1f}%'
                elif beat < -1:
                    tag = f' <<<弱{beat:+.1f}%'

            print(f"  D+{sell_off:>2}: {avg:>+6.2f}% {med:>+6.2f}% {win:>5.1f}% {sharpe:>+5.2f} {n:>6}{tag}")

    # 额外分析：收益集中度 — 多少收益来自前N天
    print("\n\n" + "=" * 100)
    print("收益集中度分析")
    print("回答：策略收益是集中在前3天，还是逐步累积到D+9？")
    print("=" * 100)

    for sname, sfn in [('策略1', strategies['策略1: pre3≤2%+mom10<5%+rc>0%']),
                        ('策略2', strategies['策略2: pre3≤2%+mom10<5%']),
                        ('策略3', strategies['策略3: rc<-2%']),
                        ('策略4', strategies['策略4: pre7<0%'])]:
        subset = [v for v in sample if sfn(v)]
        if len(subset) < 5:
            continue

        print(f"\n{sname} (n={len(subset)})")
        print(f"  {'持有期':>8} {'平均收益':>8} {' vs D+9':>8} {'累积占比':>8}")
        print("  " + "-" * 45)

        d9_avg = None
        for sell_off in range(1, 16):
            pcts = []
            for v in subset:
                r = v['post'].get(sell_off)
                if r is not None:
                    pcts.append(r)
            if len(pcts) < 5:
                continue

            avg = sum(pcts) / len(pcts)
            if sell_off == 9:
                d9_avg = avg

            vs_d9 = avg - d9_avg if d9_avg else 0
            pct_of_d9 = (avg / d9_avg * 100) if d9_avg and avg != 0 else 0

            bar = '█' * max(1, round(abs(avg) / 6 * 20)) if avg > 0 else '░' * max(1, round(abs(avg) / 6 * 20))
            print(f"  D+0→D+{sell_off:<2} {avg:>+7.2f}% {vs_d9:>+7.2f}% {pct_of_d9:>6.0f}%  {bar}")

    # 最佳卖出时机建议
    print("\n\n" + "=" * 100)
    print("最佳卖出时机建议")
    print("=" * 100)

    for sname, sfn in [('策略1', strategies['策略1: pre3≤2%+mom10<5%+rc>0%']),
                        ('策略2', strategies['策略2: pre3≤2%+mom10<5%']),
                        ('策略3', strategies['策略3: rc<-2%']),
                        ('策略4', strategies['策略4: pre7<0%'])]:
        subset = [v for v in sample if sfn(v)]
        if len(subset) < 5:
            continue

        best_sharpe_off = 1
        best_sharpe = 0
        for sell_off in range(1, 16):
            pcts = []
            for v in subset:
                r = v['post'].get(sell_off)
                if r is not None:
                    pcts.append(r)
            if len(pcts) < 5:
                continue
            avg = sum(pcts) / len(pcts)
            std = (sum((x - avg) ** 2 for x in pcts) / len(pcts)) ** 0.5
            sh = avg / std if std > 0 else 0
            if sh > best_sharpe:
                best_sharpe = sh
                best_sharpe_off = sell_off

        best_avg_off = 1
        best_avg = 0
        for sell_off in range(1, 16):
            pcts = []
            for v in subset:
                r = v['post'].get(sell_off)
                if r is not None:
                    pcts.append(r)
            if len(pcts) < 5:
                continue
            avg = sum(pcts) / len(pcts)
            if avg > best_avg:
                best_avg = avg
                best_avg_off = sell_off

        print(f"  {sname}: 夏普最高在 D+{best_sharpe_off} ({best_sharpe:+.2f}), 平均收益最高在 D+{best_avg_off} ({best_avg:+.2f}%)")


if __name__ == '__main__':
    main()
