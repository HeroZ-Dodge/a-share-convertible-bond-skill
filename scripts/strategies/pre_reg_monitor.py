# -*- coding: utf-8 -*-
"""
注册前信号监控 + 回测

策略核心：每天扫描处于"上市委通过 → 同意注册"审批通道的转债，
用 T-1 及之前的 K 线数据判断信号，T+1 开盘买入，注册日次日卖出。

买入信号：
  动量恢复:   pre3<=-1.5+mom10>=0.5+vol5<=0.9  (70%胜率, 年化+27%)
  深跌反弹:   pre5<=-3+mom10>=1+vol5<=0.8       (60%胜率, 年化+30%)
  高胜率:     pre5<=-1.5+mom10>=2+vol5<=0.9     (74%胜率, 年化+36%)
  MA5过滤:    pre5<=-1+mom10>=4+vol5<=0.85+ma5p<=-0.5 (75%胜率, 年化+42%)
  近期恢复:   pre3>=0+mom10>=3                  (66%胜率, 年化+55%)

卖出信号：持仓期间每日盯市，TP+5%/SL-5% 次日卖出

所有因子仅依赖 K 线数据（收盘价、成交量），不依赖注册日信息。

用法:
  --scan                    扫描今日注册前信号（需集思录实时数据）
  --backtest                历史回测（所有已注册转债）
  --backtest --limit 100    指定样本数
  --backtest --strategy mom_recover  指定策略
"""
import sys, os, re, math
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.backtest_cache import BacktestCache


# ========== 策略定义 ==========

SCAN_START = 20  # 距上市委通过第 20 个交易日起检测
TP = 5.0         # 止盈阈值%
SL = -5.0        # 止损阈值%


class PreRegStrategy:
    """注册前策略定义"""

    __slots__ = ('key', 'label', 'display_name', 'condition', 'best_exit', 'sharpe', 'win_rate', 'annual')

    def __init__(self, key, label, display_name, condition,
                 best_exit='', sharpe='', win_rate='', annual=''):
        self.key = key
        self.label = label
        self.display_name = display_name
        self.condition = condition
        self.best_exit = best_exit
        self.sharpe = sharpe
        self.win_rate = win_rate
        self.annual = annual

    def matches(self, factors):
        return self.condition(factors)


PRE_REG_STRATEGIES = [
    PreRegStrategy(
        key='mom_recover', label='pre3<=-1.5+mom10>=0.5+vol5<=0.9',
        display_name='动量恢复',
        condition=lambda f: f['pre3'] <= -1.5 and f['mom10'] >= 0.5 and f['vol5'] <= 0.9,
        best_exit='REG', win_rate='70%', annual='+27%',
    ),
    PreRegStrategy(
        key='deep_rebound', label='pre5<=-3+mom10>=1+vol5<=0.8',
        display_name='深跌反弹',
        condition=lambda f: f['pre5'] <= -3 and f['mom10'] >= 1 and f['vol5'] <= 0.8,
        best_exit='REG', win_rate='60%', annual='+30%',
    ),
    PreRegStrategy(
        key='high_win', label='pre5<=-1.5+mom10>=2+vol5<=0.9',
        display_name='高胜率',
        condition=lambda f: f['pre5'] <= -1.5 and f['mom10'] >= 2 and f['vol5'] <= 0.9,
        best_exit='REG', win_rate='74%', annual='+36%',
    ),
    PreRegStrategy(
        key='ma5p_filter', label='pre5<=-1+mom10>=4+vol5<=0.85+ma5p<=-0.5',
        display_name='MA5过滤',
        condition=lambda f: f['pre5'] <= -1 and f['mom10'] >= 4 and f['vol5'] <= 0.85 and f['ma5p'] <= -0.5,
        best_exit='REG', win_rate='75%', annual='+42%',
    ),
    PreRegStrategy(
        key='pre3_recovery', label='pre3>=0+mom10>=3',
        display_name='近期恢复',
        condition=lambda f: f['pre3'] >= 0 and f['mom10'] >= 3,
        best_exit='REG', win_rate='60%', annual='+39%',
    ),
]
DEPRECATED_STRATEGIES = [
    'deep_rebound',    # sh=+0.28 胜率53.5%
    'pre3_recovery',   # sh=+0.24 胜率59.8%
]


# ========== 因子计算 ==========

def find_idx(dates, target):
    """找到 d <= target 的最后一个索引"""
    result = 0
    for i, d in enumerate(dates):
        if d <= target:
            result = i
        else:
            break
    return result


def calc_factors_at(closes, volumes, idx):
    """计算 idx 日收盘后的策略因子（仅使用 idx 及之前数据，无 look-ahead bias）"""
    if idx < 22:
        return None

    t1, t3, t5, t10, t20 = closes[idx - 1], closes[idx - 3], closes[idx - 5], closes[idx - 10], closes[idx - 20]
    pre3 = ((t1 - t3) / t3 * 100) if t3 > 0 else 0
    pre5 = ((t1 - t5) / t5 * 100) if t5 > 0 else 0
    mom10 = ((t1 - t10) / t10 * 100) if t10 > 0 else 0
    mom20 = ((t1 - t20) / t20 * 100) if t20 > 0 else 0

    vol_t = volumes[idx]
    avg5 = sum(volumes[idx - 5:idx]) / 5
    vol5 = vol_t / avg5 if avg5 > 0 else 1.0
    avg10 = sum(volumes[idx - 10:idx]) / 10 if idx >= 10 else avg5
    vol10 = vol_t / avg10 if avg10 > 0 else 1.0

    cdown = sum(1 for i in range(idx, 0, -1) if closes[i] < closes[i - 1])
    cup = sum(1 for i in range(idx, 0, -1) if closes[i] >= closes[i - 1])

    ma5 = sum(closes[idx - 5:idx]) / 5
    ma5p = (closes[idx] / ma5 - 1) * 100
    ma10 = sum(closes[idx - 10:idx]) / 10
    ma10p = (closes[idx] / ma10 - 1) * 100
    ma20 = sum(closes[idx - 20:idx]) / 20
    ma20p = (closes[idx] / ma20 - 1) * 100

    return {
        'pre3': pre3, 'pre5': pre5, 'mom10': mom10, 'mom20': mom20,
        'vol5': vol5, 'vol10': vol10,
        'cdown': cdown, 'cup': cup,
        'ma5p': ma5p, 'ma10p': ma10p, 'ma20p': ma20p,
    }


def _dw(s):
    """Calculate display width (CJK chars = 2 cols)"""
    return sum(2 if '一' <= c <= '鿿' else 1 for c in str(s))

def _pad(s, width, left=True):
    """Pad/truncate string to target display width"""
    s = str(s)
    dw = _dw(s)
    if dw >= width:
        result, used = '', 0
        for c in s:
            cw = 2 if '一' <= c <= '鿿' else 1
            if used + cw > width:
                break
            result += c
            used += cw
        return result + ' ' * (width - used)
    padding = width - dw
    if left:
        return s + ' ' * padding
    else:
        return ' ' * padding + s

def parse_progress_full(text):
    """从 progress_full 解析上市委通过和同意注册日期"""
    tg_date, reg_date = '', ''
    for line in text.replace('<br>', '\n').split('\n'):
        line = line.strip()
        if '上市委通过' in line:
            m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
            if m: tg_date = m.group(1)
        if '同意注册' in line:
            m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
            if m: reg_date = m.group(1)
    return tg_date, reg_date


def scan_signals_for_bond(closes, volumes, dates, tg_idx, reg_idx, strategies):
    """扫描单只债券从上市委通过到注册期间的每日信号"""
    signals = []
    for idx in range(tg_idx + SCAN_START, reg_idx):
        factors = calc_factors_at(closes, volumes, idx)
        if not factors:
            continue
        triggered = {s.key: s.matches(factors) for s in strategies}
        if any(triggered.values()):
            signals.append({'date': dates[idx], 'idx': idx, 'factors': factors, 'triggered': triggered})
    return signals


def detect_sell_signals(closes, buy_idx, reg_idx):
    """逐日盯市，检测 TP/SL 信号"""
    buy_price = closes[buy_idx]
    tp_hit = sl_hit = None
    max_gain = 0
    for idx in range(buy_idx + 1, min(reg_idx + 2, len(closes))):
        daily_ret = (closes[idx] / buy_price - 1) * 100
        if daily_ret >= TP and tp_hit is None:
            tp_hit = idx
        if daily_ret <= SL and sl_hit is None:
            sl_hit = idx
        max_gain = max(max_gain, daily_ret)
    return {'tp_hit': tp_hit, 'sl_hit': sl_hit,
            'tp_date': '', 'sl_date': '',
            'max_gain': max_gain}


# ========== 回测引擎 ==========

def scan_daily_factors(closes, volumes, dates, ti, ri):
    """预扫描所有交易日的因子（一次计算，多策略复用）"""
    factor_map = {}
    for idx in range(ti + SCAN_START, ri):
        f = calc_factors_at(closes, volumes, idx)
        if f:
            factor_map[idx] = f
    return factor_map


def build_backtest_pool(cache, strategies, check_interval=2):
    """回测池 — 每策略独立首次触发日评估

    每个 (债券, 策略) 对有独立条目：
    - 用该策略的真正首次触发日作为信号日
    - 独立计算买入价/卖出价/收益
    - 同一债券可能出现多次（每策略一次）
    """
    today_str = datetime.now().strftime('%Y-%m-%d')
    bonds = cache.get_jisilu_bonds(phase='注册', limit=0)
    pool = []

    for b in bonds:
        sc = b.get('stock_code')
        if not sc: continue
        pf = b.get('progress_full', '')
        if not pf: continue

        tongguo_date, reg_date = parse_progress_full(pf)
        if not reg_date or reg_date > today_str: continue
        if tongguo_date and tongguo_date >= reg_date:
            tongguo_date = ''

        klines = cache.get_kline_as_dict(sc, days=1500, skip_freshness_check=True)
        if not klines: continue
        dates = sorted(klines.keys())
        if len(dates) < 25: continue

        closes = [klines[d]['close'] for d in dates]
        volumes = [klines[d].get('volume', 0) for d in dates]
        opens = [klines[d].get('open', klines[d]['close']) for d in dates]

        ti = find_idx(dates, tongguo_date) if tongguo_date else 0
        ri = find_idx(dates, reg_date)
        if ti < 22: ti = 22
        if ri is None or ri <= ti: continue

        factor_map = scan_daily_factors(closes, volumes, dates, ti, ri)

        for s in strategies:
            # 找该策略首次触发日
            first_idx = None
            first_factors = None
            for idx in sorted(factor_map.keys()):
                if s.matches(factor_map[idx]):
                    first_idx = idx
                    first_factors = factor_map[idx]
                    break
            if first_idx is None: continue

            signal_date = dates[first_idx]
            # 次日买入
            buy_idx = None
            for i in range(first_idx + 1, len(dates)):
                if dates[i] > signal_date:
                    buy_idx = i
                    break
            if buy_idx is None or buy_idx >= len(dates): continue
            buy_price = opens[buy_idx] if opens[buy_idx] > 0 else closes[buy_idx]

            # 卖出日：监控检测
            sell_idx, hold_days = find_exit_with_monitoring(dates, buy_idx, reg_date, check_interval)
            if sell_idx is None or sell_idx >= len(dates) or dates[sell_idx] > today_str: continue
            if sell_idx <= buy_idx: continue

            sell_price = closes[sell_idx]
            ret = ((sell_price - buy_price) / buy_price * 100) if buy_price > 0 else 0

            # TP/SL 检测
            tp_hit = sl_hit = None
            for si in range(buy_idx + 1, min(ri + 2, len(closes))):
                daily_ret = (closes[si] / buy_price - 1) * 100
                if daily_ret >= TP and tp_hit is None: tp_hit = si
                if daily_ret <= SL and sl_hit is None: sl_hit = si

            actual_sell = sell_idx
            sell_type = 'REG'
            if sl_hit is not None and sl_hit > buy_idx and sl_hit < sell_idx:
                actual_sell = min(sl_hit + 1, len(dates) - 1, sell_idx)
                sell_type = 'SL'
            elif tp_hit is not None and tp_hit > buy_idx and tp_hit < sell_idx:
                actual_sell = min(tp_hit + 1, len(dates) - 1, sell_idx)
                sell_type = 'TP'

            tp_sl_ret = ((closes[actual_sell] - buy_price) / buy_price * 100) if buy_price > 0 else 0
            tp_sl_hold = actual_sell - buy_idx

            pool.append({
                'code': sc,
                'name': (b.get('bond_name') or b.get('stock_name') or b.get('stock_nm') or '?')[:12],
                'anchor': reg_date,
                'strategy_key': s.key,
                'signal_date': signal_date,
                'offset_reg': first_idx - ri,
                'offset_tongguo': first_idx - ti,
                'factors': first_factors,
                'buy_price': buy_price, 'sell_price': sell_price,
                'ret': ret, 'hold_days': hold_days,
                'tp_sl_ret': tp_sl_ret, 'tp_sl_hold': tp_sl_hold,
                'sell_type': sell_type,
            })

    pool.sort(key=lambda x: x['anchor'], reverse=True)
    return pool


def run_backtest(pool, strategies):
    """运行回测（每策略独立条目，按 strategy_key 过滤）"""
    results = {}
    for s in strategies:
        triggered = [p for p in pool if p.get('strategy_key') == s.key]
        if not triggered: continue

        fixed_stats = calc_stats(triggered)
        tp_sl_trades = [{'ret': t['tp_sl_ret'], 'hold_days': t['tp_sl_hold']} for t in triggered]
        tp_sl_stats = calc_stats(tp_sl_trades)

        by_year = {}
        for t in triggered:
            yr = t['anchor'][:4]
            by_year.setdefault(yr, []).append(t)

        year_stats = {yr: calc_stats(yt) for yr, yt in by_year.items()}

        sell_types = {}
        for t in triggered:
            st = t.get('sell_type', 'REG')
            sell_types[st] = sell_types.get(st, 0) + 1

        results[s.key] = {
            'strategy': s, 'fixed': fixed_stats, 'tp_sl': tp_sl_stats,
            'by_year': year_stats, 'count': len(triggered), 'sell_types': sell_types,
        }
    return results


def find_exit_with_monitoring(dates, buy_idx, reg_date, check_interval=2):
    """模拟监控退出：每 check_interval 天检查，发现同意注册后次日卖出"""
    ri = find_idx(dates, reg_date)
    if ri is None or ri < buy_idx: return None, 0
    for check in range(buy_idx + 1, len(dates), check_interval):
        if dates[check] > reg_date:
            sell_idx = min(check + 1, len(dates) - 1)
            return sell_idx, sell_idx - buy_idx
    sell_idx = ri + 1
    if sell_idx < len(dates):
        return sell_idx, sell_idx - buy_idx
    return None, 0


def calc_stats(trades):
    """计算回测统计（含夏普）"""
    if not trades: return None
    rets = [t['ret'] for t in trades]
    n = len(rets)
    avg = sum(rets) / n
    std = (sum((x - avg) ** 2 for x in rets) / n) ** 0.5
    sharpe = avg / std if std > 0 else 0
    win = sum(1 for x in rets if x > 0) / n * 100
    avg_hold = sum(t['hold_days'] for t in trades) / n
    return {'n': n, 'avg': avg, 'win': win, 'std': std,
            'sharpe': sharpe, 'avg_hold': avg_hold,
            'best': max(rets), 'worst': min(rets)}


def run_backtest(pool, strategies):
    """运行回测"""
    results = {}
    for s in strategies:
        triggered = [p for p in pool if s.matches(p['factors'])]
        if not triggered: continue

        fixed_stats = calc_stats(triggered)
        tp_sl_trades = [{'ret': t['tp_sl_ret'], 'hold_days': t['tp_sl_hold']} for t in triggered]
        tp_sl_stats = calc_stats(tp_sl_trades)

        by_year = {}
        for t in triggered:
            yr = t['anchor'][:4]
            by_year.setdefault(yr, []).append(t)

        year_stats = {yr: calc_stats(yt) for yr, yt in by_year.items()}

        sell_types = {}
        for t in triggered:
            st = t.get('sell_type', 'REG')
            sell_types[st] = sell_types.get(st, 0) + 1

        results[s.key] = {
            'strategy': s, 'fixed': fixed_stats, 'tp_sl': tp_sl_stats,
            'by_year': year_stats, 'count': len(triggered), 'sell_types': sell_types,
        }
    return results


# ========== 回测输出 ==========

def print_backtest_report(pool, results, limit, strategies=None):
    label = f'L={limit}' if limit else '全量'
    print(f'\n{"=" * 120}')
    print(f'注册前信号回测 — {label} (条目 {len(pool)}, 策略独立扫描)')
    print(f'{"=" * 120}')
    if not results:
        print('\n  无触发样本')
        return

    # 策略对比 — 监控退出
    print(f'\n  策略对比 (监控退出: 发现同意注册后次日卖出)')
    hdr = f"  {_pad('策略', 14)} {_pad('样本', 5)} {_pad('平均%', 7)} {_pad('胜率', 7)} {_pad('标准差', 7)} {_pad('夏普', 7)} {_pad('持有', 7)} {_pad('年化', 9)} {_pad('距通过', 6)}"
    print(hdr)
    print("  " + "-" * (_dw(hdr) - 2))
    for key, r in sorted(results.items(), key=lambda x: x[1]['fixed']['sharpe'] if x[1]['fixed'] else 0, reverse=True):
        s = r['strategy']; fs = r['fixed']
        ann = fs['avg'] / fs['avg_hold'] * 245 if fs['avg_hold'] > 0 else 0
        avg_off = sum(t['offset_tongguo'] for t in pool if t.get('strategy_key') == key) / r['count'] if r['count'] > 0 else 0
        p_name = s.display_name
        p_n = str(fs['n'])
        p_avg = f"{fs['avg']:+.1f}%"
        p_win = f"{fs['win']:.1f}%"
        p_std = f"{fs['std']:.1f}%"
        p_sh = f"{fs['sharpe']:+.2f}"
        p_hold = f"{fs['avg_hold']:.1f}d"
        p_ann = f"{ann:+.1f}%"
        p_off = f"D+{avg_off:.0f}"
        print(f"  {_pad(p_name, 14)} {_pad(p_n, 5)} {_pad(p_avg, 7)} {_pad(p_win, 7)} {_pad(p_std, 7)} {_pad(p_sh, 7)} {_pad(p_hold, 7)} {_pad(p_ann, 9)} {_pad(p_off, 5)}")

    # 策略对比 — TP/SL
    print(f'\n  策略对比 (TP{TP}%/SL{SL}% 止盈止损)')
    hdr = f"  {_pad('策略', 14)} {_pad('样本', 5)} {_pad('平均%', 7)} {_pad('胜率', 7)} {_pad('标准差', 7)} {_pad('夏普', 7)} {_pad('持有', 7)} {_pad('年化', 9)}"
    print(hdr)
    print("  " + "-" * (_dw(hdr) - 2))
    for key, r in sorted(results.items(), key=lambda x: x[1]['tp_sl']['sharpe'] if x[1]['tp_sl'] else 0, reverse=True):
        s = r['strategy']; ts = r['tp_sl']
        ann = ts['avg'] / ts['avg_hold'] * 245 if ts['avg_hold'] > 0 else 0
        p_name = s.display_name
        p_n = str(ts['n'])
        p_avg = f"{ts['avg']:+.1f}%"
        p_win = f"{ts['win']:.1f}%"
        p_std = f"{ts['std']:.1f}%"
        p_sh = f"{ts['sharpe']:+.2f}"
        p_hold = f"{ts['avg_hold']:.1f}d"
        p_ann = f"{ann:+.1f}%"
        print(f"  {_pad(p_name, 14)} {_pad(p_n, 5)} {_pad(p_avg, 7)} {_pad(p_win, 7)} {_pad(p_std, 7)} {_pad(p_sh, 7)} {_pad(p_hold, 7)} {_pad(p_ann, 9)}")

    # 年份稳定性
    print(f'\n  年份稳定性 (TP{TP}%/SL{SL}%)')
    hdr = f"  {_pad('策略', 14)} "
    for yr in ['2023', '2024', '2025', '2026']:
        hdr += f"{_pad(yr, 9)} "
    print(hdr)
    print("  " + "-" * (_dw(hdr) - 2))
    for key, r in sorted(results.items()):
        s = r['strategy']
        row = f"  {_pad(s.display_name, 14)} "
        for yr in ['2023', '2024', '2025', '2026']:
            ys = r['by_year'].get(yr)
            if ys and ys['n'] >= 2:
                row += _pad(f"{ys['n']}{ys['avg']:+.0f}%", 9) + " "
            elif ys:
                row += _pad(f"{ys['n']}*", 9) + " "
            else:
                row += _pad('--', 9) + " "
        print(row)

    # 收益分布
    print(f'\n  收益分布 (监控退出)')
    hdr = f"  {_pad('范围', 10)} "
    for key, r in results.items():
        hdr += f"{_pad(r['strategy'].display_name, 14)} "
    print(hdr)
    print("  " + "-" * (_dw(hdr) - 2))
    for lbl, (lo, hi) in [('< -10%', (-999, -10)), ('-10~-5%', (-10, -5)),
                           ('-5~0%', (-5, 0)), ('0~5%', (0, 5)),
                           ('5~10%', (5, 10)), ('>10%', (10, 999))]:
        row = f"  {_pad(lbl, 10)} "
        for key, r in results.items():
            triggered = [t for t in pool if t.get('strategy_key') == key]
            c = sum(1 for t in triggered if lo <= t['ret'] < hi)
            if triggered:
                val = f"{c}({c/len(triggered)*100:.0f}%)"
                row += _pad(val, 14) + " "
            else:
                row += _pad('--', 14) + " "
        print(row)

    # 盈亏比
    print(f'\n  盈亏比分析 (监控退出)')
    hdr = f"  {_pad('策略', 14)} {_pad('盈利笔', 6)} {_pad('平均盈利', 9)} {_pad('最佳', 9)} " \
          f"{_pad('亏损笔', 6)} {_pad('平均亏损', 9)} {_pad('最差', 9)} {_pad('盈亏比', 6)}"
    print(hdr)
    print("  " + "-" * (_dw(hdr) - 2))
    for key, r in results.items():
        triggered = [t for t in pool if t.get('strategy_key') == key]
        wins = [t['ret'] for t in triggered if t['ret'] > 0]
        losses = [t['ret'] for t in triggered if t['ret'] <= 0]
        aw = sum(wins) / len(wins) if wins else 0
        al = sum(losses) / len(losses) if losses else 0
        wl = abs(aw / al) if al != 0 else 0
        p_name = r['strategy'].display_name
        p_w = str(len(wins))
        p_aw = f"{aw:+.1f}%"
        p_mw = f"{max(wins):+.1f}%" if wins else '--'
        p_l = str(len(losses))
        p_al = f"{al:+.1f}%" if losses else '--'
        p_ml = f"{min(losses):+.1f}%" if losses else '--'
        p_wl = f"{wl:.2f}"
        print(f"  {_pad(p_name, 14)} {_pad(p_w, 6)} {_pad(p_aw, 9)} {_pad(p_mw, 9)} {_pad(p_l, 6)} {_pad(p_al, 9)} {_pad(p_ml, 9)} {_pad(p_wl, 6)}")

    # 跨样本量对比
    print(f'\n  跨样本量对比 (每债券每策略独立条目)')
    hdr = f"  {_pad('策略', 14)}"
    for lim in [50, 100, 150, 200]:
        hdr += f" {_pad('L=' + str(lim), 14)}"
    hdr += f" {_pad('全量', 14)}"
    print(hdr)
    print("  " + "-" * (_dw(hdr) - 2))
    for key, r in sorted(results.items(), key=lambda x: x[1]['fixed']['sharpe'] if x[1]['fixed'] else 0, reverse=True):
        s = r['strategy']
        row = f"  {_pad(s.display_name, 14)}"
        for lim in [50, 100, 150, 200]:
            sub = pool[:lim]
            triggered_sub = [t for t in sub if t.get('strategy_key') == key]
            if len(triggered_sub) >= 2:
                ss = calc_stats(triggered_sub)
                val = f"N={ss['n']} sh={ss['sharpe']:+.2f} w={ss['win']:.0f}%"
                row += f" {_pad(val, 14)}"
            else:
                row += f" {_pad('--', 14)}"
        fs = r['fixed']
        val = f"N={fs['n']} sh={fs['sharpe']:+.2f} w={fs['win']:.0f}%"
        row += f" {_pad(val, 14)}"
        print(row)

    # 卖出类型分布
    print(f'\n  卖出类型分布')
    hdr = f"  {_pad('策略', 14)} {_pad('REG', 9)} {_pad('TP', 9)} {_pad('SL', 9)}"
    print(hdr)
    print("  " + "-" * (_dw(hdr) - 2))
    for key, r in results.items():
        st = r.get('sell_types', {'REG': r['count']})
        reg_s = f"{st.get('REG', 0)}({st.get('REG', 0)/r['count']*100:.0f}%)"
        tp_s = f"{st.get('TP', 0)}({st.get('TP', 0)/r['count']*100:.0f}%)"
        sl_s = f"{st.get('SL', 0)}({st.get('SL', 0)/r['count']*100:.0f}%)"
        print(f"  {_pad(r['strategy'].display_name, 14)} {_pad(reg_s, 9)} {_pad(tp_s, 9)} {_pad(sl_s, 9)}")

    print(f'\n{"=" * 120}')


# ========== 监控扫描 ==========

def get_pipeline_bonds(cache):
    """获取当前处于审批通道的转债（上市委通过但未注册）"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    all_bonds = []
    for phase in ['待发', '注册']:
        all_bonds.extend(cache.get_jisilu_bonds(phase=phase, limit=0))
    seen = set()
    unique = []
    for b in all_bonds:
        key = (b.get('stock_code', ''), b.get('bond_code', ''))
        if key not in seen:
            seen.add(key)
            unique.append(b)
    pipeline = []
    for b in unique:
        sc = b.get('stock_code')
        if not sc: continue
        pf = b.get('progress_full', '')
        if not pf: continue
        tg_date, reg_date = parse_progress_full(pf)
        if tg_date and tg_date <= today_str:
            if not reg_date or reg_date > today_str:
                pipeline.append(b)
    return pipeline


def mode_scan(cache, strategies):
    """扫描今日注册前信号 + 持仓卖出信号"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    print(f"\n{'=' * 110}")
    print(f'注册前信号监控 — {today_str}')
    print(f'{"=" * 110}')

    from datetime import date as date_cls
    parts = today_str.split('-')
    today_date = date_cls(int(parts[0]), int(parts[1]), int(parts[2]))

    pipeline = get_pipeline_bonds(cache)
    pool_data = []

    for b in pipeline:
        sc = b.get('stock_code')
        if not sc: continue

        pf = b.get('progress_full', '')
        tongguo_date = ''
        if pf:
            for line in pf.replace('<br>', '\n').split('\n'):
                if '上市委通过' in line:
                    m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                    if m: tongguo_date = m.group(1)
                    break

        klines = cache.get_kline_as_dict(sc, days=1500)
        if not klines: continue
        dates = sorted(klines.keys())
        if len(dates) < 25: continue

        closes = [klines[d]['close'] for d in dates]
        volumes = [klines[d].get('volume', 0) for d in dates]
        today_idx = find_idx(dates, today_str)
        factors = calc_factors_at(closes, volumes, today_idx)
        if not factors: continue
        current = klines[dates[today_idx]]

        # 首次信号日期
        first_signal_date = ''
        scan_started = False
        if tongguo_date:
            ti = find_idx(dates, tongguo_date)
            scan_started = (today_idx >= ti + SCAN_START)
            if scan_started:
                for idx in range(ti + SCAN_START, today_idx + 1):
                    sf = calc_factors_at(closes, volumes, idx)
                    if not sf: continue
                    for s in strategies:
                        if s.matches(sf):
                            first_signal_date = dates[idx]
                            break
                    if first_signal_date: break

        # 自然天
        days_natural = ''
        if tongguo_date:
            tp = tongguo_date.split('-')
            tg = date_cls(int(tp[0]), int(tp[1]), int(tp[2]))
            days_natural = f'{(today_date - tg).days}天'

        # 交易日（距上市委通过）
        trading_days = ''
        if tongguo_date:
            ti = find_idx(dates, tongguo_date)
            trading_days = f"D+{today_idx - ti}"

        # 检查今日策略触发
        triggered = {s.key: s.matches(factors) for s in strategies}

        pool_data.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_nm') or '?')[:12],
            'close': current['close'],
            'factors': factors,
            'tongguo_date': tongguo_date,
            'days_natural': days_natural,
            'trading_days': trading_days,
            'first_signal_date': first_signal_date,
            'triggered': triggered,
            'scan_started': scan_started,
        })

    # 买入信号 (仅在进入扫描窗口后)
    buy_signals = [d for d in pool_data if any(d['triggered'].values()) and d.get('scan_started', False)]
    if buy_signals:
        print(f"\n  买入信号 ({len(buy_signals)} 只，T+1 开盘买入):")
        hdr = f"  {_pad('名称', 14)} {_pad('代码', 8)} {_pad('收盘', 8)} {_pad('pre3', 7)} {_pad('pre5', 7)} {_pad('mom10', 8)} {_pad('vol5', 5)} 触发策略"
        print(hdr)
        print("  " + "-" * 100)
        for item in buy_signals:
            f = item['factors']
            tags = [s.display_name for s in strategies if item['triggered'].get(s.key)]
            c = f"{item['close']:.2f}"
            p3 = f"{f['pre3']:+.1f}%"
            p5 = f"{f['pre5']:+.1f}%"
            m10 = f"{f['mom10']:+.1f}%"
            v5 = f"{f['vol5']:.2f}"
            row = f"  {_pad(item['name'], 14)} {_pad(item['code'], 8)} {_pad(c, 8)} {_pad(p3, 7)} {_pad(p5, 7)} {_pad(m10, 8)} {_pad(v5, 5)} {' '.join(tags)}"
            print(row)

    # 即将买入 (因子已匹配但尚未进入D+20窗口)
    pending_signals = [d for d in pool_data if any(d['triggered'].values()) and not d.get('scan_started', False)]
    if pending_signals:
        print(f"\n  即将买入 ({len(pending_signals)} 只，等待进入D+{SCAN_START}窗口):")
        hdr = f"  {_pad('名称', 14)} {_pad('代码', 8)} {_pad('收盘', 8)} {_pad('上市委通过', 16)} {_pad('自然天', 10)} {_pad('pre3', 7)} {_pad('pre5', 7)} {_pad('mom10', 8)} {_pad('vol5', 5)} 触发策略"
        print(hdr)
        print("  " + "-" * 114)
        for item in pending_signals:
            f = item['factors']
            tags = [s.display_name for s in strategies if item['triggered'].get(s.key)]
            tg = item['tongguo_date'] or '--'
            c = f"{item['close']:.2f}"
            p3 = f"{f['pre3']:+.1f}%"
            p5 = f"{f['pre5']:+.1f}%"
            m10 = f"{f['mom10']:+.1f}%"
            v5 = f"{f['vol5']:.2f}"
            row = f"  {_pad(item['name'], 14)} {_pad(item['code'], 8)} {_pad(c, 8)} {_pad(tg, 16)} {_pad(item['days_natural'], 10)} {_pad(p3, 7)} {_pad(p5, 7)} {_pad(m10, 8)} {_pad(v5, 5)} {' '.join(tags)}"
            print(row)

    # 监控池
    print(f"\n  监控池 ({len(pool_data)} 只):")
    hdr = f"  {_pad('名称', 14)} {_pad('代码', 8)} {_pad('收盘', 8)} {_pad('上市委通过', 16)} {_pad('D+', 6)} {_pad('首次信号', 16)} {_pad('pre3', 7)} {_pad('pre5', 7)} {_pad('mom10', 8)} {_pad('vol5', 5)} 信号"
    print(hdr)
    print("  " + "-" * 122)
    for item in pool_data:
        f = item['factors']
        tags = [s.display_name for s in strategies if item['triggered'].get(s.key)]
        sig_tag = ' '.join(tags) if tags else ''
        if not item.get('scan_started', False):
            sig_tag = sig_tag + '(待)' if sig_tag else ''
        tg = item['tongguo_date'] or '--'
        fs = item['first_signal_date'] or '--'
        c = f"{item['close']:.2f}"
        p3 = f"{f['pre3']:+.1f}%"
        p5 = f"{f['pre5']:+.1f}%"
        m10 = f"{f['mom10']:+.1f}%"
        v5 = f"{f['vol5']:.2f}"
        row = f"  {_pad(item['name'], 14)} {_pad(item['code'], 8)} {_pad(c, 8)} {_pad(tg, 16)} {_pad(item['trading_days'], 6)} {_pad(fs, 16)} {_pad(p3, 7)} {_pad(p5, 7)} {_pad(m10, 8)} {_pad(v5, 5)} {sig_tag}"
        print(row)

    # 策略说明
    print(f"\n  因子说明:")
    print(f"    pre3  = 距今日3个交易日的跌幅 (T-3 至 T-1 收盘价涨幅)")
    print(f"    pre5  = 距今日5个交易日的跌幅 (T-5 至 T-1 收盘价涨幅)")
    print(f"    mom10 = 近10个交易日涨幅 (T-10 至 T-1 收盘价涨幅)")
    print(f"    vol5  = 今日成交量 / 近5日平均成交量 (<1 缩量, >1 放量)")
    print(f"  卖出说明: exit=REG 表示发现'同意注册'后次日卖出")
    print(f"  策略说明:")
    for s in strategies:
        print(f"    {s.display_name}: {s.label}  (exit={s.best_exit}, 胜={s.win_rate}, 年化={s.annual})")
    print(f"  卖出: TP +{TP}% / SL {SL}%（持仓期间每日盯市，触发次日卖出）")
    print(f"  买入窗口: 上市委通过 D+{SCAN_START} 起")


def mode_backtest(cache, strategies, limit=None):
    """回测模式"""
    print(f"\n{'=' * 110}")
    print(f"注册前信号回测")
    print(f'{"=" * 110}')

    pool = build_backtest_pool(cache, strategies, check_interval=2)
    if limit:
        bond_codes = set()
        for p in pool:
            if p['code'] not in bond_codes:
                bond_codes.add(p['code'])
                if len(bond_codes) >= limit:
                    break
        pool = [p for p in pool if p['code'] in bond_codes]

    print(f"\n  总样本: {len(pool)} 个信号 (涉及 {len(set(p['code'] for p in pool))} 只债券)")
    print(f"  策略: {', '.join(s.display_name for s in strategies)}")
    print(f"  买入: 信号日次日开盘（距上市委通过 D+{SCAN_START} 起检测）")
    print(f"  退出: 监控集思录发现'同意注册'后次日卖出(检查间隔2天)")
    print(f"  止盈止损: +{TP}% / -{SL}%（触发次日卖出）")
    print(f"  模式: 仅记录首个信号")

    results = run_backtest(pool, strategies)
    print_backtest_report(pool, results, limit, strategies)


# ========== 主入口 ==========

def main():
    cache = BacktestCache()
    args = sys.argv[1:]
    is_backtest = False
    limit = None
    strategy_key = None

    i = 0
    while i < len(args):
        if args[i] == '--scan':
            i += 1
        elif args[i] == '--backtest':
            is_backtest = True
            i += 1
        elif args[i] == '--limit' and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == '--strategy' and i + 1 < len(args):
            strategy_key = args[i + 1]
            i += 2
        else:
            i += 1

    if strategy_key:
        strategies = [s for s in PRE_REG_STRATEGIES if s.key == strategy_key]
        if not strategies:
            print(f"未知策略: {strategy_key}")
            print(f"可用: {', '.join(s.key for s in PRE_REG_STRATEGIES)}")
            return
    else:
        strategies = [s for s in PRE_REG_STRATEGIES if s.key not in DEPRECATED_STRATEGIES]

    if is_backtest:
        mode_backtest(cache, strategies, limit)
    else:
        mode_scan(cache, strategies)


if __name__ == '__main__':
    main()
