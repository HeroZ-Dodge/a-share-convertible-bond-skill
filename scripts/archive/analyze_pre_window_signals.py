# -*- coding: utf-8 -*-
"""
验证：信号命中但未进入D+20窗口时，提前买入是否可行？

场景：今天命中策略因子，但距上市委通过不到20个交易日。
按规则不应买入（需等D+20），但如果忽略这条规则，收益如何？
"""
import sys, os, re
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.backtest_cache import BacktestCache

SCAN_START = 20

def find_idx(dates, target):
    result = 0
    for i, d in enumerate(dates):
        if d <= target:
            result = i
        else:
            break
    return result

def calc_factors_at(closes, volumes, idx):
    if idx < 22:
        return None
    t1, t3, t5, t10, t20 = closes[idx-1], closes[idx-3], closes[idx-5], closes[idx-10], closes[idx-20]
    pre3 = ((t1 - t3) / t3 * 100) if t3 > 0 else 0
    pre5 = ((t1 - t5) / t5 * 100) if t5 > 0 else 0
    mom10 = ((t1 - t10) / t10 * 100) if t10 > 0 else 0
    mom20 = ((t1 - t20) / t20 * 100) if t20 > 0 else 0
    vol_t = volumes[idx]
    avg5 = sum(volumes[idx-5:idx]) / 5
    vol5 = vol_t / avg5 if avg5 > 0 else 1.0
    ma5 = sum(closes[idx-5:idx]) / 5
    ma5p = (closes[idx] / ma5 - 1) * 100
    return {
        'pre3': pre3, 'pre5': pre5, 'mom10': mom10, 'mom20': mom20,
        'vol5': vol5, 'ma5p': ma5p,
    }

def parse_progress_full(text):
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

cache = BacktestCache()
today_str = datetime.now().strftime('%Y-%m-%d')
bonds = cache.get_jisilu_bonds(phase='注册', limit=0)

strategies = [
    ('mom_recover', '动量恢复', lambda f: f['pre3'] <= -1.5 and f['mom10'] >= 0.5 and f['vol5'] <= 0.9),
    ('high_win', '高胜率', lambda f: f['pre5'] <= -1.5 and f['mom10'] >= 2 and f['vol5'] <= 0.9),
    ('ma5p_filter', 'MA5过滤', lambda f: f['pre5'] <= -1 and f['mom10'] >= 4 and f['vol5'] <= 0.85 and f['ma5p'] <= -0.5),
]

# 统计
print("=" * 110)
print(f"验证: 信号命中但未进入D+{SCAN_START}窗口时买入的收益")
print("=" * 110)

all_results = []

for b in bonds:
    sc = b.get('stock_code')
    if not sc: continue
    pf = b.get('progress_full', '')
    if not pf: continue
    tg_date, reg_date = parse_progress_full(pf)
    if not reg_date or reg_date > today_str: continue
    if tg_date and tg_date >= reg_date:
        tg_date = ''

    klines = cache.get_kline_as_dict(sc, days=1500, skip_freshness_check=True)
    if not klines: continue
    dates = sorted(klines.keys())
    if len(dates) < 25: continue
    closes = [klines[d]['close'] for d in dates]
    volumes = [klines[d].get('volume', 0) for d in dates]
    opens = [klines[d].get('open', klines[d]['close']) for d in dates]

    ti = find_idx(dates, tg_date) if tg_date else 0
    ri = find_idx(dates, reg_date)
    if ti < 22: ti = 22
    if ri is None or ri <= ti: continue

    # 扫描每个交易日
    for idx in range(ti + 1, ri):  # 从上市委通过次日开始
        f = calc_factors_at(closes, volumes, idx)
        if not f: continue
        d = dates[idx]

        # 计算距离上市委通过多少交易日
        trading_days_from_tg = idx - ti

        for key, name, cond in strategies:
            if not cond(f): continue

            # 找到次日买入
            buy_idx = None
            for i in range(idx + 1, len(dates)):
                if dates[i] > d:
                    buy_idx = i
                    break
            if buy_idx is None or buy_idx >= len(dates): continue
            bp = opens[buy_idx] if opens[buy_idx] > 0 else closes[buy_idx]

            # 卖出：监控检测
            sell_idx = None
            for check in range(buy_idx + 1, len(dates), 2):
                if dates[check] > reg_date:
                    sell_idx = min(check + 1, len(dates) - 1)
                    break
            if sell_idx is None:
                rs = find_idx(dates, reg_date) + 1
                if rs < len(dates): sell_idx = rs
            if sell_idx is None or sell_idx >= len(dates): continue
            if dates[sell_idx] > today_str: continue
            if sell_idx <= buy_idx: continue
            sp = closes[sell_idx]
            ret = ((sp - bp) / bp * 100) if bp > 0 else 0
            held = sell_idx - buy_idx

            in_window = trading_days_from_tg >= SCAN_START

            all_results.append({
                'date': d,
                'code': sc,
                'name': (b.get('bond_name') or '?')[:10],
                'tg_date': tg_date,
                'reg_date': reg_date,
                'tdays': trading_days_from_tg,
                'in_window': in_window,
                'strategy': name,
                'ret': ret,
                'held': held,
                'bp': bp,
                'sp': sp,
                'factors': f,
            })

# 按窗口状态分组
in_win = [r for r in all_results if r['in_window']]
out_win = [r for r in all_results if not r['in_window']]

print(f"\n总信号命中数: {len(all_results)}")
print(f"  D+{SCAN_START}内 (窗口前): {len(out_win)}")
print(f"  D+{SCAN_START}起 (窗口内): {len(in_win)}")

def calc_group_stats(trades, label):
    if not trades:
        print(f"\n  {label}: 无数据")
        return
    rets = [t['ret'] for t in trades]
    n = len(rets)
    avg = sum(rets) / n
    std = (sum((x - avg)**2 for x in rets) / n) ** 0.5
    sh = avg / std if std > 0 else 0
    win = sum(1 for x in rets if x > 0) / n * 100
    avg_hold = sum(t['held'] for t in trades) / n
    ann = avg / avg_hold * 245 if avg_hold > 0 else 0
    wins = [t['ret'] for t in trades if t['ret'] > 0]
    losses = [t['ret'] for t in trades if t['ret'] <= 0]
    aw = sum(wins) / len(wins) if wins else 0
    al = sum(losses) / len(losses) if losses else 0

    # 按策略分组
    strat_stats = {}
    for name in ['动量恢复', '高胜率', 'MA5过滤']:
        sub = [t for t in trades if t['strategy'] == name]
        if len(sub) >= 2:
            srets = [t['ret'] for t in sub]
            savg = sum(srets) / len(srets)
            swin = sum(1 for x in srets if x > 0) / len(srets) * 100
            strat_stats[name] = {'n': len(sub), 'avg': savg, 'win': swin}

    print(f"\n  {label} (N={n}):")
    print(f"    平均收益: {avg:+.2f}%   胜率: {win:.1f}%   标准差: {std:.2f}%   夏普: {sh:+.2f}")
    print(f"    平均持有: {avg_hold:.0f}天   年化: {ann:+.1f}%")
    print(f"    平均盈利: {aw:+.2f}%   平均亏损: {al:+.2f}%   盈亏比: {abs(aw/al):.2f}")
    print(f"    最佳: {max(rets):+.2f}%   最差: {min(rets):+.2f}%")
    for sname, s in strat_stats.items():
        print(f"    {sname}: N={s['n']} avg={s['avg']:+.2f}% win={s['win']:.1f}%")

# 总体对比
calc_group_stats(out_win, f"窗口前 (D+{SCAN_START}内)")
calc_group_stats(in_win, f"窗口内 (D+{SCAN_START}起)")

# 按策略分窗口状态
for key, name, _ in strategies:
    out_sub = [r for r in out_win if r['strategy'] == name]
    in_sub = [r for r in in_win if r['strategy'] == name]
    print(f"\n  --- {name} ---")
    calc_group_stats(out_sub, f"窗口前")
    calc_group_stats(in_sub, f"窗口内")

# 详细分析：窗口前的信号分布
print(f"\n\n详细分析: 窗口前信号的时间分布")
print(f"{'距通过交易日':>10} | {'信号数':>5} | {'平均收益%':>8} | {'胜率%':>6}")
print("-" * 40)
for lo in range(1, 21):
    hi = lo + 1 if lo < 20 else 999
    sub = [r for r in out_win if lo <= r['tdays'] < hi]
    if sub:
        rets = [t['ret'] for t in sub]
        avg = sum(rets) / len(rets)
        win = sum(1 for x in rets if x > 0) / len(rets) * 100
        print(f"  {lo:>2} ~ {hi-1:<2}天     | {len(sub):>5} | {avg:>+7.2f}% | {win:>5.1f}%")

# 今天命中的样本
print(f"\n\n今日(2026-04-29)命中的样本:")
today_hits = [r for r in all_results if r['date'] == '2026-04-29']
for r in sorted(today_hits, key=lambda x: x['tdays']):
    flag = "窗口内" if r['in_window'] else "窗口外"
    print(f"  {flag} {r['code']} {r['name']} {r['strategy']} tg={r['tg_date']} reg={r['reg_date']} "
          f"D+{r['tdays']} 买入{r['bp']:.2f} 卖出{r['sp']:.2f} 收益{r['ret']:+.2f}% 持有{r['held']}天")

if not today_hits:
    print("  今日无命中信号")
    # 显示最近命中的
    recent = sorted(out_win, key=lambda x: x['date'], reverse=True)[:10]
    print(f"\n  最近窗口外命中:")
    for r in recent:
        print(f"  {r['date']} {r['code']} {r['name']} {r['strategy']} tg={r['tg_date']} D+{r['tdays']} 收益{r['ret']:+.2f}%")
