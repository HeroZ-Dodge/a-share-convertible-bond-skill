#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高信号率策略挖掘 — 目标：信号率≥15% + 夏普≥0.35

原则（来自CLAUDE.md）:
- 信号率≥15%（366样本中≥55次触发）
- 夏普≥0.35
- 优先平衡，不追求极致夏普
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


def load_pool(cache):
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
        reg = prices[sd[ri]]
        reg_close = reg['close']
        if reg_close <= 0 or ri < 10: continue

        reg_open = reg.get('open', 0) or reg_close

        # 因子
        pre1  = ((reg_close - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri >= 1 else 0
        pre3  = ((reg_close - prices[sd[ri-3]]['close']) / prices[sd[ri-3]]['close'] * 100) if ri >= 3 else 0
        pre5  = ((reg_close - prices[sd[ri-5]]['close']) / prices[sd[ri-5]]['close'] * 100) if ri >= 5 else 0
        pre7  = ((reg_close - prices[sd[ri-7]]['close']) / prices[sd[ri-7]]['close'] * 100) if ri >= 7 else 0
        pre10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0
        mom5  = ((reg_close - prices[sd[ri-5]]['close']) / prices[sd[ri-5]]['close'] * 100) if ri >= 5 else 0
        mom10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0

        rc = ((reg_close - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri > 0 else 0
        body = ((reg_close - reg_open) / reg_open * 100) if reg_open > 0 else 0
        amplitude = ((reg.get('high', reg_close) - reg.get('low', reg_close)) / reg_open * 100) if reg_open > 0 else 0
        real_body = abs(body)

        vol_now = reg.get('volume', 0)
        vol_avg5 = 0; vol_avg10 = 0
        if ri >= 10:
            vlist = [prices[sd[ri-k]].get('volume',0) for k in range(1,11) if prices[sd[ri-k]].get('volume',0)>0]
            if vlist:
                vol_avg10 = sum(vlist)/len(vlist)
                vol_avg5 = sum(vlist[:5])/5
        vol_ratio5 = (vol_now / vol_avg5) if vol_avg5 > 0 else 1
        vol_ratio10 = (vol_now / vol_avg10) if vol_avg10 > 0 else 1

        # std7
        daily_rets_7 = []
        if ri >= 7:
            for k in range(7):
                idx = ri-k; prev_idx = idx-1
                if prev_idx>=0 and prices[sd[prev_idx]]['close']>0:
                    daily_rets_7.append((prices[sd[idx]]['close']-prices[sd[prev_idx]]['close'])/prices[sd[prev_idx]]['close']*100)
        std7 = 0
        if len(daily_rets_7)>=5:
            avg = sum(daily_rets_7)/len(daily_rets_7)
            std7 = (sum((x-avg)**2 for x in daily_rets_7)/len(daily_rets_7))**0.5

        # range7
        high7 = 0; low7 = 99999
        if ri >= 7:
            for k in range(ri-7, ri+1):
                h = prices[sd[k]].get('high',0)
                l = prices[sd[k]].get('low',99999)
                if h>high7: high7=h
                if l<low7: low7=l
        range7 = ((high7-low7)/low7*100) if low7>0 else 0

        # D+1 buy
        buy_idx = ri + 1
        buy_price = None
        if buy_idx < len(sd) and sd[buy_idx] <= today_str:
            buy_price = prices[sd[buy_idx]].get('open', 0)
        if not buy_price or buy_price <= 0: continue

        # hold days
        hold_days = []
        for off in range(1, 15):
            idx = ri + off
            if idx >= len(sd) or sd[idx] > today_str: break
            p = prices[sd[idx]]
            hold_days.append({
                'off': off, 'date': sd[idx],
                'open': p.get('open',0), 'close': p.get('close',0),
                'high': p.get('high',0), 'low': p.get('low',0),
            })
        if len(hold_days) < 2: continue

        pool.append({
            'code': sc, 'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'pre1': pre1, 'pre3': pre3, 'pre5': pre5, 'pre7': pre7, 'pre10': pre10,
            'mom5': mom5, 'mom10': mom10,
            'rc': rc, 'body': body, 'amplitude': amplitude, 'real_body': real_body,
            'vol_ratio5': vol_ratio5, 'vol_ratio10': vol_ratio10,
            'std7': std7, 'range7': range7,
            'buy_price': buy_price, 'hold_days': hold_days,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    return pool


# ========== 策略评估 ==========

def calc(trades):
    if not trades: return None
    rets = sorted([t['ret'] for t in trades])
    n = len(rets)
    avg = sum(rets)/n
    std = (sum((x-avg)**2 for x in rets)/n)**0.5
    sh = avg/std if std>0 else 0
    win = sum(1 for x in rets if x>0)/n*100
    med = rets[n//2]
    avg_hold = sum(t['hold'] for t in trades)/n
    return {'n':n, 'avg':avg, 'med':med, 'win':win, 'std':std, 'sharpe':sh, 'avg_hold':avg_hold}


def test_fixed_d9(pool, fn):
    rets = []
    for v in pool:
        if not fn(v): continue
        for d in v['hold_days']:
            if d['off'] == 8:
                rets.append(((d['close'] - v['buy_price']) / v['buy_price']) * 100)
                break
    if not rets: return None
    n = len(rets)
    avg = sum(rets)/n
    std = (sum((x-avg)**2 for x in rets)/n)**0.5
    sh = avg/std if std>0 else 0
    win = sum(1 for x in rets if x>0)/n*100
    return {'n':n, 'avg':avg, 'win':win, 'std':std, 'sharpe':sh}


def test_tp_sl(pool, fn, tp, sl, max_hold=10):
    trades = []
    for v in pool:
        if not fn(v): continue
        buy = v['buy_price']; hold = v['hold_days']
        exit_off = None; exit_price = None; reason = None
        for i, day in enumerate(hold):
            if i == 0: continue
            if day['close'] <= 0: continue
            ret = ((day['close'] - buy) / buy) * 100
            if ret >= tp: exit_off, exit_price, reason = day['off'], day['close'], 'tp'; break
            if ((buy - day['close']) / buy * 100) >= sl: exit_off, exit_price, reason = day['off'], day['close'], 'sl'; break
            if day['off'] - 1 >= max_hold: exit_off, exit_price, reason = day['off'], day['close'], 'timeout'; break
        if exit_off is None:
            last = hold[-1]; exit_off, exit_price, reason = last['off'], last['close'], 'timeout'
        trades.append({'ret': ((exit_price - buy) / buy) * 100, 'hold': exit_off - 1, 'reason': reason})
    return trades


def main():
    cache = BacktestCache()
    print("加载数据池...", flush=True)
    pool = load_pool(cache)
    print(f"  总样本: {len(pool)}")

    total = len(pool)

    # ========== 1) 系统扫描: pre3×mom10×vol 宽范围 ==========
    print("\n" + "=" * 120)
    print("1. 宽范围扫描: pre3≤X + mom10≤Y + vol≤Z (信号率≥15% + 夏普≥0.30)")
    print("=" * 120)

    candidates = []

    for px in range(0, 8):      # 0, 1, 2, 3, 4, 5, 6, 7
        for my in range(-3, 4): # -3, -2, -1, 0, 1, 2, 3
            for vz in [0.6, 0.7, 0.8, 0.9, 1.0, 1.2]:
                fn = lambda s, p=px, m=my, v=vz: s['pre3'] <= p and s['mom10'] <= m and s['vol_ratio5'] <= v
                triggered = [v for v in pool if fn(v)]
                if len(triggered) < int(total * 0.10): continue  # 至少10%

                st = test_fixed_d9(pool, fn)
                if not st: continue

                candidates.append({
                    'label': f"pre3<={px}+mom10<={my}+vol<={vz}",
                    'fn': fn,
                    'n': st['n'],
                    'rate': st['n']/total*100,
                    'sh_d9': st['sharpe'],
                    'avg': st['avg'],
                    'win': st['win'],
                    'px': px, 'my': my, 'vz': vz,
                })

    # 筛选信号率≥15%
    high_signal = [c for c in candidates if c['rate'] >= 15]
    high_signal.sort(key=lambda x: x['sh_d9'], reverse=True)

    print(f"\n  信号率≥15% 的组合 (按夏普排序, Top 30):")
    print(f"  {'策略':<40} {'样本':>4} {'信号率':>6} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 80)

    for c in high_signal[:30]:
        star = '★' if c['sh_d9'] >= 0.35 else ' '
        print(f"  {star} {c['label']:<38} {c['n']:>4} {c['rate']:>5.1f}% {c['avg']:>+6.2f}% {c['win']:>5.1f}% {c['sh_d9']:>+5.2f}")

    # ========== 2) 加入rc>0的效果 ==========
    print("\n" + "=" * 120)
    print("2. 加入rc>0的效果对比")
    print("=" * 120)

    print(f"\n  {'基础策略':<40} {'信号率':>6} {'夏普':>6} {'+rc>0信号率':>10} {'+rc>0夏普':>8} {'Δ'}")
    print("  " + "-" * 80)

    for c in high_signal[:15]:
        fn_rc = lambda s, f=c['fn']: f(s) and s['rc'] > 0
        triggered_rc = [v for v in pool if fn_rc(v)]
        st_rc = test_fixed_d9(pool, fn_rc)

        base_rate = c['rate']
        base_sh = c['sh_d9']
        if st_rc and st_rc['n'] >= 10:
            rc_rate = st_rc['n']/total*100
            rc_sh = st_rc['sharpe']
            delta = rc_sh - base_sh
            print(f"  {c['label']:<40} {base_rate:>5.1f}% {base_sh:>+5.2f} {rc_rate:>5.1f}% {rc_sh:>+5.2f} {delta:>+4.2f}")
        else:
            print(f"  {c['label']:<40} {base_rate:>5.1f}% {base_sh:>+5.2f} {'(太少)':>10}")

    # ========== 3) Top候选: 完整回测 ==========
    print("\n" + "=" * 120)
    print("3. Top候选策略 — 完整回测 (TP/SL动态退出)")
    print("=" * 120)

    # 选夏普最高且信号率≥15%的
    best = [c for c in high_signal if c['sh_d9'] >= 0.35]
    if not best:
        best = high_signal[:5]  # 退而求其次

    print(f"\n  选出的候选 (信号率≥15%):")
    for c in best[:8]:
        print(f"    {c['label']}: 信号率={c['rate']:.1f}%, 夏普={c['sh_d9']:+.2f}")

    for c in best[:8]:
        fn = c['fn']
        triggered = [v for v in pool if fn(v)]
        print(f"\n  {c['label']} (n={len(triggered)}, 信号率={c['rate']:.1f}%):")
        print(f"    {'退出策略':<25} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6} {'年化':>8}")

        configs = [
            ('固定D+9', 99, 99, 8),
            ('TP3/SL3', 3, 3, 10),
            ('TP4/SL4', 4, 4, 10),
            ('TP5/SL5', 5, 5, 10),
            ('TP3/SL5', 3, 5, 10),
            ('TP5/SL3', 5, 3, 10),
        ]

        for cfg_name, tp, sl, mh in configs:
            trades = test_tp_sl(pool, fn, tp, sl, max_hold=mh)
            st = calc(trades)
            if not st or st['n'] < 5: continue
            eff = st['avg'] / st['avg_hold'] * 245 if st['avg_hold'] > 0 else 0
            reasons = {}
            for t in trades:
                reasons[t['reason']] = reasons.get(t['reason'], 0) + 1
            reason_str = ', '.join(f'{k}({v})' for k, v in sorted(reasons.items()))
            star = '★' if st['sharpe'] >= 0.4 and st['n'] >= 15 else ' '
            print(f"    {star} {cfg_name:<25} {st['n']:>4} {st['avg']:>+6.2f}% {st['win']:>5.1f}% {st['sharpe']:>+5.2f} {eff:>+7.1f}%")

    # ========== 4) 加入rc增强 ==========
    print("\n" + "=" * 120)
    print("4. 带rc>0增强的完整回测")
    print("=" * 120)

    for c in best[:5]:
        fn = c['fn']
        fn_rc = lambda s, f=fn: f(s) and s['rc'] > 0
        triggered_rc = [v for v in pool if fn_rc(v)]
        if len(triggered_rc) < 10: continue

        rate_rc = len(triggered_rc) / total * 100
        st_rc = test_fixed_d9(pool, fn_rc)
        if not st_rc: continue

        print(f"\n  {c['label']}+rc>0 (n={len(triggered_rc)}, 信号率={rate_rc:.1f}%):")
        print(f"    D+9: sh={st_rc['sharpe']:+.2f} avg={st_rc['avg']:+.2f}% win={st_rc['win']:.1f}%")

        # TP5/SL5
        trades = test_tp_sl(pool, fn_rc, 5, 5, max_hold=10)
        st = calc(trades)
        if st:
            eff = st['avg'] / st['avg_hold'] * 245 if st['avg_hold'] > 0 else 0
            print(f"    TP5/SL5: sh={st['sharpe']:+.2f} 年化={eff:.0f}% win={st['win']:.1f}%")

    # ========== 5) 跨limit稳定性 ==========
    print("\n" + "=" * 120)
    print("5. 跨limit稳定性 (Top候选)")
    print("=" * 120)

    print(f"\n  {'策略':<40} {'L=100':>14} {'L=200':>14} {'全量':>14} {'趋势'}")
    print("  " + "-" * 85)

    for c in best[:6]:
        results = []
        for limit in [100, 200, 0]:
            pl = pool[:limit] if limit else pool
            trades = test_tp_sl(pl, c['fn'], 5, 5, max_hold=10)
            st = calc(trades)
            if st:
                results.append(f"sh={st['sharpe']:+.2f}(n={st['n']})")
            else:
                results.append("--")
        trend = "→稳定" if all(r != "--" for r in results) else "???"
        print(f"  {c['label']:<40} {results[0]:>14} {results[1]:>14} {results[2]:>14} {trend}")

    # ========== 6) 按年份 ==========
    print("\n" + "=" * 120)
    print("6. 按年份分组 (TP5/SL5)")
    print("=" * 120)

    for c in best[:6]:
        print(f"\n  {c['label']} (全量n={c['n']}, 信号率={c['rate']:.1f}%):")
        print(f"    {'年份':<10} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
        print("    " + "-" * 45)

        for year in ['2023', '2024', '2025', '2026']:
            yr_pool = [v for v in pool if v['anchor'].startswith(year)]
            if len(yr_pool) < 5: continue
            trades = test_tp_sl(yr_pool, c['fn'], 5, 5, max_hold=10)
            st = calc(trades)
            if not st or st['n'] < 3:
                print(f"    {year}年 {st['n'] if st else 0:>4} (样本不足)")
                continue
            print(f"    {year}年 {st['n']:>4} {st['avg']:>+6.2f}% {st['win']:>5.1f}% {st['sharpe']:>+5.2f}")

    # ========== 7) 推荐 ==========
    print("\n" + "=" * 120)
    print("7. 最终推荐 (信号率≥15% + 夏普≥0.35)")
    print("=" * 120)

    print("\n  从高信号率组合中筛选:")
    print(f"  {'策略':<45} {'信号率':>6} {'D+9夏普':>8} {'TP5/SL5夏普':>10} {'TP5/SL5年化':>10}")
    print("  " + "-" * 80)

    for c in best[:8]:
        fn = c['fn']
        trades = test_tp_sl(pool, fn, 5, 5, max_hold=10)
        st = calc(trades)
        if not st: continue
        eff = st['avg'] / st['avg_hold'] * 245 if st['avg_hold'] > 0 else 0
        print(f"  {c['label']:<45} {c['rate']:>5.1f}% {c['sh_d9']:>+6.2f} {st['sharpe']:>+8.2f} {eff:>+7.1f}%")

    print()


if __name__ == '__main__':
    main()
