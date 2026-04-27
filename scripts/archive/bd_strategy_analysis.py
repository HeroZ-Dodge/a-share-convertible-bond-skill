#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BD策略深度分析 — 年份分组、vol阈值优化、触发日分布
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


def build_events(cache):
    today_str = datetime.now().strftime('%Y-%m-%d')
    bonds = cache.get_jisilu_bonds(phase='注册', limit=0)
    events = []
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
        if reg_price <= 0 or ri < 10: continue

        future = []
        for off in range(1, 16):
            idx = ri + off
            if idx >= len(sd) or sd[idx] > today_str: break
            p = prices[sd[idx]]
            future.append({
                'off': off, 'date': sd[idx],
                'close': p.get('close', 0), 'open': p.get('open', 0),
                'high': p.get('high', 0), 'low': p.get('low', 0),
                'volume': p.get('volume', 0),
            })
        if len(future) < 3: continue

        reg_day = prices[sd[ri]]
        vol_avg5 = 0
        if ri >= 5:
            vols = [prices[sd[ri-k]].get('volume',0) for k in range(1,6) if prices[sd[ri-k]].get('volume',0)>0]
            if vols: vol_avg5 = sum(vols)/len(vols)

        events.append({
            'code': sc, 'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'reg_close': reg_day.get('close', 0),
            'reg_high': reg_day.get('high', 0),
            'reg_low': reg_day.get('low', 99999),
            'vol_avg5': vol_avg5,
            'future': future,
        })

    events.sort(key=lambda x: x['anchor'], reverse=True)
    return events


def simulate_bd(events, vol_thresh=1.5, take_profit=3.0, max_hold=10):
    """BD策略: 放量突破买入 + 止盈卖出"""
    trades = []
    for ev in events:
        future = ev['future']
        entry_off = None
        entry_price = None

        for off in range(0, min(len(future), max_hold)):
            day = future[off]
            vol = day.get('volume', 0)
            if day['open'] <= 0: continue
            ret_body = ((day['close'] - day['open']) / day['open'] * 100)
            if vol > ev['vol_avg5'] * vol_thresh and ret_body > 1:
                entry_off = off
                entry_price = day['open']
                break

        if entry_off is None or entry_price <= 0:
            continue

        # 卖出
        exit_off = None
        exit_price = None
        exit_reason = ''

        for off in range(entry_off + 1, min(len(future), entry_off + 1 + max_hold)):
            day = future[off]
            if day['close'] <= 0: continue
            ret = ((day['close'] - entry_price) / entry_price) * 100
            if ret >= take_profit:
                exit_off = off
                exit_price = day['close']
                exit_reason = 'profit'
                break
            if ((entry_price - day['close']) / entry_price * 100) >= 3:
                exit_off = off
                exit_price = day['close']
                exit_reason = 'stop'
                break

        if exit_off is None:
            last_idx = min(entry_off + max_hold, len(future) - 1)
            exit_off = future[last_idx]['off'] - 1 if last_idx >= 0 else entry_off
            exit_price = future[last_idx]['close'] if last_idx >= 0 else entry_price
            exit_reason = 'timeout'

        if exit_off <= entry_off:
            exit_off = entry_off + 1
            if exit_off < len(future):
                exit_price = future[exit_off]['close']
            else:
                continue

        ret = ((exit_price - entry_price) / entry_price) * 100
        hold = exit_off - entry_off

        trades.append({
            'code': ev['code'], 'anchor': ev['anchor'], 'name': ev['name'],
            'entry_off': entry_off, 'exit_off': exit_off, 'hold': hold,
            'ret': ret, 'entry_price': entry_price, 'exit_price': exit_price,
            'reason': exit_reason,
        })

    return trades


def calc(strets):
    if len(strets) < 5: return None
    s = sorted(strets)
    n = len(s)
    avg = sum(s)/n
    win_n = sum(1 for x in s if x > 0)
    std = (sum((x-avg)**2 for x in s)/n)**0.5
    sh = avg/std if std > 0 else 0
    return {'n':n, 'avg':avg, 'med':s[n//2], 'win':win_n/n*100, 'std':std, 'sharpe':sh,
            'best':max(s), 'worst':min(s)}


def main():
    cache = BacktestCache()
    print("加载事件...", flush=True)
    events = build_events(cache)
    print(f"  总: {len(events)}")

    # ========== 1) vol 阈值优化 ==========
    print("\n" + "=" * 80)
    print("vol 阈值优化 (BD+止盈3%)")
    print("=" * 80)

    for vol_t in [1.2, 1.3, 1.5, 1.8, 2.0, 2.5, 3.0]:
        sample = events[:200]
        trades = simulate_bd(sample, vol_thresh=vol_t, take_profit=3.0)
        rets = [t['ret'] for t in trades]
        st = calc(rets)
        if st:
            avg_hold = sum(t['hold'] for t in trades)/len(trades)
            print(f"  vol>{vol_t:.1f}: n={st['n']} avg={st['avg']:+.2f}% "
                  f"win={st['win']:.0f}% sh={st['sharpe']:+.2f} hold={avg_hold:.1f}d")

    # ========== 2) 止盈阈值优化 ==========
    print("\n" + "=" * 80)
    print("止盈阈值优化 (vol>1.5)")
    print("=" * 80)

    for tp in [2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0]:
        sample = events[:200]
        trades = simulate_bd(sample, vol_thresh=1.5, take_profit=tp)
        rets = [t['ret'] for t in trades]
        st = calc(rets)
        if st:
            avg_hold = sum(t['hold'] for t in trades)/len(trades)
            print(f"  TP≥{tp:.1f}%: n={st['n']} avg={st['avg']:+.2f}% "
                  f"win={st['win']:.0f}% sh={st['sharpe']:+.2f} hold={avg_hold:.1f}d")

    # ========== 3) 年份稳定性 ==========
    print("\n" + "=" * 80)
    print("年份稳定性 (vol>1.5, TP≥3%)")
    print("=" * 80)

    for yr in ['2020','2021','2022','2023','2024','2025','2026']:
        yr_events = [e for e in events if e['anchor'].startswith(yr)]
        if len(yr_events) < 3: continue
        trades = simulate_bd(yr_events, vol_thresh=1.5, take_profit=3.0)
        rets = [t['ret'] for t in trades]
        st = calc(rets)
        if st:
            avg_hold = sum(t['hold'] for t in trades)/len(trades) if trades else 0
            reasons = {}
            for t in trades:
                reasons[t['reason']] = reasons.get(t['reason'], 0) + 1
            print(f"  {yr}: n={st['n']} avg={st['avg']:+.2f}% "
                  f"win={st['win']:.0f}% sh={st['sharpe']:+.2f} hold={avg_hold:.1f}d "
                  f"触发率={len(yr_events)}")
            if reasons:
                print(f"    卖出原因: {reasons}")

    # ========== 4) 买入日分布 ==========
    print("\n" + "=" * 80)
    print("买入日分布 (在D+N天触发)")
    print("=" * 80)

    sample = events[:200]
    trades = simulate_bd(sample, vol_thresh=1.5, take_profit=3.0)
    if trades:
        by_entry = {}
        for t in trades:
            by_entry[t['entry_off']] = by_entry.get(t['entry_off'], 0) + 1
        for off in sorted(by_entry.keys()):
            sub = [t for t in trades if t['entry_off'] == off]
            rets = [t['ret'] for t in sub]
            st = calc(rets)
            if st:
                print(f"  D+{off}: {by_entry[off]}只  avg={st['avg']:+.2f}% "
                      f"win={st['win']:.0f}% sh={st['sharpe']:+.2f}")

    # ========== 5) 不加止损 vs 加止损 ==========
    print("\n" + "=" * 80)
    print("止损对比")
    print("=" * 80)

    sample = events[:200]

    # 无止损
    trades_np = simulate_bd(sample, vol_thresh=1.5, take_profit=3.0)

    # 加3%止损 (already included in simulate_bd)
    # 模拟有止损的版本
    print(f"\n  BD+TP3% (含3%止损):")
    reasons = {}
    for t in trades_np:
        reasons[t['reason']] = reasons.get(t['reason'], 0) + 1
    rets = [t['ret'] for t in trades_np]
    st = calc(rets)
    if st:
        print(f"    n={st['n']} avg={st['avg']:+.2f}% win={st['win']:.0f}% "
              f"sh={st['sharpe']:+.2f} worst={st['worst']:.2f}%")
        print(f"    卖出原因: {reasons}")

    # ========== 6) 最佳组合完整报告 ==========
    print("\n" + "=" * 80)
    print("BD策略完整报告 (全样本)")
    print("=" * 80)

    for sample_sz in [100, 150, 200, 300]:
        trades = simulate_bd(events[:sample_sz], vol_thresh=1.5, take_profit=3.0)
        rets = [t['ret'] for t in trades]
        st = calc(rets)
        if st:
            avg_hold = sum(t['hold'] for t in trades)/len(trades) if trades else 0
            profit_n = sum(1 for t in trades if t['reason']=='profit')
            stop_n = sum(1 for t in trades if t['reason']=='stop')
            print(f"  limit={sample_sz}: n={st['n']} avg={st['avg']:+.2f}% "
                  f"win={st['win']:.0f}% sh={st['sharpe']:+.2f} "
                  f"hold={avg_hold:.1f}d  profit={profit_n} stop={stop_n}")


if __name__ == '__main__':
    main()
