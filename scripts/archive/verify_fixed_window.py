#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 B1/S1/B3 固定窗口策略 — 用 D+1 开盘买入 vs D+9 收盘卖出

这些策略基于注册日因子，注册日收盘后即可判断，次日开盘买入是合法的。
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


def main():
    cache = BacktestCache()
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
        reg_close = prices[sd[ri]]['close']
        if reg_close <= 0 or ri < 10: continue

        # 因子
        pre3 = ((reg_close - prices[sd[ri-3]]['close']) / prices[sd[ri-3]]['close'] * 100) if ri >= 3 else 0
        pre7 = ((reg_close - prices[sd[ri-7]]['close']) / prices[sd[ri-7]]['close'] * 100) if ri >= 7 else 0
        rc = ((reg_close - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri > 0 else 0
        mom10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0

        vol_now = prices[sd[ri]].get('volume', 0)
        vol_avg5 = 0
        if ri >= 5:
            vols = [prices[sd[ri-k]].get('volume',0) for k in range(1,6) if prices[sd[ri-k]].get('volume',0)>0]
            if vols: vol_avg5 = sum(vols)/len(vols)

        # D+1 开盘买入
        buy_idx = ri + 1
        buy_price = None
        if buy_idx < len(sd) and sd[buy_idx] <= today_str:
            buy_price = prices[sd[buy_idx]].get('open', 0)

        # D+9 收盘卖出
        sell_idx = ri + 9
        sell_price = None
        if sell_idx < len(sd) and sd[sell_idx] <= today_str:
            sell_price = prices[sd[sell_idx]].get('close', 0)

        if not buy_price or buy_price <= 0 or not sell_price:
            continue

        ret = ((sell_price - buy_price) / buy_price) * 100

        vol_ratio = (vol_now / vol_avg5) if vol_avg5 > 0 else 1

        pool.append({
            'code': sc, 'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
            'vol_ratio': vol_ratio,
            'ret': ret,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)

    # 策略定义
    strategies = {
        'S1: pre3≤2+mom10<5+rc>0': lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0,
        'B1: S1+vol<0.8':           lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['vol_ratio'] < 0.8,
        'B3: S1+vol<0.7':           lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['vol_ratio'] < 0.7,
        'S2: pre3≤2+mom10<5':       lambda v: v['pre3'] <= 2 and v['mom10'] < 5,
        'S3: rc<-2%':               lambda v: v['rc'] < -2,
        'S4: pre7<0%':              lambda v: v['pre7'] < 0,
    }

    for limit in [100, 150, 200, 300]:
        sample = pool[:limit]
        print(f"\n{'='*100}")
        print(f"limit={limit} (总样本 {len(sample)}) — D+1开盘买入, D+9收盘卖出")
        print(f"{'='*100}")

        print(f"  {'策略':<30} {'样本':>4} {'平均':>7} {'中位':>7} {'胜率':>6} {'标准差':>7} {'夏普':>6} {'vol_avg':>8}")
        print("  " + "-" * 100)

        for sname, sfn in strategies.items():
            triggered = [v for v in sample if sfn(v)]
            n = len(triggered)
            if n < 5:
                print(f"  {sname:<30} {n:>4} (太少)")
                continue
            rets = [v['ret'] for v in triggered]
            s = sorted(rets)
            avg = sum(s) / n
            win_n = sum(1 for x in s if x > 0)
            win = win_n / n * 100
            std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
            sh = avg / std if std > 0 else 0
            vol_avgs = [v['vol_ratio'] for v in triggered]
            vol_mean = sum(vol_avgs) / len(vol_avgs)

            star = '★' if sh > 0.4 and n >= 15 else ' '
            print(f"  {star} {sname:<28} {n:>4} {avg:>+6.2f}% {s[n//2]:>+6.2f}% {win:>5.1f}% {std:>6.2f}% {sh:>+5.2f} {vol_mean:>7.2f}")

    # ========== 不同卖出窗口 ==========
    print(f"\n\n{'='*100}")
    print("B1 策略不同卖出窗口 (D+1买入 → D+N卖出)")
    print(f"{'='*100}")

    b1_triggered = [v for v in pool if v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['vol_ratio'] < 0.8]
    n_b1 = len(b1_triggered)

    # 需要重新加载带多窗口数据
    today_str = datetime.now().strftime('%Y-%m-%d')
    bonds = cache.get_jisilu_bonds(phase='注册', limit=0)
    b1_full = []

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
        reg_close = prices[sd[ri]]['close']
        if reg_close <= 0 or ri < 10: continue

        pre3 = ((reg_close - prices[sd[ri-3]]['close']) / prices[sd[ri-3]]['close'] * 100) if ri >= 3 else 0
        pre7 = ((reg_close - prices[sd[ri-7]]['close']) / prices[sd[ri-7]]['close'] * 100) if ri >= 7 else 0
        rc = ((reg_close - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri > 0 else 0
        mom10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0

        vol_now = prices[sd[ri]].get('volume', 0)
        vol_avg5 = 0
        if ri >= 5:
            vols = [prices[sd[ri-k]].get('volume',0) for k in range(1,6) if prices[sd[ri-k]].get('volume',0)>0]
            if vols: vol_avg5 = sum(vols)/len(vols)

        vol_ratio = (vol_now / vol_avg5) if vol_avg5 > 0 else 1

        if not (pre3 <= 2 and mom10 < 5 and rc > 0 and vol_ratio < 0.8):
            continue

        rets_window = {}
        for soff in range(3, 16):
            sell_idx = ri + soff
            if sell_idx >= len(sd) or sd[sell_idx] > today_str: continue
            sp = prices[sd[sell_idx]].get('close', 0)
            if sp <= 0: continue
            buy_price = prices[sd[ri + 1]].get('open', 0) if ri + 1 < len(sd) else 0
            if buy_price <= 0: continue
            rets_window[soff] = ((sp - buy_price) / buy_price) * 100

        entry = {**rets_window}
        entry['anchor'] = anchor
        b1_full.append(entry)

    b1_full.sort(key=lambda x: x['anchor'], reverse=True)
    b1_full = b1_full[:200]

    print(f"\nB1 (n={len(b1_full)}) 各卖出窗口:")
    print(f"  {'卖出日':>6}", end='')
    for s in range(3, 16):
        print(f"  D+{s:>2}", end='')
    print()
    print("  " + "-" * (6 + 6 * 13))

    for metric in ['夏普', '平均', '胜率', '样本']:
        print(f"  {metric:>6}", end='')
        for soff in range(3, 16):
            rets = [v[soff] for v in b1_full if soff in v]
            if len(rets) < 5:
                print(f"  {'--':>4}", end='')
                continue
            s = sorted(rets)
            n = len(s)
            avg = sum(s) / n
            std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
            sh = avg / std if std > 0 else 0
            win = sum(1 for x in s if x > 0) / n * 100

            if metric == '夏普':
                print(f"  {sh:>+4.1f}", end='')
            elif metric == '平均':
                print(f"  {avg:>+4.1f}", end='')
            elif metric == '胜率':
                print(f"  {win:>4.0f}", end='')
            elif metric == '样本':
                print(f"  {n:>4}", end='')
        print()


if __name__ == '__main__':
    main()
