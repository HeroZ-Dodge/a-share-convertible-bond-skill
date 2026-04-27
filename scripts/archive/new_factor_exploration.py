#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新因子探索 — 基于OHLCV的创意因子

新因子维度:
  1. 均线排列度 (多头排列 vs 空头排列)
  2. 连阳/连阴次数 (注册日前N天)
  3. 缺口检测 (跳空高开/低开频率)
  4. 价格斜率 (趋势方向)
  5. 量价相关性 (量价配合度)
  6. 涨跌交替频率 (振荡 vs 趋势)
  7. 上/下交易日影响 (昨涨/昨跌对今日影响)
  8. 高点/低点距离 (距离近期高点)
  9. 筹码集中度 (收盘价在区间位置)
  10. 量分布特征 (近N日量集中在哪段)
  11. 价量背离 (价涨量缩/价跌量放)
  12. 均线夹角 (MA5 vs MA20 方向)
"""
import sys, os, re, math
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


def load_samples(cache):
    today_str = datetime.now().strftime('%Y-%m-%d')
    bonds = cache.get_jisilu_bonds(phase='注册', limit=0)
    samples = []

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
        reg = prices[sd[ri]]
        reg_close = reg['close']
        if reg_close <= 0 or ri < 30: continue  # 需要足够历史数据

        # ========== 获取注册日前后数据 ==========
        closes = [prices[sd[i]]['close'] for i in range(ri + 1)]
        opens = [prices[sd[i]].get('open', closes[i]) for i in range(ri + 1)]
        highs = [prices[sd[i]].get('high', closes[i]) for i in range(ri + 1)]
        lows = [prices[sd[i]].get('low', closes[i]) for i in range(ri + 1)]
        vols = [prices[sd[i]].get('volume', 0) for i in range(ri + 1)]
        n_hist = len(closes)

        # ========== D+1 开盘 (买入价) ==========
        buy_idx = ri + 1
        if buy_idx >= len(sd) or sd[buy_idx] > today_str: continue
        buy_price = prices[sd[buy_idx]].get('open', 0)
        if not buy_price or buy_price <= 0: continue

        # ========== D+9 收盘 ==========
        d9_idx = ri + 8
        ret_d9 = None
        if d9_idx < len(sd) and sd[d9_idx] <= today_str:
            ret_d9 = ((prices[sd[d9_idx]]['close'] - buy_price) / buy_price * 100)

        # ========== 基础收益数据 ==========
        hold_prices = {}
        for off in range(1, 15):
            idx = ri + off
            if idx < n_hist:
                hold_prices[off] = prices[sd[idx]]['close']

        # ==============================================================
        # 新因子 1: 均线排列度
        # ==============================================================
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10 if n_hist >= 10 else 0
        ma20 = sum(closes[-20:]) / 20 if n_hist >= 20 else 0
        ma30 = sum(closes[-min(30, n_hist):]) / min(30, n_hist) if n_hist >= 5 else 0

        # 多头排列得分: MA5>MA10>MA20 → +1, 空头排列 → -1
        ma_alignment = 0
        if ma10 > 0 and ma20 > 0:
            if ma5 > ma10 > ma20: ma_alignment = 1      # 多头排列
            elif ma5 < ma10 < ma20: ma_alignment = -1    # 空头排列
        # 部分排列
        ma_spread_5_10 = ((ma5 - ma10) / ma10 * 100) if ma10 > 0 else 0
        ma_spread_10_20 = ((ma10 - ma20) / ma20 * 100) if ma20 > 0 else 0
        ma_spread_5_20 = ((ma5 - ma20) / ma20 * 100) if ma20 > 0 else 0

        # 价格相对均线位置
        price_vs_ma5 = ((reg_close - ma5) / ma5 * 100) if ma5 > 0 else 0
        price_vs_ma20 = ((reg_close - ma20) / ma20 * 100) if ma20 > 0 else 0

        # ==============================================================
        # 新因子 2: 连阳/连阴
        # ==============================================================
        # 注册日前5天的涨跌
        daily_chgs = []
        for i in range(max(1, n_hist - 10), n_hist):
            if closes[i-1] > 0:
                daily_chgs.append((closes[i] - closes[i-1]) / closes[i-1] * 100)

        # 注册日前连续上涨天数
        consec_up = 0
        for i in range(n_hist - 1, 0, -1):
            if closes[i] > closes[i-1]:
                consec_up += 1
            else:
                break

        # 注册日前连续下跌天数
        consec_down = 0
        for i in range(n_hist - 1, 0, -1):
            if closes[i] < closes[i-1]:
                consec_down += 1
            else:
                break

        # 注册日前5天中收涨/收跌次数
        up_count_5 = sum(1 for c in daily_chgs[-5:] if c > 0) if len(daily_chgs) >= 5 else 0
        down_count_5 = 5 - up_count_5 if len(daily_chgs) >= 5 else 0

        # 注册日前7天中收涨/收跌次数
        up_count_7 = sum(1 for c in daily_chgs[-7:] if c > 0) if len(daily_chgs) >= 7 else 0

        # 注册日前5天最大连阳
        max_consec_up_5 = 0
        cur = 0
        for c in daily_chgs[-5:]:
            if c > 0:
                cur += 1
                max_consec_up_5 = max(max_consec_up_5, cur)
            else:
                cur = 0

        # 注册日前5天最大连阴
        max_consec_down_5 = 0
        cur = 0
        for c in daily_chgs[-5:]:
            if c < 0:
                cur += 1
                max_consec_down_5 = max(max_consec_down_5, cur)
            else:
                cur = 0

        # ==============================================================
        # 新因子 3: 缺口检测
        # ==============================================================
        gap_count_5 = 0  # 近5天跳空次数
        gap_count_10 = 0  # 近10天跳空次数
        last_gap = 0  # 最近一次跳空幅度
        for i in range(max(1, n_hist - 10), n_hist):
            if opens[i] > 0 and closes[i-1] > 0:
                gap_pct = (opens[i] - closes[i-1]) / closes[i-1] * 100
                if abs(gap_pct) > 0.5:  # 跳空>0.5%算有效缺口
                    gap_count_10 += 1
                    if i >= n_hist - 5:
                        gap_count_5 += 1
                    last_gap = gap_pct

        # 最近是否有向上跳空
        has_up_gap_5 = gap_count_5 > 0 and last_gap > 0.5

        # ==============================================================
        # 新因子 4: 价格斜率 (线性回归斜率)
        # ==============================================================
        def linear_slope(values):
            n_v = len(values)
            if n_v < 2: return 0
            x_mean = (n_v - 1) / 2
            y_mean = sum(values) / n_v
            num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
            den = sum((i - x_mean) ** 2 for i in range(n_v))
            return num / den if den > 0 else 0

        slope_5 = linear_slope(closes[-5:]) / closes[-1] * 100 if closes[-1] > 0 else 0
        slope_10 = linear_slope(closes[-10:]) / closes[-1] * 100 if closes[-1] > 0 else 0
        slope_20 = linear_slope(closes[-20:]) / closes[-1] * 100 if closes[-1] > 0 else 0

        # 斜率变化 (加速/减速)
        slope_change = slope_5 - slope_10  # 短期斜率 - 长期斜率

        # ==============================================================
        # 新因子 5: 量价相关性
        # ==============================================================
        def corr(x_vals, y_vals):
            n_c = len(x_vals)
            if n_c < 3: return 0
            mx = sum(x_vals) / n_c
            my = sum(y_vals) / n_c
            num = sum((a - mx) * (b - my) for a, b in zip(x_vals, y_vals))
            dx = sum((a - mx) ** 2 for a in x_vals) ** 0.5
            dy = sum((b - my) ** 2 for b in y_vals) ** 0.5
            if dx == 0 or dy == 0: return 0
            return num / (dx * dy)

        # 近10天价量相关 (收盘价 vs 成交量)
        price_changes_10 = []
        vol_10 = []
        for i in range(max(2, n_hist - 10), n_hist):
            if closes[i-1] > 0:
                price_changes_10.append((closes[i] - closes[i-1]) / closes[i-1] * 100)
                vol_10.append(vols[i] if vols[i] > 0 else 0)

        vol_price_corr = corr(price_changes_10, vol_10) if len(price_changes_10) >= 3 else 0

        # ==============================================================
        # 新因子 6: 涨跌交替频率
        # ==============================================================
        # 近7天涨/跌变化次数 (频繁交替 vs 单边)
        flip_count_7 = 0
        if len(daily_chgs) >= 7:
            for i in range(len(daily_chgs) - 7, len(daily_chgs) - 1):
                if (daily_chgs[i] > 0) != (daily_chgs[i+1] > 0):
                    flip_count_7 += 1

        flip_count_10 = 0
        if len(daily_chgs) >= 10:
            for i in range(len(daily_chgs) - 10, len(daily_chgs) - 1):
                if (daily_chgs[i] > 0) != (daily_chgs[i+1] > 0):
                    flip_count_10 += 1

        # ==============================================================
        # 新因子 7: 上/下交易日影响
        # ==============================================================
        prev_day_chg = daily_chgs[-1] if daily_chgs else 0  # 注册日前一天涨跌
        prev2_day_chg = daily_chgs[-2] if len(daily_chgs) >= 2 else 0  # 前2天涨跌
        prev_day_up = 1 if prev_day_chg > 0 else 0

        # ==============================================================
        # 新因子 8: 距离近期高点/低点
        # ==============================================================
        high_20 = max(highs[-min(20, n_hist):]) if n_hist > 0 else 0
        low_20 = min(lows[-min(20, n_hist):]) if n_hist > 0 else 99999
        dist_to_high_20 = ((reg_close - high_20) / high_20 * 100) if high_20 > 0 else 0
        dist_to_low_20 = ((reg_close - low_20) / low_20 * 100) if low_20 > 0 else 0

        # 距离52周高点
        high_250 = max(highs[-min(250, n_hist):]) if n_hist > 0 else 0
        low_250 = min(lows[-min(250, n_hist):]) if n_hist > 0 else 99999
        dist_to_high_250 = ((reg_close - high_250) / high_250 * 100) if high_250 > 0 else 0
        position_52w = ((reg_close - low_250) / (high_250 - low_250) * 100) if high_250 > low_250 else 50

        # ==============================================================
        # 新因子 9: 筹码集中度 (收盘价分布)
        # ==============================================================
        # 近10天收盘价中位数 vs 均值 (偏态)
        closes_10 = closes[-10:] if n_hist >= 10 else closes
        med_10 = sorted(closes_10)[len(closes_10) // 2]
        mean_10 = sum(closes_10) / len(closes_10)
        skew_10 = ((reg_close - med_10) / med_10 * 100) if med_10 > 0 else 0

        # ==============================================================
        # 新因子 10: 量分布特征
        # ==============================================================
        # 近10天成交量中，前5天 vs 后5天的量占比
        vol_sum_5 = sum(vols[-5:]) if n_hist >= 5 else 0
        vol_sum_prev_5 = sum(vols[-10:-5]) if n_hist >= 10 else 0
        vol_first_half_ratio = (vol_sum_prev_5 / (vol_sum_prev_5 + vol_sum_5)) if (vol_sum_prev_5 + vol_sum_5) > 0 else 0.5
        # >0.5: 前期量多 → 后期缩量; <0.5: 后期放量

        # 近10天最大量日是否在注册日附近(最近3天)
        vol_recent_max = max(vols[-3:]) if n_hist >= 3 else 0
        vol_total_10 = sum(vols[-10:]) if n_hist >= 10 else 0
        vol_concentration = vol_recent_max / vol_total_10 if vol_total_10 > 0 else 0

        # ==============================================================
        # 新因子 11: 价量背离
        # ==============================================================
        # 近5天：价格涨但量缩 → 背离
        price_5d = ((closes[-1] - closes[-5]) / closes[-5] * 100) if n_hist >= 5 and closes[-5] > 0 else 0
        vol_5d = ((sum(vols[-3:]) / 3 - sum(vols[-5:-3]) / 2)) if n_hist >= 5 else 0
        avg_vol_5 = sum(vols[-5:]) / 5 if n_hist >= 5 else 0
        vol_5d_pct = (vol_5d / avg_vol_5 * 100) if avg_vol_5 > 0 else 0

        # 价涨量缩 = 负背离; 价跌量缩 = 正信号(洗盘结束)
        divergence = 0
        if price_5d > 0 and vol_5d_pct < -10: divergence = -1   # 价涨量缩(负背离)
        elif price_5d < 0 and vol_5d_pct < -10: divergence = 1   # 价跌量缩(好)
        elif price_5d > 0 and vol_5d_pct > 10: divergence = 2     # 价涨量增(好)
        elif price_5d < 0 and vol_5d_pct > 10: divergence = -2    # 价跌量增(坏)

        # ==============================================================
        # 新因子 12: 均线方向
        # ==============================================================
        ma5_slope = ((ma5 - (sum(closes[-10:-5]) / 5 if n_hist >= 10 else ma5)) / ma5 * 100) if ma5 > 0 else 0
        ma20_slope = ((ma20 - (sum(closes[-25:-20]) / 5 if n_hist >= 25 else ma20)) / ma20 * 100) if ma20 > 0 else 0

        # MA5上穿MA20 (Golden cross? 太复杂，简化)
        ma5_above_ma20 = 1 if ma5 > ma20 and ma20 > 0 else 0
        ma5_below_ma20 = 1 if ma5 < ma20 and ma20 > 0 else 0

        # ==============================================================
        # 新因子 13: RSI 简化版
        # ==============================================================
        gains_7 = [max(c, 0) for c in daily_chgs[-7:]] if len(daily_chgs) >= 7 else []
        losses_7 = [max(-c, 0) for c in daily_chgs[-7:]] if len(daily_chgs) >= 7 else []
        avg_gain_7 = sum(gains_7) / len(gains_7) if gains_7 else 0
        avg_loss_7 = sum(losses_7) / len(losses_7) if losses_7 else 0
        rsi_7 = (100 - 100 / (1 + avg_gain_7 / avg_loss_7)) if avg_loss_7 > 0 else 50

        # ==============================================================
        # 新因子 14: Bollinger Band 位置
        # ==============================================================
        std_20 = 0
        if n_hist >= 20:
            avg_20 = sum(closes[-20:]) / 20
            std_20 = (sum((x - avg_20) ** 2 for x in closes[-20:]) / 20) ** 0.5
        bollinger_pos = ((reg_close - (ma20 - 2 * std_20)) / (4 * std_20) * 100) if std_20 > 0 else 50
        # 0=下轨, 50=中轨, 100=上轨

        # ==============================================================
        # 新因子 15: 注册日当天特征
        # ==============================================================
        reg_open = reg.get('open', 0) or reg_close
        reg_high = reg.get('high', reg_close)
        reg_low = reg.get('low', reg_close)

        # 注册日跳空
        reg_gap = ((reg_open - closes[-2]) / closes[-2] * 100) if n_hist >= 2 and closes[-2] > 0 else 0

        # 注册日收盘价在当日高低中的位置
        reg_position = ((reg_close - reg_low) / (reg_high - reg_low) * 100) if reg_high > reg_low else 50

        # ==============================================================
        # D+1 开盘跳空
        # ==============================================================
        buy_open = buy_price
        buy_gap = ((buy_open - reg_close) / reg_close * 100) if reg_close > 0 else 0

        # ========== 保存 ==========
        samples.append({
            'code': sc,
            'name': (b.get('bond_name') or b.get('stock_name') or '?')[:12],
            'anchor': anchor,
            'buy_price': buy_open,
            'ret_d9': ret_d9,
            'hold_prices': hold_prices,
            # 新因子
            'ma_alignment': ma_alignment,
            'ma_spread_5_10': ma_spread_5_10,
            'ma_spread_10_20': ma_spread_10_20,
            'ma_spread_5_20': ma_spread_5_20,
            'price_vs_ma5': price_vs_ma5,
            'price_vs_ma20': price_vs_ma20,
            'consec_up': consec_up,
            'consec_down': consec_down,
            'up_count_5': up_count_5,
            'up_count_7': up_count_7,
            'max_consec_up_5': max_consec_up_5,
            'max_consec_down_5': max_consec_down_5,
            'gap_count_5': gap_count_5,
            'gap_count_10': gap_count_10,
            'has_up_gap_5': has_up_gap_5,
            'slope_5': slope_5,
            'slope_10': slope_10,
            'slope_20': slope_20,
            'slope_change': slope_change,
            'vol_price_corr': vol_price_corr,
            'flip_count_7': flip_count_7,
            'flip_count_10': flip_count_10,
            'prev_day_chg': prev_day_chg,
            'prev2_day_chg': prev2_day_chg,
            'dist_to_high_20': dist_to_high_20,
            'dist_to_low_20': dist_to_low_20,
            'dist_to_high_250': dist_to_high_250,
            'position_52w': position_52w,
            'skew_10': skew_10,
            'vol_first_half_ratio': vol_first_half_ratio,
            'vol_concentration': vol_concentration,
            'divergence': divergence,
            'price_5d': price_5d,
            'vol_5d_pct': vol_5d_pct,
            'ma5_slope': ma5_slope,
            'ma20_slope': ma20_slope,
            'ma5_above_ma20': ma5_above_ma20,
            'ma5_below_ma20': ma5_below_ma20,
            'rsi_7': rsi_7,
            'bollinger_pos': bollinger_pos,
            'reg_gap': reg_gap,
            'reg_position': reg_position,
            'buy_gap': buy_gap,
        })

    samples.sort(key=lambda x: x['anchor'], reverse=True)
    return samples


def stats_fn(values, min_n=15):
    if len(values) < min_n: return None
    s = sorted(values)
    n = len(s)
    avg = sum(s) / n
    std = (sum((x - avg) ** 2 for x in s) / n) ** 0.5
    sh = avg / std if std > 0 else 0
    win = sum(1 for x in s if x > 0) / n * 100
    return {'n': n, 'avg': avg, 'win': win, 'std': std, 'sharpe': sh}


def test_factor(samples, factor_name, cond_fn):
    rets = [s['ret_d9'] for s in samples if s['ret_d9'] is not None and cond_fn(s)]
    return stats_fn(rets)


def main():
    cache = BacktestCache()
    print("加载样本并计算新因子...", flush=True)
    samples = load_samples(cache)
    print(f"  总样本: {len(samples)}")

    # 统计有ret_d9的样本
    with_ret = [s for s in samples if s['ret_d9'] is not None]
    print(f"  有D+9收益: {len(with_ret)}")

    # ========== 1) 单因子阈值扫描 ==========
    print("\n" + "=" * 110)
    print("新因子单因子阈值扫描 (Top 40)")
    print("=" * 110)

    factors = [
        # 均线排列
        ('ma_alignment==1', lambda s: s['ma_alignment'] == 1),
        ('ma_alignment==-1', lambda s: s['ma_alignment'] == -1),
        ('ma5>ma20', lambda s: s['ma5_above_ma20'] == 1),
        ('ma5<ma20', lambda s: s['ma5_below_ma20'] == 1),
        ('ma_spread_5_20>1', lambda s: s['ma_spread_5_20'] > 1),
        ('price_vs_ma20>5', lambda s: s['price_vs_ma20'] > 5),
        ('price_vs_ma20<0', lambda s: s['price_vs_ma20'] < 0),
        ('price_vs_ma20>-5', lambda s: s['price_vs_ma20'] > -5),

        # 连阳/连阴
        ('consec_up>=2', lambda s: s['consec_up'] >= 2),
        ('consec_up>=3', lambda s: s['consec_up'] >= 3),
        ('consec_down>=2', lambda s: s['consec_down'] >= 2),
        ('consec_down>=3', lambda s: s['consec_down'] >= 3),
        ('up_count_5>=4', lambda s: s['up_count_5'] >= 4),
        ('up_count_5<=1', lambda s: s['up_count_5'] <= 1),
        ('max_consec_up_5>=3', lambda s: s['max_consec_up_5'] >= 3),
        ('max_consec_down_5>=3', lambda s: s['max_consec_down_5'] >= 3),

        # 缺口
        ('gap_count_5>0', lambda s: s['gap_count_5'] > 0),
        ('has_up_gap_5', lambda s: s['has_up_gap_5']),
        ('gap_count_10>0', lambda s: s['gap_count_10'] > 0),

        # 斜率
        ('slope_5>0', lambda s: s['slope_5'] > 0),
        ('slope_10>0', lambda s: s['slope_10'] > 0),
        ('slope_20>0', lambda s: s['slope_20'] > 0),
        ('slope_change>0 (加速)', lambda s: s['slope_change'] > 0),
        ('slope_5<0', lambda s: s['slope_5'] < 0),

        # 量价相关
        ('vol_price_corr>0.3', lambda s: s['vol_price_corr'] > 0.3),
        ('vol_price_corr<-0.3', lambda s: s['vol_price_corr'] < -0.3),

        # 涨跌交替
        ('flip_count_7>=5', lambda s: s['flip_count_7'] >= 5),
        ('flip_count_7<=2', lambda s: s['flip_count_7'] <= 2),

        # 距离高点/低点
        ('dist_to_high_20<-5', lambda s: s['dist_to_high_20'] < -5),
        ('dist_to_high_20>-2', lambda s: s['dist_to_high_20'] > -2),
        ('position_52w>70', lambda s: s['position_52w'] > 70),
        ('position_52w<30', lambda s: s['position_52w'] < 30),
        ('dist_to_low_20<3', lambda s: s['dist_to_low_20'] < 3),

        # 筹码
        ('skew_10>2', lambda s: s['skew_10'] > 2),

        # 量分布
        ('vol_first_half_ratio>0.6', lambda s: s['vol_first_half_ratio'] > 0.6),
        ('vol_concentration>0.2', lambda s: s['vol_concentration'] > 0.2),

        # 价量背离
        ('divergence==1 (价跌量缩)', lambda s: s['divergence'] == 1),
        ('divergence==2 (价涨量增)', lambda s: s['divergence'] == 2),
        ('divergence==-1 (价涨量缩)', lambda s: s['divergence'] == -1),
        ('divergence==-2 (价跌量增)', lambda s: s['divergence'] == -2),

        # RSI
        ('rsi_7<30 (超卖)', lambda s: s['rsi_7'] < 30),
        ('rsi_7>70 (超买)', lambda s: s['rsi_7'] > 70),
        ('rsi_7<40', lambda s: s['rsi_7'] < 40),

        # 布林带
        ('bollinger<20 (近下轨)', lambda s: s['bollinger_pos'] < 20),
        ('bollinger>80 (近上轨)', lambda s: s['bollinger_pos'] > 80),
        ('bollinger<50 (下半区)', lambda s: s['bollinger_pos'] < 50),

        # 注册日特征
        ('reg_gap>0.5 (注册日跳空)', lambda s: s['reg_gap'] > 0.5),
        ('reg_position>70 (收在高处)', lambda s: s['reg_position'] > 70),

        # D+1开盘跳空
        ('buy_gap>0 (高开)', lambda s: s['buy_gap'] > 0),
    ]

    results = []
    for label, fn in factors:
        st = test_factor(samples, label, fn)
        if st:
            results.append((label, st))

    results.sort(key=lambda x: x[1]['sharpe'], reverse=True)

    print(f"\n  {'条件':<45} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 70)

    for label, st in results[:40]:
        star = '★' if st['sharpe'] > 0.35 and st['n'] >= 15 else ' '
        print("  {}{:.<43} {:>4} {:>+6.2f}% {:>5.1f}% {:>+5.2f}".format(
            star, label, st['n'], st['avg'], st['win'], st['sharpe']))

    # ========== 2) 新因子 × 已知有效因子 (缩量+回调) ==========
    print("\n" + "=" * 110)
    print("新因子增强: B2(pre3≤-2+mom10≤-1+vol≤0.8) + 新因子")
    print("=" * 110)

    # B2 基线
    def b2_fn(s):
        return s['price_5d'] <= 0 and s['vol_5d_pct'] <= -10  # will use real factors below

    # 用 price_5d < 0 和 vol_first_half_ratio 近似 B2
    # 需要 pre3/mom10/vol — 先用简化版
    b2_samples = [s for s in samples if True]  # placeholder

    # 重新用 factor_space_scan.py 的因子提取方式
    # 这里简化：用 price_5d < 0 和 vol_ratio 代替

    print("\n  B2 基线 (用 price_5d<0 + vol_first_half_ratio>0.6 近似):")

    b2_like = [s for s in samples
               if s['price_5d'] < 0 and s['vol_first_half_ratio'] > 0.55
               and s['ret_d9'] is not None]
    if b2_like:
        rets = [s['ret_d9'] for s in b2_like]
        st = stats_fn(rets, min_n=5)
        if st:
            print(f"    B2-like: n={st['n']} avg={st['avg']:+.2f}% win={st['win']:.1f}% sh={st['sharpe']:+.2f}")

    # B2 + 每个新因子
    enhancements = [
        ('ma_alignment==1 (多头)', lambda s: s['ma_alignment'] == 1),
        ('ma_alignment==-1 (空头)', lambda s: s['ma_alignment'] == -1),
        ('consec_down>=2 (连跌≥2)', lambda s: s['consec_down'] >= 2),
        ('rsi_7<40 (超卖区)', lambda s: s['rsi_7'] < 40),
        ('position_52w<50 (低位)', lambda s: s['position_52w'] < 50),
        ('slope_5<0 (短期跌)', lambda s: s['slope_5'] < 0),
        ('slope_5>0 (短期涨)', lambda s: s['slope_5'] > 0),
        ('flip_count_7<=3 (单边)', lambda s: s['flip_count_7'] <= 3),
        ('dist_to_high_20<-10 (深跌)', lambda s: s['dist_to_high_20'] < -10),
        ('bollinger<50 (布林下半)', lambda s: s['bollinger_pos'] < 50),
        ('divergence==1 (价跌量缩)', lambda s: s['divergence'] == 1),
        ('vol_price_corr<0 (量价背离)', lambda s: s['vol_price_corr'] < 0),
        ('max_consec_down_5>=2 (连阴≥2)', lambda s: s['max_consec_down_5'] >= 2),
    ]

    print(f"\n  {'增强条件':<40} {'n':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 65)

    for label, enh_fn in enhancements:
        subset = [s for s in b2_like if enh_fn(s) and s['ret_d9'] is not None]
        if len(subset) < 5: continue
        rets = [s['ret_d9'] for s in subset]
        st = stats_fn(rets, min_n=5)
        if st:
            print(f"  {label:<40} {st['n']:>4} {st['avg']:>+6.2f}% {st['win']:>5.1f}% {st['sharpe']:>+5.2f}")

    # ========== 3) 全新策略族: 均线排列族 ==========
    print("\n" + "=" * 110)
    print("策略族: 均线排列 × 价格位置")
    print("=" * 110)

    ma_strategies = {
        '多头排列(ma5>ma10>ma20)': lambda s: s['ma_alignment'] == 1,
        '空头排列(ma5<ma10<ma20)': lambda s: s['ma_alignment'] == -1,
        '多头+价格>ma20': lambda s: s['ma_alignment'] == 1 and s['price_vs_ma20'] > 0,
        '多头+价格<ma20 (回踩)': lambda s: s['ma_alignment'] == 1 and s['price_vs_ma20'] < 0,
        '空头+价格>ma20 (反弹)': lambda s: s['ma_alignment'] == -1 and s['price_vs_ma20'] > 0,
        'ma5>ma20+价格<ma5': lambda s: s['ma5_above_ma20'] == 1 and s['price_vs_ma5'] < 0,
        'ma5<ma20+价格>ma5': lambda s: s['ma5_below_ma20'] == 1 and s['price_vs_ma5'] > 0,
        'ma_spread_5_20>2': lambda s: s['ma_spread_5_20'] > 2,
        'ma_spread_5_20<-2': lambda s: s['ma_spread_5_20'] < -2,
    }

    print(f"\n  {'条件':<45} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 70)

    for label, fn in ma_strategies.items():
        st = test_factor(samples, label, fn)
        if st:
            star = '★' if st['sharpe'] > 0.3 and st['n'] >= 10 else ' '
            print("  {}{:.<43} {:>4} {:>+6.2f}% {:>5.1f}% {:>+5.2f}".format(
                star, label, st['n'], st['avg'], st['win'], st['sharpe']))

    # ========== 4) 全新策略族: RSI + 布林带族 ==========
    print("\n" + "=" * 110)
    print("策略族: RSI + 布林带")
    print("=" * 110)

    rsi_boll_strategies = {
        'RSI<30 (超卖)': lambda s: s['rsi_7'] < 30,
        'RSI<35': lambda s: s['rsi_7'] < 35,
        'RSI<40': lambda s: s['rsi_7'] < 40,
        'RSI<45': lambda s: s['rsi_7'] < 45,
        'RSI>60 (强势)': lambda s: s['rsi_7'] > 60,
        '布林下轨(boll<20)': lambda s: s['bollinger_pos'] < 20,
        '布林下半(boll<50)': lambda s: s['bollinger_pos'] < 50,
        '布林上轨(boll>80)': lambda s: s['bollinger_pos'] > 80,
        'RSI<30+布林下轨': lambda s: s['rsi_7'] < 30 and s['bollinger_pos'] < 20,
        'RSI<40+布林下轨': lambda s: s['rsi_7'] < 40 and s['bollinger_pos'] < 30,
    }

    print(f"\n  {'条件':<45} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 70)

    for label, fn in rsi_boll_strategies.items():
        st = test_factor(samples, label, fn)
        if st:
            star = '★' if st['sharpe'] > 0.3 and st['n'] >= 10 else ' '
            print("  {}{:.<43} {:>4} {:>+6.2f}% {:>5.1f}% {:>+5.2f}".format(
                star, label, st['n'], st['avg'], st['win'], st['sharpe']))

    # ========== 5) 全新策略族: 连阳/连阴 + 斜率族 ==========
    print("\n" + "=" * 110)
    print("策略族: 连阳/连阴 + 价格斜率")
    print("=" * 110)

    trend_strategies = {
        '连跌≥2': lambda s: s['consec_down'] >= 2,
        '连跌≥3': lambda s: s['consec_down'] >= 3,
        '连涨≥2': lambda s: s['consec_up'] >= 2,
        '近5天跌≥4天': lambda s: s['up_count_5'] <= 1,
        '近5天跌≥3天': lambda s: s['up_count_5'] <= 2,
        '近7天跌≥5天': lambda s: s['up_count_7'] <= 2,
        '连阴≥2': lambda s: s['max_consec_down_5'] >= 2,
        '连阴≥3': lambda s: s['max_consec_down_5'] >= 3,
        'slope_5<0 (短期跌)': lambda s: s['slope_5'] < 0,
        'slope_10<0 (中期跌)': lambda s: s['slope_10'] < 0,
        'slope_5<0+slope_change<0 (加速跌)': lambda s: s['slope_5'] < 0 and s['slope_change'] < 0,
        'slope_5>0+slope_change>0 (加速涨)': lambda s: s['slope_5'] > 0 and s['slope_change'] > 0,
        'slope_5<0+slope_change>0 (止跌)': lambda s: s['slope_5'] < 0 and s['slope_change'] > 0,
    }

    print(f"\n  {'条件':<45} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 70)

    for label, fn in trend_strategies.items():
        st = test_factor(samples, label, fn)
        if st:
            star = '★' if st['sharpe'] > 0.3 and st['n'] >= 10 else ' '
            print("  {}{:.<43} {:>4} {:>+6.2f}% {:>5.1f}% {:>+5.2f}".format(
                star, label, st['n'], st['avg'], st['win'], st['sharpe']))

    # ========== 6) 价量背离族 ==========
    print("\n" + "=" * 110)
    print("策略族: 价量背离")
    print("=" * 110)

    divergence_strategies = {
        '价跌量缩 (好)': lambda s: s['divergence'] == 1,
        '价涨量增 (好)': lambda s: s['divergence'] == 2,
        '价涨量缩 (坏)': lambda s: s['divergence'] == -1,
        '价跌量增 (坏)': lambda s: s['divergence'] == -2,
        '量价负相关(corr<-0.3)': lambda s: s['vol_price_corr'] < -0.3,
        '量价正相关(corr>0.3)': lambda s: s['vol_price_corr'] > 0.3,
        '前期量大后期量小(vol_ratio>0.6)': lambda s: s['vol_first_half_ratio'] > 0.6,
        '前期量小后期量大(vol_ratio<0.4)': lambda s: s['vol_first_half_ratio'] < 0.4,
        '量集中在近3天(conc>0.2)': lambda s: s['vol_concentration'] > 0.2,
    }

    print(f"\n  {'条件':<45} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 70)

    for label, fn in divergence_strategies.items():
        st = test_factor(samples, label, fn)
        if st:
            star = '★' if st['sharpe'] > 0.3 and st['n'] >= 10 else ' '
            print("  {}{:.<43} {:>4} {:>+6.2f}% {:>5.1f}% {:>+5.2f}".format(
                star, label, st['n'], st['avg'], st['win'], st['sharpe']))

    # ========== 7) 综合最佳组合 ==========
    print("\n" + "=" * 110)
    print("新因子组合扫描 (Top 20)")
    print("=" * 110)

    combos = []

    # 均线排列 × 斜率
    for ma in [1, -1, 0]:
        for slope_sign in ['>0', '<0']:
            for pos in ['>0', '<0']:
                if ma == 1 and pos == '>0':  # 多头+价格>均线
                    fn = lambda s, _ma=ma, _pos=pos: (
                        s['ma_alignment'] == _ma
                        and s['price_vs_ma20'] > 0
                        and s['slope_5'] > 0 if slope_sign == '>0' else s['slope_5'] < 0
                    )
                elif ma == 1 and pos == '<0':  # 多头+价格<均线(回踩)
                    fn = lambda s, _ma=ma, _pos=pos: (
                        s['ma_alignment'] == _ma
                        and s['price_vs_ma20'] < 0
                        and s['slope_5'] > 0 if slope_sign == '>0' else s['slope_5'] < 0
                    )
                elif ma == -1 and pos == '>0':  # 空头+价格>均线(反弹)
                    fn = lambda s, _ma=ma, _pos=pos: (
                        s['ma_alignment'] == _ma
                        and s['price_vs_ma20'] > 0
                        and s['slope_5'] > 0 if slope_sign == '>0' else s['slope_5'] < 0
                    )
                else:
                    continue

                desc = f"ma={'多头' if ma==1 else '空头'} pos={pos} slope={slope_sign}"
                st = test_factor(samples, desc, fn)
                if st and st['sharpe'] > 0.2:
                    combos.append((desc, st))

    # RSI × 布林带
    for rsi_t in [30, 35, 40]:
        for boll_t in [20, 30, 40, 50]:
            fn = lambda s, _r=rsi_t, _b=boll_t: s['rsi_7'] < _r and s['bollinger_pos'] < _b
            desc = f"RSI<{rsi_t}+boll<{boll_t}"
            st = test_factor(samples, desc, fn)
            if st and st['sharpe'] > 0.2:
                combos.append((desc, st))

    # 连阴 × 斜率
    for cd in [2, 3]:
        for slope_sign in ['>0', '<0']:
            fn = lambda s, _cd=cd, _ss=slope_sign: (
                s['consec_down'] >= _cd
                and s['slope_5'] > 0 if _ss == '>0' else s['slope_5'] < 0
            )
            desc = f"连跌>={cd}+slope{'>' if slope_sign=='>' else '<'}0"
            st = test_factor(samples, desc, fn)
            if st and st['sharpe'] > 0.2:
                combos.append((desc, st))

    # 价量背离 × 斜率
    for div in [1, 2]:
        fn = lambda s, _d=div: s['divergence'] == _d
        desc = f"背离={div}+slope<0"
        fn2 = lambda s, _d=div: s['divergence'] == _d and s['slope_5'] < 0
        st = test_factor(samples, desc, fn2)
        if st and st['sharpe'] > 0.2:
            combos.append((desc, st))

    combos.sort(key=lambda x: x[1]['sharpe'], reverse=True)

    print(f"\n  {'条件':<45} {'样本':>4} {'平均':>7} {'胜率':>6} {'夏普':>6}")
    print("  " + "-" * 70)

    seen = set()
    for desc, st in combos[:30]:
        # 简单去重
        key_parts = desc.replace(' ', '').split('+')[:2]
        key = '+'.join(key_parts)
        if key in seen: continue
        seen.add(key)
        star = '★' if st['sharpe'] > 0.35 and st['n'] >= 10 else ' '
        print("  {}{:.<43} {:>4} {:>+6.2f}% {:>5.1f}% {:>+5.2f}".format(
            star, desc, st['n'], st['avg'], st['win'], st['sharpe']))


if __name__ == '__main__':
    main()
