#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多样本量对比 — 同一脚本输出 limit=50/100/150/200/300 的最优窗口
修正版：买入价用次日开盘价
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


def scan_limit(cache, limit):
    """扫描单个 limit，返回结果 dict"""
    today_str = datetime.now().strftime('%Y-%m-%d')

    strategies = {
        '策略1: pre3≤2%+mom10<5%+rc>0%': lambda v: v['pre3'] <= 2 and v['mom10'] < 5 and v['rc'] > 0,
        '策略2: pre3≤2%+mom10<5%': lambda v: v['pre3'] <= 2 and v['mom10'] < 5,
        '策略3: rc<-2%': lambda v: v['rc'] < -2,
        '策略4: pre7<0%': lambda v: v['pre7'] < 0,
    }

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

        # 因子（用 D+0 收盘价计算）
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

        # 实际价格：买入用次日开盘，卖出用目标日收盘
        buy_opens = {}
        sell_closes = {}
        for off in range(0, 16):
            # 信号日 off → 次日 off+1 开盘买入
            buy_idx = ri + off + 1
            if buy_idx < len(sd) and sd[buy_idx] <= today_str:
                buy_opens[off] = prices[sd[buy_idx]]['open']
            # 目标日 off 收盘卖出
            sell_idx = ri + off
            if sell_idx < len(sd) and sd[sell_idx] <= today_str:
                sell_closes[off] = prices[sd[sell_idx]]['close']

        pool.append({
            'pre3': pre3, 'pre7': pre7, 'rc': rc, 'mom10': mom10,
            'anchor': anchor,
            'buy_opens': buy_opens,
            'sell_closes': sell_closes,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    sample = pool[:limit]

    results = {}
    for sname, sfn in strategies.items():
        subset = [v for v in sample if sfn(v)]
        n = len(subset)

        # D+0信号→D+9收盘 baseline (修正版: D+1开盘买入)
        pcts_d09 = []
        for v in subset:
            bp = v['buy_opens'].get(0, 0)
            sp = v['sell_closes'].get(9, 0)
            if bp > 0 and sp > 0:
                pcts_d09.append(((sp - bp) / bp) * 100)
        sh_d09 = 0
        if len(pcts_d09) >= 5:
            s = sorted(pcts_d09)
            avg = sum(s) / len(s)
            std = (sum((x - avg) ** 2 for x in s) / len(s)) ** 0.5
            sh_d09 = avg / std if std > 0 else 0

        # Full window scan: 信号日 boff → 次日 boff+1 开盘买入 → soff 收盘卖出
        best = []
        for boff in range(0, 10):
            for soff in range(boff + 2, 16):  # soff >= boff+2 才能持有至少1天
                hold = soff - boff - 1
                if hold > 10: continue
                pcts = []
                for v in subset:
                    bp = v['buy_opens'].get(boff, 0)
                    sp = v['sell_closes'].get(soff, 0)
                    if bp > 0 and sp > 0:
                        pcts.append(((sp - bp) / bp) * 100)
                if len(pcts) < 5:
                    continue
                s = sorted(pcts)
                avg = sum(s) / len(s)
                std = (sum((x - avg) ** 2 for x in s) / len(s)) ** 0.5
                sh = avg / std if std > 0 else 0
                win = sum(1 for x in s if x > 0) / len(s) * 100
                best.append({
                    'boff': boff, 'soff': soff, 'hold': hold,
                    'sharpe': sh, 'avg': avg, 'win': win, 'n': len(pcts),
                })

        best.sort(key=lambda x: x['sharpe'], reverse=True)

        results[sname] = {
            'n': n,
            'sh_d09': round(sh_d09, 2),
            'best_window': "D+{}→D+{}(持{})".format(
                best[0]['boff'], best[0]['soff'], best[0]['hold']) if best else 'N/A',
            'sh_best': round(best[0]['sharpe'], 2) if best else 0,
            'avg_best': round(best[0]['avg'], 2) if best else 0,
            'win_best': round(best[0]['win'], 1) if best else 0,
            'eff_n': best[0]['n'] if best else 0,
        }

    return results


def main():
    cache = BacktestCache()
    limits = [50, 100, 150, 200, 300]

    print("正在扫描各样本量... (修正版: 买入价=次日开盘)", flush=True)

    all_results = {}
    for lim in limits:
        print(f"  limit={lim} ...", flush=True)
        all_results[lim] = scan_limit(cache, lim)
        print(f"  limit={lim} done", flush=True)

    # 输出总表
    print("\n" + "=" * 120)
    print("多样本量窗口稳定性验证 (修正版: 信号日次日开盘买入)")
    print("=" * 120)

    for sname in all_results[50].keys():
        print(f"\n{sname}")
        print(f"  {'limit':>6} {'样本':>5} {'D+0→D+9夏普':>12} {'最优窗口':>16} {'最优夏普':>8} {'平均':>7} {'胜率':>6} {'有效样本':>6}")
        print("  " + "-" * 75)

        for lim in limits:
            r = all_results[lim].get(sname, {})
            if r:
                print("  {:>5} {:>5} {:>+11}  {:>15} {:>+7} {:>+6}% {:>5.1f}% {:>7}".format(
                    lim, r['n'], r['sh_d09'], r['best_window'], r['sh_best'],
                    r['avg_best'], r['win_best'], r['eff_n']))
            else:
                print(f"  {lim:>5} N/A")

    # 稳定性分析
    print("\n\n" + "=" * 120)
    print("窗口稳定性评分")
    print("统计每个策略在5个样本量下，最优买入/卖出日的分布")
    print("=" * 120)

    for sname in all_results[50].keys():
        print(f"\n{sname}")
        boffs = []
        soffs = []
        holds = []
        for lim in limits:
            r = all_results[lim].get(sname, {})
            if r and r['best_window'] != 'N/A':
                # 解析 "D+3→D+9(持5)" 格式
                w = r['best_window']
                parts = w.replace('D+', '').split('→')
                left = parts[0].split('(')[0] if '(' in parts[0] else parts[0]
                right = parts[1].split('(')[0] if '(' in parts[1] else parts[1]
                boffs.append(int(left))
                soffs.append(int(right))
                if '持' in w:
                    hold_part = w.split('持')[1].split(')')[0]
                    holds.append(int(hold_part))

        if boffs:
            avg_b = sum(boffs) / len(boffs)
            avg_s = sum(soffs) / len(soffs)
            avg_hold = sum(holds) / len(holds) if holds else (avg_s - avg_b)
            b_range = f"D+{min(boffs)}~D+{max(boffs)}"
            s_range = f"D+{min(soffs)}~D+{max(soffs)}"
            print(f"  买入分布: {b_range}  (均值 D+{avg_b:.1f})")
            print(f"  卖出分布: {s_range}  (均值 D+{avg_s:.1f})")
            print(f"  平均持有: {avg_hold:.1f} 天")
        else:
            print("  无有效数据")


if __name__ == '__main__':
    main()
