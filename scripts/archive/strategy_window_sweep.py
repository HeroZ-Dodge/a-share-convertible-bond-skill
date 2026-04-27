#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
买卖窗口全扫描 — 每个策略在不同买入/卖出日的效果
回答：注册日之后买入还是等一等？何时买何时卖最优？
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

    # 定义策略
    strategies = {
        '基准(无筛选)': lambda v: True,
        '策略1: pre3≤2%+mom10<5%+rc>0%': lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0,
        '策略2: pre3≤2%+mom10<5%': lambda v: v['pre3'] <= 2 and v['mom10'] < 5,
        '策略3: rc<-2%': lambda v: v['rc'] < -2,
        '策略4: pre7<0%': lambda v: v['pre7'] < 0,
    }

    # 数据准备
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

        # 计算各日偏移的收益（相对注册价）
        post = {}
        for off in range(1, 16):
            idx = ri + off
            if idx >= len(sd) or sd[idx] > today_str: continue
            post[off] = ((prices[sd[idx]]['close'] - reg_price) / reg_price) * 100

        # 因子
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

        pool.append({
            'code': sc, 'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor, 'reg_price': reg_price,
            'post': post, 'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
        })

    # 支持命令行参数
    limit = 100
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            pass

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    sample = pool[:limit]

    # 买卖窗口全扫描
    print("=" * 110)
    print("买卖窗口全扫描 (limit=100)")
    print("遍历所有买入日 D+boff 到卖出日 D+soff，找出每个策略的最优窗口")
    print("=" * 110)

    for sname, sfn in strategies.items():
        subset = [v for v in sample if sfn(v)]
        if len(subset) < 5:
            continue

        print(f"\n{'=' * 60}")
        print(f"  {sname} (n={len(subset)})")
        print(f"{'=' * 60}")

        # 扫描所有窗口
        all_results = []
        for boff in range(0, 10):
            for soff in range(boff + 1, 16):
                hold = soff - boff
                if hold > 10: continue  # 持有超过10天意义不大

                pcts = []
                for v in subset:
                    if boff == 0:
                        entry_price = v['reg_price']
                    else:
                        br = v['post'].get(boff)
                        if br is None: continue
                        entry_price = v['reg_price'] * (1 + br / 100)

                    sr = v['post'].get(soff)
                    if sr is None: continue
                    exit_price = v['reg_price'] * (1 + sr / 100)

                    if entry_price <= 0: continue
                    ret = ((exit_price - entry_price) / entry_price) * 100
                    pcts.append(ret)

                if len(pcts) < 5:
                    continue

                s = sorted(pcts)
                n = len(s)
                avg = sum(s) / n
                med = s[n // 2]
                win = sum(1 for x in s if x > 0) / n * 100
                std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
                sharpe = avg / std if std > 0 else 0

                all_results.append({
                    'boff': boff, 'soff': soff, 'hold': hold,
                    'avg': avg, 'med': med, 'win': win,
                    'std': std, 'sharpe': sharpe, 'n': n,
                })

        # 按夏普排序
        all_results.sort(key=lambda x: x['sharpe'], reverse=True)

        print(f"\n  {'排名':>4}  {'买入':>4}  {'卖出':>4}  {'持有':>4}  {'平均':>7}  {'中位':>7}  {'胜率':>6}  {'夏普':>6}  {'样本':>4}")
        print("  " + "-" * 75)

        for rank, r in enumerate(all_results[:20], 1):
            tag = ''
            if rank <= 5:
                tag = f' (D+{r["boff"]}→D+{r["soff"]} 持有{r["hold"]}天)'

            star = ''
            if r['sharpe'] > 0.5 and r['win'] > 70:
                star = '★★'
            elif r['sharpe'] > 0.4 and r['win'] > 65:
                star = '★'

            print("  {:>3} {:>4}  D+{:>2} →D+{:>2} {:>4} {:>+6.2f}% {:>+6.2f}% {:>5.1f}% {:>+5.2f} {:>4} {}{}".format(
                rank, '', r['boff'], r['soff'], r['hold'] , r['avg'], r['med'], r['win'], r['sharpe'], r['n'], star, tag))

        # 按买入日分组，找出最佳买入点
        print(f"\n  按买入日分组 (只看夏普):")
        print(f"  {'买入日':>6} {'最佳卖出':>8} {'平均':>7} {'胜率':>6} {'夏普':>6} {'最优窗口':>8}")
        print("  " + "-" * 60)

        for boff in range(0, 10):
            boff_results = [r for r in all_results if r['boff'] == boff]
            if not boff_results:
                continue
            best_sh = max(boff_results, key=lambda x: x['sharpe'])
            tag = '★' if boff_results else ''
            print("  D+{:>2} {:>2}  D+{:>2}→D+{:>2} {:>+6.2f}% {:>5.1f}% {:>+5.2f}  持有{}天".format(
                boff, tag, best_sh['boff'], best_sh['soff'], best_sh['avg'], best_sh['win'], best_sh['sharpe'], best_sh['hold']))

    # 关键对比：当前D+0→D+9 vs 最优窗口
    print("\n\n" + "=" * 110)
    print("对比: 当前窗口(D+0→D+9) vs 最优窗口")
    print("=" * 110)

    print(f"\n  {'策略':<45} {'当前窗口':>10} {'当前夏普':>8} {'最优窗口':>10} {'最优夏普':>8} {'提升':>8}")
    print("  " + "-" * 95)

    for sname, sfn in strategies.items():
        subset = [v for v in sample if sfn(v)]
        if len(subset) < 5:
            continue

        # 当前窗口 D+0→D+9
        pcts_d09 = []
        for v in subset:
            sr = v['post'].get(9)
            if sr is not None:
                pcts_d09.append(sr)

        if len(pcts_d09) < 5:
            continue

        s = sorted(pcts_d09)
        n = len(s)
        avg0 = sum(s) / n
        std0 = (sum((x - avg0) ** 2 for x in s) / n) ** 0.5
        sh0 = avg0 / std0 if std0 > 0 else 0

        # 扫描所有窗口
        best_sharpe = 0
        best_window = ''
        for boff in range(0, 10):
            for soff in range(boff + 1, 16):
                hold = soff - boff
                if hold > 10: continue

                pcts = []
                for v in subset:
                    if boff == 0:
                        entry = v['reg_price']
                    else:
                        br = v['post'].get(boff)
                        if br is None: continue
                        entry = v['reg_price'] * (1 + br / 100)

                    sr = v['post'].get(soff)
                    if sr is None: continue
                    exit_p = v['reg_price'] * (1 + sr / 100)

                    if entry <= 0: continue
                    pcts.append(((exit_p - entry) / entry) * 100)

                if len(pcts) < 5:
                    continue

                s = sorted(pcts)
                avg = sum(s) / len(s)
                std = (sum((x - avg) ** 2 for x in s) / len(s)) ** 0.5
                sh = avg / std if std > 0 else 0

                if sh > best_sharpe:
                    best_sharpe = sh
                    best_window = f"D+{boff}→D+{soff}"
                    best_avg = avg
                    best_n = len(pcts)

        name_short = sname[:42]
        improvement = best_sharpe - sh0
        tag = '↑' if improvement > 0.1 else ('↓' if improvement < -0.1 else '=')
        print("  {:<42} D+0→D+9 {:>+5.2f}  {:>10} {:>+5.2f} {:+.2f}{}".format(
            name_short, sh0, best_window, best_sharpe, improvement, tag))


if __name__ == '__main__':
    main()
