#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合策略扫描 — 多类策略 × 多交易窗口

策略族:
  A. 基础动量 (pre3/mom10/rc 组合)
  B. 缩量突破 (成交量配合)
  C. 强势程度分级 (rc 大小)
  D. 前期跌幅反转 (pre7 深度)
  E. 组合强化 (多条件叠加)
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


def load_pool(cache, limit=200):
    """加载回测池"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    bonds = cache.get_jisilu_bonds(phase='注册', limit=0)
    pool = []
    for b in bonds:
        sc = b.get('stock_code')
        if not sc:
            continue
        pf = b.get('progress_full', '')
        if not pf:
            continue
        anchor = ''
        for line in pf.replace('<br>', '\n').split('\n'):
            if '同意注册' in line:
                m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                if m:
                    anchor = m.group(1)
                    break
        if not anchor or anchor > today_str:
            continue

        prices = cache.get_kline_as_dict(sc, days=1500)
        if not prices:
            continue
        sd = sorted(prices.keys())
        ri = find_idx(sd, anchor)
        reg_price = prices[sd[ri]]['close']
        if reg_price <= 0:
            continue
        if ri < 10:
            continue

        # 因子
        pre3 = 0
        if ri >= 3:
            p3 = prices[sd[ri - 3]]['close']
            if p3 > 0:
                pre3 = ((reg_price - p3) / p3) * 100

        pre7 = 0
        if ri >= 7:
            p7 = prices[sd[ri - 7]]['close']
            if p7 > 0:
                pre7 = ((reg_price - p7) / p7) * 100

        rc = 0
        if ri > 0:
            prev = prices[sd[ri - 1]]['close']
            if prev > 0:
                rc = ((reg_price - prev) / prev) * 100

        mom10 = 0
        if ri >= 10:
            p10 = prices[sd[ri - 10]]['close']
            if p10 > 0:
                mom10 = ((reg_price - p10) / p10) * 100

        # 成交量数据
        vol_now = prices[sd[ri]].get('volume', 0)
        vol_avg5 = 0
        vol_avg10 = 0
        if ri >= 5:
            vols = [prices[sd[ri - k]].get('volume', 0) for k in range(1, 6)]
            vols = [v for v in vols if v > 0]
            if vols:
                vol_avg5 = sum(vols) / len(vols)
        if ri >= 10:
            vols = [prices[sd[ri - k]].get('volume', 0) for k in range(1, 11)]
            vols = [v for v in vols if v > 0]
            if vols:
                vol_avg10 = sum(vols) / len(vols)

        # 价格区间
        high_7 = 0
        low_7 = 99999
        if ri >= 7:
            for k in range(ri - 7, ri + 1):
                h = prices[sd[k]].get('high', 0)
                l = prices[sd[k]].get('low', 99999)
                if h > high_7:
                    high_7 = h
                if l < low_7:
                    low_7 = l
        range_7 = ((high_7 - low_7) / low_7 * 100) if low_7 > 0 else 0

        # 各窗口收益
        ret = {}
        for boff in range(0, 8):
            buy_idx = ri + boff + 1
            if buy_idx >= len(sd) or sd[buy_idx] > today_str:
                continue
            bp = prices[sd[buy_idx]].get('open', 0)
            if bp <= 0:
                continue
            for soff in range(boff + 2, 16):
                sell_idx = ri + soff
                if sell_idx >= len(sd) or sd[sell_idx] > today_str:
                    continue
                sp = prices[sd[sell_idx]].get('close', 0)
                if sp <= 0:
                    continue
                ret[(boff, soff)] = ((sp - bp) / bp) * 100

        pool.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
            'vol_ratio5': (vol_now / vol_avg5) if vol_avg5 > 0 else 1,
            'vol_ratio10': (vol_now / vol_avg10) if vol_avg10 > 0 else 1,
            'range_7': range_7,
            'ret': ret,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    return pool[:limit] if limit > 0 else pool


def calc_stats(returns, min_n=8):
    """计算夏普等统计"""
    if len(returns) < min_n:
        return None
    s = sorted(returns)
    n = len(s)
    avg = sum(s) / n
    win_n = sum(1 for x in s if x > 0)
    std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
    sharpe = avg / std if std > 0 else 0
    return {
        'n': n, 'avg': avg, 'med': s[n // 2],
        'win': win_n / n * 100, 'std': std, 'sharpe': sharpe,
        'best': max(s), 'worst': min(s),
    }


def main():
    cache = BacktestCache()

    print("加载数据池...", flush=True)
    full_pool = load_pool(cache, limit=0)  # 全部
    print(f"  总样本: {len(full_pool)}")

    # ========== 定义策略族 ==========
    strategies = {}

    # A. 基础动量族
    strategies['A1: S1原始 pre3<=2+mom10<5+rc>0'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0
    strategies['A2: pre3<=2+mom10<3+rc>0'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 3 and v['rc'] > 0
    strategies['A3: pre3<=2+mom10<0+rc>0'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 0 and v['rc'] > 0
    strategies['A4: pre3<=1+mom10<5+rc>0'] = lambda v: v['pre3'] <= 1 and v['mom10'] < 5 and v['rc'] > 0
    strategies['A5: pre3<=0+mom10<5+rc>0'] = lambda v: v['pre3'] <= 0 and v['mom10'] < 5 and v['rc'] > 0
    strategies['A6: pre3<=2+mom10<5+rc>1%'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 1
    strategies['A7: pre3<=2+mom10<5+rc>2%'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 2

    # B. 缩量/放量族
    strategies['B1: S1+缩量(vol<0.8avg)'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['vol_ratio5'] < 0.8
    strategies['B2: S1+放量(vol>1.2avg)'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['vol_ratio5'] > 1.2
    strategies['B3: pre3<=2+mom10<5+rc>0+vol<0.7'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['vol_ratio5'] < 0.7
    strategies['B4: pre3<=2+rc>0+vol>1.5'] = lambda v: v['pre3'] <= 2 and v['rc'] > 0 and v['vol_ratio5'] > 1.5
    strategies['B5: pre3<=2+mom10<5+rc>0+vol<1.0+vol>0.5'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['vol_ratio5'] < 1.0 and v['vol_ratio5'] > 0.5

    # C. 前期跌幅族
    strategies['C1: S1+pre7<0'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['pre7'] < 0
    strategies['C2: pre3<=2+mom10<5+pre7<-3+rc>0'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['pre7'] < -3 and v['rc'] > 0
    strategies['C3: pre3<=2+mom10<5+pre7<-5+rc>0'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['pre7'] < -5 and v['rc'] > 0
    strategies['C4: pre7<-3+rc>0 (不限制pre3/mom10)'] = lambda v: v['pre7'] < -3 and v['rc'] > 0
    strategies['C5: pre7<-5+rc>0'] = lambda v: v['pre7'] < -5 and v['rc'] > 0
    strategies['C6: pre3<=0+pre7<-2+rc>0'] = lambda v: v['pre3'] <= 0 and v['pre7'] < -2 and v['rc'] > 0

    # D. 窄幅整理突破族
    strategies['D1: S1+窄幅(range7<5%)'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['range_7'] < 5
    strategies['D2: pre3<=2+mom10<5+rc>0+range7<8%'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['range_7'] < 8
    strategies['D3: pre3<=2+mom10<5+rc>0+range7<12%'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0 and v['range_7'] < 12
    strategies['D4: pre3<=1+mom10<3+rc>1+range7<6%'] = lambda v: v['pre3'] <= 1 and v['mom10'] < 3 and v['rc'] > 1 and v['range_7'] < 6
    strategies['D5: pre3<=0+mom10<0+rc>0+range7<5%'] = lambda v: v['pre3'] <= 0 and v['mom10'] < 0 and v['rc'] > 0 and v['range_7'] < 5

    # E. 超级组合族
    strategies['E1: pre3<=1+mom10<3+pre7<0+rc>0'] = lambda v: v['pre3'] <= 1 and v['mom10'] < 3 and v['pre7'] < 0 and v['rc'] > 0
    strategies['E2: pre3<=0+mom10<0+pre7<0+rc>0'] = lambda v: v['pre3'] <= 0 and v['mom10'] < 0 and v['pre7'] < 0 and v['rc'] > 0
    strategies['E3: pre3<=2+mom10<3+pre7<-2+rc>1'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 3 and v['pre7'] < -2 and v['rc'] > 1
    strategies['E4: pre3<=1+mom10<5+pre7<0+rc>1+vol<1'] = lambda v: v['pre3'] <= 1 and v['mom10'] < 5 and v['pre7'] < 0 and v['rc'] > 1 and v['vol_ratio5'] < 1.0
    strategies['E5: pre3<=2+mom10<0+pre7<0+rc>0'] = lambda v: v['pre3'] <= 2 and v['mom10'] < 0 and v['pre7'] < 0 and v['rc'] > 0

    # ========== 固定窗口扫描 D+boff→D+soff ==========
    print("\n" + "=" * 110)
    print("固定窗口扫描 (D+3→D+9) — 全部策略族")
    print("=" * 110)

    results = []
    for sname, sfn in strategies.items():
        triggered = [v for v in full_pool if sfn(v)]
        returns = [v['ret'][(3, 9)] for v in triggered if (3, 9) in v['ret']]
        stats = calc_stats(returns)
        if stats:
            results.append((sname, stats))
            results[-1] += (3, 9)

    results.sort(key=lambda x: x[1]['sharpe'], reverse=True)

    print(f"\n  {'策略':<55} {'样本':>4} {'平均':>7} {'中位':>7} {'胜率':>6} {'标准差':>7} {'夏普':>6}")
    print("  " + "-" * 100)
    for sname, stats, boff, soff in results:
        star = '★' if stats['sharpe'] > 0.5 and stats['n'] >= 10 else ' '
        print("  {}{:.<52} {:>4} {:>+6.2f}% {:>+6.2f}% {:>5.1f}% {:>6.2f}% {:>+5.2f}".format(
            star, sname, stats['n'], stats['avg'], stats['med'],
            stats['win'], stats['std'], stats['sharpe']))

    # ========== 最佳策略的多窗口扫描 ==========
    print("\n\n" + "=" * 110)
    print("多窗口扫描 — 前5策略")
    print("=" * 110)

    top5 = results[:5]
    for sname, _, boff, soff in top5:
        sfn = strategies[sname]
        triggered = [v for v in full_pool if sfn(v)]
        if not triggered:
            continue

        print(f"\n{sname} (总样本 {len(triggered)})")
        label = '买入\\卖出'
        print(f"  {label:>10}", end='')
        for soff_t in range(3, 16):
            print(f"  D+{soff_t:>2}", end='')
        print()
        print("  " + "-" * (10 + 6 * 13))

        for boff_t in range(0, 8):
            print(f"  {'D+' + str(boff_t):>10}", end='')
            for soff_t in range(boff_t + 2, 16):
                rets = [v['ret'][(boff_t, soff_t)] for v in triggered if (boff_t, soff_t) in v['ret']]
                st = calc_stats(rets)
                if st:
                    print(f"  {st['sharpe']:>+5.2f}", end='')
                else:
                    print(f"  {'--':>5}", end='')
            print()

    # ========== 窗口优化扫描 ==========
    print("\n\n" + "=" * 110)
    print("最优窗口详情")
    print("=" * 110)

    for sname, _, boff, soff in top5:
        sfn = strategies[sname]
        triggered = [v for v in full_pool if sfn(v)]
        if not triggered:
            continue

        # 扫描所有窗口
        best = None
        for boff_t in range(0, 8):
            for soff_t in range(boff_t + 2, 16):
                rets = [v['ret'][(boff_t, soff_t)] for v in triggered if (boff_t, soff_t) in v['ret']]
                st = calc_stats(rets, min_n=8)
                if st and (best is None or st['sharpe'] > best['sharpe']):
                    hold = soff_t - boff_t - 1
                    best = {**st, 'boff': boff_t, 'soff': soff_t, 'hold': hold}

        if best:
            print(f"\n{sname}")
            print(f"  最优窗口: D+{best['boff']}→D+{best['soff']} (持有{best['hold']}天)")
            print(f"  样本: {best['n']}  平均: {best['avg']:+.2f}%  胜率: {best['win']:.1f}%  夏普: {best['sharpe']:+.2f}")


if __name__ == '__main__':
    main()
