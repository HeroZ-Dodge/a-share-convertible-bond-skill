#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BD动态策略回测 — 放量突破买入 + 止盈止损卖出

⚠️ 重要发现:
  扫描脚本用"信号日开盘"买入(夏普+0.76)，但这是不可执行的
  信号(放量+收涨>1%)需要到收盘才能确认，实际只能用次日开盘买入
  次日开盘买入的结果: 夏普≈0，策略无效

买入方式:
  signal: 信号日开盘买入(理论回测，展示扫描结果)
  next:   次日开盘买入(实际可执行，默认)

用法:
  python3 scripts/backtest_bd_strategy.py                  # 次日开盘(默认)
  python3 scripts/backtest_bd_strategy.py --entry signal   # 信号日开盘
  python3 scripts/backtest_bd_strategy.py --entry both     # 两种都跑
  python3 scripts/backtest_bd_strategy.py --detail         # 逐只明细
"""
import sys, os, re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.backtest_cache import BacktestCache


def find_idx(sd, target):
    """找 <= target 的最后一个交易日"""
    result = 0
    for i, d in enumerate(sd):
        if d <= target:
            result = i
        else:
            break
    return result


def load_events(cache):
    """加载所有注册事件"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    bonds = cache.get_jisilu_bonds(phase='注册', limit=0)
    events = []
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
        reg_close = prices[sd[ri]]['close']
        if reg_close <= 0 or ri < 10:
            continue

        reg_day = prices[sd[ri]]
        vol_avg5 = 0
        if ri >= 5:
            vols = []
            for k in range(1, 6):
                v = prices[sd[ri - k]].get('volume', 0)
                if v > 0:
                    vols.append(v)
            if vols:
                vol_avg5 = sum(vols) / len(vols)

        future = []
        for off in range(1, 16):
            idx = ri + off
            if idx >= len(sd) or sd[idx] > today_str:
                break
            p = prices[sd[idx]]
            future.append({
                'off': off, 'date': sd[idx],
                'open': p.get('open', 0), 'close': p.get('close', 0),
                'high': p.get('high', 0), 'low': p.get('low', 0),
                'volume': p.get('volume', 0),
            })

        if len(future) < 2:
            continue

        events.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor, 'reg_close': reg_close,
            'reg_day': reg_day, 'vol_avg5': vol_avg5, 'future': future,
        })

    events.sort(key=lambda x: x['anchor'], reverse=True)
    return events


def run_trade(event, vol_thresh, tp_pct, max_scan=10, max_hold=10, entry='next'):
    """执行一次完整的买卖

    entry: 'signal'=信号日开盘, 'next'=次日开盘
    Returns: dict or None
    """
    future = event['future']
    vol_avg5 = event['vol_avg5']
    if vol_avg5 <= 0:
        return None

    # 买入信号扫描
    signal_off = None
    for off in range(0, min(len(future), max_scan)):
        day = future[off]
        if day['open'] <= 0 or day['volume'] <= 0:
            continue
        ret_body = ((day['close'] - day['open']) / day['open'] * 100) if day['open'] > 0 else 0
        if day['volume'] > vol_avg5 * vol_thresh and ret_body > 1:
            signal_off = off
            break

    if signal_off is None:
        return None

    # 买入
    if entry == 'signal':
        buy_idx = signal_off
    else:
        buy_idx = signal_off + 1

    if buy_idx >= len(future):
        return None
    buy_day = future[buy_idx]
    if buy_day['open'] <= 0:
        return None
    buy_price = buy_day['open']
    buy_off = buy_idx

    # 卖出
    exit_off = None
    exit_price = None
    exit_reason = None

    for off in range(buy_idx + 1, min(len(future), buy_idx + 1 + max_hold)):
        day = future[off]
        if day['close'] <= 0:
            continue
        ret = ((day['close'] - buy_price) / buy_price) * 100
        if ret >= tp_pct:
            exit_off = off
            exit_price = day['close']
            exit_reason = '止盈'
            break
        if ((buy_price - day['close']) / buy_price * 100) >= tp_pct:
            exit_off = off
            exit_price = day['close']
            exit_reason = '止损'
            break

    if exit_off is None:
        last_off = min(buy_idx + max_hold - 1, len(future) - 1)
        exit_off = last_off
        exit_price = future[last_off]['close']
        exit_reason = '超时'

    ret = ((exit_price - buy_price) / buy_price) * 100
    hold = exit_off - buy_off

    return {
        'code': event['code'], 'name': event['name'], 'anchor': event['anchor'],
        'reg_close': event['reg_close'],
        'signal_off': signal_off, 'buy_off': buy_off, 'exit_off': exit_off,
        'hold': hold, 'buy_price': buy_price, 'exit_price': exit_price,
        'ret': ret, 'exit_reason': exit_reason,
    }


def report(trades, label):
    """输出统计报告"""
    if not trades:
        print(f"  {label}: 无交易")
        return

    rets = sorted([t['ret'] for t in trades])
    n = len(rets)
    avg = sum(rets) / n
    win_n = sum(1 for x in rets if x > 0)
    win = win_n / n * 100
    std = (sum((x - avg) ** 2 for x in rets) / n) ** 0.5
    sharpe = avg / std if std > 0 else 0
    med = rets[n // 2]
    avg_hold = sum(t['hold'] for t in trades) / n

    reasons = {}
    for t in trades:
        reasons[t['exit_reason']] = reasons.get(t['exit_reason'], 0) + 1

    by_buy = {}
    for t in trades:
        by_buy[t['buy_off']] = by_buy.get(t['buy_off'], 0) + 1

    print(f"\n{'='*90}")
    print(f"{label}")
    print(f"{'='*90}")
    print(f"  样本: {n}")
    print(f"  平均收益: {avg:+.2f}%    中位: {med:+.2f}%")
    print(f"  胜率:   {win:.1f}%  ({win_n}/{n})")
    print(f"  标准差: {std:.2f}%     夏普: {sharpe:+.2f}")
    print(f"  最佳:   +{max(rets):.2f}%    最差: {min(rets):.2f}%")
    print(f"  平均持有: {avg_hold:.1f}天")
    print(f"  卖出原因: {', '.join(f'{k}:{v}只' for k, v in sorted(reasons.items()))}")

    print(f"\n  买入日分布:")
    for off in sorted(by_buy.keys()):
        sub = [t for t in trades if t['buy_off'] == off]
        sub_rets = [t['ret'] for t in sub]
        sub_n = len(sub_rets)
        sub_avg = sum(sub_rets) / sub_n
        sub_win = sum(1 for x in sub_rets if x > 0) / sub_n * 100
        print(f"    D+{off:>2}: {sub_n:>3}只  平均{sub_avg:+.2f}%  胜率{sub_win:.0f}%")


def main():
    vol_thresh = 1.5
    tp_pct = 3.0
    entry_mode = 'next'
    detail = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--vol' and i + 1 < len(args):
            vol_thresh = float(args[i + 1])
            i += 2
        elif args[i] == '--tp' and i + 1 < len(args):
            tp_pct = float(args[i + 1])
            i += 2
        elif args[i] == '--entry' and i + 1 < len(args):
            entry_mode = args[i + 1]
            i += 2
        elif args[i] == '--detail':
            detail = True
            i += 1
        else:
            i += 1

    cache = BacktestCache()
    print("加载注册事件...", flush=True)
    events = load_events(cache)
    print(f"  总注册事件: {len(events)}")

    modes = []
    if entry_mode in ('signal', 'both'):
        modes.append(('信号日开盘(理论)', 'signal'))
    if entry_mode in ('next', 'both'):
        modes.append(('次日开盘(可执行)', 'next'))
    if entry_mode == 'both':
        modes.append(('两种对比', 'both'))

    for label, mode in modes:
        if mode == 'both':
            continue
        print(f"\n策略参数: vol>{vol_thresh}, TP/SL±{tp_pct}%, 扫描D+1~D+10, 持有最多10天")
        print(f"买入方式: {label}", flush=True)

        trades = []
        for ev in events:
            t = run_trade(ev, vol_thresh, tp_pct, entry=mode)
            if t:
                trades.append(t)
        trades.sort(key=lambda x: x['anchor'])

        report(trades, f"BD动态策略 [{label}] — vol>{vol_thresh}, TP/SL±{tp_pct}%")

    # 对比分析
    if entry_mode in ('signal', 'both'):
        trades_sig = []
        for ev in events:
            t = run_trade(ev, vol_thresh, tp_pct, entry='signal')
            if t:
                trades_sig.append(t)

        trades_next = []
        for ev in events:
            t = run_trade(ev, vol_thresh, tp_pct, entry='next')
            if t:
                trades_next.append(t)

        if trades_sig and trades_next:
            sig_rets = [t['ret'] for t in trades_sig]
            next_rets = [t['ret'] for t in trades_next]

            def stats(rets):
                n = len(rets)
                avg = sum(rets) / n
                std = (sum((x - avg) ** 2 for x in rets) / n) ** 0.5
                return n, avg, std, avg / std if std > 0 else 0

            n1, avg1, std1, sh1 = stats(sig_rets)
            n2, avg2, std2, sh2 = stats(next_rets)

            print(f"\n{'='*90}")
            print("两种买入方式对比")
            print(f"{'='*90}")
            print(f"  {'指标':<10} {'信号日开盘':>15} {'次日开盘':>15}")
            print(f"  {'样本':>10} {n1:>15} {n2:>15}")
            print(f"  {'平均':>10} {avg1:>+13.2f}% {avg2:>+13.2f}%")
            print(f"  {'标准差':>10} {std1:>12.2f}% {std2:>12.2f}%")
            print(f"  {'夏普':>10} {sh1:>+13.2f} {sh2:>+13.2f}")

    if detail:
        for label, mode in modes:
            if mode == 'both':
                continue
            trades = []
            for ev in events:
                t = run_trade(ev, vol_thresh, tp_pct, entry=mode)
                if t:
                    trades.append(t)
            trades.sort(key=lambda x: x['ret'], reverse=True)
            print(f"\n{'='*90}")
            print(f"逐只明细 [{label}]")
            print(f"{'='*90}")
            print(f"  {'名称':<12} {'代码':>8} {'注册日':<12} {'信号D':>5} {'买入D':>5} {'卖出D':>5} "
                  f"{'持有':>4} {'买入价':>8} {'卖出价':>8} {'收益':>7} {'原因':<4}")
            print("  " + "-" * 110)
            for t in trades[:30]:
                print(f"  {t['name']:<12} {t['code']:>8} {t['anchor']:<12} "
                      f"D+{t['signal_off']:>4} D+{t['buy_off']:>4} D+{t['exit_off']:>4} "
                      f"{t['hold']:>3}d "
                      f"{t['buy_price']:>8.2f} {t['exit_price']:>8.2f} {t['ret']:>+6.1f}% "
                      f"{t['exit_reason']:<4}")


if __name__ == '__main__':
    main()
