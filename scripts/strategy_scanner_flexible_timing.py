#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扩展策略扫描 — 灵活买卖时机 + 新因子探索

扫描:
  1) 计算扩展因子（MA偏离、ATR、振幅、量趋势等）
  2) 测试不同买入时机 (D+1 ~ D+5 开盘)
  3) 测试不同退出策略 (D+9固定, TP7/SL7, TP5/SL5, TP3/SL3, Trailing Stop)
  4) 单因子相关性分析
  5) 组合策略扫描（双因子/三因子）

用法:
  python3 scripts/strategy_scanner_flexible_timing.py          # 全量扫描
  python3 scripts/strategy_scanner_flexible_timing.py --limit 200
  python3 scripts/strategy_scanner_flexible_timing.py --top    # 只看最优组合
"""
import sys, os, re, math
from datetime import datetime
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.backtest_cache import BacktestCache


# ========== 基础工具 ==========

def find_idx(sd, target):
    result = 0
    for i, d in enumerate(sd):
        if d <= target:
            result = i
        else:
            break
    return result


# ========== 扩展因子计算 ==========

def calc_extended_factors(prices, sd, ri):
    """
    计算扩展因子集合
    ri: 注册日在 sd 中的索引
    """
    if ri < 20:
        return None

    reg_close = prices[sd[ri]]['close']
    reg_high = prices[sd[ri]]['high']
    reg_low = prices[sd[ri]]['low']
    reg_vol = prices[sd[ri]].get('volume', 0)

    if reg_close <= 0:
        return None

    # --- 原始因子 ---
    pre3 = ((reg_close - prices[sd[ri-3]]['close']) / prices[sd[ri-3]]['close'] * 100) if ri >= 3 else 0
    mom10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0
    rc = ((reg_close - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri > 0 else 0

    vol_avg5 = 0
    if ri >= 5:
        vlist = [prices[sd[ri-k]].get('volume', 0) for k in range(1, 6) if prices[sd[ri-k]].get('volume', 0) > 0]
        if vlist:
            vol_avg5 = sum(vlist) / len(vlist)
    vol_ratio5 = (reg_vol / vol_avg5) if vol_avg5 > 0 else 1

    # --- 新因子 ---
    f = {}
    f['pre3'] = pre3
    f['mom10'] = mom10
    f['rc'] = rc
    f['vol_ratio5'] = vol_ratio5

    # 1. pre5 (前5日涨幅)
    f['pre5'] = ((reg_close - prices[sd[ri-5]]['close']) / prices[sd[ri-5]]['close'] * 100) if ri >= 5 else 0

    # 2. pre7 (前7日涨幅)
    f['pre7'] = ((reg_close - prices[sd[ri-7]]['close']) / prices[sd[ri-7]]['close'] * 100) if ri >= 7 else 0

    # 3. mom20 (前20日动量)
    f['mom20'] = ((reg_close - prices[sd[ri-20]]['close']) / prices[sd[ri-20]]['close'] * 100) if ri >= 20 else 0

    # 4. ma5 偏离 (价格 vs MA5)
    if ri >= 5:
        ma5 = sum(prices[sd[ri-k]]['close'] for k in range(1, 6)) / 5
        f['ma5_pct'] = (reg_close - ma5) / ma5 * 100
    else:
        f['ma5_pct'] = 0

    # 5. ma10 偏离
    if ri >= 10:
        ma10 = sum(prices[sd[ri-k]]['close'] for k in range(1, 11)) / 10
        f['ma10_pct'] = (reg_close - ma10) / ma10 * 100
    else:
        f['ma10_pct'] = 0

    # 6. ma20 偏离
    if ri >= 20:
        ma20 = sum(prices[sd[ri-k]]['close'] for k in range(1, 21)) / 20
        f['ma20_pct'] = (reg_close - ma20) / ma20 * 100
    else:
        f['ma20_pct'] = 0

    # 7. ATR(14) — 注册日真实波幅
    if ri >= 14:
        trs = []
        for k in range(1, 15):
            h = prices[sd[ri-k]]['high']
            l = prices[sd[ri-k]]['low']
            pc = prices[sd[ri-k-1]]['close'] if ri-k-1 >= 0 else prices[sd[ri-k]]['close']
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        atr14 = sum(trs) / len(trs)
        f['atr14_pct'] = (atr14 / reg_close * 100) if reg_close > 0 else 0
    else:
        f['atr14_pct'] = 0

    # 8. 振幅 (注册日 high-low)
    f['range_day'] = ((reg_high - reg_low) / prices[sd[ri-1]]['close'] * 100) if ri > 0 and prices[sd[ri-1]]['close'] > 0 else 0

    # 9. 近3日平均振幅
    if ri >= 3:
        ranges = []
        for k in range(1, 4):
            r = (prices[sd[ri-k]]['high'] - prices[sd[ri-k]]['low']) / prices[sd[ri-k]]['close'] * 100 if prices[sd[ri-k]]['close'] > 0 else 0
            ranges.append(r)
        f['range3_avg'] = sum(ranges) / len(ranges)
    else:
        f['range3_avg'] = 0

    # 10. vol_ratio3 (3日量比)
    if ri >= 3:
        v3 = [prices[sd[ri-k]].get('volume', 0) for k in range(1, 4) if prices[sd[ri-k]].get('volume', 0) > 0]
        vol_avg3 = sum(v3) / len(v3) if v3 else 0
        f['vol_ratio3'] = (reg_vol / vol_avg3) if vol_avg3 > 0 else 1
    else:
        f['vol_ratio3'] = 1

    # 11. vol_ratio10 (10日量比)
    if ri >= 10:
        v10 = [prices[sd[ri-k]].get('volume', 0) for k in range(1, 11) if prices[sd[ri-k]].get('volume', 0) > 0]
        vol_avg10 = sum(v10) / len(v10) if v10 else 0
        f['vol_ratio10'] = (reg_vol / vol_avg10) if vol_avg10 > 0 else 1
    else:
        f['vol_ratio10'] = 1

    # 12. 量趋势 (vol_trend): 近5日成交量线性回归斜率
    if ri >= 5:
        vols = [prices[sd[ri-k]].get('volume', 0) for k in range(5, 0, -1)]
        if vols and sum(vols) > 0:
            avg_v = sum(vols) / len(vols)
            if avg_v > 0:
                i_mean = 3.0
                denom = sum((i - i_mean)**2 for i in range(1, 6))
                if denom > 0:
                    slope = sum((i - i_mean) * (v - avg_v) for i, v in zip(range(1, 6), vols)) / denom
                    f['vol_trend'] = slope / avg_v * 100
                else:
                    f['vol_trend'] = 0
            else:
                f['vol_trend'] = 0
        else:
            f['vol_trend'] = 0
    else:
        f['vol_trend'] = 0

    # 13. consecutive_up — 注册日前连续上涨天数
    consec_up = 0
    for k in range(1, ri):
        prev_c = prices[sd[ri-k]]['close']
        curr_c = reg_close if k == 1 else prices[sd[ri-k+1]]['close']
        if curr_c > prev_c:
            consec_up += 1
        else:
            break
    f['consec_up'] = consec_up

    # 14. consec_down
    consec_down = 0
    for k in range(1, ri):
        prev_c = prices[sd[ri-k]]['close']
        curr_c = reg_close if k == 1 else prices[sd[ri-k+1]]['close']
        if curr_c < prev_c:
            consec_down += 1
        else:
            break
    f['consec_down'] = consec_down

    # 15. 20日高点距离
    if ri >= 20:
        high20 = max(prices[sd[ri-k]]['high'] for k in range(1, 21))
        f['dist_high20'] = (reg_close - high20) / high20 * 100 if high20 > 0 else 0
    else:
        f['dist_high20'] = 0

    # 16. 20日低点距离
    if ri >= 20:
        low20 = min(prices[sd[ri-k]]['low'] for k in range(1, 21))
        f['dist_low20'] = (reg_close - low20) / low20 * 100 if low20 > 0 else 0
    else:
        f['dist_low20'] = 0

    # 17. close_position — 收盘价在当日振幅中的位置
    day_range = reg_high - reg_low
    f['close_pos'] = ((reg_close - reg_low) / day_range) if day_range > 0 else 0.5

    # 18. 反转因子
    f['reversal_flag'] = 1 if (pre3 > 0 and mom10 < 0) else 0

    # 19. 缩量+下跌共振
    f['shrink_drop'] = 1 if (pre3 < -2 and vol_ratio5 < 0.8) else 0

    return f


# ========== 数据池构建 ==========

def build_pool(cache):
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
        reg = prices[sd[ri]]
        if reg['close'] <= 0 or ri < 20:
            continue

        factors = calc_extended_factors(prices, sd, ri)
        if not factors:
            continue

        hold_days = []
        for off in range(1, 21):
            idx = ri + off
            if idx >= len(sd) or sd[idx] > today_str:
                break
            p = prices[sd[idx]]
            hold_days.append({
                'off': off, 'date': sd[idx],
                'open': p.get('open', 0), 'close': p.get('close', 0),
                'high': p.get('high', 0), 'low': p.get('low', 0),
            })

        pool.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'factors': factors,
            'reg_idx': ri,
            'hold_days': hold_days,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    return pool


# ========== 回测引擎 ==========

def get_buy_price(pool_item, buy_offset):
    for d in pool_item['hold_days']:
        if d['off'] == buy_offset:
            return d['open']
    return None


def test_exit(hold_days, buy_price, exit_fn):
    if not hold_days or buy_price is None or buy_price <= 0:
        return None

    for i, day in enumerate(hold_days):
        if day['close'] <= 0:
            continue
        ret_pct, triggered = exit_fn(day, buy_price, i, hold_days)
        if triggered:
            return {'ret': ret_pct, 'hold': day['off']}

    last = hold_days[-1]
    return {'ret': ((last['close'] - buy_price) / buy_price * 100), 'hold': last['off']}


def exit_fixed(d9):
    def fn(day, buy, i, hds):
        if day['off'] == d9:
            return ((day['close'] - buy) / buy * 100), True
        return 0, False
    return fn


def exit_tp_sl(tp, sl):
    def fn(day, buy, i, hds):
        ret = ((day['close'] - buy) / buy * 100)
        if ret >= tp:
            return ret, True
        if ret <= -sl:
            return ret, True
        if day['off'] >= 10:
            return ret, True
        return ret, False
    return fn


def exit_trailing_stop(pct):
    def fn(day, buy, i, hds):
        if i == 0:
            return 0, False
        peak = buy
        for j in range(0, i + 1):
            if hds[j]['close'] > peak:
                peak = hds[j]['close']
        pullback = ((peak - day['close']) / peak * 100)
        ret = ((day['close'] - buy) / buy * 100)
        if pullback >= pct:
            return ret, True
        if day['off'] >= 10:
            return ret, True
        return ret, False
    return fn


def calc_stats(trades):
    if not trades:
        return None
    n = len(trades)
    rets = [t['ret'] for t in trades]
    avg = sum(rets) / n
    std = (sum((x - avg)**2 for x in rets) / n) ** 0.5
    sh = avg / std if std > 0 else 0
    win = sum(1 for x in rets if x > 0) / n * 100
    avg_hold = sum(t['hold'] for t in trades) / n
    return {'n': n, 'avg': avg, 'win': win, 'std': std, 'sharpe': sh, 'avg_hold': avg_hold,
            'best': max(rets), 'worst': min(rets)}


# ========== 单因子扫描 ==========

def scan_single_factor(pool, factor_key, buy_offsets, exit_fns, label=""):
    best = []
    for buy_off in buy_offsets:
        for exit_name, exit_fn in exit_fns:
            for threshold in [-5, -3, -2, -1, 0, 1, 2, 3, 5, 8, 10, 15]:
                for direction in ['<=', '>=']:
                    def cond(f, fk=factor_key, th=threshold, d=direction):
                        val = f.get(fk, 0)
                        if d == '<=':
                            return val <= th
                        else:
                            return val >= th

                    triggered = []
                    for p in pool:
                        f = p['factors']
                        if cond(f):
                            bp = get_buy_price(p, buy_off)
                            if bp and bp > 0:
                                triggered.append((p, bp))

                    if len(triggered) < 5:
                        continue

                    trades = []
                    for p, bp in triggered:
                        r = test_exit(p['hold_days'], bp, exit_fn)
                        if r:
                            trades.append(r)

                    if len(trades) < 5:
                        continue

                    stats = calc_stats(trades)
                    signal_rate = len(triggered) / len(pool) * 100

                    if stats and stats['n'] >= 5 and signal_rate >= 5:
                        best.append({
                            'factor': factor_key,
                            'threshold': threshold,
                            'direction': direction,
                            'buy_off': buy_off,
                            'exit': exit_name,
                            'label': label,
                            'signal_rate': signal_rate,
                            **stats,
                        })

    best.sort(key=lambda x: x['sharpe'], reverse=True)
    return best[:20]


# ========== 组合策略扫描 ==========

def scan_combo(pool, factor_a, factor_b, buy_offsets, exit_fns):
    best = []
    for buy_off in buy_offsets:
        for exit_name, exit_fn in exit_fns:
            for th_a in [-3, -2, -1, 0, 1, 2, 3, 5]:
                for th_b in [-2, -1, 0, 0.5, 0.8, 1, 1.5, 2]:
                    triggered = []
                    for p in pool:
                        f = p['factors']
                        fa = f.get(factor_a, 0)
                        fb = f.get(factor_b, 0)
                        if fa <= th_a and fb <= th_b:
                            bp = get_buy_price(p, buy_off)
                            if bp and bp > 0:
                                triggered.append((p, bp))

                    if len(triggered) < 5:
                        continue

                    trades = []
                    for p, bp in triggered:
                        r = test_exit(p['hold_days'], bp, exit_fn)
                        if r:
                            trades.append(r)

                    if len(trades) < 5:
                        continue

                    stats = calc_stats(trades)
                    signal_rate = len(triggered) / len(pool) * 100
                    if stats and stats['n'] >= 5 and signal_rate >= 5:
                        best.append({
                            'a': f"{factor_a}<={th_a}",
                            'b': f"{factor_b}<={th_b}",
                            'buy_off': buy_off,
                            'exit': exit_name,
                            'signal_rate': signal_rate,
                            **stats,
                        })

    best.sort(key=lambda x: x['sharpe'], reverse=True)
    return best[:30]


# ========== 输出格式化 ==========

def print_top(strategies, title, top_n=15):
    print(f"\n{'='*120}")
    print(f"  {title}")
    print(f"{'='*120}")
    print(f"  {'#':>3} {'因子/条件':<40} {'买入':>5} {'退出':>12} {'样本':>4} {'信号率':>6} {'平均':>7} {'胜率':>6} {'夏普':>6} {'持有':>5}")
    print("  " + "-" * 110)
    for i, s in enumerate(strategies[:top_n], 1):
        print(f"  {i:>3} {str(s.get('label', '')):<40} D+{s['buy_off']:>3} {s['exit']:>12} {s['n']:>4} {s['signal_rate']:>5.1f}% {s['avg']:>+6.2f}% {s['win']:>5.1f}% {s['sharpe']:>+5.2f} {s['avg_hold']:>4.1f}d")


def print_factor_corr(pool, buy_off, exit_name, exit_fn):
    print(f"\n{'='*120}")
    print(f"  因子相关性 (买入=D+{buy_off}, 退出={exit_name})")
    print(f"{'='*120}")

    factor_keys = [k for k in pool[0]['factors'].keys() if k not in ('buy_price', 'current_close', 'current_date', 'days_since', 'pnl_pct')]

    correlations = []
    for fk in factor_keys:
        pairs = []
        for p in pool:
            bp = get_buy_price(p, buy_off)
            if not bp or bp <= 0:
                continue
            r = test_exit(p['hold_days'], bp, exit_fn)
            if r:
                pairs.append((p['factors'].get(fk, 0), r['ret']))

        if len(pairs) < 20:
            continue

        xs = [x[0] for x in pairs]
        ys = [x[1] for x in pairs]
        n = len(pairs)
        mx = sum(xs) / n
        my = sum(ys) / n
        cov = sum((x - mx) * (y - my) for x, y in pairs) / n
        sdx = (sum((x - mx)**2 for x in xs) / n) ** 0.5
        sdy = (sum((y - my)**2 for y in ys) / n) ** 0.5
        corr = (cov / (sdx * sdy)) if sdx > 0 and sdy > 0 else 0

        sorted_pairs = sorted(pairs, key=lambda x: x[0])
        n_half = len(sorted_pairs) // 2
        low_half = sorted_pairs[:n_half]
        high_half = sorted_pairs[n_half:]

        def sh(trades_list):
            rets = [t[1] for t in trades_list]
            if len(rets) < 3:
                return 0
            a = sum(rets) / len(rets)
            s = (sum((x - a)**2 for x in rets) / len(rets)) ** 0.5
            return a / s if s > 0 else 0

        sh_low = sh(low_half)
        sh_high = sh(high_half)

        correlations.append({
            'factor': fk,
            'corr': corr,
            'sh_low': sh_low,
            'sh_high': sh_high,
        })

    correlations.sort(key=lambda x: abs(x['corr']), reverse=True)

    print(f"  {'因子':<20} {'相关系数':>10} {'低分组夏普':>12} {'高分组夏普':>12}")
    print("  " + "-" * 56)
    for c in correlations:
        sh_low_str = f"{c['sh_low']:+.2f}"
        sh_high_str = f"{c['sh_high']:+.2f}"
        print(f"  {c['factor']:<20} {c['corr']:>+9.3f} {sh_low_str:>12} {sh_high_str:>12}")


# ========== 主入口 ==========

def main():
    args = sys.argv[1:]
    limit = None
    show_top = False

    i = 0
    while i < len(args):
        if args[i] == '--limit' and i + 1 < len(args):
            limit = int(args[i+1])
            i += 2
        elif args[i] == '--top':
            show_top = True
            i += 1
        else:
            i += 1

    print("="*120)
    print("  灵活买卖时机策略扫描 — 扩展因子探索")
    print("="*120)

    cache = BacktestCache()
    pool = build_pool(cache)

    if limit:
        pool = pool[:limit]

    print(f"\n  总样本: {len(pool)}")

    exit_fns = [
        ('D+9固定', exit_fixed(9)),
        ('TP7/SL7', exit_tp_sl(7, 7)),
        ('TP5/SL5', exit_tp_sl(5, 5)),
        ('TP3/SL3', exit_tp_sl(3, 3)),
        ('TS3%', exit_trailing_stop(3)),
        ('TS5%', exit_trailing_stop(5)),
    ]
    buy_offsets = [1, 2, 3, 5]

    # 1. 因子相关性
    print(f"\n  📊 步骤 1/4: 因子相关性分析...")
    print_factor_corr(pool, 1, 'D+9固定', exit_fixed(9))

    # 2. 最优买卖时机
    if show_top:
        print(f"\n  📊 步骤 2/4: 最优买卖时机组合...")
        best_combos = []
        for exit_name, exit_fn in exit_fns:
            for buy_off in buy_offsets:
                trades = []
                for p in pool:
                    bp = get_buy_price(p, buy_off)
                    if not bp or bp <= 0:
                        continue
                    r = test_exit(p['hold_days'], bp, exit_fn)
                    if r:
                        trades.append(r)
                if len(trades) >= 20:
                    stats = calc_stats(trades)
                    stats['exit'] = exit_name
                    stats['buy_off'] = buy_off
                    best_combos.append(stats)

        best_combos.sort(key=lambda x: x['sharpe'], reverse=True)
        print_top(best_combos, "最优买卖时机 (全量样本)", top_n=20)

    # 3. 单因子扫描
    print(f"\n  📊 步骤 3/4: 单因子策略扫描...")
    factor_keys = ['pre3', 'mom10', 'pre5', 'pre7', 'mom20',
                   'ma5_pct', 'ma10_pct', 'ma20_pct',
                   'atr14_pct', 'range_day', 'range3_avg',
                   'vol_ratio5', 'vol_ratio3', 'vol_ratio10', 'vol_trend',
                   'consec_up', 'consec_down', 'close_pos']

    all_best = []
    for fk in factor_keys:
        result = scan_single_factor(pool, fk, buy_offsets, exit_fns, label=fk)
        all_best.extend(result)

    all_best.sort(key=lambda x: x['sharpe'], reverse=True)
    print_top(all_best, "单因子扫描 Top 25 (按夏普)", top_n=25)

    # 4. 组合扫描
    print(f"\n  📊 步骤 4/4: 双因子组合扫描...")
    top_factors = ['vol_ratio5', 'pre3', 'mom10', 'vol_trend', 'ma10_pct', 'pre5', 'consec_down', 'ma5_pct']
    combo_best = []
    for i in range(len(top_factors)):
        for j in range(i+1, len(top_factors)):
            result = scan_combo(pool, top_factors[i], top_factors[j], buy_offsets, exit_fns)
            combo_best.extend(result)

    combo_best.sort(key=lambda x: x['sharpe'], reverse=True)
    print(f"\n{'='*120}")
    print(f"  双因子组合扫描 Top 25 (按夏普)")
    print(f"{'='*120}")
    print(f"  {'#':>3} {'条件A':<18} {'条件B':<18} {'买入':>5} {'退出':>12} {'样本':>4} {'信号率':>6} {'平均':>7} {'胜率':>6} {'夏普':>6} {'持有':>5}")
    print("  " + "-" * 120)
    for i, c in enumerate(combo_best[:25], 1):
        print(f"  {i:>3} {c['a']:<18} {c['b']:<18} D+{c['buy_off']:>3} {c['exit']:>12} {c['n']:>4} {c['signal_rate']:>5.1f}% {c['avg']:>+6.2f}% {c['win']:>5.1f}% {c['sharpe']:>+5.2f} {c['avg_hold']:>4.1f}d")

    print(f"\n{'='*120}")
    print(f"  扫描完成")
    print(f"{'='*120}")


if __name__ == '__main__':
    main()
