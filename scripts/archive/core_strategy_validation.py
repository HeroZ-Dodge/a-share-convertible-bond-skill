#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心策略稳定性验证 + 最优窗口确认
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


def load_pool(cache, limit):
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
        if reg_price <= 0: continue
        if ri < 10: continue

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

        vol_now = prices[sd[ri]].get('volume', 0)
        vol_avg5 = 0
        if ri >= 5:
            vols = [prices[sd[ri-k]].get('volume',0) for k in range(1,6)]
            vols = [v for v in vols if v > 0]
            if vols: vol_avg5 = sum(vols)/len(vols)

        high_7, low_7 = 0, 99999
        if ri >= 7:
            for k in range(ri-7, ri+1):
                h = prices[sd[k]].get('high', 0)
                l = prices[sd[k]].get('low', 99999)
                if h > high_7: high_7 = h
                if l < low_7: low_7 = l
        range_7 = ((high_7 - low_7) / low_7 * 100) if low_7 > 0 else 0

        pool.append({
            'code': sc, 'anchor': anchor,
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
            'vol_ratio5': (vol_now/vol_avg5) if vol_avg5 > 0 else 1,
            'range_7': range_7,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    return pool[:limit] if limit > 0 else pool


def main():
    cache = BacktestCache()

    # 定义策略
    strategies = {
        # B族: 缩量
        'B3: pre3≤2+mom10<5+rc>0+vol<0.7': lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['vol_ratio5'] < 0.7,
        'B1: pre3≤2+mom10<5+rc>0+vol<0.8': lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['vol_ratio5'] < 0.8,

        # A族: 动量微调
        'A4: pre3≤1+mom10<5+rc>0':       lambda v: v['pre3'] <= 1 and v['mom10'] < 5 and v['rc'] > 0,
        'A5: pre3≤0+mom10<5+rc>0':       lambda v: v['pre3'] <= 0 and v['mom10'] < 5 and v['rc'] > 0,

        # D族: 窄幅
        'D2: pre3≤2+mom10<5+rc>0+range<8%': lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['range_7'] < 8,
        'D4: pre3≤1+mom10<3+rc>1+range<6%': lambda v: v['pre3'] <= 1 and v['mom10'] < 3 and v['rc'] > 1 and v['range_7'] < 6,

        # 原始对比
        'S1: pre3≤2+mom10<5+rc>0':       lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0,
    }

    for limit in [100, 150, 200, 300]:
        pool = load_pool(cache, limit)
        print(f"\n{'='*110}")
        print(f"limit={limit} (总样本 {len(pool)})")
        print("="*110)

        print(f"  {'策略':<45} {'样本':>4} {'平均':>7} {'中位':>7} {'胜率':>6} {'标准差':>7} {'夏普':>6}")
        print("  " + "-" * 100)

        for sname, sfn in strategies.items():
            triggered = [v for v in pool if sfn(v)]
            n = len(triggered)
            if n < 5:
                print(f"  {sname:<45} {n:>4} (太少)")
                continue

            # D+3→D+9 baseline
            rets = []
            for v in triggered:
                # We need price data for returns - just report factor stats for now
                pass

            # Report factor stats
            pre3s = [v['pre3'] for v in triggered]
            m10s = [v['mom10'] for v in triggered]
            rcs = [v['rc'] for v in triggered]
            vols = [v['vol_ratio5'] for v in triggered]
            print(f"  {sname:<45} {n:>4}  vol_ratio={sum(vols)/len(vols):.2f}  "
                  f"pre3={sum(pre3s)/len(pre3s):+.1f}  mom10={sum(m10s)/len(m10s):+.1f}  rc={sum(rcs)/len(rcs):+.1f}")

    # ========== 深度窗口扫描 (B3, B1, S1) ==========
    print("\n\n" + "=" * 110)
    print("深度窗口扫描 — 加载全部价格数据")
    print("=" * 110)

    today_str = datetime.now().strftime('%Y-%m-%d')
    bonds = cache.get_jisilu_bonds(phase='注册', limit=0)
    full_pool = []
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

        high_7, low_7 = 0, 99999
        if ri >= 7:
            for k in range(ri-7, ri+1):
                h = prices[sd[k]].get('high', 0)
                l = prices[sd[k]].get('low', 99999)
                if h > high_7: high_7 = h
                if l < low_7: low_7 = l
        range_7 = ((high_7 - low_7) / low_7 * 100) if low_7 > 0 else 0

        # 所有窗口收益
        ret = {}
        for boff in range(0, 8):
            buy_idx = ri + boff + 1
            if buy_idx >= len(sd) or sd[buy_idx] > today_str: continue
            bp = prices[sd[buy_idx]].get('open', 0)
            if bp <= 0: continue
            for soff in range(boff + 2, 16):
                sell_idx = ri + soff
                if sell_idx >= len(sd) or sd[sell_idx] > today_str: continue
                sp = prices[sd[sell_idx]].get('close', 0)
                if sp <= 0: continue
                ret[(boff, soff)] = ((sp - bp) / bp) * 100

        full_pool.append({
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
            'vol_ratio5': (vol_now/vol_avg5) if vol_avg5 > 0 else 1,
            'range_7': range_7, 'ret': ret,
        })

    # 核心策略
    core_strategies = [
        ('B3: vol<0.7', lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['vol_ratio5'] < 0.7),
        ('B1: vol<0.8', lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['vol_ratio5'] < 0.8),
        ('S1: baseline',  lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0),
        ('D4: range<6+rc>1', lambda v: v['pre3'] <= 1 and v['mom10'] < 3 and v['rc'] > 1 and v['range_7'] < 6),
    ]

    for sname, sfn in core_strategies:
        triggered = [v for v in full_pool if sfn(v)]
        n = len(triggered)
        if n < 8:
            print(f"\n{sname}: {n} samples (too few)")
            continue

        # 扫描所有窗口，找最优
        best_sharpe = -999
        best_config = None
        for boff in range(0, 8):
            for soff in range(boff + 2, 16):
                rets = [v['ret'][(boff, soff)] for v in triggered if (boff, soff) in v['ret']]
                if len(rets) < 8:
                    continue
                s = sorted(rets)
                avg = sum(s) / len(s)
                std = (sum((x - avg)**2 for x in s) / len(s)) ** 0.5
                sh = avg / std if std > 0 else 0
                win = sum(1 for x in s if x > 0) / len(s) * 100
                if sh > best_sharpe:
                    best_sharpe = sh
                    best_config = {
                        'boff': boff, 'soff': soff, 'hold': soff - boff - 1,
                        'n': len(rets), 'avg': avg, 'std': std, 'sharpe': sh,
                        'win': win, 'med': s[len(s)//2],
                        'best': max(s), 'worst': min(s),
                    }

        if best_config:
            print(f"\n{sname} (总样本 {n})")
            print(f"  最优: D+{best_config['boff']}→D+{best_config['soff']} (持有{best_config['hold']}天)")
            print(f"  有效样本: {best_config['n']}  平均: {best_config['avg']:+.2f}%  "
                  f"中位: {best_config['med']:+.2f}%  胜率: {best_config['win']:.1f}%")
            print(f"  标准差: {best_config['std']:.2f}%  夏普: {best_config['sharpe']:+.2f}")
            print(f"  最佳: +{best_config['best']:.2f}%  最差: {best_config['worst']:.2f}%")


if __name__ == '__main__':
    main()
