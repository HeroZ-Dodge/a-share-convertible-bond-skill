#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断: 逐只对比 close 买入 vs open 买入, 确认逻辑正确性
"""
import sys, os, re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.backtest_cache import BacktestCache


def find_idx(sd, target):
    """找 <= target 的最后一个交易日（处理周末/节假日注册日）"""
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
        reg_price = prices[sd[ri]]['close']
        if reg_price <= 0: continue

        # D+0 因子
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

        # 各日价格
        day_prices = {}
        for off in range(0, 13):
            idx = ri + off
            if idx < len(sd) and sd[idx] <= today_str:
                day_prices[off] = {
                    'date': sd[idx],
                    'open': prices[sd[idx]]['open'],
                    'close': prices[sd[idx]]['close'],
                }

        pool.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
            'day_prices': day_prices,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)

    print("=" * 120)
    print("诊断: close 买入 vs open 买入 逐只对比")
    print("=" * 120)

    # ========== 1. D+0 close vs D+1 open 价差分析 ==========
    print("\n【1】D+0收盘 → D+1开盘 价差分布（全样本）")
    print(f"  {'limit':>5} {'平均':>8} {'中位':>8} {'上涨%':>7} {'下跌%':>7} "
          f"{'D0close':>9} {'D1open':>9} {'D1close':>9}")
    print("  " + "-" * 70)

    for lim in [50, 100, 150]:
        sample = pool[:lim]
        gaps = []
        for v in sample:
            dp = v['day_prices']
            if 0 in dp and 1 in dp:
                d0_close = dp[0]['close']
                d1_open = dp[1]['open']
                if d0_close > 0:
                    gap = ((d1_open - d0_close) / d0_close) * 100
                    gaps.append(gap)

        if gaps:
            avg_gap = sum(gaps) / len(gaps)
            s = sorted(gaps)
            med = s[len(s) // 2]
            up_pct = sum(1 for g in gaps if g > 0) / len(gaps) * 100
            dn_pct = sum(1 for g in gaps if g < 0) / len(gaps) * 100

            d0_avg = sum(v['day_prices'][0]['close'] for v in sample if 0 in v['day_prices']) / len(sample)
            d1o_avg = sum(v['day_prices'][1]['open'] for v in sample if 1 in v['day_prices']) / len(sample)
            d1c_avg = sum(v['day_prices'][1]['close'] for v in sample if 1 in v['day_prices']) / len(sample)

            print(f"  {lim:>5} {avg_gap:>+6.2f}% {med:>+6.2f}% {up_pct:>5.0f}% {dn_pct:>5.0f}% "
                  f"{d0_avg:>8.2f} {d1o_avg:>8.2f} {d1c_avg:>8.2f}")

    # ========== 2. 策略2 逐只对比 ==========
    print("\n【2】策略2: pre3≤2%+mom10<5% 逐只对比 (limit=150)")
    print(f"  {'名称':>12} {'注册日':>12} {'D0close':>8} {'D1open':>8} {'D0→1':>6} "
          f"{'旧版收益':>8} {'新版收益':>8} {'差值':>6} {'触发':>6}")
    print("  " + "-" * 90)

    sample = pool[:150]
    # 策略2
    s2 = [v for v in sample if v['pre3'] <= 2 and v['mom10'] < 5]

    total_old = 0
    total_new = 0
    n = 0

    for v in s2:
        dp = v['day_prices']
        if 0 not in dp or 1 not in dp or 9 not in dp:
            continue

        d0_close = dp[0]['close']
        d1_open = dp[1]['open']
        d9_close = dp[9]['close']

        # 旧版: D+0 close 买入, D+9 close 卖出
        ret_old = ((d9_close - d0_close) / d0_close) * 100
        # 新版: D+1 open 买入, D+9 close 卖出
        ret_new = ((d9_close - d1_open) / d1_open) * 100
        # D+0 close → D+1 open 价差
        gap = ((d1_open - d0_close) / d0_close) * 100

        total_old += ret_old
        total_new += ret_new
        n += 1

        tag = '★' if ret_old > 5 else ' '
        diff = ret_new - ret_old
        print(f"  {tag} {v['name']:>12} {v['anchor']:>12} "
              f"{d0_close:>7.2f} {d1_open:>7.2f} {gap:>+5.1f}% "
              f"{ret_old:>+6.1f}% {ret_new:>+6.1f}% {diff:>+5.1f}%")

    if n > 0:
        print("  " + "-" * 90)
        print(f"  平均: 旧版={total_old/n:+.2f}%  新版={total_new/n:+.2f}%  差值={total_new/n - total_old/n:+.2f}%  样本={n}")

    # ========== 3. 策略1 逐只对比 ==========
    print("\n【3】策略1: pre3≤2%+mom10<5%+rc>0% 逐只对比 (limit=150)")
    print(f"  {'名称':>12} {'注册日':>12} {'D0close':>8} {'D1open':>8} {'D0→1':>6} "
          f"{'旧版收益':>8} {'新版收益':>8} {'差值':>6} {'触发':>6}")
    print("  " + "-" * 90)

    s1 = [v for v in sample if v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0]

    total_old = 0
    total_new = 0
    n = 0

    for v in s1:
        dp = v['day_prices']
        if 0 not in dp or 1 not in dp or 9 not in dp:
            continue

        d0_close = dp[0]['close']
        d1_open = dp[1]['open']
        d9_close = dp[9]['close']

        ret_old = ((d9_close - d0_close) / d0_close) * 100
        ret_new = ((d9_close - d1_open) / d1_open) * 100
        gap = ((d1_open - d0_close) / d0_close) * 100

        total_old += ret_old
        total_new += ret_new
        n += 1

        tag = '★' if ret_old > 5 else ' '
        diff = ret_new - ret_old
        print(f"  {tag} {v['name']:>12} {v['anchor']:>12} "
              f"{d0_close:>7.2f} {d1_open:>7.2f} {gap:>+5.1f}% "
              f"{ret_old:>+6.1f}% {ret_new:>+6.1f}% {diff:>+5.1f}%")

    if n > 0:
        print("  " + "-" * 90)
        print(f"  平均: 旧版={total_old/n:+.2f}%  新版={total_new/n:+.2f}%  差值={total_new/n - total_old/n:+.2f}%  样本={n}")

    # ========== 4. 窗口扫描逐日价格 ==========
    print("\n【4】全样本平均价格 (limit=150, 策略2触发)")
    print(f"  偏移  平均open  平均close  open-close差  累计收益(from D+0close)")
    print("  " + "-" * 60)

    s2_sample = [v for v in sample if v['pre3'] <= 2 and v['mom10'] < 5]
    d0_close_base = None

    for off in range(0, 13):
        opens = []
        closes = []
        for v in s2_sample:
            dp = v['day_prices']
            if off in dp:
                opens.append(dp[off]['open'])
                closes.append(dp[off]['close'])

        if opens:
            avg_o = sum(opens) / len(opens)
            avg_c = sum(closes) / len(closes)
            oc_diff = ((avg_o - avg_c) / avg_c) * 100 if avg_c > 0 else 0

            if d0_close_base is None:
                d0_close_base = avg_c
                ret_from_d0 = 0
            else:
                ret_from_d0 = ((avg_c - d0_close_base) / d0_close_base) * 100

            print(f"  D+{off:<2} {avg_o:>8.2f}  {avg_c:>8.2f}  {oc_diff:>+6.2f}%      {ret_from_d0:>+6.2f}%")

    # ========== 5. 回测逻辑验证 ==========
    print("\n【5】回测脚本逻辑验证")
    print("  回测脚本中:")
    print("    buy_opens[sig] = prices[sd[ri + sig + 1]]['open']   # sig=0 → ri+1 = D+1 open")
    print("    sell_closes[soff] = prices[sd[ri + soff]]['close']  # soff=9 → ri+9 = D+9 close")
    print("  所以 D+0信号→D+9收盘 = D+1开盘买入 → D+9收盘卖出")
    print("  旧版 D+0→D+9 = D+0收盘买入 → D+9收盘卖出")
    print("  差异 = D+0 close → D+1 open 的价差")
    print()
    print("  如果 D+0→D+1 平均涨 +2%, 则新版收益应比旧版低约 2%")
    print("  如果 D+0→D+1 平均涨 0%, 则新版收益 ≈ 旧版")


if __name__ == '__main__':
    main()
