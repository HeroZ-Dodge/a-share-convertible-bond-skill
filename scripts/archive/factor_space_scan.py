#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略空间全面扫描 — 不预设策略，穷举搜索

买入: D+1开盘 (所有因子基于注册日收盘)
卖出: D+1~D+10, D+5收盘 (两个窗口)

因子维度:
  1. 价格动量 (pre1, pre3, pre5, pre7, pre10, mom5, mom10)
  2. 注册日K线 (rc, 振幅, 上下影线, 实体)
  3. 成交量 (vol_ratio5, vol_ratio10, vol_trend)
  4. 波动率 (range7_std, range3_std)
  5. 形态 (十字星/长影/突破等)

搜索方法:
  单因子阈值扫描
  双因子组合扫描
  三因子组合扫描
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


def load_features(cache):
    """加载所有样本的特征数据"""
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
        reg_close = prices[sd[ri]]['close']
        if reg_close <= 0 or ri < 15: continue

        reg = prices[sd[ri]]
        reg_open = reg.get('open', 0) or reg_close

        # ========== 价格动量 ==========
        pre1  = ((reg_close - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri >= 1 else 0
        pre3  = ((reg_close - prices[sd[ri-3]]['close']) / prices[sd[ri-3]]['close'] * 100) if ri >= 3 else 0
        pre5  = ((reg_close - prices[sd[ri-5]]['close']) / prices[sd[ri-5]]['close'] * 100) if ri >= 5 else 0
        pre7  = ((reg_close - prices[sd[ri-7]]['close']) / prices[sd[ri-7]]['close'] * 100) if ri >= 7 else 0
        pre10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0

        mom5  = ((reg_close - prices[sd[ri-5]]['close']) / prices[sd[ri-5]]['close'] * 100) if ri >= 5 else 0
        mom10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0

        # ========== 注册日K线形态 ==========
        rc = ((reg_close - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri > 0 else 0
        body = ((reg_close - reg_open) / reg_open * 100) if reg_open > 0 else 0
        high = reg.get('high', reg_close)
        low = reg.get('low', reg_close)
        amplitude = ((high - low) / reg_open * 100) if reg_open > 0 else 0
        upper_shadow = ((high - max(reg_open, reg_close)) / reg_open * 100) if reg_open > 0 else 0
        lower_shadow = ((min(reg_open, reg_close) - low) / reg_open * 100) if reg_open > 0 else 0
        real_body = abs(body)  # 实体绝对值

        # ========== 成交量 ==========
        vol_now = reg.get('volume', 0)
        vol_avg5 = 0
        vol_avg10 = 0
        vol_trend = 0  # 近期放量还是缩量趋势
        if ri >= 10:
            vols = [prices[sd[ri-k]].get('volume',0) for k in range(1,11) if prices[sd[ri-k]].get('volume',0)>0]
            if vols:
                vol_avg10 = sum(vols)/len(vols)
                vol_avg5 = sum(vols[:5])/5
                if vol_avg5 > 0 and vol_avg10 > 0:
                    vol_trend = ((vol_avg5 - vol_avg10) / vol_avg10 * 100)
        vol_ratio5 = (vol_now / vol_avg5) if vol_avg5 > 0 else 1
        vol_ratio10 = (vol_now / vol_avg10) if vol_avg10 > 0 else 1

        # ========== 波动率 ==========
        # 7天内每日涨跌幅标准差
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

        # 3天std
        daily_rets_3 = daily_rets_7[:3] if len(daily_rets_7) >= 3 else []
        std3 = 0
        if len(daily_rets_3) >= 2:
            avg = sum(daily_rets_3)/len(daily_rets_3)
            std3 = (sum((x-avg)**2 for x in daily_rets_3)/len(daily_rets_3))**0.5

        # ========== 价格区间 ==========
        high7 = 0
        low7 = 99999
        if ri >= 7:
            for k in range(ri-7, ri+1):
                h = prices[sd[k]].get('high', 0)
                l = prices[sd[k]].get('low', 99999)
                if h > high7: high7 = h
                if l < low7: low7 = l
        range7 = ((high7 - low7) / low7 * 100) if low7 > 0 else 0
        pos_in_range7 = ((reg_close - low7) / (high7 - low7) * 100) if high7 > low7 else 50  # 注册日在7天区间的位置

        # ========== 买入价 ==========
        buy_idx = ri + 1
        buy_price = None
        if buy_idx < len(sd) and sd[buy_idx] <= today_str:
            buy_price = prices[sd[buy_idx]].get('open', 0)
        if not buy_price or buy_price <= 0:
            continue

        # ========== 卖出价 ==========
        sell_d5_idx = ri + 5
        sell_d5 = None
        if sell_d5_idx < len(sd) and sd[sell_d5_idx] <= today_str:
            sell_d5 = prices[sd[sell_d5_idx]].get('close', 0)

        sell_d9_idx = ri + 9
        sell_d9 = None
        if sell_d9_idx < len(sd) and sd[sell_d9_idx] <= today_str:
            sell_d9 = prices[sd[sell_d9_idx]].get('close', 0)

        ret_d5 = ((sell_d5 - buy_price) / buy_price * 100) if sell_d5 and sell_d5 > 0 else None
        ret_d9 = ((sell_d9 - buy_price) / buy_price * 100) if sell_d9 and sell_d9 > 0 else None

        if ret_d5 is None and ret_d9 is None:
            continue

        samples.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            # 因子
            'pre1': pre1, 'pre3': pre3, 'pre5': pre5, 'pre7': pre7, 'pre10': pre10,
            'mom5': mom5, 'mom10': mom10,
            'rc': rc, 'body': body, 'amplitude': amplitude,
            'upper_shadow': upper_shadow, 'lower_shadow': lower_shadow,
            'real_body': real_body,
            'vol_ratio5': vol_ratio5, 'vol_ratio10': vol_ratio10, 'vol_trend': vol_trend,
            'std7': std7, 'std3': std3,
            'range7': range7, 'pos_in_range7': pos_in_range7,
            # 收益
            'ret_d5': ret_d5, 'ret_d9': ret_d9,
        })

    samples.sort(key=lambda x: x['anchor'], reverse=True)
    return samples


def stats():
    """返回统计函数"""
    def fn(values, min_n=15):
        if len(values) < min_n:
            return None
        s = sorted(values)
        n = len(s)
        avg = sum(s)/n
        std = (sum((x-avg)**2 for x in s)/n)**0.5
        sh = avg/std if std > 0 else 0
        win = sum(1 for x in s if x > 0)/n*100
        return {'n':n, 'avg':avg, 'win':win, 'std':std, 'sharpe':sh}
    return fn


stats_fn = stats()


def test_condition(samples, cond_fn, window='d5'):
    """测试一个条件"""
    ret_key = 'ret_d5' if window == 'd5' else 'ret_d9'
    rets = [s[ret_key] for s in samples if s[ret_key] is not None and cond_fn(s)]
    return stats_fn(rets)


def scan_single_factor(samples):
    """单因子阈值扫描"""
    factors = [
        ('pre3≤X', 'pre3', [-3, -2, -1, 0, 1, 2, 3, 5]),
        ('pre5≤X', 'pre5', [-3, -2, -1, 0, 1, 2, 3, 5]),
        ('pre7≤X', 'pre7', [-5, -3, -2, -1, 0, 1, 2, 3, 5]),
        ('pre10≤X', 'pre10', [-5, -3, -2, -1, 0, 1, 2, 3, 5]),
        ('mom5≤X', 'mom5', [-3, -2, -1, 0, 1, 2, 3, 5]),
        ('mom10≤X', 'mom10', [-5, -3, -2, -1, 0, 1, 2, 3, 5]),
        ('rc>X', 'rc', [-1, 0, 1, 2, 3]),
        ('body>X', 'body', [-1, 0, 1, 2]),
        ('amplitude<X', 'amplitude', [2, 3, 4, 5, 6, 8]),
        ('vol_ratio5<X', 'vol_ratio5', [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2]),
        ('vol_ratio10<X', 'vol_ratio10', [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2]),
        ('range7<X', 'range7', [3, 5, 8, 10, 15]),
        ('std7<X', 'std7', [1, 1.5, 2, 2.5, 3]),
        ('std3<X', 'std3', [0.5, 1, 1.5, 2, 3]),
        ('pos_in_range7<X', 'pos_in_range7', [30, 40, 50, 60, 70]),
        ('lower_shadow>X', 'lower_shadow', [0.3, 0.5, 0.8, 1, 2]),
        ('upper_shadow<X', 'upper_shadow', [0.3, 0.5, 0.8, 1, 1.5, 2]),
        ('real_body<X', 'real_body', [0.3, 0.5, 0.8, 1, 1.5, 2]),
        ('pre1≤X', 'pre1', [-2, -1, 0, 1, 2]),
        ('vol_trend>X', 'vol_trend', [-20, -10, 0, 10, 20]),
    ]

    results = []
    for label, factor, thresholds in factors:
        for th in thresholds:
            direction = '≤' if '≤' in label else ('>' if '>' in label else '<')

            if direction == '≤':
                fn = lambda s, f=factor, t=th: s[f] <= t
                desc = f"{label.replace('X', str(th))}"
            elif direction == '>':
                fn = lambda s, f=factor, t=th: s[f] > t
                desc = f"{label.replace('X', str(th))}"
            else:
                fn = lambda s, f=factor, t=th: s[f] < t
                desc = f"{label.replace('X', str(th))}"

            for window in ['d5', 'd9']:
                st = test_condition(samples, fn, window)
                if st and st['n'] >= 15:
                    results.append({
                        'desc': desc, 'window': window,
                        'sharpe': st['sharpe'], 'n': st['n'],
                        'avg': st['avg'], 'win': st['win'],
                    })

    results.sort(key=lambda x: x['sharpe'], reverse=True)
    return results


def scan_combo2(samples):
    """双因子组合扫描"""
    combos = []

    # 动量 + 成交量
    pre_vals = [(-3, 0), (-2, 0), (-2, 1), (-1, 0), (0, 0), (1, 0), (2, 0), (2, 1), (3, 0), (5, 0)]
    vol_vals = [0.6, 0.7, 0.8, 0.9, 1.0]

    for pre_t, mom_t in pre_vals:
        for vol_t in vol_vals:
            fn = lambda s, pt=pre_t, mt=mom_t, vt=vol_t: (
                s['pre3'] <= pt and s['mom10'] <= mt and s['vol_ratio5'] <= vt
            )
            for window in ['d5', 'd9']:
                st = test_condition(samples, fn, window)
                if st and st['n'] >= 15 and st['sharpe'] > 0.3:
                    combos.append({
                        'desc': f"pre3<={pre_t}+mom10<={mom_t}+vol5<={vol_t}",
                        'window': window, 'sharpe': st['sharpe'],
                        'n': st['n'], 'avg': st['avg'], 'win': st['win'],
                    })

    # 动量 + K线
    for pre_t, mom_t in pre_vals:
        for amp_t in [3, 4, 5, 6]:
            fn = lambda s, pt=pre_t, mt=mom_t, at=amp_t: (
                s['pre3'] <= pt and s['mom10'] <= mt and s['amplitude'] <= at
            )
            for window in ['d5', 'd9']:
                st = test_condition(samples, fn, window)
                if st and st['n'] >= 15 and st['sharpe'] > 0.3:
                    combos.append({
                        'desc': f"pre3<={pre_t}+mom10<={mom_t}+amp<={amp_t}",
                        'window': window, 'sharpe': st['sharpe'],
                        'n': st['n'], 'avg': st['avg'], 'win': st['win'],
                    })

    combos.sort(key=lambda x: x['sharpe'], reverse=True)
    return combos[:50]


def scan_combo3(samples):
    """三因子组合 — 重点组合"""
    combos = []

    # 动量 + 成交量 + K线形态
    for pre_t in [-3, -2, -1, 0, 1, 2, 3]:
        for mom_t in [-3, -2, -1, 0, 2, 3, 5]:
            for vol_t in [0.6, 0.7, 0.8, 0.9]:
                for rc_cond in ['>0', '>1']:
                    rc_t = 0 if rc_cond == '>0' else 1
                    fn = lambda s, pt=pre_t, mt=mom_t, vt=vol_t, rt=rc_t: (
                        s['pre3'] <= pt and s['mom10'] <= mt and
                        s['vol_ratio5'] <= vt and s['rc'] > rt
                    )
                    for window in ['d5', 'd9']:
                        st = test_condition(samples, fn, window)
                        if st and st['n'] >= 15 and st['sharpe'] > 0.35:
                            combos.append({
                                'desc': f"pre3<={pre_t}+mom10<={mom_t}+vol5<={vol_t}+rc>{rc_t}",
                                'window': window, 'sharpe': st['sharpe'],
                                'n': st['n'], 'avg': st['avg'], 'win': st['win'],
                            })

    combos.sort(key=lambda x: x['sharpe'], reverse=True)
    # 去重 (相似的)
    seen = set()
    unique = []
    for c in combos:
        key = c['desc'].split('+')[:3]  # 只看前3个因子
        key_str = '+'.join(key)
        if key_str not in seen:
            seen.add(key_str)
            unique.append(c)
    return unique[:30]


def main():
    cache = BacktestCache()
    print("加载特征数据...", flush=True)
    samples = load_features(cache)
    print(f"  总样本: {len(samples)}")

    # ========== 1) 单因子扫描 ==========
    print("\n" + "=" * 110)
    print("单因子阈值扫描 (Top 30)")
    print("=" * 110)

    single_results = scan_single_factor(samples)
    seen = set()
    print(f"\n  {'条件':<40} {'窗口':>4} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 80)

    for r in single_results:
        desc = r['desc']
        if desc in seen:
            continue
        seen.add(desc)
        star = '★' if r['sharpe'] > 0.35 and r['n'] >= 20 else ' '
        print("  {}{:.<38} {:>4} {:>4} {:>+6.2f}% {:>5.1f}% {:>+5.2f}".format(
            star, desc, r['window'], r['n'], r['avg'], r['win'], r['sharpe']))

    # ========== 2) 双因子组合 ==========
    print("\n" + "=" * 110)
    print("双因子组合扫描 (Top 30)")
    print("=" * 110)

    combo2 = scan_combo2(samples)
    print(f"\n  {'条件':<45} {'窗口':>4} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 85)

    for r in combo2[:30]:
        star = '★' if r['sharpe'] > 0.4 and r['n'] >= 20 else ' '
        print("  {}{:.<43} {:>4} {:>4} {:>+6.2f}% {:>5.1f}% {:>+5.2f}".format(
            star, r['desc'], r['window'], r['n'], r['avg'], r['win'], r['sharpe']))

    # ========== 3) 三因子组合 ==========
    print("\n" + "=" * 110)
    print("三因子+rc 组合扫描 (去重Top 20)")
    print("=" * 110)

    print(f"\n  {'条件':<55} {'窗口':>4} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 95)

    combo3 = scan_combo3(samples)
    for r in combo3[:20]:
        star = '★' if r['sharpe'] > 0.4 and r['n'] >= 20 else ' '
        print("  {}{:.<53} {:>4} {:>4} {:>+6.2f}% {:>5.1f}% {:>+5.2f}".format(
            star, r['desc'], r['window'], r['n'], r['avg'], r['win'], r['sharpe']))

    # ========== 4) 特殊策略族 ==========
    print("\n" + "=" * 110)
    print("特殊策略族扫描")
    print("=" * 110)

    special_strategies = {
        # 十字星族 (极小实体 + 极小振幅)
        '十字星 (real_body<0.5 + amp<2)': lambda s: s['real_body'] < 0.5 and s['amplitude'] < 2,
        '十字星+rc>0': lambda s: s['real_body'] < 0.5 and s['amplitude'] < 2 and s['rc'] > 0,

        # 长下影 (探底回升)
        '长下影 (lower>1 + upper<0.5)': lambda s: s['lower_shadow'] > 1 and s['upper_shadow'] < 0.5,
        '长下影+rc>0': lambda s: s['lower_shadow'] > 1 and s['upper_shadow'] < 0.5 and s['rc'] > 0,

        # 低波动
        '低波动(std7<1.5)': lambda s: s['std7'] < 1.5,
        '低波动+缩量': lambda s: s['std7'] < 1.5 and s['vol_ratio5'] < 0.8,

        # 窄幅整理
        '窄幅(range7<5)': lambda s: s['range7'] < 5,
        '窄幅+缩量': lambda s: s['range7'] < 5 and s['vol_ratio5'] < 0.8,
        '窄幅+缩量+rc>0': lambda s: s['range7'] < 5 and s['vol_ratio5'] < 0.8 and s['rc'] > 0,

        # 缩量到极致
        '缩量极致(vol5<0.5)': lambda s: s['vol_ratio5'] < 0.5,
        '缩量极致+rc>0': lambda s: s['vol_ratio5'] < 0.5 and s['rc'] > 0,

        # 价格区间底部
        '区间底部(pos<30)': lambda s: s['pos_in_range7'] < 30,
        '区间底部+rc>0': lambda s: s['pos_in_range7'] < 30 and s['rc'] > 0,
        '区间底部+缩量': lambda s: s['pos_in_range7'] < 30 and s['vol_ratio5'] < 0.8,

        # 放量突破族
        '放量(vol5>1.5 + rc>1)': lambda s: s['vol_ratio5'] > 1.5 and s['rc'] > 1,

        # 趋势族 (近期缩量趋势)
        '缩量趋势(vol_trend<-10 + vol5<1)': lambda s: s['vol_trend'] < -10 and s['vol_ratio5'] < 1,
        '缩量趋势+pre7<0': lambda s: s['vol_trend'] < -10 and s['pre7'] < 0,
    }

    print(f"\n  {'策略':<50} {'窗口':>4} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 95)

    for name, fn in special_strategies.items():
        for window in ['d5', 'd9']:
            ret_key = 'ret_d5' if window == 'd5' else 'ret_d9'
            rets = [s[ret_key] for s in samples if s[ret_key] is not None and fn(s)]
            st = stats_fn(rets)
            if st:
                star = '★' if st['sharpe'] > 0.4 and st['n'] >= 20 else ' '
                print("  {}{:.<48} {:>4} {:>4} {:>+6.2f}% {:>5.1f}% {:>+5.2f}".format(
                    star, name, window, st['n'], st['avg'], st['win'], st['sharpe']))


if __name__ == '__main__':
    main()
