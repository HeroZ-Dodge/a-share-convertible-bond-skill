#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略挖掘：从注册日后数据中寻找最优交易窗口 + 股票筛选条件
"""
import sys
import os
import re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.backtest_cache import BacktestCache


def parse_anchor_date(bond: dict) -> str:
    pf = bond.get('progress_full', '')
    if not pf:
        return ''
    pf = pf.replace('<br>', '\n')
    for line in pf.split('\n'):
        if '同意注册' in line:
            m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
            if m:
                return m.group(1)
    return ''


def find_reg_idx(sorted_dates, target):
    for i, d in enumerate(sorted_dates):
        if d >= target:
            return i
    return len(sorted_dates) - 1


def main():
    cache = BacktestCache()
    today = datetime.now().strftime('%Y-%m-%d')

    # 获取所有注册阶段的已上市转债
    all_bonds = cache.get_jisilu_bonds(phase='注册', status_cd='OK', limit=0)
    print(f'总共有 {len(all_bonds)} 只已上市且有注册信息的转债')

    valid = []
    for b in all_bonds:
        sc = b.get('stock_code')
        if not sc:
            continue
        reg_date = parse_anchor_date(b)
        if not reg_date:
            continue
        # 跳过注册日在未来的
        if reg_date > today:
            continue

        # 获取K线
        prices = cache.get_kline_as_dict(sc, days=600)
        if not prices or len(prices) < 100:
            continue

        sd = sorted(prices.keys())
        reg_idx = find_reg_idx(sd, reg_date)
        if reg_idx is None or reg_idx < 0:
            continue

        # 确保注册日后有足够数据（到今日）
        last_idx = len(sd) - 1
        post_days = last_idx - reg_idx
        if post_days < 5:
            continue

        reg_price = prices[sd[reg_idx]]['close']
        if reg_price <= 0:
            continue

        # 计算注册日后各日收益
        post_returns = {}
        for off in range(1, min(post_days + 1, 31)):
            idx = reg_idx + off
            if idx >= len(sd):
                break
            if sd[idx] > today:
                break
            p = prices[sd[idx]]['close']
            ret = ((p - reg_price) / reg_price) * 100
            post_returns[off] = round(ret, 2)

        # 注册前数据
        pre_returns = {}
        for off in range(1, 16):
            idx = reg_idx - off
            if idx < 0:
                break
            p = prices[sd[idx]]['close']
            ret = ((p - reg_price) / reg_price) * 100
            pre_returns[off] = round(ret, 2)

        # 注册日涨跌
        reg_day_chg = 0
        if reg_idx > 0:
            prev = prices[sd[reg_idx - 1]]['close']
            if prev > 0:
                reg_day_chg = ((reg_price - prev) / prev) * 100

        # 注册前7天累计收益
        pre7_idx = reg_idx - 7
        pre7_ret = 0
        if pre7_idx >= 0 and sd[pre7_idx] <= today:
            pre7_price = prices[sd[pre7_idx]]['close']
            if pre7_price > 0:
                pre7_ret = ((reg_price - pre7_price) / pre7_price) * 100

        # 注册前5日涨幅
        pre5_idx = reg_idx - 5
        pre5_ret = 0
        if pre5_idx >= 0 and sd[pre5_idx] <= today:
            pre5_price = prices[sd[pre5_idx]]['close']
            if pre5_price > 0:
                pre5_ret = ((reg_price - pre5_price) / pre5_price) * 100

        valid.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'reg_date': reg_date,
            'reg_price': round(reg_price, 2),
            'reg_idx': reg_idx,
            'post_days': post_days,
            'post_returns': post_returns,
            'pre_returns': pre_returns,
            'reg_day_chg': round(reg_day_chg, 2),
            'pre7_ret': round(pre7_ret, 2),
            'pre5_ret': round(pre5_ret, 2),
            'prices': prices,
            'sorted_dates': sd,
        })

    print(f'有效样本: {len(valid)} 只\n')

    # ============================================================
    # 一、注册日后逐日收益分布
    # ============================================================
    print("=" * 80)
    print("一、注册日后逐日收益分布 (D+1 ~ D+30)")
    print("=" * 80)

    all_daily = {}
    for v in valid:
        for off in range(1, 31):
            ret = v['post_returns'].get(off)
            if ret is not None:
                if off not in all_daily:
                    all_daily[off] = []
                all_daily[off].append(ret)

    print(f"\n  {'偏移':>6} {'平均':>7} {'中位':>7} {'胜率':>6} {'样本':>5} {'最大':>7} {'最小':>7}")
    print("  " + "-" * 55)

    daily_stats = {}
    for off in sorted(all_daily.keys()):
        vals = all_daily[off]
        avg = sum(vals) / len(vals)
        s = sorted(vals)
        med = s[len(s) // 2]
        win = sum(1 for x in vals if x > 0) / len(vals) * 100
        best = max(vals)
        worst = min(vals)
        daily_stats[off] = {
            'avg': avg, 'med': med, 'win': win, 'n': len(vals),
            'best': best, 'worst': worst,
        }
        bar = '#' * int(abs(avg) * 1.5) if avg > 0 else '_' * int(abs(avg) * 1.5)
        print(f"  D+{off:>2d}: {avg:>+6.2f}% {med:>+6.2f}% {win:>5.1f}% {len(vals):>4} "
              f"{best:>+6.1f}% {worst:>+6.1f}%  {bar}")

    # 找最佳持有天数：平均收益最高且胜率>55%
    print("\n  有效策略候选 (胜率>55%):")
    candidates = []
    for off in sorted(daily_stats.keys()):
        ds = daily_stats[off]
        if ds['win'] > 55 and ds['n'] >= 50:
            candidates.append((off, ds))
            print(f"    D+{off:>2d}: 平均{ds['avg']:+.2f}%, 胜率{ds['win']:.0f}%, 样本{ds['n']}")

    # ============================================================
    # 二、买卖窗口组合扫描
    # ============================================================
    print("\n" + "=" * 80)
    print("二、买卖窗口组合扫描 (D+0~D+5 买入 × D+1~D+30 卖出)")
    print("=" * 80)

    buy_offsets = [0, 1, 2, 3, 4, 5]
    sell_offsets = list(range(1, 31))

    combo_results = {}
    for boff in buy_offsets:
        for soff in sell_offsets:
            if boff >= soff:
                continue
            key = (boff, soff)
            pcts = []
            for v in valid:
                b_price = None
                s_price = None

                # 买入价 = 注册日后boff天
                if boff == 0:
                    b_price = v['reg_price']
                else:
                    b_ret = v['post_returns'].get(boff)
                    if b_ret is not None:
                        b_price = v['reg_price'] * (1 + b_ret / 100)

                if b_price is None or b_price <= 0:
                    continue

                s_ret = v['post_returns'].get(soff)
                if s_ret is None:
                    continue
                s_price = v['reg_price'] * (1 + s_ret / 100)

                pct = ((s_price - b_price) / b_price) * 100
                pcts.append(pct)

            if len(pcts) >= 30:
                s = sorted(pcts)
                avg = sum(pcts) / len(pcts)
                med = s[len(s) // 2]
                win = sum(1 for x in pcts if x > 0) / len(pcts) * 100
                std = (sum((x - avg) ** 2 for x in pcts) / len(pcts)) ** 0.5
                combo_results[key] = {
                    'avg': avg, 'med': med, 'win': win, 'n': len(pcts),
                    'std': std, 'best': max(pcts), 'worst': min(pcts),
                }

    # 按胜率+平均收益排序
    sorted_combos = sorted(combo_results.items(),
                           key=lambda x: (x[1]['win'], x[1]['avg']), reverse=True)

    print(f"\n  Top 20 组合 (按胜率+平均收益排序):")
    print(f"  {'买入':>6} {'卖出':>6} {'持有':>4} {'平均':>7} {'中位':>7} {'胜率':>6} {'标准差':>7} {'样本':>5} {'最佳':>7} {'最差':>7}")
    print("  " + "-" * 75)
    for (boff, soff), cs in sorted_combos[:20]:
        hold = soff - boff
        print(f"  D+{boff:<3d} D+{soff:<3d} {hold:>3d}天 "
              f"{cs['avg']:>+6.2f}% {cs['med']:>+6.2f}% {cs['win']:>5.1f}% "
              f"{cs['std']:>6.2f}% {cs['n']:>4} {cs['best']:>+6.1f}% {cs['worst']:>+6.1f}%")

    # ============================================================
    # 三、筛选因子探索：什么特征的股票收益更好？
    # ============================================================
    print("\n" + "=" * 80)
    print("三、筛选因子探索")
    print("=" * 80)

    # 3a. 注册前涨幅分组（pre7_ret）
    print("\n  因子1: 注册前7天涨幅分组")
    groups = {'暴跌(<-5%)': [], '跌(-5~-2%)': [], '微跌(-2~0%)': [], '微涨(0~2%)': [], '涨(2~5%)': [], '大涨(>5%)': []}
    for v in valid:
        p7 = v['pre7_ret']
        if p7 < -5:
            g = '暴跌(<-5%)'
        elif p7 < -2:
            g = '跌(-5~-2%)'
        elif p7 < 0:
            g = '微跌(-2~0%)'
        elif p7 < 2:
            g = '微涨(0~2%)'
        elif p7 < 5:
            g = '涨(2~5%)'
        else:
            g = '大涨(>5%)'
        # D+3买入,D+11卖出的收益
        d3_ret = v['post_returns'].get(3)
        d11_ret = v['post_returns'].get(11)
        if d3_ret is not None and d11_ret is not None:
            entry = v['reg_price'] * (1 + d3_ret / 100)
            exit_ret = ((v['reg_price'] * (1 + d11_ret / 100) - entry) / entry) * 100
            groups[g].append(exit_ret)

    for g, vals in groups.items():
        if vals:
            avg = sum(vals) / len(vals)
            win = sum(1 for x in vals if x > 0) / len(vals) * 100
            print(f"    {g:>12}: 平均{avg:>+5.2f}%, 胜率{win:>5.1f}%, 样本{len(vals)}")

    # 3b. 注册日涨跌分组
    print("\n  因子2: 注册日涨跌分组")
    groups2 = {'大跌(<-2%)': [], '跌(-2~0%)': [], '涨(0~2%)': [], '大涨(>2%)': []}
    for v in valid:
        rc = v['reg_day_chg']
        d3_ret = v['post_returns'].get(3)
        d11_ret = v['post_returns'].get(11)
        if d3_ret is not None and d11_ret is not None:
            entry = v['reg_price'] * (1 + d3_ret / 100)
            exit_ret = ((v['reg_price'] * (1 + d11_ret / 100) - entry) / entry) * 100
            if rc < -2:
                groups2['大跌(<-2%)'].append(exit_ret)
            elif rc < 0:
                groups2['跌(-2~0%)'].append(exit_ret)
            elif rc < 2:
                groups2['涨(0~2%)'].append(exit_ret)
            else:
                groups2['大涨(>2%)'].append(exit_ret)

    for g, vals in groups2.items():
        if vals:
            avg = sum(vals) / len(vals)
            win = sum(1 for x in vals if x > 0) / len(vals) * 100
            print(f"    {g:>12}: 平均{avg:>+5.2f}%, 胜率{win:>5.1f}%, 样本{len(vals)}")

    # 3c. 注册前5日涨幅分组
    print("\n  因子3: 注册前5日涨幅分组")
    groups3 = {'暴跌(<-5%)': [], '跌(-5~0%)': [], '微涨(0~3%)': [], '涨(3~6%)': [], '大涨(>6%)': []}
    for v in valid:
        p5 = v['pre5_ret']
        d3_ret = v['post_returns'].get(3)
        d11_ret = v['post_returns'].get(11)
        if d3_ret is not None and d11_ret is not None:
            entry = v['reg_price'] * (1 + d3_ret / 100)
            exit_ret = ((v['reg_price'] * (1 + d11_ret / 100) - entry) / entry) * 100
            if p5 < -5:
                groups3['暴跌(<-5%)'].append(exit_ret)
            elif p5 < 0:
                groups3['跌(-5~0%)'].append(exit_ret)
            elif p5 < 3:
                groups3['微涨(0~3%)'].append(exit_ret)
            elif p5 < 6:
                groups3['涨(3~6%)'].append(exit_ret)
            else:
                groups3['大涨(>6%)'].append(exit_ret)

    for g, vals in groups3.items():
        if vals:
            avg = sum(vals) / len(vals)
            win = sum(1 for x in vals if x > 0) / len(vals) * 100
            print(f"    {g:>12}: 平均{avg:>+5.2f}%, 胜率{win:>5.1f}%, 样本{len(vals)}")

    # 3d. 注册后D+1涨跌分组
    print("\n  因子4: 注册后D+1涨跌分组")
    groups4 = {'大跌(<-2%)': [], '跌(-2~0%)': [], '涨(0~2%)': [], '大涨(>2%)': []}
    for v in valid:
        d1_ret = v['post_returns'].get(1)
        d3_ret = v['post_returns'].get(3)
        d11_ret = v['post_returns'].get(11)
        if d1_ret is not None and d3_ret is not None and d11_ret is not None:
            entry = v['reg_price'] * (1 + d3_ret / 100)
            exit_ret = ((v['reg_price'] * (1 + d11_ret / 100) - entry) / entry) * 100
            if d1_ret < -2:
                groups4['大跌(<-2%)'].append(exit_ret)
            elif d1_ret < 0:
                groups4['跌(-2~0%)'].append(exit_ret)
            elif d1_ret < 2:
                groups4['涨(0~2%)'].append(exit_ret)
            else:
                groups4['大涨(>2%)'].append(exit_ret)

    for g, vals in groups4.items():
        if vals:
            avg = sum(vals) / len(vals)
            win = sum(1 for x in vals if x > 0) / len(vals) * 100
            print(f"    {g:>12}: 平均{avg:>+5.2f}%, 胜率{win:>5.1f}%, 样本{len(vals)}")

    # ============================================================
    # 四、多因子组合筛选
    # ============================================================
    print("\n" + "=" * 80)
    print("四、多因子组合筛选 (D+3买 D+11卖)")
    print("=" * 80)

    rules = [
        ('基准(无筛选)', lambda v: True),
        ('注册前不涨(pre7<=2%)', lambda v: v['pre7_ret'] <= 2),
        ('注册前微涨(0<pre7<=5%)', lambda v: 0 < v['pre7_ret'] <= 5),
        ('注册日不涨(rc<=2%)', lambda v: v['reg_day_chg'] <= 2),
        ('注册日涨(rc>0%)', lambda v: v['reg_day_chg'] > 0),
        ('注册前涨+注册日涨(pre5>0 & rc>0)', lambda v: v['pre5_ret'] > 0 and v['reg_day_chg'] > 0),
        ('注册前不跌+注册日涨(pre7>=0 & rc>0)', lambda v: v['pre7_ret'] >= 0 and v['reg_day_chg'] > 0),
        ('注册前微涨(0~5%)+注册日涨', lambda v: 0 < v['pre7_ret'] <= 5 and v['reg_day_chg'] > 0),
        ('注册前跌+注册日涨(pre7<0 & rc>0)', lambda v: v['pre7_ret'] < 0 and v['reg_day_chg'] > 0),
        ('注册后D+1涨(D+1>0)', lambda v: v['post_returns'].get(1, 0) > 0),
        ('注册前不涨+D+1涨(pre7<=2 & D+1>0)', lambda v: v['pre7_ret'] <= 2 and v['post_returns'].get(1, 0) > 0),
        ('全条件(pre7<=2% & rc>0 & D+1>0)', lambda v: v['pre7_ret'] <= 2 and v['reg_day_chg'] > 0 and v['post_returns'].get(1, 0) > 0),
        ('强势(pre5>0 & rc>0 & D+1>0)', lambda v: v['pre5_ret'] > 0 and v['reg_day_chg'] > 0 and v['post_returns'].get(1, 0) > 0),
        ('温和(pre7<=5% & rc>-2% & D+1>0)', lambda v: v['pre7_ret'] <= 5 and v['reg_day_chg'] > -2 and v['post_returns'].get(1, 0) > 0),
    ]

    print(f"\n  {'规则':<40} {'平均':>6} {'中位':>6} {'胜率':>6} {'样本':>5} {'夏普':>6}")
    print("  " + "-" * 75)

    for name, rule in rules:
        subset = [v for v in valid if rule(v)]
        pcts = []
        for v in subset:
            d3 = v['post_returns'].get(3)
            d11 = v['post_returns'].get(11)
            if d3 is not None and d11 is not None:
                entry = v['reg_price'] * (1 + d3 / 100)
                pct_val = ((v['reg_price'] * (1 + d11 / 100) - entry) / entry) * 100
                pcts.append(pct_val)

        if len(pcts) >= 10:
            avg = sum(pcts) / len(pcts)
            s = sorted(pcts)
            med = s[len(s) // 2]
            win = sum(1 for x in pcts if x > 0) / len(pcts) * 100
            std = (sum((x - avg) ** 2 for x in pcts) / len(pcts)) ** 0.5
            sharpe = avg / std if std > 0 else 0
            print(f"  {name:<40} {avg:>+5.2f}% {med:>+5.2f}% {win:>5.1f}% {len(pcts):>4} {sharpe:>+5.2f}")

    # ============================================================
    # 五、不同窗口下的因子效果
    # ============================================================
    print("\n" + "=" * 80)
    print("五、不同买卖窗口下的因子效果对比")
    print("=" * 80)

    windows = [(0, 7), (0, 10), (1, 8), (1, 10), (3, 11), (5, 12)]
    best_rules = [
        ('无筛选', lambda v: True),
        ('pre7<=2%', lambda v: v['pre7_ret'] <= 2),
        ('rc>0%', lambda v: v['reg_day_chg'] > 0),
        ('pre7<=2%+rc>0%', lambda v: v['pre7_ret'] <= 2 and v['reg_day_chg'] > 0),
        ('D+1>0%', lambda v: v['post_returns'].get(1, 0) > 0),
        ('pre7<=2%+rc>0%+D+1>0%', lambda v: v['pre7_ret'] <= 2 and v['reg_day_chg'] > 0 and v['post_returns'].get(1, 0) > 0),
    ]

    for (boff, soff) in windows:
        label = f'D+{boff} → D+{soff} (持有{soff-boff}天)'
        print(f"\n  {label}:")
        for rname, rule in best_rules:
            subset = [v for v in valid if rule(v)]
            pcts = []
            for v in subset:
                b_ret = v['post_returns'].get(boff) if boff > 0 else 0
                s_ret = v['post_returns'].get(soff)
                if b_ret is not None and s_ret is not None:
                    entry = v['reg_price'] * (1 + b_ret / 100)
                    exit_ret = ((v['reg_price'] * (1 + s_ret / 100) - entry) / entry) * 100
                    pcts.append(exit_ret)

            if len(pcts) >= 10:
                avg = sum(pcts) / len(pcts)
                win = sum(1 for x in pcts if x > 0) / len(pcts) * 100
                print(f"    {rname:<30} 平均{avg:>+5.2f}%  胜率{win:>5.1f}%  样本{len(pcts)}")


if __name__ == '__main__':
    main()
