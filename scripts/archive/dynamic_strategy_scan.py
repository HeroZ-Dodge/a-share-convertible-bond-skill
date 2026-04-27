#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册后动态策略扫描 — 用价格行为决定买卖，不用固定天数

买入策略:
  BA: 突破注册日最高价
  BB: 突破注册以来最高价(从D+1开始)
  BC: 连涨2日后
  BD: 放量突破(成交量>1.5×5日均量 且收涨)
  BE: 回调后反转(先跌>2%再收涨)
  BF: 注册日收盘为锚, 突破注册日收盘价>2%
  BG: 收在D+1最高价之上(追涨)

卖出策略:
  SA: 盈利>+5%
  SB: 盈利>+3%
  SC: 亏损> -3% (止损)
  SD: 跌破注册日最低价
  SE: 跌破注册以来最低价
  SF: 高点回撤>2% (盈利后回落)
  SG: 盈利后出现阴线即走

约束: 最多持有10个交易日
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
    """构建注册事件列表，含完整日线数据"""
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

        # 提取注册日后15天的K线
        future = []
        for off in range(1, 16):
            idx = ri + off
            if idx >= len(sd) or sd[idx] > today_str:
                break
            p = prices[sd[idx]]
            future.append({
                'off': off,
                'date': sd[idx],
                'close': p.get('close', 0),
                'open': p.get('open', 0),
                'high': p.get('high', 0),
                'low': p.get('low', 0),
                'volume': p.get('volume', 0),
            })

        if len(future) < 3:
            continue

        # 注册日数据
        reg_day = prices[sd[ri]]
        reg_high = reg_day.get('high', 0)
        reg_low = reg_day.get('low', 99999)
        reg_close = reg_day.get('close', 0)
        reg_open = reg_day.get('open', 0)
        reg_vol = reg_day.get('volume', 0)

        # 过去5日均量
        vol_avg5 = 0
        if ri >= 5:
            vols = [prices[sd[ri-k]].get('volume', 0) for k in range(1, 6)
                    if prices[sd[ri-k]].get('volume', 0) > 0]
            if vols: vol_avg5 = sum(vols) / len(vols)

        # 注册前5天平均价
        avg_price_5 = 0
        if ri >= 5:
            closes = [prices[sd[ri-k]]['close'] for k in range(1, 6)
                      if prices[sd[ri-k]]['close'] > 0]
            if closes: avg_price_5 = sum(closes) / len(closes)

        events.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'reg': {
                'close': reg_close, 'open': reg_open,
                'high': reg_high, 'low': reg_low,
                'volume': reg_vol,
            },
            'vol_avg5': vol_avg5,
            'avg_price_5': avg_price_5,
            'future': future,
        })

    events.sort(key=lambda x: x['anchor'], reverse=True)
    return events


def simulate(event, buy_rules, sell_rules, max_hold=10):
    """模拟一个事件的交易结果

    buy_rules: list of (name, fn) — fn(event, future, current_off) -> bool
    sell_rules: list of (name, fn) — fn(event, future, entry_off, current_off) -> bool

    Returns: dict with entry/exit info per rule combo
    """
    reg = event['reg']
    future = event['future']
    if not future:
        return None

    results = {}

    for bname, bfn in buy_rules:
        entry_off = None
        entry_price = None

        for off in range(0, min(len(future), max_hold)):
            day = future[off]
            # 计算信号日的累计收益(用于卖出判断)
            if bfn(event, future, off, entry_off is None):
                entry_off = off
                entry_price = day['open']  # 信号日开盘买入
                if entry_price <= 0:
                    entry_price = day['close']
                break

        if entry_off is None or entry_price <= 0:
            continue

        # 卖出模拟
        for sname, sfn in sell_rules:
            exit_off = None
            exit_price = None

            for off in range(entry_off + 1, min(len(future), entry_off + 1 + max_hold)):
                day = future[off]
                if day['close'] <= 0:
                    continue
                ret = ((day['close'] - entry_price) / entry_price) * 100

                if sfn(event, future, entry_off, off, entry_price, ret):
                    exit_off = off
                    exit_price = day['close']
                    break

            # 没触发卖出，用最后一天
            if exit_off is None:
                last = future[min(entry_off + max_hold, len(future) - 1)]
                exit_off = last['off'] - 1
                exit_price = last['close']
                sold = False
            else:
                sold = True

            ret = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            hold = exit_off - entry_off

            key = (bname, sname)
            if key not in results:
                results[key] = []
            results[key].append({
                'code': event['code'],
                'anchor': event['anchor'],
                'entry_off': entry_off,
                'exit_off': exit_off,
                'hold': hold,
                'ret': ret,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'sold': sold,
            })

    return results


def calc_stats(returns, min_n=10):
    if len(returns) < min_n: return None
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


# ========== 买入策略 ==========

def buy_a(event, future, off, is_signal_check):
    """突破注册日最高价 (D+0 high)"""
    if not future: return False
    day = future[off]
    if off == 0:
        return day['high'] > event['reg']['high']
    prev_high = max(event['reg']['high'], future[off-1]['high'])
    return day['high'] > event['reg']['high']


def buy_b(event, future, off, is_signal_check):
    """突破注册以来最高价 (rolling high)"""
    if off < 1: return False
    rolling_high = event['reg']['high']
    for k in range(off):
        rolling_high = max(rolling_high, future[k]['high'])
    return future[off]['high'] > rolling_high


def buy_c(event, future, off, is_signal_check):
    """连涨2日"""
    if off < 2: return False
    ret0 = ((future[off]['close'] - future[off-1]['close']) / future[off-1]['close'] * 100)
    ret1 = ((future[off-1]['close'] - future[off-2]['close']) / future[off-2]['close'] * 100)
    return ret0 > 0 and ret1 > 0


def buy_d(event, future, off, is_signal_check):
    """放量突破: 量>1.5×5日均量 且 收涨>1%"""
    if off < 1: return False
    day = future[off]
    vol = day.get('volume', 0)
    ret = ((day['close'] - day['open']) / day['open'] * 100) if day['open'] > 0 else 0
    return vol > event['vol_avg5'] * 1.5 and ret > 1


def buy_e(event, future, off, is_signal_check):
    """回调后反转: 先有任意日跌>2%, 然后收涨>0%"""
    if off < 1: return False
    ret_today = ((future[off]['close'] - future[off-1]['close']) / future[off-1]['close'] * 100)
    if ret_today <= 0:
        return False
    # 之前有过回调
    for k in range(off):
        if k == 0:
            prev_close = event['reg']['close']
        else:
            prev_close = future[k-1]['close']
        prev_day_close = future[k]['close']
        if ((prev_day_close - prev_close) / prev_close * 100) < -2:
            return True
    return False


def buy_f(event, future, off, is_signal_check):
    """突破注册日收盘价 +2%"""
    day = future[off]
    return day['close'] > event['reg']['close'] * 1.02


def buy_g(event, future, off, is_signal_check):
    """D+1收盘后(等D+1信号)"""
    return off >= 1


# ========== 卖出策略 ==========

def sell_a(event, future, entry_off, off, entry_price, ret_pct):
    """盈利>+5%"""
    return ret_pct >= 5


def sell_b(event, future, entry_off, off, entry_price, ret_pct):
    """盈利>+3%"""
    return ret_pct >= 3


def sell_c(event, future, entry_off, off, entry_price, ret_pct):
    """亏损> -3% (止损)"""
    return ret_pct <= -3


def sell_d(event, future, entry_off, off, entry_price, ret_pct):
    """跌破注册日最低价"""
    return future[off]['low'] < event['reg']['low']


def sell_e(event, future, entry_off, off, entry_price, ret_pct):
    """跌破注册以来最低价"""
    rolling_low = event['reg']['low']
    for k in range(entry_off, off + 1):
        rolling_low = min(rolling_low, future[k]['low'])
    return future[off]['close'] < rolling_low


def sell_f(event, future, entry_off, off, entry_price, ret_pct):
    """高点回撤>2% (需要记录最高浮盈)"""
    # 计算从entry到当前的最大浮盈
    if entry_off == off:
        return False
    peak_ret = ret_pct
    for k in range(entry_off + 1, off):
        kret = ((future[k]['close'] - entry_price) / entry_price) * 100
        if kret > peak_ret:
            peak_ret = kret
    if peak_ret < 3:  # 必须先有3%以上的浮盈
        return False
    drawdown = peak_ret - ret_pct
    return drawdown > 2


def sell_g(event, future, entry_off, off, entry_price, ret_pct):
    """连涨后收跌就走"""
    if off - entry_off < 2:
        return False
    ret_today = ((future[off]['close'] - future[off-1]['close']) / future[off-1]['close'] * 100)
    # 前几日涨过
    prev_ret = ((future[off-1]['close'] - future[off-2]['close']) / future[off-2]['close'] * 100)
    return ret_today < 0 and prev_ret > 0


def sell_h(event, future, entry_off, off, entry_price, ret_pct):
    """持有5天就卖"""
    return (off - entry_off) >= 5


BUY_RULES = [
    ('BA:突破注册日高', buy_a),
    ('BB:突破注册以来高', buy_b),
    ('BC:连涨2日', buy_c),
    ('BD:放量突破', buy_d),
    ('BE:回调反转', buy_e),
    ('BF:突破注册收盘+2%', buy_f),
    ('BG:D+1开盘', buy_g),
]

SELL_RULES = [
    ('SA:≥5%止盈', sell_a),
    ('SB:≥3%止盈', sell_b),
    ('SC:≤-3%止损', sell_c),
    ('SD:跌破注册日低', sell_d),
    ('SE:跌破注册以来低', sell_e),
    ('SF:高点回撤>2%', sell_f),
    ('SG:涨后收跌', sell_g),
    ('SH:持5天卖出', sell_h),
]


def main():
    cache = BacktestCache()
    print("加载注册事件...", flush=True)
    events = build_events(cache)
    print(f"  总事件: {len(events)}")

    # 采样
    sample = events[:200]

    # 扫描所有 买入×卖出 组合
    print(f"\n扫描策略组合... ({len(BUY_RULES)}×{len(SELL_RULES)} 组合)", flush=True)
    all_results = []
    total = len(BUY_RULES) * len(SELL_RULES)
    done = 0

    for bname, bfn in BUY_RULES:
        for sname, sfn in SELL_RULES:
            done += 1
            combo = [(bname, bfn), (sname, sfn)]
            trades = []
            for ev in sample:
                r = simulate(ev, [(bname, bfn)], [(sname, sfn)])
                if r:
                    key = (bname, sname)
                    if key in r:
                        trades.extend(r[key])

            rets = [t['ret'] for t in trades]
            st = calc_stats(rets, min_n=10)
            if st:
                avg_hold = sum(t['hold'] for t in trades) / len(trades)
                all_results.append({
                    'buy': bname, 'sell': sname,
                    'n': st['n'], 'avg': st['avg'], 'med': st['med'],
                    'win': st['win'], 'std': st['std'], 'sharpe': st['sharpe'],
                    'hold': avg_hold,
                    'best': st['best'], 'worst': st['worst'],
                })

    all_results.sort(key=lambda x: x['sharpe'], reverse=True)

    print("\n" + "=" * 120)
    print("Top 动态策略组合 (limit=200, 最多持有10日)")
    print("=" * 120)
    print(f"\n  {'买入':<20} {'卖出':<20} {'样本':>4} {'平均':>7} {'中位':>7} {'胜率':>6} {'标准差':>7} {'夏普':>6} {'持有':>5}")
    print("  " + "-" * 120)

    for r in all_results[:30]:
        star = '★' if r['sharpe'] > 0.6 and r['n'] >= 20 else ' '
        print("  {}{:.<18} {:.<18} {:>4} {:>+6.2f}% {:>+6.2f}% {:>5.1f}% {:>6.2f}% {:>+5.2f} {:>4.1f}d".format(
            star, r['buy'], r['sell'], r['n'], r['avg'], r['med'],
            r['win'], r['std'], r['sharpe'], r['hold']))

    # ========== 稳定性验证 ==========
    print("\n\n" + "=" * 120)
    print("稳定性验证 — Top 5 组合在不同limit")
    print("=" * 120)

    top5 = all_results[:5]
    for limit in [100, 150, 200, 300]:
        sample = events[:limit]
        print(f"\nlimit={limit}:")
        for r in top5:
            trades = []
            for ev in sample:
                bname = r['buy']
                sname = r['sell']
                bfn = [x[1] for x in BUY_RULES if x[0] == bname][0]
                sfn = [x[1] for x in SELL_RULES if x[0] == sname][0]
                res = simulate(ev, [(bname, bfn)], [(sname, sfn)])
                if res:
                    key = (bname, sname)
                    if key in res:
                        trades.extend(res[key])
            rets = [t['ret'] for t in trades]
            st = calc_stats(rets, min_n=5)
            if st:
                avg_hold = sum(t['hold'] for t in trades) / len(trades) if trades else 0
                print(f"  {r['buy']}+{r['sell']}: n={st['n']} sh={st['sharpe']:+.2f} "
                      f"avg={st['avg']:+.2f}% win={st['win']:.0f}% hold={avg_hold:.1f}d")

    # ========== 逐只明细 (最佳组合) ==========
    print("\n\n" + "=" * 120)
    print("最佳组合逐只明细")
    print("=" * 120)

    best = all_results[0]
    bname = best['buy']
    sname = best['sell']
    bfn = [x[1] for x in BUY_RULES if x[0] == bname][0]
    sfn = [x[1] for x in SELL_RULES if x[0] == sname][0]

    sample = events[:200]
    trades = []
    for ev in sample:
        res = simulate(ev, [(bname, bfn)], [(sname, sfn)])
        if res:
            key = (bname, sname)
            if key in res:
                trades.extend(res[key])

    trades.sort(key=lambda x: x['ret'], reverse=True)
    print(f"\n{bname} + {sname} (前200只)")
    print(f"  {'名称':<12} {'代码':>8} {'注册日':<12} {'买入D':>5} {'卖出D':>5} {'持有':>5} {'买入价':>8} {'卖出价':>8} {'收益':>7}")
    for t in trades[:30]:
        ev = [e for e in sample if e['code'] == t['code'] and e['anchor'] == t['anchor']]
        name = ev[0]['name'] if ev else '?'
        print(f"  {name:<12} {t['code']:>8} {t['anchor']:<12} "
              f"D+{t['entry_off']:>4} D+{t['exit_off']:>4} {t['hold']:>4}d "
              f"{t['entry_price']:>8.2f} {t['exit_price']:>8.2f} {t['ret']:>+6.1f}%")


if __name__ == '__main__':
    main()
