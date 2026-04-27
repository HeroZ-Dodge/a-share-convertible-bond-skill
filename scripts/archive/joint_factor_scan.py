#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新旧因子联合扫描 — 新因子 × 已知有效因子

目标: 用新因子过滤/增强已有策略(B2等), 找到更高夏普组合
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
        opens = [prices[sd[i]].get('open', closes[i]) for i in range(ri + 1)]
        highs = [prices[sd[i]].get('high', closes[i]) for i in range(ri + 1)]
        lows = [prices[sd[i]].get('low', closes[i]) for i in range(ri + 1)]
        vols = [prices[sd[i]].get('volume', 0) for i in range(ri + 1)]
        n = len(closes)

        reg_open = reg.get('open', 0) or reg_close

        # ========== 已有有效因子 ==========
        pre3  = ((reg_close - prices[sd[ri-3]]['close']) / prices[sd[ri-3]]['close'] * 100) if ri >= 3 else 0
        pre7  = ((reg_close - prices[sd[ri-7]]['close']) / prices[sd[ri-7]]['close'] * 100) if ri >= 7 else 0
        rc = ((reg_close - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri > 0 else 0
        mom10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0

        vol_now = reg.get('volume', 0)
        vol_avg5 = 0
        if ri >= 5:
            vlist = [prices[sd[ri-k]].get('volume',0) for k in range(1,6) if prices[sd[ri-k]].get('volume',0)>0]
            if vlist: vol_avg5 = sum(vlist)/len(vlist)
        vol_ratio5 = (vol_now / vol_avg5) if vol_avg5 > 0 else 1

        # ========== 新因子 (关键) ==========
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10 if n >= 10 else 0
        ma20 = sum(closes[-20:]) / 20 if n >= 20 else 0

        # 均线排列
        ma_alignment = 0
        if ma10 > 0 and ma20 > 0:
            if ma5 > ma10 > ma20: ma_alignment = 1
            elif ma5 < ma10 < ma20: ma_alignment = -1

        ma_spread_5_20 = ((ma5 - ma20) / ma20 * 100) if ma20 > 0 else 0
        price_vs_ma5 = ((reg_close - ma5) / ma5 * 100) if ma5 > 0 else 0
        price_vs_ma20 = ((reg_close - ma20) / ma20 * 100) if ma20 > 0 else 0

        # 连阳/连阴
        daily_chgs = []
        for i in range(max(1, n - 10), n):
            if closes[i-1] > 0:
                daily_chgs.append((closes[i] - closes[i-1]) / closes[i-1] * 100)

        consec_down = 0
        for i in range(n - 1, 0, -1):
            if closes[i] < closes[i-1]:
                consec_down += 1
            else:
                break

        consec_up = 0
        for i in range(n - 1, 0, -1):
            if closes[i] > closes[i-1]:
                consec_up += 1
            else:
                break

        up_count_5 = sum(1 for c in daily_chgs[-5:] if c > 0) if len(daily_chgs) >= 5 else 0

        # 斜率
        def linear_slope(values):
            nv = len(values)
            if nv < 2: return 0
            xm = (nv - 1) / 2; ym = sum(values) / nv
            num = sum((i - xm) * (v - ym) for i, v in enumerate(values))
            den = sum((i - xm) ** 2 for i in range(nv))
            return num / den if den > 0 else 0

        slope_5 = linear_slope(closes[-5:]) / closes[-1] * 100 if closes[-1] > 0 else 0
        slope_10 = linear_slope(closes[-10:]) / closes[-1] * 100 if closes[-1] > 0 else 0
        slope_change = slope_5 - slope_10

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

        pc_10 = []; vl_10 = []
        for i in range(max(2, n-10), n):
            if closes[i-1] > 0:
                pc_10.append((closes[i]-closes[i-1])/closes[i-1]*100)
                vl_10.append(vols[i] if vols[i]>0 else 0)
        vol_price_corr = corr(pc_10, vl_10) if len(pc_10) >= 3 else 0

        # 价量背离
        price_5d = ((closes[-1]-closes[-5])/closes[-5]*100) if n>=5 and closes[-5]>0 else 0
        vol_5d = ((sum(vols[-3:])/3 - sum(vols[-5:-3])/2)) if n>=5 else 0
        avg_vol_5 = sum(vols[-5:])/5 if n>=5 else 0
        vol_5d_pct = (vol_5d/avg_vol_5*100) if avg_vol_5>0 else 0

        divergence = 0
        if price_5d>0 and vol_5d_pct<-10: divergence=-1
        elif price_5d<0 and vol_5d_pct<-10: divergence=1
        elif price_5d>0 and vol_5d_pct>10: divergence=2
        elif price_5d<0 and vol_5d_pct>10: divergence=-2

        # RSI
        gains_7 = [max(c,0) for c in daily_chgs[-7:]] if len(daily_chgs)>=7 else []
        losses_7 = [max(-c,0) for c in daily_chgs[-7:]] if len(daily_chgs)>=7 else []
        ag7 = sum(gains_7)/len(gains_7) if gains_7 else 0
        al7 = sum(losses_7)/len(losses_7) if losses_7 else 0
        rsi_7 = (100-100/(1+ag7/al7)) if al7>0 else 50

        # 布林带
        std_20 = 0
        if n >= 20:
            avg20 = sum(closes[-20:])/20
            std_20 = (sum((x-avg20)**2 for x in closes[-20:])/20)**0.5
        bollinger_pos = ((reg_close-(ma20-2*std_20))/(4*std_20)*100) if std_20>0 else 50

        # 52周位置
        high_250 = max(highs[-min(250,n):]) if n>0 else 0
        low_250 = min(lows[-min(250,n):]) if n>0 else 99999
        position_52w = ((reg_close-low_250)/(high_250-low_250)*100) if high_250>low_250 else 50

        # 波动率
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
        if ri >= 7:
            high7 = max(prices[sd[k]].get('high',0) for k in range(ri-7,ri+1))
            low7 = min(prices[sd[k]].get('low',99999) for k in range(ri-7,ri+1))
            range7 = ((high7-low7)/low7*100) if low7>0 else 0
        else:
            range7 = 0

        # D+1 buy
        buy_idx = ri + 1
        buy_price = None
        if buy_idx < len(sd) and sd[buy_idx] <= today_str:
            buy_price = prices[sd[buy_idx]].get('open', 0)
        if not buy_price or buy_price <= 0: continue

        # D+9 sell
        d9_idx = ri + 8
        ret_d9 = None
        if d9_idx < len(sd) and sd[d9_idx] <= today_str:
            ret_d9 = ((prices[sd[d9_idx]]['close'] - buy_price) / buy_price * 100)

        # D+5 sell
        d5_idx = ri + 4
        ret_d5 = None
        if d5_idx < len(sd) and sd[d5_idx] <= today_str:
            ret_d5 = ((prices[sd[d5_idx]]['close'] - buy_price) / buy_price * 100)

        samples.append({
            'code': sc, 'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'buy_price': buy_price, 'ret_d9': ret_d9, 'ret_d5': ret_d5,
            # Old factors
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
            'vol_ratio5': vol_ratio5,
            'std7': std7, 'range7': range7,
            # New factors
            'ma_alignment': ma_alignment,
            'ma_spread_5_20': ma_spread_5_20,
            'price_vs_ma5': price_vs_ma5,
            'price_vs_ma20': price_vs_ma20,
            'consec_down': consec_down, 'consec_up': consec_up,
            'up_count_5': up_count_5,
            'slope_5': slope_5, 'slope_10': slope_10, 'slope_change': slope_change,
            'vol_price_corr': vol_price_corr,
            'divergence': divergence, 'price_5d': price_5d, 'vol_5d_pct': vol_5d_pct,
            'rsi_7': rsi_7, 'bollinger_pos': bollinger_pos,
            'position_52w': position_52w,
        })

    samples.sort(key=lambda x: x['anchor'], reverse=True)
    return samples


def stats_fn(values, min_n=15):
    if len(values) < min_n: return None
    s = sorted(values); n = len(s)
    avg = sum(s)/n; std = (sum((x-avg)**2 for x in s)/n)**0.5
    sh = avg/std if std>0 else 0; win = sum(1 for x in s if x>0)/n*100
    return {'n':n, 'avg':avg, 'win':win, 'std':std, 'sharpe':sh}


def main():
    cache = BacktestCache()
    print("加载样本...", flush=True)
    samples = load_samples(cache)
    print(f"  总样本: {len(samples)}")

    # ========== 1) B2 基线 ==========
    def b2(s): return s['pre3']<=-2 and s['mom10']<=-1 and s['vol_ratio5']<=0.8
    def b2r(s): return s['pre3']<=2 and s['mom10']<=-1 and s['vol_ratio5']<=0.8
    def b1(s): return s['pre3']<=2 and s['mom10']<5 and s['rc']>0 and s['vol_ratio5']<0.8

    print("\n" + "=" * 110)
    print("B2 基线 + 新因子增强 (D+9窗口)")
    print("=" * 110)

    new_factor_filters = [
        ('ma_alignment==1 (多头排列)', lambda s: s['ma_alignment']==1),
        ('ma_alignment==-1 (空头排列)', lambda s: s['ma_alignment']==-1),
        ('ma_spread_5_20>1', lambda s: s['ma_spread_5_20']>1),
        ('price_vs_ma5<0 (回踩MA5)', lambda s: s['price_vs_ma5']<0),
        ('price_vs_ma20<0 (回踩MA20)', lambda s: s['price_vs_ma20']<0),
        ('price_vs_ma5<0+ma_alignment==1 (多头回踩)', lambda s: s['price_vs_ma5']<0 and s['ma_alignment']==1),
        ('consec_down>=2 (连跌≥2)', lambda s: s['consec_down']>=2),
        ('consec_down>=3 (连跌≥3)', lambda s: s['consec_down']>=3),
        ('up_count_5<=1 (近5天跌≥4天)', lambda s: s['up_count_5']<=1),
        ('slope_5<0 (短期跌)', lambda s: s['slope_5']<0),
        ('slope_change>0 (减速跌/止跌)', lambda s: s['slope_change']>0),
        ('slope_change<0 (加速跌)', lambda s: s['slope_change']<0),
        ('divergence==1 (价跌量缩)', lambda s: s['divergence']==1),
        ('vol_price_corr>0.3 (量价正相关)', lambda s: s['vol_price_corr']>0.3),
        ('RSI<40 (超卖)', lambda s: s['rsi_7']<40),
        ('bollinger<50 (下半区)', lambda s: s['bollinger_pos']<50),
        ('position_52w<50 (52周低位)', lambda s: s['position_52w']<50),
        ('std7<1.5 (低波动)', lambda s: s['std7']<1.5),
        ('range7<10 (窄幅)', lambda s: s['range7']<10),
    ]

    for base_name, base_fn in [('B2 (pre3≤-2+mom10≤-1+vol≤0.8)', b2),
                                ('B2-relaxed (pre3≤2+mom10≤-1+vol≤0.8)', b2r),
                                ('B1 (pre3≤2+mom10<5+rc>0+vol<0.8)', b1)]:
        base_triggered = [s for s in samples if base_fn(s) and s['ret_d9'] is not None]
        base_st = stats_fn([s['ret_d9'] for s in base_triggered], min_n=5)
        if not base_st: continue

        print(f"\n  {base_name} (n={base_st['n']}, sh={base_st['sharpe']:+.2f}):")
        print(f"    {'新因子条件':<40} {'n':>4} {'平均':>7} {'胜率':>6} {'夏普':>6} {'Δ夏普':>6}")
        print("    " + "-" * 75)

        for nf_label, nf_fn in new_factor_filters:
            subset = [s for s in base_triggered if nf_fn(s)]
            if len(subset) < 5: continue
            rets = [s['ret_d9'] for s in subset]
            st = stats_fn(rets, min_n=5)
            if st:
                delta = st['sharpe'] - base_st['sharpe']
                marker = '★' if st['sharpe'] > base_st['sharpe'] + 0.1 and st['n'] >= 8 else ' '
                print(f"    {marker} {nf_label:<38} {st['n']:>4} {st['avg']:>+6.2f}% {st['win']:>5.1f}% {st['sharpe']:>+5.2f} {delta:>+5.2f}")

    # ========== 2) 三因子组合: B2 + 1新因子 + 1旧因子 ==========
    print("\n" + "=" * 110)
    print("三因子组合: B2 + 旧因子 + 新因子 (D+9)")
    print("=" * 110)

    # 先算B2触发样本
    b2_triggered = [s for s in samples if b2(s) and s['ret_d9'] is not None]

    old_filters = [
        ('pre3≤-3', lambda s: s['pre3']<=-3),
        ('pre3≤-2', lambda s: s['pre3']<=-2),
        ('rc>0', lambda s: s['rc']>0),
        ('rc>1', lambda s: s['rc']>1),
        ('std7<1', lambda s: s['std7']<1),
        ('range7<8', lambda s: s['range7']<8),
    ]

    combo_results = []
    for of_label, of_fn in old_filters:
        of_triggered = [s for s in b2_triggered if of_fn(s)]
        if len(of_triggered) < 5: continue

        for nf_label, nf_fn in new_factor_filters:
            subset = [s for s in of_triggered if nf_fn(s)]
            if len(subset) < 5: continue
            rets = [s['ret_d9'] for s in subset]
            st = stats_fn(rets, min_n=5)
            if st and st['sharpe'] > 0.3:
                combo_results.append((f"B2+{of_label}+{nf_label}", st))

    combo_results.sort(key=lambda x: x[1]['sharpe'], reverse=True)

    print(f"\n  {'组合条件':<65} {'n':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 80)

    seen = set()
    for label, st in combo_results[:25]:
        key = label.split('+')[-2]  # 看倒数第二个因子(去重)
        if key in seen: continue
        seen.add(key)
        star = '★' if st['sharpe'] > 0.5 and st['n'] >= 8 else ' '
        print(f"  {star} {label:<63} {st['n']:>4} {st['avg']:>+6.2f}% {st['win']:>5.1f}% {st['sharpe']:>+5.2f}")

    # ========== 3) 最强信号: 多头排列 + B2 ==========
    print("\n" + "=" * 110)
    print("深度分析: 多头排列 + B2")
    print("=" * 110)

    ma1_b2 = [s for s in samples if b2(s) and s['ma_alignment']==1 and s['ret_d9'] is not None]
    b2_only = [s for s in samples if b2(s) and s['ma_alignment']!=1 and s['ret_d9'] is not None]

    print(f"\n  B2 + 多头排列: n={len(ma1_b2)}")
    if ma1_b2:
        rets = [s['ret_d9'] for s in ma1_b2]
        st = stats_fn(rets, min_n=3)
        if st:
            print(f"    D+9: avg={st['avg']:+.2f}% win={st['win']:.1f}% sh={st['sharpe']:+.2f}")

    print(f"\n  B2 仅基线(无多头): n={len(b2_only)}")
    if b2_only:
        rets = [s['ret_d9'] for s in b2_only]
        st = stats_fn(rets, min_n=3)
        if st:
            print(f"    D+9: avg={st['avg']:+.2f}% win={st['win']:.1f}% sh={st['sharpe']:+.2f}")

    # 4) 新因子在不同年份的表现
    print("\n" + "=" * 110)
    print("按年份: B2 + 多头排列 vs B2 alone")
    print("=" * 110)

    for year in ['2023', '2024', '2025']:
        yr_b2 = [s for s in samples if b2(s) and s['anchor'].startswith(year) and s['ret_d9'] is not None]
        yr_b2_ma1 = [s for s in yr_b2 if s['ma_alignment']==1]

        print(f"\n  {year}年:")
        if yr_b2_ma1:
            rets = [s['ret_d9'] for s in yr_b2_ma1]
            st = stats_fn(rets, min_n=3)
            if st:
                print(f"    B2+多头: n={st['n']} avg={st['avg']:+.2f}% win={st['win']:.1f}% sh={st['sharpe']:+.2f}")
        if yr_b2:
            rets = [s['ret_d9'] for s in yr_b2]
            st = stats_fn(rets, min_n=3)
            if st:
                print(f"    B2 all:  n={st['n']} avg={st['avg']:+.2f}% win={st['win']:.1f}% sh={st['sharpe']:+.2f}")


if __name__ == '__main__':
    main()
