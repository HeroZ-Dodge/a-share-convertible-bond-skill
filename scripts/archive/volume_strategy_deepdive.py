#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B1/B3 策略稳定性：不同 limit、不同窗口、不同年份
"""
import sys, os, re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.backtest_cache import BacktestCache


def find_idx(sd, target):
    result = 0
    for i, d in enumerate(sd):
        if d <= target:
            result = i
        else:
            break
    return result


def build_full_pool(cache):
    """构建全量数据池，含所有窗口收益"""
    today_str = datetime.now().strftime('%Y-%m-%d')
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
        if reg_price <= 0 or ri < 10: continue

        pre3 = ((reg_price - prices[sd[ri-3]]['close']) / prices[sd[ri-3]]['close'] * 100) if ri >= 3 else 0
        pre7 = ((reg_price - prices[sd[ri-7]]['close']) / prices[sd[ri-7]]['close'] * 100) if ri >= 7 else 0
        rc = ((reg_price - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri > 0 else 0
        mom10 = ((reg_price - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0

        vol_now = prices[sd[ri]].get('volume', 0)
        vol_avg5 = 0
        if ri >= 5:
            vols = [prices[sd[ri-k]].get('volume',0) for k in range(1,6) if prices[sd[ri-k]].get('volume',0) > 0]
            if vols: vol_avg5 = sum(vols)/len(vols)

        # 所有窗口收益
        ret = {}
        for boff in range(0, 8):
            buy_idx = ri + boff + 1
            if buy_idx >= len(sd) or sd[buy_idx] > today_str: continue
            bp = prices[sd[buy_idx]].get('open', 0)
            if bp <= 0: continue
            for soff in range(boff + 1, 16):
                sell_idx = ri + soff
                if sell_idx >= len(sd) or sd[sell_idx] > today_str: continue
                sp = prices[sd[sell_idx]].get('close', 0)
                if sp <= 0: continue
                ret[(boff, soff)] = ((sp - bp) / bp) * 100

        pool.append({
            'anchor': anchor,
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
            'vol_ratio5': (vol_now/vol_avg5) if vol_avg5 > 0 else 1,
            'ret': ret,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    return pool


def calc(strets, min_n=5):
    if len(strets) < min_n: return None
    s = sorted(strets)
    n = len(s)
    avg = sum(s)/n
    std = (sum((x-avg)**2 for x in s)/n)**0.5
    sh = avg/std if std > 0 else 0
    win = sum(1 for x in s if x > 0)/n*100
    return {'n':n, 'avg':avg, 'med':s[n//2], 'win':win, 'std':std, 'sharpe':sh}


def main():
    cache = BacktestCache()
    pool = build_full_pool(cache)
    print(f"总样本: {len(pool)}")

    # 定义
    def b3(v): return v['pre3']<=2 and v['mom10']<5 and v['rc']>0 and v['vol_ratio5']<0.7
    def b1(v): return v['pre3']<=2 and v['mom10']<5 and v['rc']>0 and v['vol_ratio5']<0.8
    def s1(v): return v['pre3']<=2 and v['mom10']<5 and v['rc']>0

    strategies = [('B3:vol<0.7', b3, 0.7), ('B1:vol<0.8', b1, 0.8), ('S1:baseline', s1, None)]

    # ========== 1) 不同 limit 下全窗口最优 ==========
    print("\n" + "=" * 120)
    print("各 limit 下最优窗口")
    print("=" * 120)

    for sname, sfn, vthresh in strategies:
        print(f"\n{sname}:")
        for limit in [100, 150, 200, 300]:
            sample = pool[:limit]
            triggered = [v for v in sample if sfn(v)]
            if len(triggered) < 5:
                print(f"  limit={limit}: {len(triggered)} samples")
                continue

            best = None
            for boff in range(0, 8):
                for soff in range(boff+1, 16):
                    rets = [v['ret'][(boff,soff)] for v in triggered if (boff,soff) in v['ret']]
                    st = calc(rets, min_n=5)
                    if st and (best is None or st['sharpe'] > best['sharpe']):
                        best = {**st, 'boff':boff, 'soff':soff, 'hold':soff-boff-1}

            if best:
                print(f"  limit={limit:>3}: D+{best['boff']}→D+{best['soff']}(持{best['hold']}) "
                      f"n={best['n']} avg={best['avg']:+.2f}% win={best['win']:.0f}% sh={best['sharpe']:+.2f}")

    # ========== 2) 固定最优窗口，按年份分组 ==========
    print("\n" + "=" * 120)
    print("按年份分组 — 最优窗口稳定性")
    print("=" * 120)

    # B1 最优: D+3→D+5, B3 最优: D+3→D+9
    fixed_windows = [
        ('B3: D+3→D+9', b3, 3, 9),
        ('B1: D+3→D+5', b1, 3, 5),
        ('S1: D+3→D+5', s1, 3, 5),
    ]

    for sname, sfn, boff, soff in fixed_windows:
        by_year = {}
        for v in pool:
            if not sfn(v): continue
            year = v['anchor'][:4]
            if (boff, soff) in v['ret']:
                by_year.setdefault(year, []).append(v['ret'][(boff, soff)])

        print(f"\n{sname}:")
        for year in sorted(by_year.keys()):
            rets = by_year[year]
            st = calc(rets)
            if st:
                print(f"  {year}: n={st['n']} avg={st['avg']:+.2f}% win={st['win']:.0f}% sh={st['sharpe']:+.2f}  "
                      f"med={st['med']:+.2f}% std={st['std']:.2f}%")

    # ========== 3) 触发条件分析 — 各因子在 B1/B3 vs S1 的差异 ==========
    print("\n" + "=" * 120)
    print("触发因子对比 (全样本)")
    print("=" * 120)

    for sname, sfn, vthresh in strategies:
        triggered = [v for v in pool if sfn(v)]
        if not triggered: continue
        pre3s = [v['pre3'] for v in triggered]
        m10s = [v['mom10'] for v in triggered]
        rcs = [v['rc'] for v in triggered]
        vols = [v['vol_ratio5'] for v in triggered]
        avg_pre3 = sum(pre3s)/len(pre3s)
        avg_m10 = sum(m10s)/len(m10s)
        avg_rc = sum(rcs)/len(rcs)
        avg_vol = sum(vols)/len(vols)
        print(f"\n{sname} (n={len(triggered)}):")
        print(f"  pre3均值={avg_pre3:+.2f}%  mom10均值={avg_m10:+.2f}%  "
              f"rc均值={avg_rc:+.2f}%  vol_ratio均值={avg_vol:.2f}")

    # ========== 4) vol_ratio 分档效果 ==========
    print("\n" + "=" * 120)
    print("vol_ratio 分档 — 在 S1 触发基础上")
    print("=" * 120)

    s1_triggered = [v for v in pool if s1(v)]
    if s1_triggered:
        # 对所有 s1 触发股，按 vol_ratio 分档
        bins = [(0, 0.5), (0.5, 0.7), (0.7, 0.8), (0.8, 1.0), (1.0, 1.2), (1.2, 99)]
        for lo, hi in bins:
            subset = [v for v in s1_triggered if lo < v['vol_ratio5'] <= hi]
            if not subset: continue
            rets_d35 = [v['ret'][(3,5)] for v in subset if (3,5) in v['ret']]
            st = calc(rets_d35)
            if st:
                print(f"  vol {lo:.1f}~{hi:.1f}: n={st['n']} avg={st['avg']:+.2f}% "
                      f"win={st['win']:.0f}% sh={st['sharpe']:+.2f}")


if __name__ == '__main__':
    main()
