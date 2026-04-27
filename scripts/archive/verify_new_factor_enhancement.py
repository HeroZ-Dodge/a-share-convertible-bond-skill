#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新因子增强稳定性验证 — 跨 limit 测试

验证: B2 + 新因子在不同limit下的夏普稳定性
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


def load_samples(cache):
    today_str = datetime.now().strftime('%Y-%m-%d')
    bonds = cache.get_jisilu_bonds(phase='注册', limit=0)
    samples = []

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
        if reg_close <= 0 or ri < 30: continue

        closes = [prices[sd[i]]['close'] for i in range(ri + 1)]
        vols = [prices[sd[i]].get('volume', 0) for i in range(ri + 1)]
        n = len(closes)

        pre3 = ((reg_close - prices[sd[ri-3]]['close']) / prices[sd[ri-3]]['close'] * 100) if ri >= 3 else 0
        rc = ((reg_close - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri > 0 else 0
        mom10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0

        vol_now = reg.get('volume', 0)
        vol_avg5 = 0
        if ri >= 5:
            vlist = [prices[sd[ri-k]].get('volume',0) for k in range(1,6) if prices[sd[ri-k]].get('volume',0)>0]
            if vlist: vol_avg5 = sum(vlist)/len(vlist)
        vol_ratio5 = (vol_now / vol_avg5) if vol_avg5 > 0 else 1

        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20 if n >= 20 else 0
        ma_alignment = 1 if ma5 > ma20 and ma20 > 0 else (-1 if ma5 < ma20 and ma20 > 0 else 0)

        # 量价相关
        def corr(xv, yv):
            nc = len(xv)
            if nc < 3: return 0
            mx = sum(xv)/nc; my = sum(yv)/nc
            num = sum((a-mx)*(b-my) for a,b in zip(xv,yv))
            dx = sum((a-mx)**2 for a in xv)**0.5
            dy = sum((b-my)**2 for b in yv)**0.5
            if dx==0 or dy==0: return 0
            return num/(dx*dy)

        pc = []; vl = []
        for i in range(max(2, n-10), n):
            if closes[i-1] > 0:
                pc.append((closes[i]-closes[i-1])/closes[i-1]*100)
                vl.append(vols[i] if vols[i]>0 else 0)
        vol_price_corr = corr(pc, vl) if len(pc) >= 3 else 0

        # 价量背离
        price_5d = ((closes[-1]-closes[-5])/closes[-5]*100) if n>=5 and closes[-5]>0 else 0
        vol_5d = ((sum(vols[-3:])/3 - sum(vols[-5:-3])/2)) if n>=5 else 0
        avg_vol_5 = sum(vols[-5:])/5 if n>=5 else 0
        vol_5d_pct = (vol_5d/avg_vol_5*100) if avg_vol_5>0 else 0
        divergence = 0
        if price_5d<0 and vol_5d_pct<-10: divergence=1
        elif price_5d>0 and vol_5d_pct>10: divergence=2

        # 斜率
        def linear_slope(values):
            nv = len(values)
            if nv < 2: return 0
            xm = (nv-1)/2; ym = sum(values)/nv
            num = sum((i-xm)*(v-ym) for i,v in enumerate(values))
            den = sum((i-xm)**2 for i in range(nv))
            return num/den if den>0 else 0

        slope_5 = linear_slope(closes[-5:])/closes[-1]*100 if closes[-1]>0 else 0
        slope_10 = linear_slope(closes[-10:])/closes[-1]*100 if closes[-1]>0 else 0
        slope_change = slope_5 - slope_10

        # Buy/sell
        buy_idx = ri + 1
        buy_price = None
        if buy_idx < len(sd) and sd[buy_idx] <= today_str:
            buy_price = prices[sd[buy_idx]].get('open', 0)
        if not buy_price or buy_price <= 0: continue

        d9_idx = ri + 8
        ret_d9 = None
        if d9_idx < len(sd) and sd[d9_idx] <= today_str:
            ret_d9 = ((prices[sd[d9_idx]]['close'] - buy_price) / buy_price * 100)

        samples.append({
            'code': sc, 'anchor': anchor, 'buy_price': buy_price, 'ret_d9': ret_d9,
            'pre3': pre3, 'mom10': mom10, 'rc': rc, 'vol_ratio5': vol_ratio5,
            'ma_alignment': ma_alignment, 'vol_price_corr': vol_price_corr,
            'divergence': divergence, 'slope_change': slope_change,
        })

    samples.sort(key=lambda x: x['anchor'], reverse=True)
    return samples


def stats_fn(values, min_n=5):
    if len(values) < min_n: return None
    s = sorted(values); n = len(s)
    avg = sum(s)/n; std = (sum((x-avg)**2 for x in s)/n)**0.5
    sh = avg/std if std>0 else 0; win = sum(1 for x in s if x>0)/n*100
    return {'n':n, 'avg':avg, 'win':win, 'sharpe':sh}


def main():
    cache = BacktestCache()
    print("加载样本...", flush=True)
    samples = load_samples(cache)
    print(f"  总样本: {len(samples)}")

    def b2(s): return s['pre3']<=-2 and s['mom10']<=-1 and s['vol_ratio5']<=0.8
    def b2r(s): return s['pre3']<=2 and s['mom10']<=-1 and s['vol_ratio5']<=0.8

    # 增强因子
    enhancers = {
        '+ma==1':        lambda s: s['ma_alignment']==1,
        '+vol_corr>0.3': lambda s: s['vol_price_corr']>0.3,
        '+divergence==1':lambda s: s['divergence']==1,
        '+slope_chg>0':  lambda s: s['slope_change']>0,
        # 组合增强
        '+ma==1+vol_corr': lambda s: s['ma_alignment']==1 and s['vol_price_corr']>0.3,
    }

    print("\n" + "=" * 120)
    print("B2 跨 limit 稳定性验证")
    print("=" * 120)

    print(f"\n  {'策略':<40} {'L=100':>10} {'L=200':>10} {'全量':>10} {'趋势'}")
    print("  " + "-" * 75)

    for enh_name, enh_fn in enhancers.items():
        label = f"B2{enh_name}"
        for limit in [100, 200, 0]:
            pool = samples[:limit] if limit else samples
            triggered = [s for s in pool if b2(s) and enh_fn(s) and s['ret_d9'] is not None]
            if not triggered:
                print(f"  {label:<40}", end='')
                break
            rets = [s['ret_d9'] for s in triggered]
            st = stats_fn(rets, min_n=3)
            if st:
                print(f"  {label:<40}", end='')
                print(f" sh={st['sharpe']:+.2f}(n={st['n']})  ", end='')

        # Print all at once for readability
        print()

    # Redo in cleaner format
    print("\n  夏普 (n=样本量):")
    print(f"  {'策略':<35} {'limit=100':>16} {'limit=200':>16} {'全量':>16}")
    print("  " + "-" * 70)

    for enh_name, enh_fn in enhancers.items():
        results = []
        for limit in [100, 200, 0]:
            pool = samples[:limit] if limit else samples
            triggered = [s for s in pool if b2(s) and enh_fn(s) and s['ret_d9'] is not None]
            rets = [s['ret_d9'] for s in triggered]
            st = stats_fn(rets, min_n=3)
            results.append(st)

        label = f"B2{enh_name}"
        parts = []
        for st in results:
            if st:
                parts.append(f"sh={st['sharpe']:+.2f}(n={st['n']})")
            else:
                parts.append("--")
        print(f"  {label:<35} {parts[0]:>16} {parts[1]:>16} {parts[2]:>16}")

    # B2 自身为基线
    print("\n  基线 B2:")
    for limit in [100, 200, 0]:
        pool = samples[:limit] if limit else samples
        triggered = [s for s in pool if b2(s) and s['ret_d9'] is not None]
        rets = [s['ret_d9'] for s in triggered]
        st = stats_fn(rets, min_n=3)
        if st:
            print(f"    limit={'ALL' if limit==0 else limit}: sh={st['sharpe']:+.2f}(n={st['n']})")

    print("\n" + "=" * 120)
    print("B2-relaxed 跨 limit 稳定性验证")
    print("=" * 120)

    print(f"\n  {'策略':<35} {'limit=100':>16} {'limit=200':>16} {'全量':>16}")
    print("  " + "-" * 70)

    for enh_name, enh_fn in enhancers.items():
        results = []
        for limit in [100, 200, 0]:
            pool = samples[:limit] if limit else samples
            triggered = [s for s in pool if b2r(s) and enh_fn(s) and s['ret_d9'] is not None]
            rets = [s['ret_d9'] for s in triggered]
            st = stats_fn(rets, min_n=3)
            results.append(st)

        label = f"B2R{enh_name}"
        parts = []
        for st in results:
            if st:
                parts.append(f"sh={st['sharpe']:+.2f}(n={st['n']})")
            else:
                parts.append("--")
        print(f"  {label:<35} {parts[0]:>16} {parts[1]:>16} {parts[2]:>16}")

    # B2R 基线
    print("\n  基线 B2R:")
    for limit in [100, 200, 0]:
        pool = samples[:limit] if limit else samples
        triggered = [s for s in pool if b2r(s) and s['ret_d9'] is not None]
        rets = [s['ret_d9'] for s in triggered]
        st = stats_fn(rets, min_n=3)
        if st:
            print(f"    limit={'ALL' if limit==0 else limit}: sh={st['sharpe']:+.2f}(n={st['n']})")

    # ========== 深入分析 ==========
    print("\n" + "=" * 120)
    print("增强因子效果分析")
    print("=" * 120)

    # B2 全量, 各增强因子的详细对比
    b2_all = [s for s in samples if b2(s) and s['ret_d9'] is not None]
    b2_st = stats_fn([s['ret_d9'] for s in b2_all])

    print(f"\n  B2 全量基线: n={b2_st['n']} avg={b2_st['avg']:+.2f}% win={b2_st['win']:.1f}% sh={b2_st['sharpe']:+.2f}")
    print(f"    标准差: {b2_st['std']:.2f}%")

    for enh_name, enh_fn in enhancers.items():
        subset = [s for s in b2_all if enh_fn(s)]
        if len(subset) < 5: continue
        rets = [s['ret_d9'] for s in subset]
        st = stats_fn(rets)
        other = [s for s in b2_all if not enh_fn(s)]
        other_st = stats_fn([s['ret_d9'] for s in other])

        print(f"\n  B2{enh_name}: n={st['n']} avg={st['avg']:+.2f}% win={st['win']:.1f}% sh={st['sharpe']:+.2f} std={st['std']:.2f}%")
        print(f"  B2(no{enh_name}): n={other_st['n'] if other_st else '0'} avg={other_st['avg']:+.2f}% sh={other_st['sharpe']:+.2f} std={other_st['std']:.2f}%")


if __name__ == '__main__':
    main()
