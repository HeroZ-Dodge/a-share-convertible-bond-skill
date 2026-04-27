#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终策略验证 — 基于近100只注册转债的因子挖掘结果
"""
import sys, os, re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.backtest_cache import BacktestCache


def find_reg_idx(sd, target):
    for i, d in enumerate(sd):
        if d >= target: return i
    return len(sd) - 1


def main():
    cache = BacktestCache()
    today_str = datetime.now().strftime('%Y-%m-%d')

    # ============================================================
    # 数据准备
    # ============================================================
    all_bonds = cache.get_jisilu_bonds(phase='注册')

    pool = []
    for b in all_bonds:
        sc = b.get('stock_code')
        if not sc: continue
        pf = b.get('progress_full', '')
        if not pf: continue
        reg = ''
        for line in pf.replace('<br>', '\n').split('\n'):
            if '同意注册' in line:
                m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                if m: reg = m.group(1); break
        if not reg or reg > today_str: continue
        prices = cache.get_kline_as_dict(sc, days=600)
        if not prices or len(prices) < 50: continue
        sd = sorted(prices.keys())
        ri = find_reg_idx(sd, reg)
        if ri is None: continue
        reg_price = prices[sd[ri]]['close']
        if reg_price <= 0: continue

        # Post returns
        post = {}
        for off in range(1, 16):
            idx = ri + off
            if idx >= len(sd) or sd[idx] > today_str: continue
            post[off] = ((prices[sd[idx]]['close'] - reg_price) / reg_price) * 100

        # Pre returns
        pre3_ret = 0
        if ri - 3 >= 0:
            p3 = prices[sd[ri - 3]]['close']
            if p3 > 0: pre3_ret = ((reg_price - p3) / p3) * 100

        pre7_ret = 0
        if ri - 7 >= 0:
            p7 = prices[sd[ri - 7]]['close']
            if p7 > 0: pre7_ret = ((reg_price - p7) / p7) * 100

        # Registration day change
        reg_day_chg = 0
        if ri > 0:
            prev = prices[sd[ri - 1]]['close']
            if prev > 0: reg_day_chg = ((reg_price - prev) / prev) * 100

        # 10-day momentum
        mom10 = 0
        if ri - 10 >= 0:
            p10 = prices[sd[ri - 10]]['close']
            if p10 > 0: mom10 = ((reg_price - p10) / p10) * 100

        pool.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'reg_date': reg,
            'reg_price': reg_price,
            'reg_day_chg': reg_day_chg,
            'pre3_ret': pre3_ret,
            'pre7_ret': pre7_ret,
            'mom10': mom10,
            'post': post,
        })

    pool.sort(key=lambda x: x['reg_date'], reverse=True)
    recent100 = pool[:100]
    all_valid = pool[:352] if len(pool) >= 352 else pool

    print("=" * 90)
    print("近100只注册转债 策略验证")
    print("注册日期范围: {} ~ {}".format(recent100[-1]['reg_date'], recent100[0]['reg_date']))
    print("=" * 90)

    # ============================================================
    # 策略定义
    # ============================================================
    strategies = [
        ('基准(无筛选)', lambda v: True),

        # 单因子
        ('pre3<0%', lambda v: v['pre3_ret'] < 0),
        ('pre7<0%', lambda v: v['pre7_ret'] < 0),
        ('pre3<2%', lambda v: v['pre3_ret'] < 2),
        ('pre7<2%', lambda v: v['pre7_ret'] < 2),
        ('rc<-2%', lambda v: v['reg_day_chg'] < -2),
        ('rc>2%', lambda v: v['reg_day_chg'] > 2),

        # 双因子
        ('pre3<0%+rc>0%', lambda v: v['pre3_ret'] < 0 and v['reg_day_chg'] > 0),
        ('pre7<0%+rc>0%', lambda v: v['pre7_ret'] < 0 and v['reg_day_chg'] > 0),
        ('pre3<2%+mom10<5%', lambda v: v['pre3_ret'] < 2 and v['mom10'] < 5),
        ('pre7<2%+mom10<5%', lambda v: v['pre7_ret'] < 2 and v['mom10'] < 5),

        # 三因子
        ('pre3<2%+mom10<5%+rc>0%', lambda v: v['pre3_ret'] < 2 and v['mom10'] < 5 and v['reg_day_chg'] > 0),
        ('pre3<0%+mom10<5%+rc>0%', lambda v: v['pre3_ret'] < 0 and v['mom10'] < 5 and v['reg_day_chg'] > 0),
        ('pre7<0%+mom10<5%+rc>0%', lambda v: v['pre7_ret'] < 0 and v['mom10'] < 5 and v['reg_day_chg'] > 0),
        ('pre7<0%+rc>2%', lambda v: v['pre7_ret'] < 0 and v['reg_day_chg'] > 2),
        ('pre3<2%+rc<-2%', lambda v: v['pre3_ret'] < 2 and v['reg_day_chg'] < -2),
        ('pre3<0%+rc<-2%', lambda v: v['pre3_ret'] < 0 and v['reg_day_chg'] < -2),
    ]

    windows = [(0, 7), (0, 9), (0, 10), (0, 12), (1, 8), (1, 9), (1, 10)]

    # ============================================================
    # 逐窗口评估
    # ============================================================
    for boff, soff in windows:
        hold = soff - boff
        print("\n" + "=" * 90)
        print("D+{} → D+{} (持有{}天) — 近100只".format(boff, soff, hold))
        print("=" * 90)

        results = []
        for sname, sfn in strategies:
            subset = [v for v in recent100 if sfn(v)]
            if len(subset) < 5:
                continue

            pcts = []
            for v in subset:
                if boff == 0:
                    entry = v['reg_price']
                else:
                    br = v['post'].get(boff)
                    if br is None: continue
                    entry = v['reg_price'] * (1 + br / 100)
                sr = v['post'].get(soff)
                if sr is None: continue
                exit_p = v['reg_price'] * (1 + sr / 100)
                if entry <= 0: continue
                pcts.append(((exit_p - entry) / entry) * 100)

            if len(pcts) < 5:
                continue

            s = sorted(pcts)
            n = len(s)
            avg = sum(s) / n
            med = s[n // 2]
            win_n = sum(1 for x in s if x > 0)
            win_rate = win_n / n * 100
            std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
            sharpe = avg / std if std > 0 else 0

            # Trimmed mean (remove top/bottom 10%)
            trim = max(1, n // 10)
            trimmed = s[trim:n - trim] if n > 20 else s
            trimmed_avg = sum(trimmed) / len(trimmed)

            # Annual efficiency
            annual = (avg / hold) * 245 if hold > 0 else 0

            results.append({
                'name': sname, 'avg': avg, 'med': med, 'win': win_rate,
                'n': n, 'std': std, 'sharpe': sharpe, 'trimmed': trimmed_avg,
                'annual': annual, 'pcts': pcts,
            })

        # Sort by Sharpe
        results.sort(key=lambda x: (x['sharpe'], x['avg']), reverse=True)

        print("  {:<38} {:>5} {:>6} {:>6} {:>6} {:>6} {:>6} {:>6}".format(
            '策略', '样本', '平均', '中位', '胜率', '标准差', '夏普', '年化'))
        print("  " + "-" * 100)

        for r in results:
            star = '★' if r['sharpe'] > 0.4 and r['n'] >= 15 else ' '
            print("  {}{:<36} {:>4} {:>+5.2f}% {:>+5.2f}% {:>5.1f}% {:>5.2f}% {:>+5.2f} {:>+5.1f}%".format(
                star, r['name'], r['n'], r['avg'], r['med'], r['win'], r['std'], r['sharpe'], r['annual']))

    # ============================================================
    # 全量数据验证（352只）
    # ============================================================
    print("\n" + "=" * 90)
    print("全量验证 (352只) — D+0→D+9")
    print("=" * 90)

    best_rules = [
        ('基准(无筛选)', lambda v: True),
        ('pre3<0%', lambda v: v['pre3_ret'] < 0),
        ('pre7<0%', lambda v: v['pre7_ret'] < 0),
        ('pre3<2%+mom10<5%', lambda v: v['pre3_ret'] < 2 and v['mom10'] < 5),
        ('pre3<2%+mom10<5%+rc>0%', lambda v: v['pre3_ret'] < 2 and v['mom10'] < 5 and v['reg_day_chg'] > 0),
        ('pre3<0%+mom10<5%+rc>0%', lambda v: v['pre3_ret'] < 0 and v['mom10'] < 5 and v['reg_day_chg'] > 0),
        ('pre7<0%+mom10<5%+rc>0%', lambda v: v['pre7_ret'] < 0 and v['mom10'] < 5 and v['reg_day_chg'] > 0),
        ('pre7<0%+rc>2%', lambda v: v['pre7_ret'] < 0 and v['reg_day_chg'] > 2),
        ('pre3<2%+rc<-2%', lambda v: v['pre3_ret'] < 2 and v['reg_day_chg'] < -2),
    ]

    for sname, sfn in best_rules:
        subset = [v for v in all_valid if sfn(v)]
        if len(subset) < 10: continue

        pcts = []
        for v in subset:
            sr = v['post'].get(9)
            if sr is None: continue
            pcts.append(sr)  # D+0 buy, return already relative to reg price

        if len(pcts) < 10: continue
        s = sorted(pcts)
        n = len(s)
        avg = sum(s) / n
        win_n = sum(1 for x in s if x > 0)
        win_rate = win_n / n * 100
        std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
        sharpe = avg / std if std > 0 else 0

        print("  {:<38} {:>4} {:>+5.2f}% {:>5.1f}% {:>5.2f} 样本={}".format(
            sname, n, avg, win_rate, sharpe, n))

    # ============================================================
    # 策略推荐
    # ============================================================
    print("\n" + "=" * 90)
    print("策略推荐")
    print("=" * 90)

    # Find the best balanced strategy (n>=15, sharpe>0.3, avg>2%)
    # on the D+0→D+9 window for recent100
    print("\n  在 D+0→D+9 (近100只) 中筛选条件:")
    print("  - 样本 >= 15")
    print("  - 夏普 >= 0.3")
    print("  - 平均收益 > 基准(+2.20%)")
    print("  - 胜率 > 基准(62.2%)")
    print()

    # Re-eval D+0→D+9
    for boff, soff in [(0, 9)]:
        hold = soff - boff
        candidates = []
        for sname, sfn in strategies:
            subset = [v for v in recent100 if sfn(v)]
            if len(subset) < 15: continue

            pcts = []
            for v in subset:
                if boff == 0:
                    entry = v['reg_price']
                else:
                    br = v['post'].get(boff)
                    if br is None: continue
                    entry = v['reg_price'] * (1 + br / 100)
                sr = v['post'].get(soff)
                if sr is None: continue
                exit_p = v['reg_price'] * (1 + sr / 100)
                if entry <= 0: continue
                pcts.append(((exit_p - entry) / entry) * 100)

            if len(pcts) < 15: continue
            s = sorted(pcts)
            n = len(s)
            avg = sum(s) / n
            win_rate = sum(1 for x in s if x > 0) / n * 100
            std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
            sharpe = avg / std if std > 0 else 0

            candidates.append({
                'name': sname, 'avg': avg, 'win': win_rate, 'n': n,
                'std': std, 'sharpe': sharpe,
                'meets': avg > 2.2 and win_rate > 62.2 and sharpe >= 0.3,
            })

        candidates.sort(key=lambda x: x['sharpe'], reverse=True)
        for c in candidates:
            tag = ' ✓' if c['meets'] else ''
            print("  {name:<40} avg={avg:+5.2f}%  win={win:.1f}%  std={std:.2f}%  sharpe={sharpe:+.2f}  n={n}{tag}".format(
                tag=tag, **c))

    print()
    print("  结论:")
    print("  - 近100只基准: D+0→D+9 平均+2.20%, 胜率62.2%, 夏普0.22")
    print("  - 最佳策略应同时满足: 样本>=15, 夏普>=0.3, 收益>2.2%, 胜率>62%")


if __name__ == '__main__':
    main()
