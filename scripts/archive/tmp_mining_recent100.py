#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
近100只注册转债选股因子挖掘
"""
import sys, os, re
from datetime import datetime
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.backtest_cache import BacktestCache


def find_reg_idx(sd, target):
    for i, d in enumerate(sd):
        if d >= target: return i
    return len(sd) - 1


def main():
    cache = BacktestCache()
    today = datetime.now().strftime('%Y-%m-%d')

    all_bonds = cache.get_jisilu_bonds(phase='注册')
    today_str = today

    # Parse all bonds
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

        # Post returns D+1 to D+15
        post = {}
        for off in range(1, 16):
            idx = ri + off
            if idx >= len(sd) or sd[idx] > today_str: continue
            p = prices[sd[idx]]['close']
            post[off] = ((p - reg_price) / reg_price) * 100

        # Pre returns
        pre = {}
        for off in range(1, 16):
            idx = ri - off
            if idx < 0: continue
            p = prices[sd[idx]]['close']
            pre[off] = ((p - reg_price) / reg_price) * 100

        # Registration day change
        reg_day_chg = 0
        if ri > 0:
            prev = prices[sd[ri - 1]]['close']
            if prev > 0: reg_day_chg = ((reg_price - prev) / prev) * 100

        # Pre-7 cumulative return (from D-7 to D+0)
        pre7_idx = ri - 7
        pre7_ret = 0
        if pre7_idx >= 0 and sd[pre7_idx] <= today_str:
            p7 = prices[sd[pre7_idx]]['close']
            if p7 > 0: pre7_ret = ((reg_price - p7) / p7) * 100

        # Pre-5 cumulative return
        pre5_ret = 0
        if ri - 5 >= 0:
            p5 = prices[sd[ri - 5]]['close']
            if p5 > 0: pre5_ret = ((reg_price - p5) / p5) * 100

        # Pre-3 cumulative return
        pre3_ret = 0
        if ri - 3 >= 0:
            p3 = prices[sd[ri - 3]]['close']
            if p3 > 0: pre3_ret = ((reg_price - p3) / p3) * 100

        # Volume analysis
        baseline_vol = []
        for idx in range(ri - 20, ri - 5):
            if 0 <= idx < len(sd):
                baseline_vol.append(prices[sd[idx]]['volume'])
        baseline_avg = sum(baseline_vol) / len(baseline_vol) if baseline_vol else 1

        # Vol ratio on registration day
        vol_ratio_reg = prices[sd[ri]]['volume'] / baseline_avg if baseline_avg > 0 else 1

        # Vol ratio on D-1
        vol_ratio_d1 = 0
        if ri > 0:
            vol_ratio_d1 = prices[sd[ri - 1]]['volume'] / baseline_avg if baseline_avg > 0 else 1

        # Vol ratio on D+1
        vol_ratio_dp1 = 0
        if ri + 1 < len(sd) and sd[ri + 1] <= today_str:
            vol_ratio_dp1 = prices[sd[ri + 1]]['volume'] / baseline_avg if baseline_avg > 0 else 1

        # Price momentum: 20-day return
        mom20 = 0
        if ri - 20 >= 0:
            p20 = prices[sd[ri - 20]]['close']
            if p20 > 0: mom20 = ((reg_price - p20) / p20) * 100

        # Price momentum: 10-day return
        mom10 = 0
        if ri - 10 >= 0:
            p10 = prices[sd[ri - 10]]['close']
            if p10 > 0: mom10 = ((reg_price - p10) / p10) * 100

        # Price trend: consecutive up days before registration
        cons_up = 0
        for off in range(1, 8):
            idx = ri - off
            if idx <= 0: break
            chg = 0
            if prices[sd[idx - 1]]['close'] > 0:
                chg = ((prices[sd[idx]]['close'] - prices[sd[idx - 1]]['close']) / prices[sd[idx - 1]]['close']) * 100
            if chg > 0:
                cons_up += 1
            else:
                break

        # Volatility: 20-day std of daily returns
        daily_rets = []
        for idx in range(ri - 20, ri):
            if 0 < idx < len(sd) and prices[sd[idx - 1]]['close'] > 0:
                r = ((prices[sd[idx]]['close'] - prices[sd[idx - 1]]['close']) / prices[sd[idx - 1]]['close']) * 100
                daily_rets.append(r)
        vol_20d = 0
        if len(daily_rets) > 2:
            avg_r = sum(daily_rets) / len(daily_rets)
            vol_20d = (sum((r - avg_r) ** 2 for r in daily_rets) / len(daily_rets)) ** 0.5

        pool.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'reg_date': reg,
            'reg_price': reg_price,
            'reg_day_chg': reg_day_chg,
            'pre7_ret': pre7_ret,
            'pre5_ret': pre5_ret,
            'pre3_ret': pre3_ret,
            'mom10': mom10,
            'mom20': mom20,
            'vol_ratio_reg': vol_ratio_reg,
            'vol_ratio_d1': vol_ratio_d1,
            'vol_ratio_dp1': vol_ratio_dp1,
            'cons_up': cons_up,
            'vol_20d': vol_20d,
            'post': post,
            'prices': prices,
            'sd': sd,
            'ri': ri,
        })

    # Sort by reg_date desc, take top 100
    pool.sort(key=lambda x: x['reg_date'], reverse=True)
    sample = pool[:100]
    print(f"样本: 最近100只 (注册日期 {sample[-1]['reg_date']} ~ {sample[0]['reg_date']})\n")

    # Baseline
    def calc_perf(subset, boff, soff):
        if not subset:
            return {'avg': 0, 'med': 0, 'win': 0, 'n': 0, 'std': 0, 'sharpe': 0}
        pcts = []
        for v in subset:
            br = v['pre7_ret']  # dummy, need actual
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
        if not pcts:
            return {'avg': 0, 'med': 0, 'win': 0, 'n': 0, 'std': 0, 'sharpe': 0}
        s = sorted(pcts)
        n = len(s)
        avg = sum(s) / n
        med = s[n // 2]
        win = sum(1 for x in s if x > 0) / n * 100
        std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
        return {'avg': avg, 'med': med, 'win': win, 'n': n, 'std': std,
                'sharpe': avg / std if std > 0 else 0, 'pcts': pcts}

    # ============================================================
    # 一、基础因子分组测试 (D+0买 → D+7/9/10/12卖)
    # ============================================================
    windows = [(0, 7), (0, 9), (0, 10), (0, 12), (1, 8), (1, 9), (1, 10)]

    print("=" * 90)
    print("一、全样本基准（近100只，无筛选）")
    print("=" * 90)
    for boff, soff in windows:
        p = calc_perf(sample, boff, soff)
        hold = soff - boff
        print("  D+{boff}→D+{soff} ({hold}天): 平均{avg:+6.2f}% 中位{med:+6.2f}% 胜率{win:.1f}% "
              "标准差{std:.2f}% 夏普{sharpe:+.2f} 样本{n}".format(
                  boff=boff, soff=soff, hold=hold, **p))

    # ============================================================
    # 二、注册前涨幅因子
    # ============================================================
    print("\n" + "=" * 90)
    print("二、注册前7天涨幅分组 (D+0→D+9)")
    print("=" * 90)
    bins = [
        ('暴跌(<-5%)', lambda v: v['pre7_ret'] < -5),
        ('跌(-5~-2%)', lambda v: -5 <= v['pre7_ret'] < -2),
        ('微跌(-2~0%)', lambda v: -2 <= v['pre7_ret'] < 0),
        ('微涨(0~2%)', lambda v: 0 <= v['pre7_ret'] < 2),
        ('涨(2~5%)', lambda v: 2 <= v['pre7_ret'] < 5),
        ('大涨(>5%)', lambda v: v['pre7_ret'] >= 5),
    ]
    for label, fn in bins:
        subset = [v for v in sample if fn(v)]
        if not subset:
            continue
        p = calc_perf(subset, 0, 9)
        print("  {label:>12}: {avg:+6.2f}% {med:+6.2f}% {win:.1f}% {std:.2f}% {sharpe:+.2f} n={n}".format(label=label, **p))

    # ============================================================
    # 三、注册前3天涨幅因子
    # ============================================================
    print("\n" + "=" * 90)
    print("三、注册前3天涨幅分组 (D+0→D+9)")
    print("=" * 90)
    bins3 = [
        ('暴跌(<-3%)', lambda v: v['pre3_ret'] < -3),
        ('跌(-3~0%)', lambda v: -3 <= v['pre3_ret'] < 0),
        ('微涨(0~2%)', lambda v: 0 <= v['pre3_ret'] < 2),
        ('涨(2~4%)', lambda v: 2 <= v['pre3_ret'] < 4),
        ('大涨(>4%)', lambda v: v['pre3_ret'] >= 4),
    ]
    for label, fn in bins3:
        subset = [v for v in sample if fn(v)]
        if not subset:
            continue
        p = calc_perf(subset, 0, 9)
        print("  {label:>12}: {avg:+6.2f}% {med:+6.2f}% {win:.1f}% {std:.2f}% {sharpe:+.2f} n={n}".format(label=label, **p))

    # ============================================================
    # 四、注册日涨跌因子
    # ============================================================
    print("\n" + "=" * 90)
    print("四、注册日涨跌分组 (D+0→D+9)")
    print("=" * 90)
    bins_rc = [
        ('大跌(<-2%)', lambda v: v['reg_day_chg'] < -2),
        ('跌(-2~0%)', lambda v: -2 <= v['reg_day_chg'] < 0),
        ('涨(0~2%)', lambda v: 0 <= v['reg_day_chg'] < 2),
        ('大涨(>2%)', lambda v: v['reg_day_chg'] >= 2),
    ]
    for label, fn in bins_rc:
        subset = [v for v in sample if fn(v)]
        if not subset:
            continue
        p = calc_perf(subset, 0, 9)
        print("  {label:>12}: {avg:+6.2f}% {med:+6.2f}% {win:.1f}% {std:.2f}% {sharpe:+.2f} n={n}".format(label=label, **p))

    # ============================================================
    # 五、动量因子（20日/10日涨幅）
    # ============================================================
    print("\n" + "=" * 90)
    print("五、动量因子 (D+0→D+9)")
    print("=" * 90)

    # 20日动量
    print("  20日动量分组:")
    mom20_bins = [
        ('弱势(<-10%)', lambda v: v['mom20'] < -10),
        ('跌(-10~0%)', lambda v: -10 <= v['mom20'] < 0),
        ('涨(0~10%)', lambda v: 0 <= v['mom20'] < 10),
        ('强势(>10%)', lambda v: v['mom20'] >= 10),
    ]
    for label, fn in mom20_bins:
        subset = [v for v in sample if fn(v)]
        if not subset: continue
        p = calc_perf(subset, 0, 9)
        print("    {label:>14}: {avg:+6.2f}% {med:+6.2f}% {win:.1f}% {std:.2f}% {sharpe:+.2f} n={n}".format(label=label, **p))

    # 10日动量
    print("  10日动量分组:")
    mom10_bins = [
        ('弱势(<-5%)', lambda v: v['mom10'] < -5),
        ('跌(-5~0%)', lambda v: -5 <= v['mom10'] < 0),
        ('涨(0~5%)', lambda v: 0 <= v['mom10'] < 5),
        ('强势(>5%)', lambda v: v['mom10'] >= 5),
    ]
    for label, fn in mom10_bins:
        subset = [v for v in sample if fn(v)]
        if not subset: continue
        p = calc_perf(subset, 0, 9)
        print("    {label:>14}: {avg:+6.2f}% {med:+6.2f}% {win:.1f}% {std:.2f}% {sharpe:+.2f} n={n}".format(label=label, **p))

    # ============================================================
    # 六、成交量因子
    # ============================================================
    print("\n" + "=" * 90)
    print("六、成交量因子 (D+0→D+9)")
    print("=" * 90)

    # Volume ratio on registration day
    vr_bins = [
        ('极度缩量(<0.5)', lambda v: v['vol_ratio_reg'] < 0.5),
        ('缩量(0.5~0.8)', lambda v: 0.5 <= v['vol_ratio_reg'] < 0.8),
        ('正常(0.8~1.2)', lambda v: 0.8 <= v['vol_ratio_reg'] < 1.2),
        ('放量(1.2~1.5)', lambda v: 1.2 <= v['vol_ratio_reg'] < 1.5),
        ('大幅放量(>1.5)', lambda v: v['vol_ratio_reg'] >= 1.5),
    ]
    print("  注册日量比:")
    for label, fn in vr_bins:
        subset = [v for v in sample if fn(v)]
        if not subset: continue
        p = calc_perf(subset, 0, 9)
        print("    {label:>14}: {avg:+6.2f}% {med:+6.2f}% {win:.1f}% {std:.2f}% {sharpe:+.2f} n={n}".format(label=label, **p))

    # Volume ratio D+1
    vr_bins_d1 = [
        ('极度缩量(<0.5)', lambda v: v['vol_ratio_dp1'] < 0.5),
        ('缩量(0.5~0.8)', lambda v: 0.5 <= v['vol_ratio_dp1'] < 0.8),
        ('正常(0.8~1.2)', lambda v: 0.8 <= v['vol_ratio_dp1'] < 1.2),
        ('放量(1.2~1.5)', lambda v: 1.2 <= v['vol_ratio_dp1'] < 1.5),
        ('大幅放量(>1.5)', lambda v: v['vol_ratio_dp1'] >= 1.5),
    ]
    print("  D+1量比:")
    for label, fn in vr_bins_d1:
        subset = [v for v in sample if fn(v)]
        if not subset: continue
        p = calc_perf(subset, 0, 9)
        print("    {label:>14}: {avg:+6.2f}% {med:+6.2f}% {win:.1f}% {std:.2f}% {sharpe:+.2f} n={n}".format(label=label, **p))

    # ============================================================
    # 七、波动率因子
    # ============================================================
    print("\n" + "=" * 90)
    print("七、波动率因子 (D+0→D+9)")
    print("=" * 90)
    vol_bins = [
        ('低波动(<1%)', lambda v: v['vol_20d'] < 1),
        ('中波动(1~2%)', lambda v: 1 <= v['vol_20d'] < 2),
        ('高波动(>2%)', lambda v: v['vol_20d'] >= 2),
    ]
    for label, fn in vol_bins:
        subset = [v for v in sample if fn(v)]
        if not subset: continue
        p = calc_perf(subset, 0, 9)
        print("  {label:>12}: {avg:+6.2f}% {med:+6.2f}% {win:.1f}% {std:.2f}% {sharpe:+.2f} n={n}".format(label=label, **p))

    # ============================================================
    # 八、多因子组合筛选
    # ============================================================
    print("\n" + "=" * 90)
    print("八、多因子组合筛选")
    print("=" * 90)

    rules = [
        ('基准(无筛选)', lambda v: True),
        ('pre3<0%', lambda v: v['pre3_ret'] < 0),
        ('pre3<2%', lambda v: v['pre3_ret'] < 2),
        ('pre5<0%', lambda v: v['pre5_ret'] < 0),
        ('pre5<2%', lambda v: v['pre5_ret'] < 2),
        ('pre7<0%', lambda v: v['pre7_ret'] < 0),
        ('pre7<2%', lambda v: v['pre7_ret'] < 2),
        ('rc>0%', lambda v: v['reg_day_chg'] > 0),
        ('rc>2%', lambda v: v['reg_day_chg'] > 2),
        ('rc<-2%', lambda v: v['reg_day_chg'] < -2),
        ('pre3<0%+rc>0%', lambda v: v['pre3_ret'] < 0 and v['reg_day_chg'] > 0),
        ('pre3<2%+rc>0%', lambda v: v['pre3_ret'] < 2 and v['reg_day_chg'] > 0),
        ('pre5<0%+rc>0%', lambda v: v['pre5_ret'] < 0 and v['reg_day_chg'] > 0),
        ('pre5<2%+rc>0%', lambda v: v['pre5_ret'] < 2 and v['reg_day_chg'] > 0),
        ('pre7<0%+rc>0%', lambda v: v['pre7_ret'] < 0 and v['reg_day_chg'] > 0),
        ('pre7<2%+rc>0%', lambda v: v['pre7_ret'] < 2 and v['reg_day_chg'] > 0),
        ('pre5<0%+rc>0%+vr_reg<1.5', lambda v: v['pre5_ret'] < 0 and v['reg_day_chg'] > 0 and v['vol_ratio_reg'] < 1.5),
        ('pre7<2%+rc>0%+vr_reg<1.5', lambda v: v['pre7_ret'] < 2 and v['reg_day_chg'] > 0 and v['vol_ratio_reg'] < 1.5),
        ('pre7<2%+rc>0%+vr_dp1<1', lambda v: v['pre7_ret'] < 2 and v['reg_day_chg'] > 0 and v['vol_ratio_dp1'] < 1),
        ('pre3<0%+rc>0%+vr_reg<1', lambda v: v['pre3_ret'] < 0 and v['reg_day_chg'] > 0 and v['vol_ratio_reg'] < 1),
        ('pre7<2%+mom10<5%', lambda v: v['pre7_ret'] < 2 and v['mom10'] < 5),
        ('pre7<2%+mom20<5%', lambda v: v['pre7_ret'] < 2 and v['mom20'] < 5),
        ('pre3<2%+mom10<5%', lambda v: v['pre3_ret'] < 2 and v['mom10'] < 5),
        ('pre3<2%+mom10<5%+rc>0%', lambda v: v['pre3_ret'] < 2 and v['mom10'] < 5 and v['reg_day_chg'] > 0),
        ('pre5<2%+mom10<5%+rc>0%', lambda v: v['pre5_ret'] < 2 and v['mom10'] < 5 and v['reg_day_chg'] > 0),
        ('pre3<2%+mom20<10%+rc>0%', lambda v: v['pre3_ret'] < 2 and v['mom20'] < 10 and v['reg_day_chg'] > 0),
        ('pre7<2%+rc>0%+vol<2%', lambda v: v['pre7_ret'] < 2 and v['reg_day_chg'] > 0 and v['vol_20d'] < 2),
        ('pre5<2%+rc>0%+vol<2%', lambda v: v['pre5_ret'] < 2 and v['reg_day_chg'] > 0 and v['vol_20d'] < 2),
        ('pre3<0%+rc>0%+vol<2%', lambda v: v['pre3_ret'] < 0 and v['reg_day_chg'] > 0 and v['vol_20d'] < 2),
        ('pre7<0%+rc>0%+vol<2%', lambda v: v['pre7_ret'] < 0 and v['reg_day_chg'] > 0 and v['vol_20d'] < 2),
    ]

    # Test all rules across multiple windows
    for boff, soff in windows:
        hold = soff - boff
        print(f"\n  D+{boff}→D+{soff} ({hold}天):")
        print(f"  {'规则':<42} {'平均':>6} {'中位':>6} {'胜率':>6} {'样本':>5} {'夏普':>6}")
        print("  " + "-" * 80)
        for name, fn in rules:
            subset = [v for v in sample if fn(v)]
            if len(subset) < 3:
                continue
            p = calc_perf(subset, boff, soff)
            if p['n'] < 3:
                continue
            print("  {name:<42} {avg:>+5.2f}% {med:>+5.2f}% {win:>5.1f}% {n:>4} {sharpe:>+5.2f}".format(
                name=name, **p))

    # ============================================================
    # 九、Top因子逐日效果（D+1到D+15）
    # ============================================================
    print("\n" + "=" * 90)
    print("九、Top因子逐日效果 (筛选 vs 无筛选)")
    print("=" * 90)

    # Find best 3 rules from D+0→D+9
    best_rules = []
    for name, fn in rules[1:]:  # skip baseline
        subset = [v for v in sample if fn(v)]
        if len(subset) < 5:
            continue
        p = calc_perf(subset, 0, 9)
        if p['n'] < 5:
            continue
        best_rules.append((name, fn, p))
    best_rules.sort(key=lambda x: (x[2]['sharpe'], x[2]['avg']), reverse=True)

    print("\n  Top 3 规则 (D+0→D+9):")
    for name, fn, p in best_rules[:3]:
        print("    {name}: 平均{avg:+.2f}% 胜率{win:.1f}% 夏普{sharpe:+.2f} n={n}".format(name=name, **p))

    print(f"\n  {'规则':<35} {'D+1':>7} {'D+3':>7} {'D+5':>7} {'D+7':>7} {'D+9':>7} {'D+10':>7} {'D+12':>7}")
    print("  " + "-" * 70)

    for name, fn, _ in best_rules[:5]:
        subset = [v for v in sample if fn(v)]
        if len(subset) < 3: continue
        line = "  {name:<35}".format(name=name)
        for soff in [1, 3, 5, 7, 9, 10, 12]:
            p = calc_perf(subset, 0, soff)
            if p['n'] >= 3:
                line += " {avg:>+6.2f}%".format(**p)
            else:
                line += "     -"
        print(line)

    # Baseline
    line = "  {'无筛选':<35}"
    for soff in [1, 3, 5, 7, 9, 10, 12]:
        p = calc_perf(sample, 0, soff)
        line += " {avg:>+6.2f}%".format(**p)
    print(line)


if __name__ == '__main__':
    main()
