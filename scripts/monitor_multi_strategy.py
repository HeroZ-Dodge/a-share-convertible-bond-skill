#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多策略组合监控 + 回测 — 6个策略 + 组合信号

策略从 lib/strategies.py 加载，修改策略条件请编辑该文件。
添加新策略：
    from lib.strategies import registry, Strategy
    registry.register(Strategy('NEW1', '条件描述', lambda f: ..., best_exit='TP5/SL5'))

监控模式:
  --scan     扫描今日注册事件，按策略分组输出
  --hold     查看持仓中债券的止盈止损状态（按策略动态退出）
  --once     scan + hold 一次运行（默认）
  --combo    组合模式输出（任一策略触发即报）
  --status   列出所有近期注册事件 + 各策略触发情况

数据库:
  --sync-db  将理论信号写入 monitor.db（theory_signals 表）
  --compare CODE  查看某只股票的理论 vs 实际对比
  --buy CODE DATE PRICE [REG_DATE]   记录实际买入
  --sell CODE DATE PRICE [REG_DATE]  记录实际卖出

回测模式:
  --backtest              6个策略独立回测 (L=100/150/200)
  --backtest --combo      组合回测 (union=任一触发, intersection=全部触发)
  --backtest --combo all  组合回测 (union + 至少2个 + 全部触发)
  --backtest --limit 150  指定limit

参数:
  --disable deep_pullback,up_momentum  禁用指定策略（逗号分隔，监控/回测均生效）
"""
import sys, os, re, json
import unicodedata
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.backtest_cache import BacktestCache
from lib.strategies import registry
from lib.monitor_db import MonitorDB


def _dw(s):
    """Display width (CJK chars = 2 cols)"""
    width = 0
    for c in str(s):
        code = ord(c)
        if c in ('\u200d', '\ufe0e', '\ufe0f') or unicodedata.combining(c):
            continue
        if unicodedata.east_asian_width(c) in ('F', 'W'):
            width += 2
        elif 0x2600 <= code <= 0x27BF or 0x1F300 <= code <= 0x1FAFF:
            width += 2
        else:
            width += 1
    return width


def _pad(s, width, left=True):
    """Pad/truncate string to target display width"""
    s = str(s)
    dw = _dw(s)
    if dw >= width:
        result, used = '', 0
        for c in s:
            if c in ('\u200d', '\ufe0e', '\ufe0f') or unicodedata.combining(c):
                cw = 0
            elif unicodedata.east_asian_width(c) in ('F', 'W'):
                cw = 2
            elif 0x2600 <= ord(c) <= 0x27BF or 0x1F300 <= ord(c) <= 0x1FAFF:
                cw = 2
            else:
                cw = 1
            if used + cw > width:
                break
            result += c
            used += cw
        return result + ' ' * (width - used)
    padding = width - dw
    return (s + ' ' * padding) if left else (' ' * padding + s)


def _center(s, width):
    """Center text to target display width"""
    s = str(s)
    dw = _dw(s)
    if dw >= width:
        return _pad(s, width)
    left = (width - dw) // 2
    right = width - dw - left
    return ' ' * left + s + ' ' * right


def find_idx(sd, target):
    result = 0
    for i, d in enumerate(sd):
        if d <= target:
            result = i
        else:
            break
    return result


def calc_factors(cache, sc, anchor, as_of_date=None):
    """计算所有因子。

    盘中若 anchor 恰好是当天最新未收盘交易日，则回退到上一完整交易日。
    """
    prices = cache.get_kline_as_dict(sc, days=1500)
    if not prices:
        return None
    sd = sorted(prices.keys())
    today_str = datetime.now().strftime('%Y-%m-%d')
    ri = find_idx(sd, anchor)
    if as_of_date and ri > 0 and sd[ri] == as_of_date:
        ri -= 1
    reg = prices[sd[ri]]
    reg_close = reg['close']
    if reg_close <= 0 or ri < 10:
        return None

    pre3 = ((reg_close - prices[sd[ri-3]]['close']) / prices[sd[ri-3]]['close'] * 100) if ri >= 3 else 0
    mom10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0
    rc = ((reg_close - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri > 0 else 0

    vol_now = reg.get('volume', 0)
    vol_avg5 = 0
    if ri >= 5:
        vlist = [prices[sd[ri-k]].get('volume', 0) for k in range(1, 6)
                 if prices[sd[ri-k]].get('volume', 0) > 0]
        if vlist:
            vol_avg5 = sum(vlist) / len(vlist)
    vol_ratio5 = (vol_now / vol_avg5) if vol_avg5 > 0 else 1

    # consec_down: 注册日前连续下跌天数（从D-1往回看）
    consec_down = 0
    for k in range(1, ri):
        prev_c = prices[sd[ri - k]]['close']
        curr_c = reg_close if k == 1 else prices[sd[ri - k + 1]]['close']
        if curr_c < prev_c:
            consec_down += 1
        else:
            break

    # 注册日后第 N 个交易日开盘价（D+1 买入）
    buy_idx = ri + 1
    buy_price = None
    if buy_idx < len(sd):
        buy_price = prices[sd[buy_idx]].get('open', 0)

    # Current
    latest_idx = find_idx(sd, today_str)
    if latest_idx > 0 and sd[latest_idx] == today_str:
        latest_idx -= 1
    if latest_idx < len(sd) and sd[latest_idx] <= today_str:
        current_close = prices[sd[latest_idx]].get('close', 0)
        current_date = sd[latest_idx]
    else:
        current_close = 0
        current_date = sd[-1] if sd else ''

    # Trading days since registration
    days_since = 0
    for i in range(ri + 1, len(sd)):
        if sd[i] > today_str:
            break
        days_since += 1

    pnl_pct = None
    if buy_price and buy_price > 0 and current_close > 0:
        pnl_pct = ((current_close - buy_price) / buy_price) * 100

    return {
        'pre3': pre3, 'mom10': mom10, 'rc': rc, 'vol_ratio5': vol_ratio5,
        'consec_down': consec_down,
        'buy_price': buy_price,
        'current_close': current_close,
        'current_date': current_date,
        'days_since': days_since,
        'pnl_pct': pnl_pct,
    }


def find_first_signal(cache, stock_code, anchor, today_str):
    """扫描同意注册后到当前为止的首次策略触发日"""
    prices = cache.get_kline_as_dict(stock_code, days=1500)
    if not prices:
        return '', {}, []

    sd = sorted(prices.keys())
    start_idx = find_idx(sd, anchor)
    if start_idx >= len(sd):
        return '', {}, []

    for idx in range(start_idx, len(sd)):
        signal_date = sd[idx]
        if signal_date > today_str:
            break
        factors = calc_factors(cache, stock_code, signal_date, as_of_date=today_str)
        if not factors:
            continue
        triggered = check_strategies(factors)
        active_triggered = {k: v for k, v in triggered.items() if k in registry.active_keys()}
        if any(active_triggered.values()):
            labels = [_short_name(k) for k in registry.active_keys() if active_triggered.get(k)]
            return signal_date, active_triggered, labels

    return '', {}, []


def _anchor_signal_meta_from_row(row):
    """只取同意注册日当天的信号元信息"""
    if not row:
        return '', {}, []
    triggered = row.get('triggered', {}) or {}
    active_triggered = {k: v for k, v in triggered.items() if k in registry.active_keys()}
    if not any(active_triggered.values()):
        return '', {}, []
    labels = [_short_name(k) for k in registry.active_keys() if active_triggered.get(k)]
    return row.get('anchor') or '', active_triggered, labels


# ========== 策略定义 ==========
# 策略从 lib/strategies.py 加载，不在脚本内联定义
# registry.all()       — 所有已注册策略
# registry.active()    — 已启用策略（排除禁用的）
# registry.active_keys() — 已启用策略的 key 列表


def check_strategies(factors):
    """检查所有策略触发情况"""
    return {s.key: s.matches(factors) for s in registry.all()}


# ========== 数据池构建（回测用） ==========

def build_pool(cache):
    """构建完整历史数据池，含因子+持仓K线"""
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

        prices = cache.get_kline_as_dict(sc, days=1500, skip_freshness_check=True)
        if not prices:
            continue
        sd = sorted(prices.keys())
        ri = find_idx(sd, anchor)
        reg = prices[sd[ri]]
        reg_close = reg['close']
        if reg_close <= 0 or ri < 10:
            continue

        # Factors
        pre3 = ((reg_close - prices[sd[ri-3]]['close']) / prices[sd[ri-3]]['close'] * 100) if ri >= 3 else 0
        mom10 = ((reg_close - prices[sd[ri-10]]['close']) / prices[sd[ri-10]]['close'] * 100) if ri >= 10 else 0
        rc = ((reg_close - prices[sd[ri-1]]['close']) / prices[sd[ri-1]]['close'] * 100) if ri > 0 else 0

        vol_now = reg.get('volume', 0)
        vol_avg5 = 0
        if ri >= 5:
            vlist = [prices[sd[ri-k]].get('volume', 0) for k in range(1, 6)
                     if prices[sd[ri-k]].get('volume', 0) > 0]
            if vlist:
                vol_avg5 = sum(vlist) / len(vlist)
        vol_ratio5 = (vol_now / vol_avg5) if vol_avg5 > 0 else 1

        # consec_down
        consec_down = 0
        for k in range(1, ri):
            prev_c = prices[sd[ri - k]]['close']
            curr_c = reg_close if k == 1 else prices[sd[ri - k + 1]]['close']
            if curr_c < prev_c:
                consec_down += 1
            else:
                break

        factors = {
            'pre3': pre3, 'mom10': mom10, 'rc': rc, 'vol_ratio5': vol_ratio5,
            'consec_down': consec_down,
        }

        # D+1 buy price
        buy_idx = ri + 1
        buy_price = None
        if buy_idx < len(sd) and sd[buy_idx] <= today_str:
            buy_price = prices[sd[buy_idx]].get('open', 0)
        if not buy_price or buy_price <= 0:
            continue

        # Hold period K-lines
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
        if len(hold_days) < 2:
            continue

        # Strategy triggers
        triggered = check_strategies(factors)
        hit_count = sum(1 for v in triggered.values() if v)

        pool.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'factors': factors,
            'triggered': triggered,
            'hit_count': hit_count,
            'buy_price': buy_price,
            'hold_days': hold_days,
        })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    return pool


# ========== 回测引擎 ==========

def calc_stats(trades):
    """计算回测统计"""
    if not trades:
        return None
    rets = sorted([t['ret'] for t in trades])
    n = len(rets)
    avg = sum(rets) / n
    std = (sum((x - avg) ** 2 for x in rets) / n) ** 0.5
    sh = avg / std if std > 0 else 0
    win = sum(1 for x in rets if x > 0) / n * 100
    avg_hold = sum(t['hold'] for t in trades) / n
    return {
        'n': n, 'avg': avg, 'win': win, 'std': std,
        'sharpe': sh, 'avg_hold': avg_hold,
        'best': max(rets), 'worst': min(rets),
    }


def test_d9_exit(pool):
    """D+9 固定退出"""
    trades = []
    for s in pool:
        buy = s['buy_price']
        for d in s['hold_days']:
            if d['off'] == 8:
                trades.append({
                    'ret': ((d['close'] - buy) / buy) * 100,
                    'hold': 8,
                })
                break
    return calc_stats(trades)


def test_tp5_sl5_exit(pool):
    """TP5/SL5 动态退出"""
    trades = []
    for s in pool:
        buy = s['buy_price']
        exit_off = None
        exit_price = None
        for i, day in enumerate(s['hold_days']):
            if i == 0:
                continue
            if day['close'] <= 0:
                continue
            ret = ((day['close'] - buy) / buy) * 100
            if ret >= 5:
                exit_off, exit_price = day['off'], day['close']
                break
            if ((buy - day['close']) / buy * 100) >= 5:
                exit_off, exit_price = day['off'], day['close']
                break
            if day['off'] - 1 >= 10:
                exit_off, exit_price = day['off'], day['close']
                break
        if exit_off is None:
            last = s['hold_days'][-1]
            exit_off, exit_price = last['off'], last['close']
        trades.append({
            'ret': ((exit_price - buy) / buy) * 100,
            'hold': exit_off - 1,
        })
    return calc_stats(trades)


def trigger_combo_fn(pool, mode):
    """根据组合模式筛选触发样本（仅统计活跃策略）"""
    active = registry.active_keys()
    if mode == 'union':
        return [s for s in pool if any(s['triggered'].get(k) for k in active)]
    elif mode == 'intersection':
        return [s for s in pool if all(s['triggered'].get(k) for k in active) and len(active) > 0]
    elif mode == 'at_least_2':
        return [s for s in pool if sum(1 for k in active if s['triggered'].get(k)) >= 2]
    elif mode == 'at_least_3':
        return [s for s in pool if sum(1 for k in active if s['triggered'].get(k)) >= 3]
    return []


def run_backtest_single(pool, key):
    """单个策略回测"""
    s = registry.get(key)
    if not s:
        return None, None
    triggered = [p for p in pool if s.matches(p['factors'])]
    if not triggered:
        return None, None
    d9 = test_d9_exit(triggered)
    tp = test_tp5_sl5_exit(triggered)
    return d9, tp


def run_backtest_combo(pool, mode):
    """组合策略回测"""
    triggered = trigger_combo_fn(pool, mode)
    if not triggered:
        return None, None
    d9 = test_d9_exit(triggered)
    tp = test_tp5_sl5_exit(triggered)
    return d9, tp


def combo_label(mode):
    """组合模式标签"""
    labels = {
        'union': '任一触发',
        'intersection': '全部触发',
        'at_least_2': '至少2个',
        'at_least_3': '至少3个',
    }
    return labels.get(mode, mode)


# ========== 回测输出 ==========

def mode_backtest(cache, combo_mode=None):
    """回测模式"""
    print("\n" + "=" * 110)
    print("多策略回测")
    print("=" * 110)

    pool = build_pool(cache)
    total = len(pool)
    print(f"\n  总样本: {total}")

    if combo_mode:
        # 组合回测
        print(f"\n" + "-" * 110)
        print(f"  组合模式回测")
        print(f"{'-'*110}")

        modes = []
        if combo_mode == 'all':
            modes = ['union', 'at_least_2', 'at_least_3', 'intersection']
        else:
            modes = [combo_mode]

        for mode in modes:
            print(f"\n  {combo_label(mode)}:")
            hdr = f"  {_pad('Limit', 10)} {_pad('样本', 4)} {_pad('平均', 7)} {_pad('胜率', 6)} {_pad('夏普', 6)} {_pad('持有', 5)} {_pad('年化', 8)}"
            print(hdr)
            print("  " + "-" * (_dw(hdr) - 2))

            for limit in [100, 150, 200, 0]:
                pl = pool[:limit] if limit else pool
                d9, tp = run_backtest_combo(pl, mode)
                label = f'L={limit}' if limit else '全量'

                if tp:
                    eff = tp['avg'] / tp['avg_hold'] * 245 if tp['avg_hold'] > 0 else 0
                    star = '★' if tp['sharpe'] >= 0.5 and tp['n'] >= 10 else ' '
                    print(f"  {star} {label:<10} {tp['n']:>4} {tp['avg']:>+6.2f}% {tp['win']:>5.1f}% {tp['sharpe']:>+5.2f} {tp['avg_hold']:>4.1f}d {eff:>+7.1f}%")
                else:
                    print(f"    {label:<10} {'(样本不足)':>4}")

    else:
        # 独立策略回测
        print(f"\n" + "-" * 110)
        print(f"  独立策略回测 (D+9 固定退出)")
        print(f"{'-'*110}")

        hdr = f"  {_pad('策略', 42)}"
        for lim in ['L=100', 'L=150', 'L=200', '全量']:
            hdr += f" {_pad(lim, 20)}"
        print(hdr)
        sub = f"  {_pad('', 42)}"
        for _ in range(4):
            sub += f" {_pad('n avg sh', 20)}"
        print(sub)
        print("  " + "-" * (_dw(hdr) - 2))

        for key in registry.active_keys():
            parts = []
            for limit in [100, 150, 200, 0]:
                pl = pool[:limit] if limit else pool
                d9, tp = run_backtest_single(pl, key)
                if d9:
                    val = f"{d9['n']} {d9['avg']:+.1f}% sh={d9['sharpe']:+.2f}"
                    parts.append(_pad(val, 20))
                else:
                    parts.append(_pad('--', 20))
            print(f"  {_pad(_display_name(key), 42)} {' '.join(parts)}")

        print(f"\n" + "-" * 110)
        print(f"  独立策略回测 (TP5/SL5 动态退出)")
        print(f"{'-'*110}")

        hdr = f"  {_pad('策略', 42)}"
        for lim in ['L=100', 'L=150', 'L=200', '全量']:
            hdr += f" {_pad(lim, 30)}"
        print(hdr)
        sub = f"  {_pad('', 42)}"
        for _ in range(4):
            sub += f" {_pad('n avg sh eff', 30)}"
        print(sub)
        print("  " + "-" * (_dw(hdr) - 2))

        for key in registry.active_keys():
            parts = []
            for limit in [100, 150, 200, 0]:
                pl = pool[:limit] if limit else pool
                d9, tp = run_backtest_single(pl, key)
                if tp:
                    eff = tp['avg'] / tp['avg_hold'] * 245 if tp['avg_hold'] > 0 else 0
                    val = f"{tp['n']} {tp['avg']:+.1f}% sh={tp['sharpe']:+.2f} eff={eff:+.0f}%"
                    parts.append(_pad(val, 30))
                else:
                    parts.append(_pad('--', 30))
            print(f"  {_pad(_display_name(key), 42)} {' '.join(parts)}")

        # 稳定性总结
        print(f"\n" + "-" * 110)
        print(f"  稳定性总结 (TP5/SL5夏普趋势)")
        print(f"{'-'*110}")

        hdr = f"  {_pad('策略', 42)}"
        for lim in ['L=100', 'L=150', 'L=200', '全量', '趋势']:
            hdr += f" {_pad(lim, 10)}"
        print(hdr)
        print("  " + "-" * (_dw(hdr) - 2))

        for key in registry.active_keys():
            shards = []
            for limit in [100, 150, 200, 0]:
                pl = pool[:limit] if limit else pool
                d9, tp = run_backtest_single(pl, key)
                shards.append(tp['sharpe'] if tp else None)
            if all(x is not None for x in shards):
                diff = shards[-1] - shards[0]
                trend = '→稳定' if abs(diff) < 0.2 else '→衰减' if diff < -0.2 else '→上升'
                parts_s = [_pad(f'{x:+.2f}', 10) for x in shards]
            else:
                trend = '???'; parts_s = [_pad(f'{x:+.2f}' if x else '--', 10) for x in shards]
            parts_s.append(_pad(trend, 10))
            print(f"  {_pad(_display_name(key), 42)} {' '.join(parts_s)}")

    # 年份分组（只对L=200和全量）
    print(f"\n" + "-" * 110)
    print(f"  按年份分组 (L=200, TP5/SL5)")
    print(f"{'-'*110}")

    pool_200 = pool[:200]
    for key in registry.active_keys():
        s_cond = registry.get(key).condition
        print(f"\n  {_display_name(key)}:")
        hdr = f"    {_pad('年份', 8)} {_pad('样本', 4)} {_pad('平均', 7)} {_pad('胜率', 6)} {_pad('夏普', 6)} {_pad('年化', 8)}"
        print(hdr)
        print("    " + "-" * (_dw(hdr) - 4))
        for year in ['2023', '2024', '2025', '2026']:
            yr_pool = [s for s in pool_200 if s['anchor'].startswith(year) and s_cond(s['factors'])]
            if not yr_pool:
                continue
            tp = test_tp5_sl5_exit(yr_pool)
            if tp and tp['n'] >= 2:
                eff = tp['avg'] / tp['avg_hold'] * 245 if tp['avg_hold'] > 0 else 0
                print(f"    {_pad(year + '年', 8)} {_pad(str(tp['n']), 4)} {tp['avg']:>+6.2f}% {tp['win']:>5.1f}% {tp['sharpe']:>+5.2f} {eff:>+7.1f}%")
            elif tp:
                print(f"    {_pad(year + '年', 8)} {_pad(str(tp['n']), 4)} (样本不足)")


# ========== 数据池构建（监控用 — 复用 build_pool） ==========


def scan_registrations(cache):
    """扫描近期注册事件"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    bonds = cache.get_latest_jisilu_data()
    if not bonds:
        bonds = cache.get_jisilu_bonds(phase='注册', limit=0)

    results = []
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

        try:
            anchor_dt = datetime.strptime(anchor, '%Y-%m-%d')
            today_dt = datetime.strptime(today_str, '%Y-%m-%d')
            calendar_diff = (today_dt - anchor_dt).days
        except ValueError:
            continue
        if calendar_diff > 20:
            continue

        factors = calc_factors(cache, sc, anchor, as_of_date=today_str)
        if not factors:
            continue

        triggered = check_strategies(factors)
        hit_count = sum(1 for v in triggered.values() if v)
        active_triggered = {k: v for k, v in triggered.items() if k in registry.active_keys()}
        first_signal_date = anchor if any(active_triggered.values()) else ''
        first_signal_triggered = active_triggered
        first_signal_labels = [_short_name(k) for k in registry.active_keys() if active_triggered.get(k)]

        results.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'stock_name': (b.get('stock_name') or '')[:12],
            'bond_code': b.get('bond_code') or '',
            'bond_name': (b.get('bond_name') or '')[:12],
            'anchor': anchor,
            'calendar_diff': calendar_diff,
            'days_since': factors.get('days_since', 0),
            'first_signal_date': first_signal_date,
            'first_signal_triggered': first_signal_triggered or {},
            'first_signal_labels': first_signal_labels,
            'factors': factors,
            'triggered': triggered,
            'hit_count': hit_count,
        })

    results.sort(key=lambda x: x['anchor'], reverse=True)
    return results


def scan_buy_signals(cache):
    """扫描 D+1 买入信号（仅统计活跃策略）"""
    active = registry.active_keys()
    results = scan_registrations(cache)
    buy_signals = [r for r in results
                   if r['calendar_diff'] <= 1
                   and any(r['triggered'].get(k) for k in active)]
    return buy_signals


def scan_holdings(cache):
    """扫描持仓中的触发信号（仅统计活跃策略）"""
    active = registry.active_keys()
    results = scan_registrations(cache)
    holdings = [r for r in results
                if r['calendar_diff'] > 1 and r['calendar_diff'] <= 15
                and any(r['triggered'].get(k) for k in active)]
    return holdings


# ========== 输出格式 ==========

def _display_name(key):
    """获取策略全名（中文+条件）"""
    s = registry.get(key)
    if not s:
        return key
    if s.display_name and s.label:
        return f"{s.display_name}({s.label})"
    return s.display_name or key


def _short_name(key):
    """获取策略短名（仅中文）"""
    s = registry.get(key)
    return s.display_name if s and s.display_name else key


def _display_names(triggered):
    """将触发字典转为中文显示名列表（短名）"""
    return [_short_name(k) for k in registry.active_keys() if triggered.get(k)]


def print_strategy_bar(triggered, factors):
    """打印策略触发条: 深调缩量✅ 浅调缩量❌ ..."""
    parts = []
    for key in registry.active_keys():
        name = _short_name(key)
        if triggered.get(key, False):
            parts.append(f"{name}✅")
        else:
            parts.append(f"{name}❌")
    return ' '.join(parts)


def active_hit_count(triggered):
    """计算活跃策略中触发的数量"""
    return sum(1 for k in registry.active_keys() if triggered.get(k))


def active_tags(triggered):
    """打印触发的活跃策略标签（短名）"""
    return ' '.join(_short_name(k) for k in registry.active_keys() if triggered.get(k))


def print_strategy_tags(triggered):
    """打印触发的策略标签（别名，同 active_tags）"""
    return active_tags(triggered)


def _labels_text(labels, default='—'):
    """把策略标签列表压成展示文本"""
    if not labels:
        return default
    if isinstance(labels, str):
        text = labels.strip()
        return text or default
    items = [str(x).strip() for x in labels if str(x).strip()]
    return '/'.join(items) if items else default


def _position_source_label(position):
    """将持仓 source 转为展示标签"""
    if not position:
        return '实际'
    return '模拟' if position.get('source') == 'backfill' else '实际'


def _actual_sell_alert(current_price, buy_price, sell_mode='TPSL', registration_date=None):
    """根据实际持仓的卖出模式生成卖出提醒"""
    mode = (sell_mode or 'TPSL').upper()
    if mode in ('REG', 'REG_ONLY', 'REGISTRATION'):
        if registration_date:
            try:
                if datetime.now().strftime('%Y-%m-%d') >= registration_date:
                    return '卖出信号(同意注册后卖出)'
            except ValueError:
                pass
        return '持仓中'

    try:
        buy_price = float(buy_price)
        current_price = float(current_price)
    except (TypeError, ValueError):
        return '持仓中'

    if buy_price <= 0 or current_price <= 0:
        return '持仓中'

    pnl_pct = (current_price / buy_price - 1) * 100
    if pnl_pct >= 5:
        return '卖出信号(TP+5%)'
    if pnl_pct <= -5:
        return '卖出信号(SL-5%)'
    return '持仓中'


def load_position_notes_data(pos):
    """安全解析 positions.notes"""
    try:
        return json.loads(pos.get('notes') or '{}')
    except (TypeError, ValueError):
        return {}


def resolve_actual_signal_meta(cache, stock_code, reg_date=None):
    """为实际买入解析触发策略信息"""
    db = MonitorDB()

    theory_rows = db.get_theory_signals(stock_code)
    if theory_rows:
        if reg_date:
            matched = next((r for r in theory_rows if r.get('registration_date') == reg_date), None)
        else:
            matched = theory_rows[0]
        if matched:
            triggered = matched.get('triggered_strategies', []) or []
            return (
                triggered,
                matched.get('strategy_labels', []) or [],
                matched.get('registration_date') or reg_date or '',
                (matched.get('registration_date') or reg_date or '') if triggered else '',
            )

    for pos in db.get_backfill_positions():
        if pos.get('stock_code') != stock_code:
            continue
        notes = load_position_notes_data(pos)
        labels = notes.get('strategy_labels', []) or []
        triggered = notes.get('triggered_strategies', []) or []
        if labels or triggered:
            return (
                triggered,
                labels,
                pos.get('registration_date') or reg_date or '',
                (pos.get('registration_date') or reg_date or '') if (labels or triggered) else '',
            )

    scan_rows = scan_registrations(cache)
    matched = next((r for r in scan_rows if r.get('code') == stock_code and (not reg_date or r.get('anchor') == reg_date)), None)
    if matched:
        triggered = matched.get('triggered', {}) or {}
        active_triggered = {k: v for k, v in triggered.items() if k in registry.active_keys()}
        return (
            list(active_triggered.keys()),
            [registry.get(k).display_name for k in registry.active_keys()
             if active_triggered.get(k) and registry.get(k)],
            matched.get('anchor') or reg_date or '',
            (matched.get('anchor') or reg_date or '') if any(active_triggered.values()) else '',
        )

    return [], [], reg_date or '', ''


def _first_triggered_strategy(triggered):
    """返回首个命中的活跃策略 key"""
    for key in registry.active_keys():
        if triggered.get(key):
            return key
    return None


def _hold_display_parts(factors, triggered):
    """生成持仓展示所需的统一字段"""
    bp = f"{factors['buy_price']:.2f}" if factors.get('buy_price') else '--'
    cp = f"{factors['current_close']:.2f}" if factors.get('current_close') else '--'
    pnl = f"{factors['pnl_pct']:+.1f}%" if factors.get('pnl_pct') is not None else '--'

    tp_val, sl_val = 5, 5
    exit_label = 'D+9'
    first_key = _first_triggered_strategy(triggered)
    if first_key:
        s = registry.get(first_key)
        if s:
            tp_val, sl_val = parse_exit_thresholds(s.best_exit)
            exit_label = s.best_exit or 'D+9'

    pnl_val = factors.get('pnl_pct')
    tp_mark = '✅' if pnl_val is not None and pnl_val >= tp_val else ' '
    sl_mark = '⚠️' if pnl_val is not None and pnl_val <= -sl_val else ' '
    exit_str = f"{tp_mark}{sl_mark} ({exit_label})"

    return {
        'buy_price': bp,
        'current_price': cp,
        'pnl': pnl,
        'exit_str': exit_str,
        'tags': print_strategy_tags(triggered),
    }


def _actual_sell_alert(current_price, buy_price, tp=5, sl=5):
    """根据实际持仓现价和买价生成卖出提醒"""
    try:
        buy_price = float(buy_price)
        current_price = float(current_price)
    except (TypeError, ValueError):
        return '持仓中'

    if buy_price <= 0 or current_price <= 0:
        return '持仓中'

    pnl_pct = (current_price / buy_price - 1) * 100
    if pnl_pct >= tp:
        return f'卖出信号(TP+{tp}%)'
    if pnl_pct <= -sl:
        return f'卖出信号(SL-{sl}%)'
    return '持仓中'


def _format_simulated_position(factors, triggered):
    """将模拟持仓压成单行展示文本"""
    parts = _hold_display_parts(factors, triggered)
    if parts['buy_price'] == '--':
        return '--'
    return f"买{parts['buy_price']} 现{parts['current_price']} 盈{parts['pnl']} {parts['exit_str']} {parts['tags']}"


def _format_t_plus(days, width=6):
    """格式化 T+N，避免 T+ 后面出现多余空格"""
    try:
        return _pad(f"T+{int(days)}", width)
    except (TypeError, ValueError):
        return _pad('--', width)


def _format_days(days, width=6):
    """格式化纯天数显示"""
    try:
        return _pad(str(int(days)), width)
    except (TypeError, ValueError):
        return _pad('--', width)


def _format_pct(value, width):
    """格式化百分比字段"""
    try:
        return _pad(f"{float(value):+.1f}%", width)
    except (TypeError, ValueError):
        return _pad('--', width)


def _build_hold_row_from_scan(r):
    """把扫描结果转成持仓行所需字段"""
    parts = _hold_display_parts(r['factors'], r['triggered'])
    display_days = r.get('days_since', r['calendar_diff'])
    first_labels = _labels_text(r.get('first_signal_labels', []))
    current_labels = _labels_text(print_strategy_tags(r['triggered']))
    return {
        'name': r['name'],
        'code': r['code'],
        'days': display_days,
        'buy_price': parts['buy_price'],
        'current_price': parts['current_price'],
        'pnl': parts['pnl'],
        'exit_str': '模拟持仓',
        'tags': f"首:{first_labels} 今:{current_labels}",
    }


def _hold_row_cells(row):
    """把持仓行格式化成固定列字符串"""
    return [
        _pad(row['name'], 14),
        _pad(row['code'], 8),
        _format_t_plus(row['days'], 6),
        _pad(row['buy_price'], 8),
        _pad(row['current_price'], 8),
        _pad(row['pnl'], 8),
        _pad(row['exit_str'], 24),
        row['tags'],
    ]


def _print_hold_table(title, rows):
    """打印与持仓监控一致的表格"""
    print(f"\n  📊 {title} ({len(rows)}只):")
    hdr = f"  {_pad('名称', 14)} {_pad('代码', 8)} {_pad('T+', 6)} {_pad('买价', 8)} {_pad('现价', 8)} {_pad('盈亏', 8)} {_pad('止盈止损', 24)} {'触发策略'}"
    print(hdr)
    print("  " + "-" * (_dw(hdr) - 2))
    if not rows:
        print("  无持仓")
        return
    for row in rows:
        print("  " + " ".join(_hold_row_cells(row)))


def _build_simulated_hold_rows(cache, db, registrations):
    """根据 backfill 持仓和最新扫描结果生成模拟持仓行"""
    scan_map = {r['code']: r for r in registrations}
    rows = []
    for pos in db.get_backfill_positions():
        if pos.get('status') != 'active':
            continue
        sc = pos.get('stock_code')
        if not sc:
            continue

        notes = load_position_notes_data(pos)
        monitor_script = notes.get('monitor_script', '')
        labels = notes.get('strategy_labels', []) or []
        if monitor_script and monitor_script != 'monitor_multi_strategy':
            continue
        if not monitor_script:
            own_labels = {registry.get(k).display_name for k in registry.active_keys() if registry.get(k)}
            if labels and not any(lbl in own_labels for lbl in labels):
                continue

        r = scan_map.get(sc)
        if r:
            row = _build_hold_row_from_scan(r)
            row['name'] = pos.get('stock_name') or row['name']
            rows.append(row)
            continue

        reg_date = pos.get('registration_date') or ''
        days = 0
        if reg_date:
            try:
                days = (datetime.now() - datetime.strptime(reg_date, '%Y-%m-%d')).days
            except ValueError:
                days = 0

        buy_price = pos.get('actual_buy_price')
        buy_str = f"{buy_price:.2f}" if buy_price else '--'
        rows.append({
            'name': (pos.get('stock_name') or pos.get('bond_name') or '?')[:12],
            'code': sc,
            'days': days,
            'buy_price': buy_str,
            'current_price': '--',
            'pnl': '--',
            'exit_str': '模拟持仓',
            'tags': f"首:{_labels_text(labels)} 今:—",
        })

    rows.sort(key=lambda x: x['days'])
    return rows


# ========== 输出模式 ==========

def parse_exit_thresholds(exit_str):
    """解析策略退出条件, 返回 (tp, sl) 百分比阈值"""
    if not exit_str:
        return 5, 5  # 默认 TP5/SL5
    exit_str = exit_str.upper().replace(' ', '')
    # 格式如 TP5/SL5, TP7/SL7, TP3/SL3, D+9
    tp_m = re.search(r'TP(\d+)', exit_str)
    sl_m = re.search(r'SL(\d+)', exit_str)
    tp = int(tp_m.group(1)) if tp_m else 999
    sl = int(sl_m.group(1)) if sl_m else 999
    return tp, sl


def mode_combo(cache):
    """组合模式 — 任一策略触发即报"""
    results = scan_registrations(cache)
    active = registry.active_keys()
    triggered = [r for r in results if any(r['triggered'].get(k) for k in active)]
    today_str = datetime.now().strftime('%Y-%m-%d')

    print(f"\n{'='*110}")
    print(f"组合模式 — {today_str}")
    print(f"{'='*110}")

    if not triggered:
        print(f"\n  无策略触发")
        return

    print(f"\n  组合信号 ({len(triggered)}只):")
    hdr = f"  {_pad('名称', 14)} {_pad('代码', 8)} {_pad('注册日', 16)} {_pad('天数', 6)} {_pad('策略数', 6)} {_pad('触发策略', 30)} 盈亏"
    print(hdr)
    print("  " + "-" * (_dw(hdr) - 2))

    # 买入信号优先
    buy = [r for r in triggered if r['calendar_diff'] <= 1]
    hold = [r for r in triggered if r['calendar_diff'] > 1 and r['calendar_diff'] <= 15]
    past = [r for r in triggered if r['calendar_diff'] > 15]

    if buy:
        print(f"\n  📢 买入信号:")
        for s in buy:
            f = s['factors']
            bp = f"{f['buy_price']:.2f}" if f['buy_price'] else '--'
            tags = print_strategy_tags(s['triggered'])
            d = s.get('days_since', s['calendar_diff'])
            print(f"  {_pad(s['name'], 14)} {_pad(s['code'], 8)} {_pad(s['anchor'], 16)} "
                  f"T+{d:>3}  {active_hit_count(s['triggered'])}个策略  {tags}")

    if hold:
        print(f"\n  📊 持仓:")
        for h in hold:
            f = h['factors']
            pnl = f"{f['pnl_pct']:+.1f}%" if f['pnl_pct'] is not None else '--'
            tags = print_strategy_tags(h['triggered'])
            d = h.get('days_since', h['calendar_diff'])
            print(f"  {_pad(h['name'], 14)} {_pad(h['code'], 8)} {_pad(h['anchor'], 16)} "
                  f"T+{d:>3}  {active_hit_count(h['triggered'])}个策略  {tags} {pnl}")

    if past:
        print(f"\n  已过退出期:")
        for p in past[:5]:
            f = p['factors']
            pnl = f"{f['pnl_pct']:+.1f}%" if f['pnl_pct'] is not None else '--'
            tags = print_strategy_tags(p['triggered'])
            d = p.get('days_since', p['calendar_diff'])
            print(f"  {_pad(p['name'], 14)} {_pad(p['code'], 8)} {_pad(p['anchor'], 16)} "
                  f"T+{d:>3}  {active_hit_count(p['triggered'])}个策略  {tags} {pnl}")


def mode_status(cache):
    """列出所有近期注册事件"""
    results = scan_registrations(cache)
    today_str = datetime.now().strftime('%Y-%m-%d')

    print(f"\n{'='*110}")
    print(f"全部注册事件 — {today_str} ({len(results)}只)")
    print(f"{'='*110}")

    active = registry.active_keys()
    col_w = max(5, max(_dw(_short_name(k))+1 for k in active)) if active else 6
    print(f"\n  {_pad('名称', 14)} {_pad('代码', 8)} {_pad('注册日', 16)} {'天数':>6}  "
          f"{''.join(_pad(_short_name(k), col_w) for k in active)}  "
          f"{'pre3':>7} {'mom10':>8} {'rc':>6} {'vol':>5}")
    print("  " + "-" * 110)

    for r in results:
        f = r['factors']
        t = r['triggered']
        cols = ' '.join(f"{'✅' if t.get(k) else '' :>{col_w}}" for k in active)
        d = r.get('days_since', r['calendar_diff'])
        print(f"  {_pad(r['name'], 14)} {_pad(r['code'], 8)} {_pad(r['anchor'], 16)} "
              f"T+{d:>3}  {cols}  "
              f"{f['pre3']:>+6.1f}% {f['mom10']:>+7.1f}% "
              f"{f['rc']:>+5.1f}% {f['vol_ratio5']:>5.2f}")


def mode_sync_db(cache):
    """将理论信号和模拟持仓写入 monitor.db（自动跳过相同数据）"""
    results = scan_registrations(cache)
    db = MonitorDB()

    # 获取所有触发策略的注册事件
    triggered_results = [r for r in results
                        if any(r['triggered'].get(k) for k in registry.active_keys())]

    if not triggered_results:
        return {'theory_synced': 0, 'simulated_created': 0}

    synced = 0
    simulated_created = 0
    for r in triggered_results:
        f = r['factors']
        triggered_keys = [k for k in registry.active_keys() if r['triggered'].get(k)]
        triggered_labels = [_short_name(k) for k in registry.active_keys() if r['triggered'].get(k)]

        # 取第一个触发策略的退出方式
        exit_type = ''
        if triggered_keys:
            s = registry.get(triggered_keys[0])
            if s:
                exit_type = s.best_exit or 'D+9'

        # 读取实际数据（如果用户已手动录入）
        actual = db.get_position_comparison(r['code'])
        has_actual = False
        if actual and actual.get('actual'):
            a = actual['actual']
            has_actual = bool(a.get('actual_buy_price') or a.get('actual_sell_price'))

        db.upsert_theory_signal(r['code'], r['anchor'], {
            'stock_name': r.get('name', ''),
            'bond_code': r.get('bond_code', ''),
            'bond_name': r.get('bond_name', ''),
            'first_signal_date': r.get('first_signal_date', ''),
            'triggered_strategies': triggered_keys,
            'strategy_labels': triggered_labels,
            'calendar_diff': r['calendar_diff'],
            'trading_days': r.get('days_since', 0),
            'theory_buy_date': (datetime.strptime(r['anchor'], '%Y-%m-%d')
                              + __import__('datetime').timedelta(days=1)).strftime('%Y-%m-%d')
            if r['anchor'] else '',
            'theory_buy_price': f['buy_price'],
            'theory_exit_type': exit_type,
            'theory_factors': {k: v for k, v in f.items()
                             if k not in ('buy_price', 'current_close', 'current_date',
                                         'days_since', 'pnl_pct')},
            'theory_pnl_pct': f.get('pnl_pct'),
            'current_price': f.get('current_price'),
            'current_date': f.get('current_date'),
        })
        if f.get('buy_price') and f['buy_price'] > 0:
            sim_result = db.upsert_simulated_position(r['code'], r['anchor'], {
                'stock_name': r.get('stock_name') or r.get('name', ''),
                'bond_code': r.get('bond_code', ''),
                'bond_name': r.get('bond_name', ''),
                'monitor_script': 'monitor_multi_strategy',
                'first_signal_date': r.get('first_signal_date', ''),
                'theory_buy_date': (datetime.strptime(r['anchor'], '%Y-%m-%d')
                                  + __import__('datetime').timedelta(days=1)).strftime('%Y-%m-%d')
                if r['anchor'] else '',
                'theory_buy_price': f['buy_price'],
                'triggered_strategies': triggered_keys,
                'strategy_labels': triggered_labels,
                'theory_exit_type': exit_type,
                'theory_factors': {k: v for k, v in f.items()
                                 if k not in ('buy_price', 'current_close', 'current_date',
                                             'days_since', 'pnl_pct')},
            })
            if sim_result.get('created'):
                simulated_created += 1
        synced += 1

    return {'theory_synced': synced, 'simulated_created': simulated_created}


def backfill_first_signal_history(cache):
    """回填历史理论信号和实际持仓的首次信号日"""
    db = MonitorDB()
    theory_updated = 0
    actual_updated = 0
    simulated_updated = 0
    backfill_map = {p['stock_code']: p for p in db.get_backfill_positions()}
    scan_rows = scan_registrations(cache)
    scan_map = {(r.get('code'), r.get('anchor')): r for r in scan_rows}

    for row in db.get_theory_signals():
        if row.get('first_signal_date'):
            continue
        reg_date = row.get('registration_date') or ''
        stock_code = row.get('stock_code')
        if not stock_code or not reg_date:
            continue
        scan_row = scan_map.get((stock_code, reg_date))
        first_signal_date, first_signal_triggered, first_signal_labels = _anchor_signal_meta_from_row(scan_row)
        if not first_signal_date:
            continue
        db.upsert_theory_signal(stock_code, reg_date, {
            'stock_name': row.get('stock_name', ''),
            'bond_code': row.get('bond_code', ''),
            'bond_name': row.get('bond_name', ''),
            'first_signal_date': first_signal_date,
            'triggered_strategies': row.get('triggered_strategies', []) or list(first_signal_triggered.keys()),
            'strategy_labels': row.get('strategy_labels', []) or first_signal_labels,
            'calendar_diff': row.get('calendar_diff'),
            'trading_days': row.get('trading_days'),
            'theory_buy_date': row.get('theory_buy_date', ''),
            'theory_buy_price': row.get('theory_buy_price'),
            'theory_exit_type': row.get('theory_exit_type', ''),
            'theory_factors': row.get('theory_factors', {}) or {},
            'theory_pnl_pct': row.get('theory_pnl_pct'),
            'current_price': row.get('current_price'),
            'current_date': row.get('current_date', ''),
        })
        theory_updated += 1

    with db._get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM positions
            WHERE source IN ('real', 'manual')
              AND status = 'active'
        """).fetchall()
        for row in rows:
            pos = dict(row)
            notes = load_position_notes_data(pos)
            if notes.get('first_signal_date'):
                continue
            reg_date = (
                pos.get('registration_date')
                or (backfill_map.get(pos.get('stock_code')) or {}).get('registration_date')
                or ''
            )
            stock_code = pos.get('stock_code')
            if not stock_code or not reg_date:
                continue
            scan_row = scan_map.get((stock_code, reg_date))
            first_signal_date, first_signal_triggered, first_signal_labels = _anchor_signal_meta_from_row(scan_row)
            if not first_signal_date:
                continue
            notes['origin'] = notes.get('origin') or 'actual'
            notes['first_signal_date'] = first_signal_date
            if not notes.get('triggered_strategies'):
                notes['triggered_strategies'] = list(first_signal_triggered.keys())
            if not notes.get('strategy_labels'):
                notes['strategy_labels'] = first_signal_labels
            conn.execute(
                "UPDATE positions SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE position_id = ?",
                (json.dumps(notes, ensure_ascii=False), pos.get('position_id'))
            )
            actual_updated += 1

        sim_rows = conn.execute("""
            SELECT * FROM positions
            WHERE source = 'backfill'
              AND status = 'active'
        """).fetchall()
        for row in sim_rows:
            pos = dict(row)
            notes = load_position_notes_data(pos)
            if notes.get('first_signal_date'):
                continue
            reg_date = pos.get('registration_date') or ''
            stock_code = pos.get('stock_code')
            if not stock_code or not reg_date:
                continue
            scan_row = scan_map.get((stock_code, reg_date))
            first_signal_date, first_signal_triggered, first_signal_labels = _anchor_signal_meta_from_row(scan_row)
            if not first_signal_date:
                continue
            notes['origin'] = notes.get('origin') or 'simulated'
            notes['first_signal_date'] = first_signal_date
            if not notes.get('triggered_strategies'):
                notes['triggered_strategies'] = list(first_signal_triggered.keys())
            if not notes.get('strategy_labels'):
                notes['strategy_labels'] = first_signal_labels
            conn.execute(
                "UPDATE positions SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE position_id = ?",
                (json.dumps(notes, ensure_ascii=False), pos.get('position_id'))
            )
            simulated_updated += 1
        conn.commit()

    return {
        'theory_updated': theory_updated,
        'actual_updated': actual_updated,
        'simulated_updated': simulated_updated,
    }


def mode_scan(cache):
    """扫描 D+1 买入信号 + 同步理论信号到数据库"""
    db = MonitorDB()
    signals = scan_buy_signals(cache)
    today_str = datetime.now().strftime('%Y-%m-%d')
    all_results = scan_registrations(cache)

    # 同步理论信号
    sync_stats = mode_sync_db(cache)

    print(f"\n{'='*110}")
    sync_msg = ""
    if sync_stats['theory_synced'] or sync_stats['simulated_created']:
        sync_msg = (f" (同步 {sync_stats['theory_synced']} 个理论信号"
                    f"，生成 {sync_stats['simulated_created']} 条模拟持仓)")
    print(f"多策略组合监控 — {today_str}{sync_msg}")
    print(f"{'='*110}")

    if not signals:
        print(f"\n  今日无买入信号")
        if all_results:
            print(f"\n  近期注册事件 ({len(all_results)}只，20天内):")
            hdr = (
                f"  {_pad('名称', 14)} {_pad('代码', 8)} {_pad('注册日', 16)} "
                f"{_pad('T+', 6)} {_pad('首次信号', 16)} {_pad('首次策略', 18)} {_pad('当天策略', 18)} "
                f"{_pad('pre3', 7)} {_pad('mom10', 8)} {_pad('rc', 6)} {_pad('vol', 5)}"
            )
            print(hdr)
            print("  " + "-" * (_dw(hdr) - 2))
            for r in all_results[:10]:
                first_tag = _labels_text(r.get('first_signal_labels', []))
                current_tag = print_strategy_tags(r['triggered']) or '—'
                f = r['factors']
                d = r.get('days_since', r['calendar_diff'])
                fs = r.get('first_signal_date') or '--'
                row = [
                    _pad(r['name'], 14),
                    _pad(r['code'], 8),
                    _pad(r['anchor'], 16),
                    _format_t_plus(d, 6),
                    _pad(fs, 16),
                    _pad(first_tag, 18),
                    _pad(current_tag or '—', 18),
                    _format_pct(f['pre3'], 7),
                    _format_pct(f['mom10'], 8),
                    _format_pct(f['rc'], 6),
                    _pad(f"{f['vol_ratio5']:.2f}", 5),
                ]
                print("  " + " ".join(row))
    else:
        # 按触发数量排序（触发越多越优先）
        signals.sort(key=lambda x: active_hit_count(x['triggered']), reverse=True)

        print(f"\n  📢 买入信号 ({len(signals)}只, D+1开盘):")
        hdr = f"  {_pad('名称', 14)} {_pad('代码', 8)} {_pad('注册日', 16)} {_pad('买价', 8)} {'触发策略'}"
        print(hdr)
        print("  " + "-" * (_dw(hdr) - 2))

        for s in signals:
            f = s['factors']
            tags = print_strategy_tags(s['triggered'])
            bp = f"{s['factors']['buy_price']:.2f}" if s['factors']['buy_price'] else '--'
            print(f"  {_pad(s['name'], 14)} {_pad(s['code'], 8)} {_pad(s['anchor'], 16)} {_pad(bp, 8)} {tags}")

        # 按策略分组
        print(f"\n  按策略分组:")
        for key in registry.active_keys():
            group = [s for s in signals if s['triggered'].get(key)]
            if group:
                print(f"    {_display_name(key)}  sh={registry.get(key).sharpe}  exit={registry.get(key).best_exit}")
                for s in group:
                    bp = f"{s['factors']['buy_price']:.2f}" if s['factors']['buy_price'] else '--'
                    print(f"      {s['name']} {s['code']} 买价{bp}")

    simulated_rows = _build_simulated_hold_rows(cache, db, all_results)
    _print_hold_table("模拟持仓", simulated_rows)


def mode_hold(cache):
    """持仓监控 — 按策略动态退出信号 + 显示实际数据"""
    db = MonitorDB()
    holdings = scan_holdings(cache)
    today_str = datetime.now().strftime('%Y-%m-%d')
    backfill_map = {p['stock_code']: p for p in db.get_backfill_positions()}

    print(f"\n  📊 持仓监控 ({len(holdings)}只):")
    hdr = f"  {_pad('名称', 14)} {_pad('代码', 8)} {_pad('T+', 6)} {_pad('买价', 8)} {_pad('现价', 8)} {_pad('盈亏', 8)} {_pad('止盈止损', 24)} {'触发策略'}"
    print(hdr)
    print("  " + "-" * (_dw(hdr) - 2))

    if not holdings:
        print(f"  无持仓")
        return

    holdings.sort(key=lambda x: x['calendar_diff'])
    for h in holdings:
        f = h['factors']
        parts = _hold_display_parts(f, h['triggered'])
        bp = parts['buy_price']
        cp = parts['current_price']
        pnl = parts['pnl']
        exit_str = parts['exit_str']
        tags = parts['tags']

        # 显示交易日天数
        display_days = h.get('days_since', h['calendar_diff'])

        # 读取实际数据
        actual_info = ''
        comp = db.get_position_comparison(h['code'])
        if comp and comp.get('actual'):
            a = comp['actual']
            if a.get('actual_buy_price'):
                pos_label = _position_source_label(a)
                actual_buy = f"{a['actual_buy_price']:.2f}"
                notes = a.get('notes_data', {}) or {}
                if not notes and backfill_map.get(h['code']):
                    notes = load_position_notes_data(backfill_map[h['code']])
                signal_labels = notes.get('strategy_labels', []) or []
                sell_mode = notes.get('sell_mode', 'TPSL')
                actual_signal = _actual_sell_alert(
                    h['factors'].get('current_close'),
                    a['actual_buy_price'],
                    sell_mode,
                    a.get('registration_date') or backfill_map.get(h['code'], {}).get('registration_date')
                )
                signal_str = '/'.join(signal_labels) if signal_labels else '--'
                if a.get('actual_sell_price'):
                    actual_sell = f"{a['actual_sell_price']:.2f}"
                    actual_ret = f"{a.get('return_pct', 0):+.1f}%"
                    actual_info = f" |{pos_label}:信号[{signal_str}] 买{actual_buy}卖{actual_sell}收{actual_ret}"
                else:
                    actual_info = f" |{pos_label}:信号[{signal_str}] 买{actual_buy} {actual_signal}"
            elif a.get('status') == 'closed':
                actual_info = f" |{_position_source_label(a)}:已平仓"

        row = {
            'name': h['name'],
            'code': h['code'],
            'days': display_days,
            'buy_price': bp,
            'current_price': cp,
            'pnl': pnl,
            'exit_str': exit_str,
            'tags': tags + actual_info,
        }
        print("  " + " ".join(_hold_row_cells(row)))


def mode_compare(cache, stock_code):
    """查看理论 vs 实际对比"""
    db = MonitorDB()
    comp = db.get_position_comparison(stock_code)
    backfill_map = {p['stock_code']: p for p in db.get_backfill_positions()}

    print(f"\n{'='*110}")
    print(f"  理论 vs 实际对比 — {stock_code}")
    print(f"{'='*110}")

    if not comp:
        print(f"\n  无数据")
        return

    theory = comp.get('theory')
    actual = comp.get('actual')
    comparison = comp.get('comparison')

    if theory:
        print(f"\n  📊 理论信号:")
        print(f"    注册日: {theory.get('registration_date', '')}")
        print(f"    首次信号日: {theory.get('first_signal_date') or '--'}")
        print(f"    首次策略: {', '.join(theory.get('strategy_labels', [])) or '--'}")
        current_row = next((r for r in scan_registrations(cache) if r.get('code') == stock_code), None)
        print(f"    当天策略: {print_strategy_tags(current_row['triggered']) if current_row else '--'}")
        print(f"    买入价: {theory.get('theory_buy_price', '--')}")
        print(f"    退出方式: {theory.get('theory_exit_type', '--')}")
        print(f"    理论收益: {theory.get('theory_pnl_pct', '--'):+.2f}%")
        factors = theory.get('theory_factors', {})
        if factors:
            factor_str = ' '.join(f"{k}={v:+.2f}" if isinstance(v, float) else f"{k}={v}"
                                 for k, v in factors.items()
                                 if k in ('pre3', 'mom10', 'rc', 'vol_ratio5', 'consec_down'))
            print(f"    因子: {factor_str}")

    if actual:
        section_title = "模拟持仓" if actual.get('source') == 'backfill' else "实际操作"
        print(f"\n  📊 {section_title}:")
        pnl_label = "模拟收益" if section_title == "模拟持仓" else "实际收益"
        notes = actual.get('notes_data', {}) or {}
        if not notes and backfill_map.get(stock_code):
            notes = load_position_notes_data(backfill_map[stock_code])
        signal_labels = notes.get('strategy_labels', []) or []
        current_row = next((r for r in scan_registrations(cache) if r.get('code') == stock_code), None)
        current_labels = print_strategy_tags(current_row['triggered']) if current_row else '--'
        sell_mode = notes.get('sell_mode', 'TPSL')
        first_signal_date = notes.get('first_signal_date') or actual.get('first_signal_date') or '--'
        print(f"    买入日: {actual.get('actual_buy_date') or '--'}")
        print(f"    首次信号日: {first_signal_date}")
        print(f"    首次策略: {'/'.join(signal_labels) if signal_labels else '--'}")
        print(f"    当天策略: {current_labels}")
        print(f"    买入价: {actual.get('actual_buy_price') or '--'}")
        print(f"    卖出日: {actual.get('actual_sell_date') or '--'}")
        print(f"    卖出价: {actual.get('actual_sell_price') or '--'}")
        print(f"    持仓天数: {actual.get('hold_days') or '--'}")
        rp = actual.get('return_pct')
        print(f"    {pnl_label}: {rp:+.2f}%" if rp is not None else f"    {pnl_label}: --")
        print(f"    状态: {actual.get('status') or '--'}")
        if signal_labels:
            print(f"    触发策略: {'/'.join(signal_labels)}")
        print(f"    卖出模式: {sell_mode}")

    if comparison:
        print(f"\n  📊 对比:")
        print(f"    买入价差异: {comparison['price_diff_pct']:+.2f}%")
        print(f"    理论收益: {comparison['theory_return_pct']:+.2f}%")
        print(f"    实际收益: {comparison['actual_return_pct']:+.2f}%")
        print(f"    收益差异: {comparison['return_diff_pct']:+.2f}%")


# ========== 主入口 ==========

def main():
    cache = BacktestCache()
    db = MonitorDB()

    args = sys.argv[1:]
    mode = '--once'
    combo_mode = None
    is_backtest = False
    disable_keys = []
    is_sync_db = False
    compare_code = None
    buy_cmd = None   # (code, date, price, reg_date?)
    sell_cmd = None  # (code, date, price, reg_date?)

    i = 0
    while i < len(args):
        if args[i] == '--backtest':
            is_backtest = True
            i += 1
        elif args[i] == '--disable' and i + 1 < len(args):
            disable_keys = [k.strip() for k in args[i+1].split(',')]
            i += 2
        elif args[i] == '--combo' and not is_backtest:
            mode = '--combo'
            i += 1
        elif args[i] == '--scan':
            mode = '--scan'
            i += 1
        elif args[i] == '--hold':
            mode = '--hold'
            i += 1
        elif args[i] == '--status':
            mode = '--status'
            i += 1
        elif args[i] == '--once':
            mode = '--once'
            i += 1
        elif args[i] == '--sync-db':
            is_sync_db = True
            i += 1
        elif args[i] == '--compare' and i + 1 < len(args):
            compare_code = args[i+1]
            i += 2
        elif args[i] == '--buy' and i + 3 < len(args):
            code = args[i+1]
            date = args[i+2]
            price = float(args[i+3])
            reg_date = args[i+4] if i + 4 < len(args) and not args[i+4].startswith('--') else None
            buy_cmd = (code, date, price, reg_date)
            i += 4 + (1 if reg_date else 0)
        elif args[i] == '--sell' and i + 3 < len(args):
            code = args[i+1]
            date = args[i+2]
            price = float(args[i+3])
            reg_date = args[i+4] if i + 4 < len(args) and not args[i+4].startswith('--') else None
            sell_cmd = (code, date, price, reg_date)
            i += 4 + (1 if reg_date else 0)
        else:
            i += 1

    if disable_keys:
        registry.disable(disable_keys)

    if is_backtest:
        for a in args:
            if a == '--combo':
                combo_mode = 'union'
                break
        if 'all' in args:
            combo_mode = 'all'
        mode_backtest(cache, combo_mode)
        return

    cache.ensure_jisilu_data_for_today()
    backfill_stats = backfill_first_signal_history(cache)
    if backfill_stats['theory_updated'] or backfill_stats['actual_updated']:
        print(
            f"回填首次信号: 理论{backfill_stats['theory_updated']}条, "
            f"实际{backfill_stats['actual_updated']}条"
        )

    if is_sync_db:
        mode_sync_db(cache)
        return

    if compare_code:
        mode_compare(cache, compare_code)
        return

    if buy_cmd:
        code, date, price, reg_date = buy_cmd
        # 从注册事件查名称
        name = ''
        if reg_date:
            with db._get_conn() as conn:
                row = conn.execute(
                    "SELECT stock_name FROM registration_events WHERE stock_code=? AND registration_date=?",
                    (code, reg_date)
                ).fetchone()
                if row:
                    name = (row['stock_name'] or '')[:12]
        triggered_keys, triggered_labels, resolved_reg_date, first_signal_date = resolve_actual_signal_meta(cache, code, reg_date)
        db.record_actual_buy(stock_code=code, buy_date=date, buy_price=price,
                             registration_date=resolved_reg_date or reg_date, stock_name=name,
                             first_signal_date=first_signal_date,
                             triggered_strategies=triggered_keys,
                             strategy_labels=triggered_labels,
                             sell_mode='TPSL')
        current_row = next((r for r in scan_registrations(cache) if r.get('code') == code), None)
        current_labels = print_strategy_tags(current_row['triggered']) if current_row else '--'
        print(f"已记录买入: {name or code}({code}) 买价={price:.2f} 日期={date}"
              + (f" 注册日={resolved_reg_date or reg_date}" if (resolved_reg_date or reg_date) else "")
              + (f" 首信号={first_signal_date}" if first_signal_date else "")
              + (f" 首次策略={'/'.join(triggered_labels)}" if triggered_labels else "")
              + (f" 当天策略={current_labels}")
              + " 卖出=TP/SL")
        return

    if sell_cmd:
        code, date, price, reg_date = sell_cmd
        result = db.record_actual_sell(stock_code=code, sell_date=date, sell_price=price,
                                       registration_date=reg_date)
        ret = result.get('return_pct', 0)
        print(f"已记录卖出: {code} 卖价={price:.2f} 日期={date} 收益={ret:+.2f}%")
        return

    if mode == '--scan':
        mode_scan(cache)
    elif mode == '--hold':
        mode_hold(cache)
    elif mode == '--combo':
        mode_combo(cache)
    elif mode == '--status':
        mode_status(cache)
    elif mode == '--once':
        mode_scan(cache)
        mode_hold(cache)
        print()
        print(f"{'='*110}")
        print("策略说明:")
        for key in registry.active_keys():
            s = registry.get(key)
            print(f"  {_display_name(key)}  (exit={s.best_exit}, sh={s.sharpe})")
        print(f"{'='*110}")
    else:
        print(f"未知模式: {mode}")
        print("可用: --scan --hold --once --combo --status --sync-db --compare CODE")
        print("回测: --backtest [--combo]")


if __name__ == '__main__':
    main()
