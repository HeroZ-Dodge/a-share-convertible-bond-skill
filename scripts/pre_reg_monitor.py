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
  --hold                    查看模拟持仓与持仓监控
  --backtest                历史回测（所有已注册转债）
  --backtest --limit 100    指定样本数
  --backtest --strategy mom_recover  指定策略
  --buy CODE DATE PRICE [REG_DATE]   记录实际买入
  --sell CODE DATE PRICE [REG_DATE]  记录实际卖出
"""
import sys, os, re, math, json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.backtest_cache import BacktestCache
from lib.monitor_db import MonitorDB


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


def calc_factors_at(closes, volumes, idx, dates=None, as_of_date=None):
    """计算 idx 日收盘后的策略因子。

    盘中若 idx 对应当天最新未收盘交易日，则自动回退到上一完整交易日。
    """
    factor_idx = idx
    if dates and as_of_date and idx < len(dates) and dates[idx] == as_of_date and idx > 0:
        factor_idx = idx - 1

    if factor_idx < 22:
        return None

    t1, t3, t5, t10, t20 = (
        closes[factor_idx - 1],
        closes[factor_idx - 3],
        closes[factor_idx - 5],
        closes[factor_idx - 10],
        closes[factor_idx - 20],
    )
    pre3 = ((t1 - t3) / t3 * 100) if t3 > 0 else 0
    pre5 = ((t1 - t5) / t5 * 100) if t5 > 0 else 0
    mom10 = ((t1 - t10) / t10 * 100) if t10 > 0 else 0
    mom20 = ((t1 - t20) / t20 * 100) if t20 > 0 else 0

    vol_t = volumes[factor_idx]
    avg5 = sum(volumes[factor_idx - 5:factor_idx]) / 5
    vol5 = vol_t / avg5 if avg5 > 0 else 1.0
    avg10 = sum(volumes[factor_idx - 10:factor_idx]) / 10 if factor_idx >= 10 else avg5
    vol10 = vol_t / avg10 if avg10 > 0 else 1.0

    cdown = sum(1 for i in range(factor_idx, 0, -1) if closes[i] < closes[i - 1])
    cup = sum(1 for i in range(factor_idx, 0, -1) if closes[i] >= closes[i - 1])

    ma5 = sum(closes[factor_idx - 5:factor_idx]) / 5
    ma5p = (closes[factor_idx] / ma5 - 1) * 100
    ma10 = sum(closes[factor_idx - 10:factor_idx]) / 10
    ma10p = (closes[factor_idx] / ma10 - 1) * 100
    ma20 = sum(closes[factor_idx - 20:factor_idx]) / 20
    ma20p = (closes[factor_idx] / ma20 - 1) * 100

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


def parse_exit_thresholds(exit_str):
    """解析退出配置，返回 (tp, sl) 百分比阈值"""
    if not exit_str:
        return 5, 5
    exit_str = exit_str.upper().replace(' ', '')
    tp_m = re.search(r'TP(\d+)', exit_str)
    sl_m = re.search(r'SL(\d+)', exit_str)
    tp = int(tp_m.group(1)) if tp_m else 5
    sl = int(sl_m.group(1)) if sl_m else 5
    return tp, sl


def _first_triggered_strategy(triggered):
    """返回首次命中的策略 key"""
    for s in PRE_REG_STRATEGIES:
        if triggered.get(s.key):
            return s.key
    return None


def _hold_display_parts(factors, triggered):
    """生成持仓展示所需的统一字段"""
    bp = f"{factors['buy_price']:.2f}" if factors.get('buy_price') else '--'
    cp = f"{factors['current_close']:.2f}" if factors.get('current_close') else '--'
    pnl = f"{factors['pnl_pct']:+.1f}%" if factors.get('pnl_pct') is not None else '--'

    tp_val, sl_val = 5, 5
    exit_label = 'REG'
    first_key = _first_triggered_strategy(triggered)
    if first_key:
        s = next((x for x in PRE_REG_STRATEGIES if x.key == first_key), None)
        if s:
            tp_val, sl_val = parse_exit_thresholds(s.best_exit)
            exit_label = s.best_exit or 'REG'

    pnl_val = factors.get('pnl_pct')
    tp_mark = '✅' if pnl_val is not None and pnl_val >= tp_val else ' '
    sl_mark = '⚠️' if pnl_val is not None and pnl_val <= -sl_val else ' '
    exit_str = f"{tp_mark}{sl_mark} ({exit_label})"

    tags = ' '.join(s.display_name for s in PRE_REG_STRATEGIES if triggered.get(s.key))

    return {
        'buy_price': bp,
        'current_price': cp,
        'pnl': pnl,
        'exit_str': exit_str,
        'tags': tags,
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


def _format_t_plus(days, width=6):
    """格式化 T+N，避免 T+ 后面出现多余空格"""
    try:
        return _pad(f"T+{int(days)}", width)
    except (TypeError, ValueError):
        return _pad('--', width)


def _labels_text(labels, default='—'):
    """把策略标签压成展示文本"""
    if not labels:
        return default
    if isinstance(labels, str):
        text = labels.strip()
        return text or default
    items = [str(x).strip() for x in labels if str(x).strip()]
    return '/'.join(items) if items else default


def _strategy_conclusion_text(strategies):
    """根据当前回测结论生成策略排序摘要"""
    names = [s.display_name for s in strategies]
    if {'动量恢复', '高胜率', 'MA5过滤'}.issubset(set(names)):
        return '结论(当前历史回测): MA5过滤 > 高胜率 > 动量恢复；优先保留 MA5过滤，高胜率次选，动量恢复观察。'
    return '结论(当前历史回测): 请以回测排序表为准，优先保留夏普更高、平均亏损更小且年份更稳定的策略。'


# ========== 回测引擎 ==========

def scan_daily_factors(closes, volumes, dates, ti, ri):
    """预扫描所有交易日的因子（一次计算，多策略复用）"""
    factor_map = {}
    for idx in range(ti + SCAN_START, ri):
        f = calc_factors_at(closes, volumes, idx)
        if f:
            factor_map[idx] = f
    return factor_map


def find_first_signal(closes, volumes, dates, ti, ri, strategies, as_of_date=None):
    """找出首次触发策略的交易日"""
    first_idx = None
    first_factors = None
    first_triggered = None
    for idx in range(ti + SCAN_START, ri):
        f = calc_factors_at(closes, volumes, idx, dates=dates, as_of_date=as_of_date)
        if not f:
            continue
        triggered = {s.key: s.matches(f) for s in strategies}
        if any(triggered.values()):
            first_idx = idx
            first_factors = f
            first_triggered = triggered
            break
    return first_idx, first_factors, first_triggered


def simulate_exit(dates, closes, buy_idx, reg_idx):
    """按回测规则模拟退出点"""
    if buy_idx is None or reg_idx is None or reg_idx <= buy_idx:
        return None, None, None

    tp_hit = None
    sl_hit = None
    for idx in range(buy_idx + 1, min(reg_idx + 2, len(closes))):
        daily_ret = (closes[idx] / closes[buy_idx] - 1) * 100 if closes[buy_idx] > 0 else 0
        if daily_ret >= TP and tp_hit is None:
            tp_hit = idx
        if daily_ret <= SL and sl_hit is None:
            sl_hit = idx

    sell_idx = reg_idx + 1 if reg_idx + 1 < len(dates) else None
    sell_reason = 'REG'
    if sl_hit is not None and sl_hit > buy_idx and (sell_idx is None or sl_hit < sell_idx):
        sell_idx = min(sl_hit + 1, len(dates) - 1)
        sell_reason = 'SL'
    elif tp_hit is not None and tp_hit > buy_idx and (sell_idx is None or tp_hit < sell_idx):
        sell_idx = min(tp_hit + 1, len(dates) - 1)
        sell_reason = 'TP'

    if sell_idx is None:
        return None, None, None
    return sell_idx, sell_reason, closes[sell_idx]


def _hold_row_cells(row):
    """统一持仓行输出"""
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


def print_hold_table(title, rows):
    """打印持仓表"""
    print(f"\n  📊 {title} ({len(rows)}只):")
    hdr = f"  {_pad('名称', 14)} {_pad('代码', 8)} {_pad('T+', 6)} {_pad('买价', 8)} {_pad('现价', 8)} {_pad('盈亏', 8)} {_pad('止盈止损', 24)} {'触发策略'}"
    print(hdr)
    print("  " + "-" * (_dw(hdr) - 2))
    if not rows:
        print("  无持仓")
        return
    for row in rows:
        print("  " + " ".join(_hold_row_cells(row)))


def resolve_stock_name(stock_code, reg_date=None):
    """根据股票代码解析名称，优先按注册日精确匹配"""
    db = MonitorDB()
    if reg_date:
        with db._get_conn() as conn:
            row = conn.execute(
                "SELECT stock_name FROM registration_events WHERE stock_code = ? AND registration_date = ?",
                (stock_code, reg_date)
            ).fetchone()
            if row and row['stock_name']:
                return (row['stock_name'] or '')[:12]

    event = db.get_registration_by_stock(stock_code)
    if event and event.get('stock_name'):
        return (event['stock_name'] or '')[:12]
    return ''


def resolve_actual_signal_meta(cache, strategies, stock_code, reg_date=None):
    """为实际买入解析触发策略信息"""
    db = MonitorDB()

    pool_data = build_monitor_pool(cache, strategies)
    item = next((x for x in pool_data if x.get('code') == stock_code), None)
    if item:
        triggered = item.get('first_signal_triggered', {}) or {}
        labels = item.get('first_signal_labels', []) or []
        if any(triggered.values()) or labels:
            return (
                list(triggered.keys()),
                labels,
                item.get('tongguo_date') or reg_date or '',
                item.get('first_signal_date') or '',
            )

    theory_rows = db.get_theory_signals(stock_code)
    if theory_rows:
        theory = theory_rows[0]
        return (
            theory.get('triggered_strategies', []) or [],
            theory.get('strategy_labels', []) or [],
            theory.get('registration_date') or reg_date or '',
            theory.get('first_signal_date') or '',
        )

    return [], [], reg_date or '', ''


def load_position_notes_data(pos):
    """安全解析 positions.notes"""
    try:
        return json.loads(pos.get('notes') or '{}')
    except (TypeError, ValueError):
        return {}


def _actual_sell_alert(current_price, buy_price, sell_mode='REG', registration_date=None):
    """根据实际持仓的卖出模式生成卖出提醒"""
    mode = (sell_mode or 'REG').upper()
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
    if pnl_pct >= TP:
        return f'卖出信号(TP+{TP}%)'
    if pnl_pct <= SL:
        return f'卖出信号(SL{SL}%)'
    return '持仓中'


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

    def _avg_loss(trades):
        losses = [t['ret'] for t in trades if t['ret'] < 0]
        return sum(losses) / len(losses) if losses else 0.0

    ranking = []
    for key, r in results.items():
        s = r['strategy']
        fixed = r['fixed']
        tp_sl = r['tp_sl']
        triggered = [p for p in pool if p.get('strategy_key') == key]
        tp_sl_trades = [{'ret': t['tp_sl_ret'], 'hold_days': t['tp_sl_hold']} for t in triggered]
        ranking.append({
            'key': key,
            'name': s.display_name,
            'fixed': fixed,
            'tp_sl': tp_sl,
            'fixed_avg_loss': _avg_loss(triggered),
            'tp_sl_avg_loss': _avg_loss(tp_sl_trades),
            'count': r['count'],
            'by_year': r['by_year'],
        })

    def _stable_years(item):
        vals = [v['sharpe'] for v in item['by_year'].values() if v and v.get('n', 0) >= 2]
        if len(vals) < 2:
            return 0.0
        spread = max(vals) - min(vals)
        # 越小越稳定，转成分数方便排序
        return 1 / (1 + spread)

    def _print_ranking(title, metric_key, avg_loss_key, tie_key):
        rows = sorted(
            ranking,
            key=lambda x: (
                x[metric_key]['sharpe'] if x[metric_key] else -999,
                x[metric_key]['avg'] if x[metric_key] else -999,
                _stable_years(x),
                x[tie_key],
            ),
            reverse=True,
        )
        print(f'\n  策略排序 ({title})')
        hdr = (
            f"  {_pad('排序', 4)} {_pad('策略', 14)} {_pad('样本', 5)} "
            f"{_pad('平均%', 7)} {_pad('胜率', 7)} {_pad('平均亏损', 9)} {_pad('夏普', 7)} "
            f"{_pad('持有', 7)} {_pad('稳定性', 8)}"
        )
        print(hdr)
        print("  " + "-" * (_dw(hdr) - 2))
        for idx, item in enumerate(rows, 1):
            stat = item[metric_key]
            if not stat:
                continue
            stable = _stable_years(item)
            avg_txt = f"{stat['avg']:+.1f}%"
            win_txt = f"{stat['win']:.1f}%"
            loss_txt = f"{item[avg_loss_key]:+.1f}%"
            sh_txt = f"{stat['sharpe']:+.2f}"
            hold_txt = f"{stat['avg_hold']:.1f}d"
            stable_txt = f"{stable:.2f}"
            print(
                f"  {_pad(str(idx), 4)} {_pad(item['name'], 14)} {_pad(str(stat['n']), 5)} "
                f"{_pad(avg_txt, 7)} {_pad(win_txt, 7)} {_pad(loss_txt, 9)} {_pad(sh_txt, 7)} "
                f"{_pad(hold_txt, 7)} {_pad(stable_txt, 8)}"
            )

    _print_ranking('监控退出', 'fixed', 'fixed_avg_loss', 'count')
    _print_ranking(f'TP{TP}%/SL{SL}%', 'tp_sl', 'tp_sl_avg_loss', 'count')

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


def build_monitor_pool(cache, strategies):
    """构建监控池，并附带首次信号与模拟持仓状态"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    from datetime import date as date_cls
    parts = today_str.split('-')
    today_date = date_cls(int(parts[0]), int(parts[1]), int(parts[2]))

    pipeline = get_pipeline_bonds(cache)
    pool_data = []

    for b in pipeline:
        sc = b.get('stock_code')
        if not sc:
            continue

        pf = b.get('progress_full', '')
        tongguo_date = ''
        if pf:
            for line in pf.replace('<br>', '\n').split('\n'):
                if '上市委通过' in line:
                    m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                    if m:
                        tongguo_date = m.group(1)
                    break

        klines = cache.get_kline_as_dict(sc, days=1500)
        if not klines:
            continue
        dates = sorted(klines.keys())
        if len(dates) < 25:
            continue

        closes = [klines[d]['close'] for d in dates]
        volumes = [klines[d].get('volume', 0) for d in dates]
        opens = [klines[d].get('open', klines[d]['close']) for d in dates]
        today_idx = find_idx(dates, today_str)
        if today_idx is None:
            continue

        current_idx = today_idx
        if dates[today_idx] == today_str and today_idx > 0:
            current_idx = today_idx - 1

        factors = calc_factors_at(closes, volumes, current_idx, dates=dates, as_of_date=today_str)
        if not factors:
            continue
        current = klines[dates[current_idx]]

        # 首次信号
        first_signal_idx, first_signal_factors, first_signal_triggered = None, None, None
        scan_started = False
        buy_idx = None
        buy_date = ''
        buy_price = None
        if tongguo_date:
            ti = find_idx(dates, tongguo_date)
            scan_started = (today_idx >= ti + SCAN_START)
            if ti >= 0:
                first_signal_idx, first_signal_factors, first_signal_triggered = find_first_signal(
                    closes, volumes, dates, ti, today_idx + 1, strategies, as_of_date=today_str
                )
                if first_signal_idx is not None:
                    buy_idx = first_signal_idx + 1
                    if buy_idx < len(dates):
                        buy_date = dates[buy_idx]
                        buy_price = opens[buy_idx] if opens[buy_idx] > 0 else closes[buy_idx]

        first_signal_date = dates[first_signal_idx] if first_signal_idx is not None else ''
        first_signal_labels = [s.display_name for s in strategies if first_signal_triggered and first_signal_triggered.get(s.key)] if first_signal_triggered else []

        # 模拟退出
        sim_sell_idx = sim_sell_reason = None
        sim_sell_price = None
        if buy_idx is not None and buy_idx < len(dates) and tongguo_date:
            ri = find_idx(dates, tongguo_date)
            sim_sell_idx, sim_sell_reason, sim_sell_price = simulate_exit(dates, closes, buy_idx, ri)

        current_pnl = None
        if buy_price and buy_price > 0 and current['close'] > 0:
            current_pnl = ((current['close'] - buy_price) / buy_price) * 100

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
            trading_days = f"T+{current_idx - ti}"

        # 今日策略触发
        triggered = {s.key: s.matches(factors) for s in strategies}
        current_labels = [s.display_name for s in strategies if triggered.get(s.key)]

        pool_data.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_nm') or '?')[:12],
            'close': current['close'],
            'dates': dates,
            'factors': factors,
            'tongguo_date': tongguo_date,
            'days_natural': days_natural,
            'trading_days': trading_days,
            'first_signal_date': first_signal_date,
            'first_signal_idx': first_signal_idx,
            'first_signal_factors': first_signal_factors or {},
            'first_signal_triggered': first_signal_triggered or {},
            'first_signal_labels': first_signal_labels,
            'current_labels': current_labels,
            'buy_idx': buy_idx,
            'buy_date': buy_date,
            'buy_price': buy_price,
            'sell_date': dates[sim_sell_idx] if sim_sell_idx is not None and sim_sell_idx < len(dates) else '',
            'sim_sell_idx': sim_sell_idx,
            'sim_sell_reason': sim_sell_reason,
            'sim_sell_price': sim_sell_price,
            'current_pnl': current_pnl,
            'triggered': triggered,
            'scan_started': scan_started,
        })

    return pool_data


def sync_simulated_positions(db, pool_data):
    """同步模拟持仓到数据库，首次信号生效，后续不覆盖"""
    existing = {p['stock_code']: p for p in db.get_backfill_positions()}
    created = 0
    closed = 0

    for item in pool_data:
        if not item.get('buy_date') or not item.get('buy_price'):
            continue

        sc = item['code']
        pos = existing.get(sc)

        payload = {
            'stock_name': item.get('name', ''),
            'bond_code': '',
            'bond_name': item.get('name', ''),
            'monitor_script': 'pre_reg_monitor',
            'first_signal_date': item.get('first_signal_date', ''),
            'theory_buy_date': item['buy_date'],
            'theory_buy_price': item['buy_price'],
            'triggered_strategies': list(item.get('first_signal_triggered', {}).keys()),
            'strategy_labels': item.get('first_signal_labels', []),
            'theory_exit_type': item.get('sim_sell_reason') or 'REG',
            'theory_factors': item.get('first_signal_factors', {}) or {},
        }

        if not pos:
            create_result = db.upsert_simulated_position(sc, item.get('tongguo_date', ''), payload)
            created += 1
            pos = {'position_id': create_result.get('position_id')}
        else:
            pos = dict(pos)

        if not pos or pos.get('status') == 'closed':
            continue

        if item.get('sim_sell_idx') is not None and item.get('sim_sell_price') is not None:
            today_str = datetime.now().strftime('%Y-%m-%d')
            sell_date = item.get('sell_date', '')
            if sell_date and sell_date <= today_str:
                db.execute_sell(
                    pos['position_id'],
                    sell_date,
                    item['sim_sell_price'],
                    item.get('sim_sell_reason') or 'REG'
                )
                closed += 1

    return {'created': created, 'closed': closed}


def build_simulated_hold_rows(pool_data, db, active_only=True):
    """从数据库 + 监控池构建模拟持仓行"""
    pool_map = {item['code']: item for item in pool_data}
    rows = []
    for pos in db.get_backfill_positions():
        if pos.get('status') not in ('active', 'closed'):
            continue
        if active_only and pos.get('status') != 'active':
            continue

        item = pool_map.get(pos.get('stock_code'))
        if not item:
            continue
        notes_data = load_position_notes_data(pos)
        first_labels = notes_data.get('strategy_labels', []) or item.get('first_signal_labels', []) or []
        current_labels = item.get('current_labels', []) or []
        reg_date = pos.get('registration_date') or item.get('tongguo_date') or ''
        days = item.get('trading_days')
        if not days and reg_date:
            try:
                days = f"T+{(datetime.now() - datetime.strptime(reg_date, '%Y-%m-%d')).days}"
            except ValueError:
                days = '--'

        if pos.get('status') == 'closed':
            buy_price = f"{pos.get('actual_buy_price'):.2f}" if pos.get('actual_buy_price') else '--'
            current_price = f"{pos.get('actual_sell_price'):.2f}" if pos.get('actual_sell_price') else '--'
            pnl = f"{pos.get('return_pct', 0):+.1f}%" if pos.get('return_pct') is not None else '--'
            exit_str = f"已平仓({pos.get('sell_reason') or 'REG'})"
            tags = ' '.join(labels) if labels else '—'
        else:
            buy_price = f"{item['buy_price']:.2f}" if item.get('buy_price') else f"{pos.get('actual_buy_price'):.2f}" if pos.get('actual_buy_price') else '--'
            current_price = f"{item['close']:.2f}" if item.get('close') else '--'
            pnl_val = item.get('current_pnl')
            pnl = f"{pnl_val:+.1f}%" if pnl_val is not None else '--'
            exit_str = '模拟持仓'
            tags = f"首:{_labels_text(first_labels)} 今:{_labels_text(current_labels)}"

        rows.append({
            'name': item['name'],
            'code': item['code'],
            'days': days or '--',
            'buy_price': buy_price,
            'current_price': current_price,
            'pnl': pnl,
            'exit_str': exit_str,
            'tags': tags,
            'status': pos.get('status') or '--',
        })

    def _day_key(v):
        m = re.search(r'(\d+)', str(v))
        return int(m.group(1)) if m else 9999

    rows.sort(key=lambda x: _day_key(x['days']))
    return rows


def build_actual_hold_rows(pool_data, db, active_only=True):
    """从数据库 + 监控池构建实际持仓行"""
    pool_map = {item['code']: item for item in pool_data}
    backfill_map = {p['stock_code']: p for p in db.get_backfill_positions()}
    rows = []
    with db._get_conn() as conn:
        query = """
            SELECT * FROM positions
            WHERE status = 'active'
              AND source IN ('real', 'manual')
        """
        if active_only:
            query += " ORDER BY actual_buy_date DESC, id DESC"
        else:
            query += " ORDER BY actual_buy_date DESC, id DESC"
        positions = [dict(row) for row in conn.execute(query).fetchall()]

    for pos in positions:
        if pos.get('source') == 'backfill':
            continue

        item = pool_map.get(pos.get('stock_code'))
        buy_price = pos.get('actual_buy_price')
        current_price = item.get('close') if item else None
        notes_data = load_position_notes_data(pos)
        fallback = load_position_notes_data(backfill_map.get(pos.get('stock_code'), {})) if backfill_map.get(pos.get('stock_code')) else {}
        sell_mode = notes_data.get('sell_mode') or fallback.get('sell_mode', 'REG')
        signal_labels = notes_data.get('strategy_labels', []) or fallback.get('strategy_labels', []) or []
        current_labels = item.get('current_labels', []) if item else []
        registration_date = pos.get('registration_date') or backfill_map.get(pos.get('stock_code'), {}).get('registration_date') or ''
        days = item.get('trading_days') if item and item.get('trading_days') else '--'
        if days == '--' and registration_date:
            try:
                days = f"T+{(datetime.now() - datetime.strptime(registration_date, '%Y-%m-%d')).days}"
            except ValueError:
                days = '--'

        if buy_price and current_price:
            pnl = f"{((current_price - buy_price) / buy_price) * 100:+.1f}%"
            exit_str = _actual_sell_alert(current_price, buy_price, sell_mode, registration_date)
        else:
            pnl = '--'
            exit_str = '持仓中' if (sell_mode or '').upper() != 'REG' else '卖出信号(同意注册后卖出)'

        rows.append({
            'name': (pos.get('stock_name') or pos.get('stock_code') or '')[:12],
            'code': pos.get('stock_code') or '--',
            'days': days or '--',
            'buy_price': f"{buy_price:.2f}" if buy_price else '--',
            'current_price': f"{current_price:.2f}" if current_price else '--',
            'pnl': pnl,
            'exit_str': '已平仓' if pos.get('status') != 'active' else exit_str,
            'tags': f"首:{_labels_text(signal_labels)} 今:{_labels_text(current_labels)}",
        })

    def _day_key(v):
        m = re.search(r'(\d+)', str(v))
        return int(m.group(1)) if m else 9999

    rows.sort(key=lambda x: _day_key(x['days']))
    return rows


def mode_scan(cache, strategies):
    """扫描今日注册前信号 + 同步模拟持仓"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    print(f"\n{'=' * 110}")
    print(f'注册前信号监控 — {today_str}')
    print(f'{"=" * 110}')

    pool_data = build_monitor_pool(cache, strategies)
    db = MonitorDB()
    sync_stats = sync_simulated_positions(db, pool_data)
    if sync_stats['created'] or sync_stats['closed']:
        print(f"  同步模拟持仓: 新建{sync_stats['created']} 条, 平仓{sync_stats['closed']} 条")

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
    hdr = f"  {_pad('名称', 14)} {_pad('代码', 8)} {_pad('收盘', 8)} {_pad('上市委通过', 16)} {_pad('T+', 6)} {_pad('首次信号', 16)} {_pad('首次策略', 18)} {_pad('当天策略', 18)} {_pad('pre3', 7)} {_pad('pre5', 7)} {_pad('mom10', 8)} {_pad('vol5', 5)}"
    print(hdr)
    print("  " + "-" * (_dw(hdr) - 2))
    for item in pool_data:
        f = item['factors']
        first_tag = _labels_text(item.get('first_signal_labels', []))
        current_tag = _labels_text(item.get('current_labels', []))
        tg = item['tongguo_date'] or '--'
        fs = item['first_signal_date'] or '--'
        c = f"{item['close']:.2f}"
        p3 = f"{f['pre3']:+.1f}%"
        p5 = f"{f['pre5']:+.1f}%"
        m10 = f"{f['mom10']:+.1f}%"
        v5 = f"{f['vol5']:.2f}"
        row = f"  {_pad(item['name'], 14)} {_pad(item['code'], 8)} {_pad(c, 8)} {_pad(tg, 16)} {_pad(item['trading_days'], 6)} {_pad(fs, 16)} {_pad(first_tag, 18)} {_pad(current_tag, 18)} {_pad(p3, 7)} {_pad(p5, 7)} {_pad(m10, 8)} {_pad(v5, 5)}"
        print(row)

    # 模拟持仓
    actual_rows = build_actual_hold_rows(pool_data, db, active_only=True)
    print_hold_table("实际持仓", actual_rows)

    sim_rows = build_simulated_hold_rows(pool_data, db, active_only=True)
    print_hold_table("模拟持仓", sim_rows)

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
    print(f"    {_strategy_conclusion_text(strategies)}")
    print(f"  卖出: TP +{TP}% / SL {SL}%（持仓期间每日盯市，触发次日卖出）")
    print(f"  买入窗口: 上市委通过 D+{SCAN_START} 起")


def mode_hold(cache, strategies):
    """持仓监控"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    print(f"\n{'=' * 110}")
    print(f'注册前持仓监控 — {today_str}')
    print(f'{"=" * 110}')

    pool_data = build_monitor_pool(cache, strategies)
    db = MonitorDB()
    sync_stats = sync_simulated_positions(db, pool_data)
    if sync_stats['created'] or sync_stats['closed']:
        print(f"  同步模拟持仓: 新建{sync_stats['created']} 条, 平仓{sync_stats['closed']} 条")

    actual_rows = build_actual_hold_rows(pool_data, db, active_only=True)
    print_hold_table("实际持仓", actual_rows)

    hold_rows = build_simulated_hold_rows(pool_data, db, active_only=False)
    print_hold_table("持仓监控", hold_rows)


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
    mode = 'scan'
    is_backtest = False
    limit = None
    strategy_key = None
    buy_cmd = None
    sell_cmd = None

    i = 0
    while i < len(args):
        if args[i] == '--scan':
            mode = 'scan'
            i += 1
        elif args[i] == '--hold':
            mode = 'hold'
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
        elif args[i] == '--buy' and i + 3 < len(args):
            code = args[i + 1]
            date = args[i + 2]
            price = float(args[i + 3])
            reg_date = args[i + 4] if i + 4 < len(args) and not args[i + 4].startswith('--') else None
            buy_cmd = (code, date, price, reg_date)
            i += 4 + (1 if reg_date else 0)
        elif args[i] == '--sell' and i + 3 < len(args):
            code = args[i + 1]
            date = args[i + 2]
            price = float(args[i + 3])
            reg_date = args[i + 4] if i + 4 < len(args) and not args[i + 4].startswith('--') else None
            sell_cmd = (code, date, price, reg_date)
            i += 4 + (1 if reg_date else 0)
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
    elif buy_cmd:
        code, date, price, reg_date = buy_cmd
        name = resolve_stock_name(code, reg_date)
        triggered_keys, triggered_labels, resolved_reg_date, first_signal_date = resolve_actual_signal_meta(
            cache, strategies, code, reg_date
        )
        db = MonitorDB()
        db.record_actual_buy(
            stock_code=code,
            buy_date=date,
            buy_price=price,
            registration_date=resolved_reg_date or reg_date,
            stock_name=name,
            first_signal_date=first_signal_date,
            triggered_strategies=triggered_keys,
            strategy_labels=triggered_labels,
            sell_mode='REG',
        )
        print(
            f"已记录买入: {name or code}({code}) 买价={price:.2f} 日期={date}"
            + (f" 注册日={resolved_reg_date or reg_date}" if (resolved_reg_date or reg_date) else "")
            + (f" 首信号={first_signal_date}" if first_signal_date else "")
            + (f" 策略={'/'.join(triggered_labels)}" if triggered_labels else "")
            + " 卖出=同意注册后卖出"
        )
    elif sell_cmd:
        code, date, price, reg_date = sell_cmd
        db = MonitorDB()
        result = db.record_actual_sell(
            stock_code=code,
            sell_date=date,
            sell_price=price,
            registration_date=reg_date,
        )
        ret = result.get('return_pct', 0)
        print(f"已记录卖出: {code} 卖价={price:.2f} 日期={date} 收益={ret:+.2f}%")
    else:
        cache.ensure_jisilu_data_for_today()
        if mode == 'hold':
            mode_hold(cache, strategies)
        else:
            mode_scan(cache, strategies)


if __name__ == '__main__':
    main()
