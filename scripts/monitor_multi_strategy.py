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
import sys, os, re
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.backtest_cache import BacktestCache
from lib.strategies import registry
from lib.monitor_db import MonitorDB


def find_idx(sd, target):
    result = 0
    for i, d in enumerate(sd):
        if d <= target:
            result = i
        else:
            break
    return result


def calc_factors(cache, sc, anchor):
    """计算所有因子"""
    prices = cache.get_kline_as_dict(sc, days=1500)
    if not prices:
        return None
    sd = sorted(prices.keys())
    today_str = datetime.now().strftime('%Y-%m-%d')
    ri = find_idx(sd, anchor)
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
            print(f"  {'Limit':<10} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6} {'持有':>5} {'年化':>8}")
            print("  " + "-" * 60)

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

        print(f"\n  {'策略':<42} {'L=100':>14} {'L=150':>14} {'L=200':>14} {'全量':>14}")
        print(f"  {'':42} {'n avg sh':>14} {'n avg sh':>14} {'n avg sh':>14} {'n avg sh':>14}")
        print("  " + "-" * 80)

        for key in registry.active_keys():
            parts = []
            for limit in [100, 150, 200, 0]:
                pl = pool[:limit] if limit else pool
                d9, tp = run_backtest_single(pl, key)
                if d9:
                    parts.append(f"{d9['n']:>3} {d9['avg']:>+4.1f}% sh={d9['sharpe']:+.2f}")
                else:
                    parts.append("        --")
            print(f"  {_display_name(key):<42} {parts[0]:>14} {parts[1]:>14} {parts[2]:>14} {parts[3]:>14}")

        print(f"\n" + "-" * 110)
        print(f"  独立策略回测 (TP5/SL5 动态退出)")
        print(f"{'-'*110}")

        print(f"\n  {'策略':<42} {'L=100':>22} {'L=150':>22} {'L=200':>22} {'全量':>22}")
        print(f"  {'':42} {'n avg sh eff':>22} {'n avg sh eff':>22} {'n avg sh eff':>22} {'n avg sh eff':>22}")
        print("  " + "-" * 115)

        for key in registry.active_keys():
            parts = []
            for limit in [100, 150, 200, 0]:
                pl = pool[:limit] if limit else pool
                d9, tp = run_backtest_single(pl, key)
                if tp:
                    eff = tp['avg'] / tp['avg_hold'] * 245 if tp['avg_hold'] > 0 else 0
                    parts.append(f"{tp['n']:>3} {tp['avg']:>+4.1f}% sh={tp['sharpe']:+.2f} eff={eff:+.0f}%")
                else:
                    parts.append("            --")
            print(f"  {_display_name(key):<42} {parts[0]:>22} {parts[1]:>22} {parts[2]:>22} {parts[3]:>22}")

        # 稳定性总结
        print(f"\n" + "-" * 110)
        print(f"  稳定性总结 (TP5/SL5夏普趋势)")
        print(f"{'-'*110}")

        print(f"\n  {'策略':<42} {'L=100':>8} {'L=150':>8} {'L=200':>8} {'全量':>8} {'趋势':>10}")
        print("  " + "-" * 90)

        for key in registry.active_keys():
            shards = []
            for limit in [100, 150, 200, 0]:
                pl = pool[:limit] if limit else pool
                d9, tp = run_backtest_single(pl, key)
                shards.append(tp['sharpe'] if tp else None)
            if all(x is not None for x in shards):
                diff = shards[-1] - shards[0]
                trend = '→稳定' if abs(diff) < 0.2 else '→衰减' if diff < -0.2 else '→上升'
                parts_s = [f'{x:+.2f}' for x in shards]
            else:
                trend = '???'; parts_s = [f'{x:+.2f}' if x else '--' for x in shards]
            print(f"  {_display_name(key):<42} {parts_s[0]:>8} {parts_s[1]:>8} {parts_s[2]:>8} {parts_s[3]:>8} {trend:>10}")

    # 年份分组（只对L=200和全量）
    print(f"\n" + "-" * 110)
    print(f"  按年份分组 (L=200, TP5/SL5)")
    print(f"{'-'*110}")

    pool_200 = pool[:200]
    for key in registry.active_keys():
        s_cond = registry.get(key).condition
        print(f"\n  {_display_name(key)}:")
        print(f"    {'年份':<8} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6} {'年化':>8}")
        print("    " + "-" * 50)
        for year in ['2023', '2024', '2025', '2026']:
            yr_pool = [s for s in pool_200 if s['anchor'].startswith(year) and s_cond(s['factors'])]
            if not yr_pool:
                continue
            tp = test_tp5_sl5_exit(yr_pool)
            if tp and tp['n'] >= 2:
                eff = tp['avg'] / tp['avg_hold'] * 245 if tp['avg_hold'] > 0 else 0
                print(f"    {year}年 {tp['n']:>4} {tp['avg']:>+6.2f}% {tp['win']:>5.1f}% {tp['sharpe']:>+5.2f} {eff:>+7.1f}%")
            elif tp:
                print(f"    {year}年 {tp['n']:>4} (样本不足)")


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

        factors = calc_factors(cache, sc, anchor)
        if not factors:
            continue

        triggered = check_strategies(factors)
        hit_count = sum(1 for v in triggered.values() if v)

        results.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'calendar_diff': calendar_diff,
            'days_since': factors.get('days_since', 0),
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
    print(f"  {'名称':<12} {'代码':>8} {'注册日':<12} {'天数':>4} {'策略数':>4} {'触发策略':>50} {'盈亏'}")
    print("  " + "-" * 105)

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
            print(f"  {s['name']:<12} {s['code']:>8} {s['anchor']:<12} "
                  f"T+{d:>3}  {active_hit_count(s['triggered'])}个策略  {tags:<48} 买价{bp}")

    if hold:
        print(f"\n  📊 持仓:")
        for h in hold:
            f = h['factors']
            pnl = f"{f['pnl_pct']:+.1f}%" if f['pnl_pct'] is not None else '--'
            tags = print_strategy_tags(h['triggered'])
            d = h.get('days_since', h['calendar_diff'])
            print(f"  {h['name']:<12} {h['code']:>8} {h['anchor']:<12} "
                  f"T+{d:>3}  {active_hit_count(h['triggered'])}个策略  {tags:<48} {pnl}")

    if past:
        print(f"\n  已过退出期:")
        for p in past[:5]:
            f = p['factors']
            pnl = f"{f['pnl_pct']:+.1f}%" if f['pnl_pct'] is not None else '--'
            tags = print_strategy_tags(p['triggered'])
            d = p.get('days_since', p['calendar_diff'])
            print(f"  {p['name']:<12} {p['code']:>8} {p['anchor']:<12} "
                  f"T+{d:>3}  {active_hit_count(p['triggered'])}个策略  {tags:<48} {pnl}")


def mode_status(cache):
    """列出所有近期注册事件"""
    results = scan_registrations(cache)
    today_str = datetime.now().strftime('%Y-%m-%d')

    print(f"\n{'='*110}")
    print(f"全部注册事件 — {today_str} ({len(results)}只)")
    print(f"{'='*110}")

    active = registry.active_keys()
    col_w = max(5, max(len(_short_name(k))+1 for k in active)) if active else 6
    header_cols = ' '.join(f"{_short_name(k):>{col_w}}" for k in active)
    print(f"\n  {'名称':<12} {'代码':>8} {'注册日':<12} {'天数':>4}  {header_cols}  "
          f"{'pre3':>7} {'mom10':>7} {'rc':>6} {'vol':>5}")
    print("  " + "-" * 110)

    for r in results:
        f = r['factors']
        t = r['triggered']
        cols = ' '.join(f"{'✅' if t.get(k) else '':>{col_w}}" for k in active)
        d = r.get('days_since', r['calendar_diff'])
        print(f"  {r['name']:<12} {r['code']:>8} {r['anchor']:<12} "
              f"T+{d:>3}  {cols}  "
              f"{f['pre3']:>+6.1f}% {f['mom10']:>+6.1f}% "
              f"{f['rc']:>+5.1f}% {f['vol_ratio5']:>5.2f}")


def mode_sync_db(cache):
    """将理论信号写入 monitor.db（自动跳过相同数据）"""
    results = scan_registrations(cache)
    db = MonitorDB()

    # 获取所有触发策略的注册事件
    triggered_results = [r for r in results
                        if any(r['triggered'].get(k) for k in registry.active_keys())]

    if not triggered_results:
        return 0

    synced = 0
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
        synced += 1

    return synced


def mode_scan(cache):
    """扫描 D+1 买入信号 + 同步理论信号到数据库"""
    db = MonitorDB()
    signals = scan_buy_signals(cache)
    today_str = datetime.now().strftime('%Y-%m-%d')

    # 同步理论信号
    synced = mode_sync_db(cache)

    print(f"\n{'='*110}")
    print(f"多策略组合监控 — {today_str}" + (f" (同步 {synced} 个理论信号)" if synced else ""))
    print(f"{'='*110}")

    if not signals:
        print(f"\n  今日无买入信号")
        # 显示近期注册事件（附加实际数据）
        all_results = scan_registrations(cache)
        if all_results:
            print(f"\n  近期注册事件 ({len(all_results)}只，20天内):")
            print(f"  {'名称':<12} {'代码':>8} {'注册日':<12} {'天数':>4} {'策略触发'}")
            print("  " + "-" * 90)
            for r in all_results[:10]:
                tag = print_strategy_tags(r['triggered']) or '—'
                f = r['factors']
                d = r.get('days_since', r['calendar_diff'])

                # 读取实际数据
                actual_info = ''
                comp = db.get_position_comparison(r['code'])
                if comp and comp.get('actual'):
                    a = comp['actual']
                    if a.get('actual_buy_price'):
                        buy_p = f"买={a['actual_buy_price']:.2f}"
                        if a.get('actual_sell_price'):
                            sell_p = f"卖={a['actual_sell_price']:.2f}"
                            ret_p = f"收益={a.get('return_pct', 0):+.1f}%"
                            actual_info = f" [{buy_p} {sell_p} {ret_p}]"
                        else:
                            actual_info = f" [{buy_p} 持仓中]"
                    elif a.get('status') == 'closed':
                        actual_info = f" [已平仓]"

                print(f"  {r['name']:<12} {r['code']:>8} {r['anchor']:<12} "
                      f"T+{d:>3}  {tag}{actual_info}  "
                      f"pre3={f['pre3']:+.1f}% mom10={f['mom10']:+.1f}% "
                      f"rc={f['rc']:+.1f}% vol={f['vol_ratio5']:.2f}")
        return

    # 按触发数量排序（触发越多越优先）
    signals.sort(key=lambda x: active_hit_count(x['triggered']), reverse=True)

    print(f"\n  📢 买入信号 ({len(signals)}只, D+1开盘):")
    print(f"  {'名称':<12} {'代码':>8} {'注册日':<12} {'买价':>8} {'触发策略':>50}")
    print("  " + "-" * 95)

    for s in signals:
        f = s['factors']
        tags = print_strategy_tags(s['triggered'])
        bp = f"{s['factors']['buy_price']:.2f}" if s['factors']['buy_price'] else '--'
        print(f"  {s['name']:<12} {s['code']:>8} {s['anchor']:<12} {bp:>8} {tags}")

    # 按策略分组
    print(f"\n  按策略分组:")
    for key in registry.active_keys():
        group = [s for s in signals if s['triggered'].get(key)]
        if group:
            print(f"    {_display_name(key)}  sh={registry.get(key).sharpe}  exit={registry.get(key).best_exit}")
            for s in group:
                bp = f"{s['factors']['buy_price']:.2f}" if s['factors']['buy_price'] else '--'
                print(f"      {s['name']} {s['code']} 买价{bp}")


def mode_hold(cache):
    """持仓监控 — 按策略动态退出信号 + 显示实际数据"""
    db = MonitorDB()
    holdings = scan_holdings(cache)
    today_str = datetime.now().strftime('%Y-%m-%d')

    print(f"\n  📊 持仓监控 ({len(holdings)}只):")
    print(f"  {'名称':<12} {'代码':>8} {'持仓':>4} {'买价':>8} {'现价':>8} {'盈亏':>8} {'止盈止损':>6} {'触发策略'}")
    print("  " + "-" * 100)

    if not holdings:
        print(f"  无持仓")
        return

    holdings.sort(key=lambda x: x['calendar_diff'])
    for h in holdings:
        f = h['factors']
        bp = f"{f['buy_price']:.2f}" if f['buy_price'] else '--'
        cp = f"{f['current_close']:.2f}" if f['current_close'] else '--'
        pnl = f"{f['pnl_pct']:+.1f}%" if f['pnl_pct'] is not None else '--'

        # 从触发的策略中取最优退出阈值
        triggered_keys = [k for k in registry.active_keys() if h['triggered'].get(k)]
        tp_val, sl_val = 5, 5
        exit_label = 'D+9'
        if triggered_keys:
            s = registry.get(triggered_keys[0])
            if s:
                tp_val, sl_val = parse_exit_thresholds(s.best_exit)
                exit_label = s.best_exit or 'D+9'

        tp_mark = '✅' if f['pnl_pct'] and f['pnl_pct'] >= tp_val else ' '
        sl_mark = '⚠️' if f['pnl_pct'] and f['pnl_pct'] <= -sl_val else ' '
        exit_str = f"{tp_mark}{sl_mark} ({exit_label})"
        tags = print_strategy_tags(h['triggered'])

        # 显示交易日天数
        display_days = h.get('days_since', h['calendar_diff'])

        # 读取实际数据
        actual_info = ''
        comp = db.get_position_comparison(h['code'])
        if comp and comp.get('actual'):
            a = comp['actual']
            if a.get('actual_buy_price'):
                actual_buy = f"{a['actual_buy_price']:.2f}"
                if a.get('actual_sell_price'):
                    actual_sell = f"{a['actual_sell_price']:.2f}"
                    actual_ret = f"{a.get('return_pct', 0):+.1f}%"
                    actual_info = f" |实际:买{actual_buy}卖{actual_sell}收{actual_ret}"
                else:
                    actual_info = f" |实际:买{actual_buy}持仓中"
            elif a.get('status') == 'closed':
                actual_info = f" |实际:已平仓"

        print(f"  {h['name']:<12} {h['code']:>8} T+{display_days:>3} "
              f"{bp:>8} {cp:>8} {pnl:>8} {exit_str:>8} {tags}{actual_info}")


def mode_compare(cache, stock_code):
    """查看理论 vs 实际对比"""
    db = MonitorDB()
    comp = db.get_position_comparison(stock_code)

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
        print(f"    策略: {', '.join(theory.get('triggered_strategies', []))}")
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
        print(f"\n  📊 实际操作:")
        print(f"    买入日: {actual.get('actual_buy_date') or '--'}")
        print(f"    买入价: {actual.get('actual_buy_price') or '--'}")
        print(f"    卖出日: {actual.get('actual_sell_date') or '--'}")
        print(f"    卖出价: {actual.get('actual_sell_price') or '--'}")
        print(f"    持仓天数: {actual.get('hold_days') or '--'}")
        rp = actual.get('return_pct')
        print(f"    实际收益: {rp:+.2f}%" if rp is not None else "    实际收益: --")
        print(f"    状态: {actual.get('status') or '--'}")

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
        db.record_actual_buy(stock_code=code, buy_date=date, buy_price=price,
                             registration_date=reg_date, stock_name=name)
        print(f"已记录买入: {name or code}({code}) 买价={price:.2f} 日期={date}"
              + (f" 注册日={reg_date}" if reg_date else ""))
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
