#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对比扫描脚本和回测脚本的逻辑差异
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


def load_events(cache):
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
        reg_close = prices[sd[ri]]['close']
        if reg_close <= 0 or ri < 10: continue

        reg_day = prices[sd[ri]]
        vol_avg5 = 0
        if ri >= 5:
            vols = [prices[sd[ri-k]].get('volume',0) for k in range(1,6) if prices[sd[ri-k]].get('volume',0)>0]
            if vols: vol_avg5 = sum(vols)/len(vols)

        future = []
        for off in range(1, 16):
            idx = ri + off
            if idx >= len(sd) or sd[idx] > today_str: break
            p = prices[sd[idx]]
            future.append({
                'off': off, 'date': sd[idx],
                'open': p.get('open',0), 'close': p.get('close',0),
                'high': p.get('high',0), 'low': p.get('low',0),
                'volume': p.get('volume',0),
            })
        if len(future) < 2: continue

        events.append({
            'code': sc, 'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor, 'reg_close': reg_close,
            'reg_day': reg_day, 'vol_avg5': vol_avg5, 'future': future,
        })
    events.sort(key=lambda x: x['anchor'], reverse=True)
    return events


def simulate_scan_style(events, vol_thresh=1.5, tp=3.0, max_scan=10, max_hold=10):
    """模仿扫描脚本的逻辑: 信号日当天开盘买入"""
    trades = []
    for ev in events:
        future = ev['future']
        vol_avg5 = ev['vol_avg5']
        if vol_avg5 <= 0: continue

        signal_off = None
        for off in range(0, min(len(future), max_scan)):
            day = future[off]
            if day['open'] <= 0 or day['volume'] <= 0: continue
            ret_body = ((day['close'] - day['open']) / day['open'] * 100) if day['open'] > 0 else 0
            if day['volume'] > vol_avg5 * vol_thresh and ret_body > 1:
                signal_off = off
                break

        if signal_off is None: continue

        # 扫描脚本用的是信号日当天开盘
        buy_idx = signal_off
        buy_day = future[buy_idx]
        if buy_day['open'] <= 0: continue
        buy_price = buy_day['open']
        buy_off = buy_idx

        exit_off = None
        exit_price = None
        for off in range(buy_idx + 1, min(len(future), buy_idx + 1 + max_hold)):
            day = future[off]
            if day['close'] <= 0: continue
            ret = ((day['close'] - buy_price) / buy_price) * 100
            if ret >= tp:
                exit_off = off
                exit_price = day['close']
                break
            if ((buy_price - day['close']) / buy_price * 100) >= tp:
                exit_off = off
                exit_price = day['close']
                break

        if exit_off is None:
            last_off = min(buy_idx + max_hold - 1, len(future) - 1)
            exit_off = last_off
            exit_price = future[last_off]['close']

        ret = ((exit_price - buy_price) / buy_price) * 100
        trades.append({'ret': ret, 'hold': exit_off - buy_off, 'code': ev['code']})
    return trades


def simulate_nextday_style(events, vol_thresh=1.5, tp=3.0, max_scan=10, max_hold=10):
    """次日开盘买入"""
    trades = []
    for ev in events:
        future = ev['future']
        vol_avg5 = ev['vol_avg5']
        if vol_avg5 <= 0: continue

        signal_off = None
        for off in range(0, min(len(future), max_scan)):
            day = future[off]
            if day['open'] <= 0 or day['volume'] <= 0: continue
            ret_body = ((day['close'] - day['open']) / day['open'] * 100) if day['open'] > 0 else 0
            if day['volume'] > vol_avg5 * vol_thresh and ret_body > 1:
                signal_off = off
                break

        if signal_off is None: continue

        # 次日开盘
        buy_idx = signal_off + 1
        if buy_idx >= len(future): continue
        buy_day = future[buy_idx]
        if buy_day['open'] <= 0: continue
        buy_price = buy_day['open']
        buy_off = buy_idx

        exit_off = None
        exit_price = None
        for off in range(buy_idx + 1, min(len(future), buy_idx + 1 + max_hold)):
            day = future[off]
            if day['close'] <= 0: continue
            ret = ((day['close'] - buy_price) / buy_price) * 100
            if ret >= tp:
                exit_off = off
                exit_price = day['close']
                break
            if ((buy_price - day['close']) / buy_price * 100) >= tp:
                exit_off = off
                exit_price = day['close']
                break

        if exit_off is None:
            last_off = min(buy_idx + max_hold - 1, len(future) - 1)
            exit_off = last_off
            exit_price = future[last_off]['close']

        ret = ((exit_price - buy_price) / buy_price) * 100
        trades.append({'ret': ret, 'hold': exit_off - buy_off, 'code': ev['code']})
    return trades


def calc(trades):
    if not trades: return None
    rets = sorted([t['ret'] for t in trades])
    n = len(rets)
    avg = sum(rets)/n
    std = (sum((x-avg)**2 for x in rets)/n)**0.5
    sh = avg/std if std > 0 else 0
    win = sum(1 for x in rets if x > 0)/n*100
    return {'n':n, 'avg':avg, 'med':rets[n//2], 'win':win, 'std':std, 'sharpe':sh}


def main():
    cache = BacktestCache()
    print("加载事件...", flush=True)
    events = load_events(cache)
    print(f"  总: {len(events)}")

    # 对比信号日 vs 次日买入
    for label, sim in [('信号日开盘', simulate_scan_style), ('次日开盘', simulate_nextday_style)]:
        print(f"\n{'='*60}")
        print(f"{label}买入")
        print(f"{'='*60}")
        for limit in [100, 150, 200, 300, 0]:
            sample = events[:limit] if limit > 0 else events
            trades = sim(sample)
            st = calc(trades)
            if st:
                avg_hold = sum(t['hold'] for t in trades)/len(trades)
                print(f"  limit={limit if limit > 0 else 'all'}: n={st['n']} avg={st['avg']:+.2f}% "
                      f"win={st['win']:.0f}% sh={st['sharpe']:+.2f} hold={avg_hold:.1f}d")

    # 深入分析: 为什么信号日买入效果好?
    print("\n" + "=" * 60)
    print("信号日 vs 次日 买入价差异分析 (limit=200)")
    print("=" * 60)

    sample = events[:200]
    st_trades = simulate_scan_style(sample)
    nt_trades = simulate_nextday_style(sample)

    # 逐只对比
    # 需要同一个信号触发才能对比
    for ev in sample[:20]:
        future = ev['future']
        vol_avg5 = ev['vol_avg5']
        if vol_avg5 <= 0: continue

        signal_off = None
        for off in range(0, min(len(future), 10)):
            day = future[off]
            if day['open'] <= 0 or day['volume'] <= 0: continue
            ret_body = ((day['close'] - day['open']) / day['open'] * 100) if day['open'] > 0 else 0
            if day['volume'] > vol_avg5 * 1.5 and ret_body > 1:
                signal_off = off
                break

        if signal_off is None: continue

        sig_day = future[signal_off]
        next_day = future[signal_off + 1] if signal_off + 1 < len(future) else None
        if next_day is None: continue

        gap = ((next_day['open'] - sig_day['close']) / sig_day['close'] * 100)
        print(f"  {ev['name'][:10]} {ev['anchor']} D+{signal_off}: "
              f"信号日收{sig_day['close']:.2f} → 次日开{next_day['open']:.2f} 跳{gap:+.2f}%")


if __name__ == '__main__':
    main()
