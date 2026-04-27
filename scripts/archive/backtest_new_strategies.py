#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新策略稳定性验证 + 动态退出测试

验证 factor_space_scan 发现的 top 策略:
  1. 跨 limit 稳定性
  2. TP/SL 动态退出效果
  3. 年化效率
  4. 不同年份稳定性
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
        reg_close = prices[sd[ri]]['close']
        if reg_close <= 0 or ri < 10: continue

        reg = prices[sd[ri]]
        reg_open = reg.get('open', 0) or reg_close

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
            vols = [prices[sd[ri-k]].get('volume',0) for k in range(1,11) if prices[sd[ri-k]].get('volume',0)>0]
            if vols:
                vol_avg10 = sum(vols)/len(vols)
                vol_avg5 = sum(vols[:5])/5
        vol_ratio5 = (vol_now / vol_avg5) if vol_avg5 > 0 else 1
        vol_ratio10 = (vol_now / vol_avg10) if vol_avg10 > 0 else 1

        # range7
        high7 = 0; low7 = 99999
        if ri >= 7:
            for k in range(ri-7, ri+1):
                h = prices[sd[k]].get('high', 0)
                l = prices[sd[k]].get('low', 99999)
                if h > high7: high7 = h
                if l < low7: low7 = l
        range7 = ((high7 - low7) / low7 * 100) if low7 > 0 else 0
        pos_in_range7 = ((reg_close - low7) / (high7 - low7) * 100) if high7 > low7 else 50

        # std7
        daily_rets_7 = []
        if ri >= 7:
            for k in range(7):
                idx = ri - k
                prev_idx = idx - 1
                if prev_idx >= 0 and prices[sd[prev_idx]]['close'] > 0:
                    dr = ((prices[sd[idx]]['close'] - prices[sd[prev_idx]]['close']) / prices[sd[prev_idx]]['close'] * 100)
                    daily_rets_7.append(dr)
        std7 = 0
        if len(daily_rets_7) >= 5:
            avg = sum(daily_rets_7)/len(daily_rets_7)
            std7 = (sum((x-avg)**2 for x in daily_rets_7)/len(daily_rets_7))**0.5

        # buy D+1 open
        buy_idx = ri + 1
        buy_price = None
        if buy_idx < len(sd) and sd[buy_idx] <= today_str:
            buy_price = prices[sd[buy_idx]].get('open', 0)
        if not buy_price or buy_price <= 0: continue

        # hold period
        hold_days = []
        for off in range(1, 21):
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
            'std7': std7, 'range7': range7, 'pos_in_range7': pos_in_range7,
            'buy_price': buy_price, 'hold_days': hold_days,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    return pool


def calc(trades):
    if not trades: return None
    rets = sorted([t['ret'] for t in trades])
    n = len(rets)
    avg = sum(rets)/n
    std = (sum((x-avg)**2 for x in rets)/n)**0.5
    sh = avg/std if std > 0 else 0
    win = sum(1 for x in rets if x > 0)/n*100
    med = rets[n//2]
    avg_hold = sum(t['hold'] for t in trades)/n
    return {'n':n, 'avg':avg, 'med':med, 'win':win, 'std':std, 'sharpe':sh, 'avg_hold':avg_hold}


def test_fixed_tp_sl(pool, tp, sl, max_hold=10, strat_fn=None):
    if strat_fn: pool = [v for v in pool if strat_fn(v)]
    trades = []
    for v in pool:
        buy = v['buy_price']; hold = v['hold_days']
        exit_off = None; exit_price = None; reason = None
        for i, day in enumerate(hold):
            if i == 0: continue
            if day['close'] <= 0: continue
            ret = ((day['close'] - buy) / buy) * 100
            if ret >= tp:
                exit_off, exit_price, reason = day['off'], day['close'], 'tp'; break
            if ((buy - day['close']) / buy * 100) >= sl:
                exit_off, exit_price, reason = day['off'], day['close'], 'sl'; break
            if day['off'] - 1 >= max_hold:
                exit_off, exit_price, reason = day['off'], day['close'], 'timeout'; break
        if exit_off is None:
            last = hold[-1]; exit_off, exit_price, reason = last['off'], last['close'], 'timeout'
        trades.append({'ret': ((exit_price - buy) / buy) * 100, 'hold': exit_off - 1, 'reason': reason})
    return trades


def test_trailing_stop(pool, tp_min, trail_pct, max_hold=10, strat_fn=None):
    if strat_fn: pool = [v for v in pool if strat_fn(v)]
    trades = []
    for v in pool:
        buy = v['buy_price']; hold = v['hold_days']
        peak_ret = -999; exit_off = None; exit_price = None; reason = None
        for i, day in enumerate(hold):
            if day['close'] <= 0: continue
            ret = ((day['close'] - buy) / buy) * 100
            if ret > peak_ret: peak_ret = ret
            if i == 0: continue
            if peak_ret >= tp_min and i > 0:
                drawdown = peak_ret - ret
                if drawdown >= trail_pct:
                    exit_off, exit_price, reason = day['off'], day['close'], 'trailing'; break
            if day['off'] - 1 >= max_hold and exit_off is None:
                exit_off, exit_price, reason = day['off'], day['close'], 'timeout'
        if exit_off is None:
            last = hold[-1]; exit_off, exit_price, reason = last['off'], last['close'], 'timeout'
        trades.append({'ret': ((exit_price - buy) / buy) * 100, 'hold': exit_off - 1, 'reason': reason})
    return trades


# ========== 策略定义 ==========

strategies = {
    # --- 窄幅整理族 ---
    '窄幅(range7<5)': lambda v: v['range7'] < 5,

    # --- 低波动族 ---
    '低波动(std7<1)': lambda v: v['std7'] < 1,

    # --- 双因子族 ---
    'pre3<=-2+mom10<=0+vol5<=0.8': lambda v: v['pre3'] <= -2 and v['mom10'] <= 0 and v['vol_ratio5'] <= 0.8,
    'pre3<=-1+mom10<=0+vol5<=0.8': lambda v: v['pre3'] <= -1 and v['mom10'] <= 0 and v['vol_ratio5'] <= 0.8,
    'pre3<=2+mom10<=0+vol5<=0.8': lambda v: v['pre3'] <= 2 and v['mom10'] <= 0 and v['vol_ratio5'] <= 0.8,
    'pre3<=2+mom10<=0+vol5<=0.7': lambda v: v['pre3'] <= 2 and v['mom10'] <= 0 and v['vol_ratio5'] <= 0.7,

    # --- 三因子+rc ---
    'pre3<=-1+mom10<=0+vol5<=0.8+rc>0': lambda v: v['pre3'] <= -1 and v['mom10'] <= 0 and v['vol_ratio5'] <= 0.8 and v['rc'] > 0,
    'pre3<=2+mom10<=0+vol5<=0.8+rc>0': lambda v: v['pre3'] <= 2 and v['mom10'] <= 0 and v['vol_ratio5'] <= 0.8 and v['rc'] > 0,

    # --- 区间底部 ---
    '区间底部+rc>0': lambda v: v['pos_in_range7'] < 30 and v['rc'] > 0,
    '区间底部+缩量': lambda v: v['pos_in_range7'] < 30 and v['vol_ratio5'] < 0.8,

    # --- 基线 ---
    'B1(pre3<=2+mom10<5+rc>0+vol<0.8)': lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['vol_ratio5'] < 0.8,
    'S1(pre3<=2+mom10<5+rc>0)': lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0,
}


def main():
    cache = BacktestCache()
    print("加载数据...", flush=True)
    pool = load_pool(cache)
    print(f"  总样本: {len(pool)}")

    # ========== 1) 跨 limit 稳定性 ==========
    print("\n" + "=" * 120)
    print("策略稳定性: 跨 limit 对比 (D+1买→D+9收盘)")
    print("=" * 120)

    print(f"\n  {'策略':<50} {'limit=100 n':>9} {'limit=100 sh':>9} {'limit=200 n':>9} {'limit=200 sh':>9} {'全量 n':>8} {'全量 sh':>8}")
    print("  " + "-" * 110)

    for name, fn in strategies.items():
        results = []
        for limit in [100, 200, 0]:
            sample = pool[:limit] if limit else pool
            triggered = [v for v in sample if fn(v)]
            if len(triggered) < 5:
                results.append((0, 0.0))
                continue
            rets = []
            for v in triggered:
                # D+9 sell
                d9 = None
                for d in v['hold_days']:
                    if d['off'] == 8:
                        d9 = d; break
                if d9 and d9['close'] > 0:
                    rets.append(((d9['close'] - v['buy_price']) / v['buy_price']) * 100)
                else:
                    rets.append(0)
            n = len(rets)
            avg = sum(rets)/n
            std = (sum((x-avg)**2 for x in rets)/n)**0.5
            sh = avg/std if std > 0 else 0
            results.append((n, sh))

        name_short = name[:48]
        l100n, l100sh = results[0]
        l200n, l200sh = results[1]
        fulln, fullsh = results[2]
        print(f"  {name_short:<50} {l100n:>6} {l100sh:>+8.2f} {l200n:>6} {l200sh:>+8.2f} {fulln:>6} {fullsh:>+8.2f}")

    # ========== 2) D+9 固定窗口多策略对比 ==========
    print("\n" + "=" * 120)
    print("D+1开盘→D+9收盘 固定窗口多策略对比 (limit=全量)")
    print("=" * 120)

    print(f"\n  {'策略':<50} {'样本':>4} {'平均':>7} {'中位':>7} {'胜率':>6} {'标准差':>7} {'夏普':>6}")
    print("  " + "-" * 100)

    for name, fn in strategies.items():
        triggered = [v for v in pool if fn(v)]
        n = len(triggered)
        if n < 5:
            print(f"  {name:<50} {n:>4} (太少)")
            continue
        rets = []
        for v in triggered:
            d9 = None
            for d in v['hold_days']:
                if d['off'] == 8:
                    d9 = d; break
            if d9 and d9['close'] > 0:
                rets.append(((d9['close'] - v['buy_price']) / v['buy_price']) * 100)
            else:
                rets.append(0)
        s = sorted(rets)
        avg = sum(s)/n
        win = sum(1 for x in s if x > 0)/n*100
        std = (sum((x-avg)**2 for x in s)/n)**0.5
        sh = avg/std if std > 0 else 0
        star = '★' if sh > 0.4 and n >= 15 else ' '
        print(f"  {star} {name:<48} {n:>4} {avg:>+6.2f}% {s[n//2]:>+6.2f}% {win:>5.1f}% {std:>6.2f}% {sh:>+5.2f}")

    # ========== 3) 动态退出 TP/SL 扫描 ==========
    print("\n" + "=" * 120)
    print("动态退出 TP/SL 扫描")
    print("=" * 120)

    # 重点测试高夏普但样本少的策略
    key_strategies = {
        '窄幅(range7<5)': strategies['窄幅(range7<5)'],
        'pre3<=-2+mom10<=0+vol5<=0.8': strategies['pre3<=-2+mom10<=0+vol5<=0.8'],
        'pre3<=-1+mom10<=0+vol5<=0.8': strategies['pre3<=-1+mom10<=0+vol5<=0.8'],
        'pre3<=2+mom10<=0+vol5<=0.8': strategies['pre3<=2+mom10<=0+vol5<=0.8'],
        'pre3<=2+mom10<=0+vol5<=0.8+rc>0': strategies['pre3<=2+mom10<=0+vol5<=0.8+rc>0'],
        'B1': strategies['B1(pre3<=2+mom10<5+rc>0+vol<0.8)'],
    }

    for sname, sfn in key_strategies.items():
        triggered = [v for v in pool if sfn(v)]
        if len(triggered) < 5: continue

        print(f"\n  {sname} (n={len(triggered)}):")
        print(f"    {'退出策略':<25} {'样本':>4} {'平均':>7} {'中位':>7} {'胜率':>6} {'持有':>5} {'夏普':>6} {'年化':>8}")

        configs = [
            ('固定D+9', 99, 99, 8),
            ('TP3/SL3', 3, 3, 10),
            ('TP4/SL4', 4, 4, 10),
            ('TP5/SL5', 5, 5, 10),
            ('TP3/SL5', 3, 5, 10),
            ('TP5/SL3', 5, 3, 10),
            ('trailing(盈4回2)', None, None, 10),  # special
        ]

        for cfg in configs:
            if cfg[0].startswith('trailing'):
                trades = test_trailing_stop(pool, 4, 2, max_hold=cfg[5] if len(cfg) > 5 else 10, strat_fn=sfn)
            else:
                tp, sl, mh = cfg[1], cfg[2], cfg[3]
                trades = test_fixed_tp_sl(pool, tp, sl, max_hold=mh, strat_fn=sfn)
            st = calc(trades)
            if not st or st['n'] < 5: continue
            eff = st['avg'] / st['avg_hold'] * 245 if st['avg_hold'] > 0 else 0
            reasons = {}
            for t in trades:
                reasons[t['reason']] = reasons.get(t['reason'], 0) + 1
            reason_str = ', '.join(f'{k}({v})' for k, v in sorted(reasons.items()))
            print(f"    {cfg[0]:<25} {st['n']:>4} {st['avg']:>+6.2f}% {st['med']:>+6.2f}% {st['win']:>5.1f}% {st['avg_hold']:>4.1f}d {st['sharpe']:>+5.2f} {eff:>+7.1f}%")
            # print(f"      退出原因: {reason_str}")

    # ========== 4) 寻找最大样本 + 合理夏普 ==========
    print("\n" + "=" * 120)
    print("样本-夏普曲线: 放宽条件找更多样本")
    print("=" * 120)

    # 以 pre3≤X+mom10≤Y+vol5≤Z 为主线
    print(f"\n  pre3≤X + mom10≤Y + vol5≤0.8 (D+5, D+9):")
    print(f"  {'X':>3} {'Y':>3} {'D+5 n':>6} {'D+5 sh':>7} {'D+9 n':>6} {'D+9 sh':>7}")
    print("  " + "-" * 40)

    for px in [-3, -2, -1, 0, 1, 2, 3]:
        for my in [-2, -1, 0, 1, 2]:
            fn = lambda v, p=px, m=my: v['pre3'] <= p and v['mom10'] <= m and v['vol_ratio5'] <= 0.8
            triggered = [v for v in pool if fn(v)]
            if len(triggered) < 3: continue

            for wlabel, woff in [('d5', 4), ('d9', 8)]:
                rets = []
                for v in triggered:
                    for d in v['hold_days']:
                        if d['off'] == woff:
                            rets.append(((d['close'] - v['buy_price']) / v['buy_price']) * 100)
                            break
                if not rets:
                    print(f"  ", end='')
                    continue
                n = len(rets)
                avg = sum(rets)/n
                std = (sum((x-avg)**2 for x in rets)/n)**0.5
                sh = avg/std if std > 0 else 0
                if wlabel == 'd5':
                    print(f"  {px:>3} {my:>3} {n:>6} {sh:>+7.2f}", end='')
                else:
                    print(f" {n:>6} {sh:>+7.2f}")
            print()

    # ========== 5) 按年份分组稳定性 ==========
    print("\n" + "=" * 120)
    print("按年份分组 (Top 策略)")
    print("=" * 120)

    top_strategies = {
        'pre3<=-2+mom10<=0+vol5<=0.8': strategies['pre3<=-2+mom10<=0+vol5<=0.8'],
        'pre3<=2+mom10<=0+vol5<=0.8': strategies['pre3<=2+mom10<=0+vol5<=0.8'],
        '窄幅(range7<5)': strategies['窄幅(range7<5)'],
        'B1': strategies['B1(pre3<=2+mom10<5+rc>0+vol<0.8)'],
    }

    for year in ['2023', '2024', '2025', '2026']:
        year_pool = [v for v in pool if v['anchor'].startswith(year)]
        if len(year_pool) < 5: continue

        print(f"\n  {year}年 (n={len(year_pool)}):")
        print(f"    {'策略':<45} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
        print("    " + "-" * 75)

        for sname, sfn in top_strategies.items():
            triggered = [v for v in year_pool if sfn(v)]
            n = len(triggered)
            if n < 3:
                print(f"    {sname:<45} {n:>4} (太少)")
                continue
            rets = []
            for v in triggered:
                for d in v['hold_days']:
                    if d['off'] == 8:
                        rets.append(((d['close'] - v['buy_price']) / v['buy_price']) * 100)
                        break
            if not rets: continue
            n = len(rets)
            avg = sum(rets)/n
            win = sum(1 for x in rets if x > 0)/n*100
            std = (sum((x-avg)**2 for x in rets)/n)**0.5
            sh = avg/std if std > 0 else 0
            print(f"    {sname:<45} {n:>4} {avg:>+6.2f}% {win:>5.1f}% {sh:>+5.2f}")


if __name__ == '__main__':
    main()
