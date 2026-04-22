#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
潜伏策略监控脚本 (带自我进化)

核心功能:
1. 监控上市委通过后的转债，捕捉资金布局信号
2. 自动保存集思录数据到本地数据库
3. 跟踪信号结果，用于自我进化
4. 基于历史数据自动优化监控参数

🧬 自我进化: 随着监控案例增多，自动提升判断准确性
"""

import sys
import os
import json
import re
from datetime import datetime, timedelta
# 添加项目根目录到路径 (向上 3 级：monitor -> scripts -> 根目录)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lib.data_source import JisiluAPI, SinaFinanceAPI
from lib.stock_quality import StockQualityEvaluator
from lib.sqlite_database import SQLiteDatabase
from lib.self_evolution import SelfEvolution
from lib.signal_tracker import SignalTracker


def parse_progress_dates(progress_full: str) -> dict:
    """解析进度字符串，提取各个节点的日期"""
    if not progress_full:
        return {}
    
    progress_full = progress_full.replace('<br>', '\n')
    dates = {}
    pattern = r'(\d{4}-\d{2}-\d{2})\s+([^\n]+)'
    
    for match in re.finditer(pattern, progress_full):
        date_str = match.group(1)
        event = match.group(2).strip()
        dates[event] = date_str
    
    return dates


def load_monitor_history():
    """加载监控历史记录"""
    history_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'monitor_history.json')
    if os.path.exists(history_path):
        with open(history_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'bonds': {}, 'alerts': [], 'signals': {}}


def save_monitor_history(data):
    """保存监控历史记录"""
    history_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'monitor_history.json')
    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def check_volume_signal(prices: dict, lookback_days: int = 5) -> dict:
    """检查成交量信号"""
    if not prices or len(prices) < 10:
        return {'signal': False, 'vol_ratio': 0, 'price_change': 0, 'combined_signal': False}
    
    sorted_dates = sorted(prices.keys())
    latest_date = sorted_dates[-1]
    latest_vol = prices[latest_date]['volume']
    latest_close = prices[latest_date]['close']
    
    avg_vol_5d = sum(prices[sorted_dates[-i]]['volume'] for i in range(1, 6)) / 5
    prev_close = prices[sorted_dates[-6]]['close'] if len(sorted_dates) >= 6 else latest_close
    
    vol_ratio = latest_vol / avg_vol_5d if avg_vol_5d > 0 else 0
    price_change = (latest_close - prev_close) / prev_close * 100
    
    signal = vol_ratio > 2.0
    combined_signal = signal and price_change > 2.0
    
    return {
        'signal': signal,
        'vol_ratio': vol_ratio,
        'price_change': price_change,
        'combined_signal': combined_signal,
    }


def monitor_latent_strategy(save_data: bool = True, auto_evolve: bool = True, use_cache: bool = True, track_signals: bool = True):
    """
    潜伏策略监控 (带自我进化)
    
    Args:
        save_data: 是否保存数据到本地数据库
        auto_evolve: 是否自动进化
        use_cache: 是否使用缓存数据（提高性能）
    """
    jsl = JisiluAPI(timeout=20)  # 降低超时时间
    sina = SinaFinanceAPI(timeout=15)  # 降低超时时间
    evaluator = StockQualityEvaluator(sina_api=sina)
    db = SQLiteDatabase()
    evolution = SelfEvolution(db)
    tracker = SignalTracker(db=db, sina_api=sina) if track_signals else None
    
    print('=' * 80)
    print('潜伏策略监控 - 消息泄露信号挖掘 (🧬 自我进化版)')
    print('=' * 80)
    print(f'检查时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print()
    
    # 显示进化统计
    if auto_evolve:
        print('🧬 自我进化状态:')
        stats = db.get_stats()
        if stats:
            print(f'   总信号数：{stats.get("total_signals", 0)}')
            print(f'   成功率：{stats.get("success_rate", 0):.1f}%')
            print(f'   平均收益：{stats.get("avg_return", 0):+.2f}%')
            
            # 显示进化建议
            suggestions = db.get_evolution_suggestions() if hasattr(db, "get_evolution_suggestions") else []
            if suggestions:
                print()
                print('   💡 进化建议:')
                for sug in suggestions[:3]:
                    print(f'      - {sug}')
        else:
            print('   数据积累中，需要更多监控案例...')
        print()
    
    # 获取并保存待发转债数据
    print('📥 从集思录获取待发转债数据...')
    bonds = jsl.fetch_pending_bonds(limit=100)
    print(f'获取到 {len(bonds)} 只转债')
    
    # 保存到本地数据库
    if save_data:
        db.save_pending_bonds(bonds, source='jisilu')
        print('💾 数据已保存到本地数据库')
    print()
    
    history = load_monitor_history()
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 获取进化后的参数
    evolved_params = evolution.evolved_params.get('latent', {})
    min_days = evolved_params.get('min_days_since_tongguo', 25)
    max_days = evolved_params.get('max_days_since_tongguo', 55)
    min_rating = evolved_params.get('min_quality_rating', 'B')
    
    print(f'🎯 监控参数 (已进化):')
    print(f'   时间窗口：上市后 {min_days}-{max_days} 天')
    print(f'   最低评级：{min_rating}级')
    print()
    
    monitoring_list = []
    
    for b in bonds:
        bond_name = b.get('bond_name') or 'N/A'
        bond_code = b.get('bond_code', '')
        stock_code = b.get('stock_code', '')
        stock_name = b.get('stock_name') or 'N/A'
        progress_full = b.get('progress_full', '')
        
        dates = parse_progress_dates(progress_full)
        
        # 只关注"上市委通过"但未"同意注册"的转债
        if '上市委通过' not in dates or '同意注册' in dates:
            continue
        
        tongguo_date = dates['上市委通过']
        tongguo_dt = datetime.strptime(tongguo_date, '%Y-%m-%d')
        days_since_tongguo = (today_dt - tongguo_dt).days
        
        # 使用进化后的时间窗口
        if days_since_tongguo < min_days or days_since_tongguo > max_days:
            continue
        
        monitoring_list.append({
            'bond_name': bond_name,
            'bond_code': bond_code,
            'stock_name': stock_name,
            'stock_code': stock_code,
            'tongguo_date': tongguo_date,
            'days_since_tongguo': days_since_tongguo,
        })
    
    print(f'📋 监控列表：{len(monitoring_list)} 只转债')
    print()
    
    if not monitoring_list:
        print('✅ 暂无需要监控的转债')
        return
    
    # 检查信号
    print('🔍 检查信号...')
    print()
    
    signals_found = []
    rating_order = {'A': 4, 'B': 3, 'C': 2, 'D': 1}
    min_rating_value = rating_order.get(min_rating, 3)
    
    # 批量获取股价数据（性能优化）
    stock_codes = [m['stock_code'] for m in monitoring_list]
    print(f'📊 批量获取 {len(stock_codes)} 只股票数据...')
    
    for i, m in enumerate(monitoring_list, 1):
        stock_code = m['stock_code']
        bond_code = m['bond_code']
        
        prices = sina.fetch_history(stock_code, days=30)
        if not prices:
            continue
        
        vol_signal = check_volume_signal(prices)
        quality = evaluator.evaluate(stock_code)
        
        # 检查评级
        if rating_order.get(quality['rating'], 0) < min_rating_value:
            continue
        
        # 计算信号数量 (优化后的条件)
        signal_count = 0
        signal_details = []
        
        # 成交量信号 (降低阈值到 1.5 倍)
        if vol_signal['vol_ratio'] > 1.5:
            signal_count += 1
            signal_details.append(f'成交量{vol_signal["vol_ratio"]:.1f}倍')
        elif vol_signal['vol_ratio'] > 1.2:
            signal_details.append(f'成交量{vol_signal["vol_ratio"]:.1f}倍 (弱)')
        
        # 2 日涨跌幅信号 (降低阈值到 1.5%)
        if vol_signal['price_change'] > 1.5:
            signal_count += 1
            signal_details.append(f'2 日{vol_signal["price_change"]:+.1f}%')
        
        # 5 日涨跌幅信号 (降低阈值到 2.5%)
        sorted_dates = sorted(prices.keys())
        latest_close = prices[sorted_dates[-1]]['close']
        close_5d_ago = prices[sorted_dates[-5]]['close'] if len(sorted_dates) >= 5 else latest_close
        price_change_5d = (latest_close - close_5d_ago) / close_5d_ago * 100
        if price_change_5d > 2.5:
            signal_count += 1
            signal_details.append(f'5 日{price_change_5d:+.1f}%')
        
        # 突破 20 日高点
        high_20d = max(prices[sorted_dates[-i]]['high'] for i in range(1, min(21, len(sorted_dates)+1)))
        if latest_close > high_20d:
            signal_count += 1
            signal_details.append('突破 20 日高点')
        
        # 接近高点也算信号 (新增)
        if high_20d > 0 and latest_close > high_20d * 0.95:
            signal_details.append(f'接近 20 日高点 ({latest_close/high_20d*100:.1f}%)')
        
        # 需要至少 2 个信号 (或者 1 个强信号)
        is_strong_signal = signal_count >= 2 or (signal_count >= 1 and vol_signal['vol_ratio'] > 2.0)
        
        if is_strong_signal:
            alert_key = f"{bond_code}_latent_{today}"
            if alert_key not in history.get('alerts', []):
                # 过滤掉弱信号显示
                strong_details = [d for d in signal_details if '(弱)' not in d]
                signals_found.append({
                    **m,
                    'signal_count': len(strong_details),
                    'signal_details': strong_details if strong_details else signal_details,
                    'quality': quality,
                })
                history.setdefault('alerts', []).append(alert_key)
    
    save_monitor_history(history)
    
    # 输出信号
    if signals_found:
        print(f'🚨 发现 {len(signals_found)} 个潜伏信号！')
        print()
        
        for i, s in enumerate(signals_found, 1):
            print(f'【{i}】{s["bond_name"]} ({s["bond_code"]})')
            print(f'   正股：{s["stock_name"]} ({s["stock_code"]})')
            print(f'   上市委通过：{s["tongguo_date"]} (已过{s["days_since_tongguo"]}天)')
            print(f'   信号：{", ".join(s["signal_details"])} (强度：{s["signal_count"]}个)')
            print(f'   股票质量：{s["quality"]["total_score"]:.1f}分 ({s["quality"]["rating"]}级)')
            print(f'   推荐：{s["quality"]["recommendation"]}')
            print()
            print('   💡 操作建议:')
            print('      - 可能即将发布同意注册公告')
            print('      - 建议入场时机：信号出现当日或次日')
            print('      - 目标收益：注册前 5 天平均 +4.56%')
            print('      - 止损位：-5%')
            print()
            
            # 保存到数据库
            if save_data:
                db.save_signal({
                    'bond_code': s['bond_code'],
                    'bond_name': s['bond_name'],
                    'stock_code': s['stock_code'],
                    'signal_type': 'latent',
                    'tongguo_date': s['tongguo_date'],
                    'days_since_tongguo': s['days_since_tongguo'],
                    'signal_count': s['signal_count'],
                    'stock_quality': s['quality'],
                    'signal_id': f"{s['bond_code']}_{today}",  # 唯一信号 ID
                })
            
            print('-' * 60)
            print()
    else:
        print('✅ 暂无潜伏信号')
        print()
    
    # 显示监控列表
    print('📋 完整监控列表:')
    print('-' * 60)
    for m in sorted(monitoring_list, key=lambda x: x['days_since_tongguo'], reverse=True):
        days_left = max_days - m['days_since_tongguo']
        status = '⚠️' if days_left <= 10 else '➖'
        print(f'{status} {m["bond_name"]} ({m["stock_code"]}): 上市后{m["days_since_tongguo"]}天 (剩余{days_left}天)')
    
    print()
    
    # 自动进化
    if auto_evolve:
        print('🧬 执行自动进化...')
        evolution.auto_evolve()
        print('✅ 进化完成')
        print()
    
    # 跟踪信号结果
    if track_signals and tracker:
        print('📊 跟踪信号结果...')
        tracking_results = tracker.update_all_signals()
        ended_count = sum(1 for r in tracking_results if r.get('status') == 'ended')
        if ended_count > 0:
            print(f'   已结束 {ended_count} 个信号')
            for r in tracking_results:
                if r.get('status') == 'ended':
                    ret = r.get('final_return', 0)
                    ret_str = f'{ret:+.1f}%'
                    ret_icon = '✅' if ret > 0 else '❌'
                    print(f'   {r.get("bond_name", "")} ({r["bond_code"]}): {ret_str} {ret_icon} ({r.get("exit_reason", "")})')
        print()
    
    return signals_found


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='潜伏策略监控 (带自我进化)')
    parser.add_argument('--once', action='store_true', help='只运行一次')
    parser.add_argument('--interval', type=int, default=60, help='监控间隔（分钟），默认 60')
    parser.add_argument('--no-save', action='store_true', help='不保存数据到本地数据库')
    parser.add_argument('--no-evolve', action='store_true', help='禁用自动进化')
    parser.add_argument('--no-track', action='store_true', help='禁用信号跟踪')
    parser.add_argument('--export', action='store_true', help='导出数据')
    parser.add_argument('--report', action='store_true', help='显示进化报告')
    parser.add_argument('--tracking-report', action='store_true', help='显示信号跟踪报告')
    args = parser.parse_args()
    
    if args.tracking_report:
        tracker = SignalTracker()
        print(tracker.get_tracking_report())
        return
    
    if args.report:
        evolution = SelfEvolution()
        print(evolution.get_evolution_report())
        return
    
    if args.export:
        db = SQLiteDatabase()
        db.export_data()
        return
    
    save_data = not args.no_save
    auto_evolve = not args.no_evolve
    track_signals = not args.no_track
    
    if args.once:
        monitor_latent_strategy(save_data=save_data, auto_evolve=auto_evolve, track_signals=track_signals)
    else:
        import time
        print(f'开始监控，每{args.interval}分钟检查一次...')
        print('按 Ctrl+C 停止监控')
        print()
        
        try:
            while True:
                monitor_latent_strategy(save_data=save_data, auto_evolve=auto_evolve)
                print(f'下次检查：{args.interval}分钟后')
                print()
                time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            print('\n监控已停止')


if __name__ == '__main__':
    today_dt = datetime.now()
    main()
