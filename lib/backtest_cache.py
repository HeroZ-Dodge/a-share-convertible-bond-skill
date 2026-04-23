# -*- coding: utf-8 -*-
"""
回测缓存数据库模块

将集思录待发数据、东方财富K线、主力资金、实时行情、涨停数据缓存到 SQLite，
供分析脚本复用，避免 API 限流导致数据不完整。

用法:
    # 独立运行，获取集思录快照
    python3 lib/backtest_cache.py

    # 在脚本中使用
    from lib.backtest_cache import BacktestCache
    cache = BacktestCache()
    bonds = cache.get_latest_jisilu_data()
    klines = cache.get_kline_as_dict('300622', days=90)
"""

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple


class BacktestCache:
    """回测缓存数据库管理"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'data', 'backtest_cache.db'
            )
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表"""
        with self._get_conn() as conn:
            # 集思录待发转债快照
            conn.execute('''
                CREATE TABLE IF NOT EXISTS jisilu_pending_bonds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_date TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_nm TEXT,
                    bond_id TEXT,
                    bond_nm TEXT,
                    apply_date TEXT,
                    apply_cd TEXT,
                    ration_cd TEXT,
                    record_dt TEXT,
                    record_price REAL,
                    ration REAL,
                    amount REAL,
                    convert_price REAL,
                    rating_cd TEXT,
                    progress_nm TEXT,
                    progress_full TEXT,
                    status_cd TEXT,
                    margin_flg TEXT,
                    fetched_at TEXT,
                    UNIQUE(stock_code, snapshot_date)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_jisilu_snapshot ON jisilu_pending_bonds(snapshot_date)')

            # 东方财富股票日K线
            conn.execute('''
                CREATE TABLE IF NOT EXISTS eastmoney_kline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL,
                    close REAL,
                    high REAL,
                    low REAL,
                    volume REAL,
                    amount REAL,
                    amplitude REAL,
                    change_pct REAL,
                    change_amount REAL,
                    turnover_rate REAL,
                    UNIQUE(stock_code, trade_date)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_kline_stock_date ON eastmoney_kline(stock_code, trade_date)')

            # 东方财富主力资金流向
            conn.execute('''
                CREATE TABLE IF NOT EXISTS eastmoney_fund_flow (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    main_net_inflow REAL,
                    main_net_inflow_rate REAL,
                    super_large_net_inflow REAL,
                    large_net_inflow REAL,
                    medium_net_inflow REAL,
                    small_net_inflow REAL,
                    UNIQUE(stock_code, trade_date)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_fflow_stock_date ON eastmoney_fund_flow(stock_code, trade_date)')

            # 东方财富实时行情快照
            conn.execute('''
                CREATE TABLE IF NOT EXISTS eastmoney_realtime_quote (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    snapshot_date TEXT NOT NULL,
                    price REAL,
                    change_pct REAL,
                    change_amount REAL,
                    open REAL,
                    high REAL,
                    low REAL,
                    volume REAL,
                    amount REAL,
                    volume_ratio REAL,
                    pe_ttm REAL,
                    pb REAL,
                    pe_static REAL,
                    total_market_cap REAL,
                    float_market_cap REAL,
                    eps REAL,
                    net_asset_per_share REAL,
                    roe REAL,
                    gross_margin REAL,
                    debt_ratio REAL,
                    margin_balance REAL,
                    short_balance REAL,
                    total_margin REAL,
                    UNIQUE(stock_code, snapshot_date)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_quote_stock_date ON eastmoney_realtime_quote(stock_code, snapshot_date)')

            # 东方财富涨停数据
            conn.execute('''
                CREATE TABLE IF NOT EXISTS eastmoney_limit_up (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT,
                    limit_up_price REAL,
                    change_pct REAL,
                    volume REAL,
                    amount REAL,
                    consecutive_limit_up INTEGER,
                    seal_amount REAL,
                    seal_ratio REAL,
                    fetch_time TEXT,
                    UNIQUE(stock_code, trade_date)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_limitup_date ON eastmoney_limit_up(trade_date)')

            # 东方财富融资融券
            conn.execute('''
                CREATE TABLE IF NOT EXISTS eastmoney_margin_trading (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    stock_name TEXT,
                    margin_balance REAL,
                    short_volume REAL,
                    total_margin REAL,
                    short_balance REAL,
                    margin_buy_amount REAL,
                    change_pct REAL,
                    balance_change REAL,
                    UNIQUE(stock_code, trade_date)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_margin_stock_date ON eastmoney_margin_trading(stock_code, trade_date)')

            # 东方财富大宗交易
            conn.execute('''
                CREATE TABLE IF NOT EXISTS eastmoney_block_trade (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    stock_name TEXT,
                    deal_price REAL,
                    close_price REAL,
                    premium_ratio REAL,
                    deal_volume REAL,
                    deal_amount REAL,
                    buyer_name TEXT,
                    seller_name TEXT,
                    UNIQUE(stock_code, trade_date)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_block_stock_date ON eastmoney_block_trade(stock_code, trade_date)')

            # 东方财富股东户数
            conn.execute('''
                CREATE TABLE IF NOT EXISTS eastmoney_holder_num (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    stock_name TEXT,
                    holder_num INTEGER,
                    prev_holder_num INTEGER,
                    holder_num_change REAL,
                    holder_num_ratio REAL,
                    interval_change_pct REAL,
                    UNIQUE(stock_code, end_date)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_holder_stock_date ON eastmoney_holder_num(stock_code, end_date)')

            # 东方财富机构调研
            conn.execute('''
                CREATE TABLE IF NOT EXISTS eastmoney_institutional_research (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    research_date TEXT NOT NULL,
                    stock_name TEXT,
                    receive_object TEXT,
                    investigators TEXT,
                    num INTEGER,
                    total INTEGER,
                    survey_type TEXT,
                    UNIQUE(stock_code, research_date, receive_object)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_research_stock_date ON eastmoney_institutional_research(stock_code, research_date)')

            # 东方财富北向资金持股
            conn.execute('''
                CREATE TABLE IF NOT EXISTS eastmoney_northbound (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    stock_name TEXT,
                    shares REAL,
                    shares_ratio REAL,
                    share_change REAL,
                    market_cap REAL,
                    free_ratio REAL,
                    UNIQUE(stock_code, trade_date)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_northbound_stock_date ON eastmoney_northbound(stock_code, trade_date)')

            conn.commit()

    # ============================================================
    # 集思录快照
    # ============================================================

    def save_jisilu_snapshot(self) -> Dict[str, int]:
        """
        从集思录获取快照并缓存到数据库

        Returns:
            {total: N, new: N, changed: N, unchanged: N}
        """
        from lib.data_source import JisiluAPI

        jsl = JisiluAPI(timeout=30)
        bonds = jsl.fetch_pending_bonds(limit=200)
        if not bonds:
            print('⚠️  集思录数据获取失败')
            return {'total': 0, 'new': 0, 'changed': 0, 'unchanged': 0}

        today = datetime.now().strftime('%Y-%m-%d')
        now = datetime.now().isoformat()

        with self._get_conn() as conn:
            # 获取上次快照
            cursor = conn.execute(
                'SELECT stock_code, progress_nm, progress_full FROM jisilu_pending_bonds WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM jisilu_pending_bonds WHERE snapshot_date < ?)',
                (today,)
            )
            old_data = {row['stock_code']: {'progress_nm': row['progress_nm'], 'progress_full': row['progress_full']} for row in cursor.fetchall()}

            stats = {'total': len(bonds), 'new': 0, 'changed': 0, 'unchanged': 0}

            for bond in bonds:
                stock_code = bond.get('stock_code', '')
                if not stock_code:
                    continue

                old = old_data.get(stock_code, {})
                has_changed = (
                    old.get('progress_nm') != bond.get('progress_nm') or
                    old.get('progress_full') != bond.get('progress_full')
                )

                conn.execute('''
                    INSERT OR REPLACE INTO jisilu_pending_bonds
                    (stock_code, stock_nm, bond_id, bond_nm, apply_date, apply_cd, ration_cd,
                     record_dt, record_price, ration, amount, convert_price, rating_cd,
                     progress_nm, progress_full, status_cd, margin_flg, snapshot_date, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    stock_code,
                    bond.get('stock_name', ''),
                    bond.get('bond_code', ''),
                    bond.get('bond_name', ''),
                    bond.get('apply_date', ''),
                    bond.get('apply_code', ''),
                    bond.get('ration_code', ''),
                    bond.get('record_date', ''),
                    bond.get('record_price', 0),
                    bond.get('ration', 0),
                    bond.get('amount', 0),
                    bond.get('convert_price', 0),
                    bond.get('rating', ''),
                    bond.get('progress', ''),
                    bond.get('progress_full', ''),
                    bond.get('status', ''),
                    bond.get('market', ''),
                    today,
                    now,
                ))

                if stock_code not in old_data:
                    stats['new'] += 1
                elif has_changed:
                    stats['changed'] += 1
                else:
                    stats['unchanged'] += 1

            conn.commit()

        print(f'💾 集思录快照已保存 | 总数: {stats["total"]}, 新增: {stats["new"]}, 变化: {stats["changed"]}, 未变: {stats["unchanged"]}')
        return stats

    def get_latest_jisilu_data(self) -> List[Dict[str, Any]]:
        """
        获取最新快照的待发转债数据（带字段名标准化）

        Returns:
            列表，每项字段与 BondDataSource 格式一致
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                'SELECT * FROM jisilu_pending_bonds WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM jisilu_pending_bonds)'
            )
            rows = cursor.fetchall()

        if not rows:
            return []

        result = []
        for row in rows:
            d = dict(row)
            result.append({
                'bond_code': d.get('bond_id', ''),
                'bond_name': d.get('bond_nm', ''),
                'stock_code': d.get('stock_code', ''),
                'stock_name': d.get('stock_nm', ''),
                'apply_date': d.get('apply_date', ''),
                'apply_code': d.get('apply_cd', ''),
                'ration_code': d.get('ration_cd', ''),
                'record_date': d.get('record_dt', ''),
                'record_price': d.get('record_price', 0),
                'per_share_amount': d.get('ration', 0),
                'ration': d.get('ration', 0),
                'issue_amount': d.get('amount', 0),
                'amount': d.get('amount', 0),
                'convert_price': d.get('convert_price', 0),
                'credit_rating': d.get('rating_cd', ''),
                'rating': d.get('rating_cd', ''),
                'progress': d.get('progress_nm', ''),
                'progress_full': d.get('progress_full', ''),
                'status': d.get('status_cd', ''),
                'market': d.get('margin_flg', ''),
                'source': 'jisilu',
            })
        return result

    def get_jisilu_history(self, stock_code: str, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        """
        获取某只转债的历史进度变化

        Args:
            stock_code: 股票代码
            start_date: 起始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD

        Returns:
            历史记录列表
        """
        query = 'SELECT * FROM jisilu_pending_bonds WHERE stock_code = ?'
        params: list = [stock_code]

        if start_date:
            query += ' AND snapshot_date >= ?'
            params.append(start_date)
        if end_date:
            query += ' AND snapshot_date <= ?'
            params.append(end_date)

        query += ' ORDER BY snapshot_date'

        with self._get_conn() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    # ============================================================
    # K 线数据
    # ============================================================

    def fetch_and_save_kline(self, stock_code: str, days: int = 90) -> List[Dict[str, Any]]:
        """
        从东方财富获取日 K 线并缓存（失败时降级到新浪财经）

        Args:
            stock_code: 6位股票代码
            days: 获取天数

        Returns:
            K 线数据列表
        """
        from lib.data_source import EastmoneyAPI, SinaFinanceAPI

        klines = []

        # 尝试东方财富
        em = EastmoneyAPI(timeout=15)
        klines = em.fetch_stock_kline(stock_code, days=days)

        # 降级到新浪财经
        if not klines:
            sina = SinaFinanceAPI(timeout=20)
            prices = sina.fetch_history(stock_code, days=days)
            for date, data in sorted(prices.items()):
                klines.append({
                    'date': date,
                    'open': data['open'],
                    'close': data['close'],
                    'high': data['high'],
                    'low': data['low'],
                    'volume': data['volume'],
                    'amount': 0,
                    'amplitude': 0,
                    'change_pct': 0,
                    'change_amount': 0,
                    'turnover_rate': 0,
                })

        if not klines:
            return []

        with self._get_conn() as conn:
            for k in klines:
                conn.execute('''
                    INSERT OR IGNORE INTO eastmoney_kline
                    (stock_code, trade_date, open, close, high, low, volume, amount,
                     amplitude, change_pct, change_amount, turnover_rate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    stock_code,
                    k['date'],
                    k['open'], k['close'], k['high'], k['low'],
                    k['volume'], k.get('amount', 0),
                    k.get('amplitude', 0), k.get('change_pct', 0),
                    k.get('change_amount', 0), k.get('turnover_rate', 0),
                ))
            conn.commit()

        return klines

    def get_kline_as_dict(self, stock_code: str, days: int = 90) -> Dict[str, Dict[str, float]]:
        """
        获取 K 线数据并转换为 {date: {open, close, ...}} 格式，兼容现有脚本

        Args:
            stock_code: 6位股票代码
            days: 获取天数

        Returns:
            {date: {open, close, high, low, volume, amount, amplitude, change_pct, change_amount, turnover_rate}}
        """
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT * FROM eastmoney_kline
                WHERE stock_code = ?
                ORDER BY trade_date DESC
                LIMIT ?
            ''', (stock_code, days))
            rows = cursor.fetchall()

        if not rows or len(rows) < min(days, 60):
            # 缓存数据不足，从 API 补充
            self.fetch_and_save_kline(stock_code, days=days)
            with self._get_conn() as conn:
                cursor = conn.execute('''
                    SELECT * FROM eastmoney_kline
                    WHERE stock_code = ?
                    ORDER BY trade_date DESC
                    LIMIT ?
                ''', (stock_code, days))
                rows = cursor.fetchall()

        result = {}
        for row in reversed(rows):
            d = dict(row)
            result[d['trade_date']] = {
                'open': d['open'],
                'close': d['close'],
                'high': d['high'],
                'low': d['low'],
                'volume': d['volume'],
                'amount': d['amount'],
                'amplitude': d['amplitude'],
                'change_pct': d['change_pct'],
                'change_amount': d['change_amount'],
                'turnover_rate': d['turnover_rate'],
            }
        return result

    def ensure_kline(self, stock_code: str, days: int = 90) -> List[Dict[str, Any]]:
        """
        缓存不足时自动从 API 补充

        Returns:
            K 线数据列表
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                'SELECT COUNT(*) as cnt FROM eastmoney_kline WHERE stock_code = ?',
                (stock_code,)
            )
            count = cursor.fetchone()['cnt']

        if count < min(days, 60):
            return self.fetch_and_save_kline(stock_code, days=days)

        return self.get_kline_data(stock_code, days=days)

    def get_kline_data(self, stock_code: str, days: int = 90) -> List[Dict[str, Any]]:
        """获取 K 线数据列表"""
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT * FROM eastmoney_kline
                WHERE stock_code = ?
                ORDER BY trade_date DESC
                LIMIT ?
            ''', (stock_code, days))
            return [dict(row) for row in cursor.fetchall()]

    # ============================================================
    # 主力资金流向
    # ============================================================

    def fetch_and_save_fund_flow(self, stock_code: str, days: int = 120) -> List[Dict[str, Any]]:
        """
        从东方财富获取主力流向并缓存

        Args:
            stock_code: 6位股票代码
            days: 获取天数

        Returns:
            主力流向数据列表
        """
        from lib.data_source import EastmoneyAPI

        em = EastmoneyAPI(timeout=15)
        flows = em.fetch_fund_flow(stock_code, days=days)

        if not flows:
            return []

        with self._get_conn() as conn:
            for f in flows:
                conn.execute('''
                    INSERT OR IGNORE INTO eastmoney_fund_flow
                    (stock_code, trade_date, main_net_inflow, main_net_inflow_rate,
                     super_large_net_inflow, large_net_inflow, medium_net_inflow, small_net_inflow)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    stock_code,
                    f['date'],
                    f['main_net_inflow'], f['main_net_inflow_rate'],
                    f['超大单_net_inflow'], f['large_net_inflow'],
                    f['medium_net_inflow'], f['small_net_inflow'],
                ))
            conn.commit()

        return flows

    def get_fund_flow(self, stock_code: str, days: int = 120) -> List[Dict[str, Any]]:
        """
        从缓存读取主力流向

        Args:
            stock_code: 6位股票代码
            days: 获取天数

        Returns:
            主力流向数据列表
        """
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT * FROM eastmoney_fund_flow
                WHERE stock_code = ?
                ORDER BY trade_date DESC
                LIMIT ?
            ''', (stock_code, days))
            rows = cursor.fetchall()

        if len(rows) < min(days, 60):
            self.fetch_and_save_fund_flow(stock_code, days=days)
            cursor = conn.execute('''
                SELECT * FROM eastmoney_fund_flow
                WHERE stock_code = ?
                ORDER BY trade_date DESC
                LIMIT ?
            ''', (stock_code, days))
            rows = cursor.fetchall()

        return [dict(row) for row in reversed(rows)]

    def ensure_fund_flow(self, stock_code: str, days: int = 120) -> List[Dict[str, Any]]:
        """缓存不足时自动从 API 补充"""
        with self._get_conn() as conn:
            cursor = conn.execute(
                'SELECT COUNT(*) as cnt FROM eastmoney_fund_flow WHERE stock_code = ?',
                (stock_code,)
            )
            count = cursor.fetchone()['cnt']

        if count < min(days, 60):
            return self.fetch_and_save_fund_flow(stock_code, days=days)

        return self.get_fund_flow(stock_code, days=days)

    # ============================================================
    # 实时行情快照
    # ============================================================

    def fetch_and_save_realtime_quote(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        获取单只股票的实时行情快照并缓存

        Args:
            stock_code: 6位股票代码

        Returns:
            行情快照字典
        """
        from lib.data_source import EastmoneyAPI

        em = EastmoneyAPI(timeout=15)
        quote = em.fetch_realtime_quote(stock_code)

        if not quote:
            return None

        today = datetime.now().strftime('%Y-%m-%d')

        with self._get_conn() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO eastmoney_realtime_quote
                (stock_code, snapshot_date, price, change_pct, change_amount, open, high, low,
                 volume, amount, volume_ratio, pe_ttm, pb, pe_static,
                 total_market_cap, float_market_cap, eps, net_asset_per_share,
                 roe, gross_margin, debt_ratio, margin_balance, short_balance, total_margin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                stock_code, today,
                quote.get('price', 0), quote.get('change_pct', 0), quote.get('change_amount', 0),
                quote.get('open', 0), quote.get('high', 0), quote.get('low', 0),
                quote.get('volume', 0), quote.get('amount', 0), quote.get('volume_ratio', 0),
                quote.get('pe_ttm', 0), quote.get('pb', 0), quote.get('pe_static', 0),
                quote.get('total_market_cap', 0), quote.get('float_market_cap', 0),
                quote.get('eps', 0), quote.get('net_asset_per_share', 0),
                quote.get('roe', 0), quote.get('gross_margin', 0), quote.get('debt_ratio', 0),
                quote.get('margin_balance', 0), quote.get('short_balance', 0), quote.get('total_margin', 0),
            ))
            conn.commit()

        return quote

    def get_realtime_quote(self, stock_code: str, date: str = None) -> Optional[Dict[str, Any]]:
        """
        从缓存读取行情快照

        Args:
            stock_code: 6位股票代码
            date: 日期，None=最新

        Returns:
            行情快照字典
        """
        query = 'SELECT * FROM eastmoney_realtime_quote WHERE stock_code = ?'
        params: list = [stock_code]

        if date:
            query += ' AND snapshot_date = ?'
            params.append(date)
        else:
            query += ' ORDER BY snapshot_date DESC LIMIT 1'

        with self._get_conn() as conn:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()

        if not row:
            return None

        return dict(row)

    # ============================================================
    # 涨停数据
    # ============================================================

    def fetch_and_save_limit_up(self, trade_date: str = None) -> Dict[str, int]:
        """
        获取某日涨停股池并批量插入数据库

        Args:
            trade_date: 交易日期 YYYY-MM-DD，None=最新

        Returns:
            {total: N, new: N}
        """
        from lib.data_source import EastmoneyAPI

        em = EastmoneyAPI(timeout=15)
        stocks = em.fetch_limit_up_pool(trade_date=trade_date)

        if not stocks:
            return {'total': 0, 'new': 0}

        fetch_date = trade_date or datetime.now().strftime('%Y-%m-%d')
        now = datetime.now().isoformat()

        with self._get_conn() as conn:
            new_count = 0
            for s in stocks:
                cursor = conn.execute(
                    'SELECT id FROM eastmoney_limit_up WHERE stock_code = ? AND trade_date = ?',
                    (s['stock_code'], fetch_date)
                )
                exists = cursor.fetchone()

                conn.execute('''
                    INSERT OR REPLACE INTO eastmoney_limit_up
                    (stock_code, stock_name, trade_date, limit_up_price, change_pct,
                     volume, amount, consecutive_limit_up, seal_amount, seal_ratio, fetch_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    s['stock_code'], s['stock_name'], fetch_date,
                    s['limit_up_price'], s['change_pct'],
                    s['volume'], s['amount'],
                    s.get('consecutive_limit_up', 0),
                    s.get('seal_amount', 0), s.get('seal_ratio', 0),
                    now,
                ))

                if not exists:
                    new_count += 1

            conn.commit()

        stats = {'total': len(stocks), 'new': new_count}
        print(f'💾 涨停数据已保存 | 总数: {stats["total"]}, 新增: {stats["new"]}')
        return stats

    def get_limit_up(self, trade_date: str = None) -> List[Dict[str, Any]]:
        """
        从缓存读取涨停数据

        Args:
            trade_date: 交易日期，None=最新

        Returns:
            涨停股票列表
        """
        with self._get_conn() as conn:
            if trade_date:
                cursor = conn.execute(
                    'SELECT * FROM eastmoney_limit_up WHERE trade_date = ? ORDER BY change_pct DESC',
                    (trade_date,)
                )
            else:
                max_date = conn.execute('SELECT MAX(trade_date) as d FROM eastmoney_limit_up').fetchone()['d']
                cursor = conn.execute(
                    'SELECT * FROM eastmoney_limit_up WHERE trade_date = ? ORDER BY change_pct DESC',
                    (max_date,)
                ) if max_date else conn.execute('SELECT * FROM eastmoney_limit_up ORDER BY trade_date DESC LIMIT 0')
            return [dict(row) for row in cursor.fetchall()]

    def is_stock_limit_up(self, stock_code: str, trade_date: str) -> bool:
        """查询某股票某日是否涨停"""
        with self._get_conn() as conn:
            cursor = conn.execute(
                'SELECT id FROM eastmoney_limit_up WHERE stock_code = ? AND trade_date = ?',
                (stock_code, trade_date)
            )
            return cursor.fetchone() is not None

    # ============================================================
    # 融资融券
    # ============================================================

    def fetch_and_save_margin_trading(self, stock_code: str, days: int = 90) -> List[Dict[str, Any]]:
        """获取融资融券数据并缓存"""
        from lib.data_source import EastmoneyAPI
        em = EastmoneyAPI(timeout=15)
        data = em.fetch_margin_trading(stock_code, days=days)
        if not data:
            return []
        with self._get_conn() as conn:
            for d in data:
                conn.execute('''INSERT OR IGNORE INTO eastmoney_margin_trading
                    (stock_code, trade_date, stock_name, margin_balance, short_volume,
                     total_margin, short_balance, margin_buy_amount, change_pct, balance_change)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''', (
                    stock_code, d['date'], d['stock_name'], d['margin_balance'],
                    d['short_volume'], d['total_margin'], d['short_balance'],
                    d['margin_buy_amount'], d['change_pct'], d['balance_change']))
            conn.commit()
        return data

    def get_margin_data(self, stock_code: str, days: int = 90) -> List[Dict[str, Any]]:
        """获取融资融券数据"""
        with self._get_conn() as conn:
            cursor = conn.execute('''SELECT * FROM eastmoney_margin_trading
                WHERE stock_code = ? ORDER BY trade_date DESC LIMIT ?''', (stock_code, days))
            rows = cursor.fetchall()
        if len(rows) < min(days, 30):
            self.fetch_and_save_margin_trading(stock_code, days=days)
            with self._get_conn() as conn:
                cursor = conn.execute('''SELECT * FROM eastmoney_margin_trading
                    WHERE stock_code = ? ORDER BY trade_date DESC LIMIT ?''', (stock_code, days))
                rows = cursor.fetchall()
        return [dict(row) for row in reversed(rows)]

    # ============================================================
    # 大宗交易
    # ============================================================

    def fetch_and_save_block_trade(self, stock_code: str, days: int = 90) -> List[Dict[str, Any]]:
        """获取大宗交易数据并缓存"""
        from lib.data_source import EastmoneyAPI
        em = EastmoneyAPI(timeout=15)
        data = em.fetch_block_trade(stock_code, days=days)
        if not data:
            return []
        with self._get_conn() as conn:
            for d in data:
                conn.execute('''INSERT OR IGNORE INTO eastmoney_block_trade
                    (stock_code, trade_date, stock_name, deal_price, close_price,
                     premium_ratio, deal_volume, deal_amount, buyer_name, seller_name)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''', (
                    stock_code, d['date'], d['stock_name'], d['deal_price'],
                    d['close_price'], d['premium_ratio'], d['deal_volume'],
                    d['deal_amount'], d['buyer_name'], d['seller_name']))
            conn.commit()
        return data

    def get_block_trade_data(self, stock_code: str, days: int = 90) -> List[Dict[str, Any]]:
        """获取大宗交易数据"""
        with self._get_conn() as conn:
            cursor = conn.execute('''SELECT * FROM eastmoney_block_trade
                WHERE stock_code = ? ORDER BY trade_date DESC LIMIT ?''', (stock_code, days))
            rows = cursor.fetchall()
        if not rows:
            self.fetch_and_save_block_trade(stock_code, days=days)
            with self._get_conn() as conn:
                cursor = conn.execute('''SELECT * FROM eastmoney_block_trade
                    WHERE stock_code = ? ORDER BY trade_date DESC LIMIT ?''', (stock_code, days))
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    # ============================================================
    # 股东户数
    # ============================================================

    def fetch_and_save_holder_count(self, stock_code: str) -> List[Dict[str, Any]]:
        """获取股东户数数据并缓存"""
        from lib.data_source import EastmoneyAPI
        em = EastmoneyAPI(timeout=15)
        data = em.fetch_holder_count(stock_code)
        if not data:
            return []
        with self._get_conn() as conn:
            for d in data:
                conn.execute('''INSERT OR IGNORE INTO eastmoney_holder_num
                    (stock_code, end_date, stock_name, holder_num, prev_holder_num,
                     holder_num_change, holder_num_ratio, interval_change_pct)
                    VALUES (?,?,?,?,?,?,?,?)''', (
                    stock_code, d['end_date'], d['stock_name'], d['holder_num'],
                    d['prev_holder_num'], d['holder_num_change'],
                    d['holder_num_ratio'], d['interval_change_pct']))
            conn.commit()
        return data

    def get_holder_count(self, stock_code: str) -> List[Dict[str, Any]]:
        """获取股东户数数据"""
        with self._get_conn() as conn:
            cursor = conn.execute('''SELECT * FROM eastmoney_holder_num
                WHERE stock_code = ? ORDER BY end_date DESC''', (stock_code,))
            rows = cursor.fetchall()
        if not rows:
            self.fetch_and_save_holder_count(stock_code)
            with self._get_conn() as conn:
                cursor = conn.execute('''SELECT * FROM eastmoney_holder_num
                    WHERE stock_code = ? ORDER BY end_date DESC''', (stock_code,))
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    # ============================================================
    # 机构调研
    # ============================================================

    def fetch_and_save_institutional_research(self, stock_code: str, days: int = 180) -> List[Dict[str, Any]]:
        """获取机构调研数据并缓存"""
        from lib.data_source import EastmoneyAPI
        em = EastmoneyAPI(timeout=15)
        data = em.fetch_institutional_research(stock_code, days=days)
        if not data:
            return []
        with self._get_conn() as conn:
            for d in data:
                conn.execute('''INSERT OR IGNORE INTO eastmoney_institutional_research
                    (stock_code, research_date, stock_name, receive_object, investigators,
                     num, total, survey_type)
                    VALUES (?,?,?,?,?,?,?,?)''', (
                    stock_code, d['date'], d['stock_name'], d['receive_object'],
                    d['investigators'], d['num'], d['total'], d['survey_type']))
            conn.commit()
        return data

    def get_institutional_research(self, stock_code: str, days: int = 180) -> List[Dict[str, Any]]:
        """获取机构调研数据"""
        with self._get_conn() as conn:
            cursor = conn.execute('''SELECT * FROM eastmoney_institutional_research
                WHERE stock_code = ? ORDER BY research_date DESC''', (stock_code,))
            rows = cursor.fetchall()
        if not rows:
            self.fetch_and_save_institutional_research(stock_code, days=days)
            with self._get_conn() as conn:
                cursor = conn.execute('''SELECT * FROM eastmoney_institutional_research
                    WHERE stock_code = ? ORDER BY research_date DESC''', (stock_code,))
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    # ============================================================
    # 北向资金持股
    # ============================================================

    def fetch_and_save_northbound(self, stock_code: str, days: int = 90) -> List[Dict[str, Any]]:
        """获取北向资金持股数据并缓存"""
        from lib.data_source import EastmoneyAPI
        em = EastmoneyAPI(timeout=15)
        data = em.fetch_northbound_holding(stock_code, days=days)
        if not data:
            return []
        with self._get_conn() as conn:
            for d in data:
                conn.execute('''INSERT OR IGNORE INTO eastmoney_northbound
                    (stock_code, trade_date, stock_name, shares, shares_ratio,
                     share_change, market_cap, free_ratio)
                    VALUES (?,?,?,?,?,?,?,?)''', (
                    stock_code, d['trade_date'], d['stock_name'], d['shares'],
                    d['shares_ratio'], d['share_change'], d['market_cap'], d['free_ratio']))
            conn.commit()
        return data

    def get_northbound_data(self, stock_code: str, days: int = 90) -> List[Dict[str, Any]]:
        """获取北向资金持股数据"""
        with self._get_conn() as conn:
            cursor = conn.execute('''SELECT * FROM eastmoney_northbound
                WHERE stock_code = ? ORDER BY trade_date DESC LIMIT ?''', (stock_code, days))
            rows = cursor.fetchall()
        if not rows:
            self.fetch_and_save_northbound(stock_code, days=days)
            with self._get_conn() as conn:
                cursor = conn.execute('''SELECT * FROM eastmoney_northbound
                    WHERE stock_code = ? ORDER BY trade_date DESC LIMIT ?''', (stock_code, days))
                rows = cursor.fetchall()
        return [dict(row) for row in reversed(rows)]

    # ============================================================
    # 便捷方法
    # ============================================================

    def get_stock_data(self, stock_code: str, days: int = 90) -> Dict[str, Any]:
        """
        一键获取股票所有缓存数据

        Returns:
            {klines: dict, fund_flow: list, quote: dict}
        """
        return {
            'klines': self.get_kline_as_dict(stock_code, days=days),
            'fund_flow': self.get_fund_flow(stock_code, days=max(days, 120)),
            'quote': self.get_realtime_quote(stock_code),
        }

    def ensure_all_stock_data(self, stock_code: str, days: int = 90):
        """确保股票所有数据已缓存"""
        self.ensure_kline(stock_code, days=days)
        self.ensure_fund_flow(stock_code, days=max(days, 120))
        self.fetch_and_save_realtime_quote(stock_code)

    def get_stats(self) -> Dict[str, int]:
        """获取数据库统计信息"""
        with self._get_conn() as conn:
            stats = {}
            stats['jisilu_snapshots'] = conn.execute(
                'SELECT COUNT(DISTINCT snapshot_date) FROM jisilu_pending_bonds'
            ).fetchone()[0]
            stats['jisilu_records'] = conn.execute(
                'SELECT COUNT(*) FROM jisilu_pending_bonds'
            ).fetchone()[0]
            stats['kline_records'] = conn.execute(
                'SELECT COUNT(*) FROM eastmoney_kline'
            ).fetchone()[0]
            stats['kline_stocks'] = conn.execute(
                'SELECT COUNT(DISTINCT stock_code) FROM eastmoney_kline'
            ).fetchone()[0]
            stats['fund_flow_records'] = conn.execute(
                'SELECT COUNT(*) FROM eastmoney_fund_flow'
            ).fetchone()[0]
            stats['quote_records'] = conn.execute(
                'SELECT COUNT(*) FROM eastmoney_realtime_quote'
            ).fetchone()[0]
            stats['limit_up_records'] = conn.execute(
                'SELECT COUNT(*) FROM eastmoney_limit_up'
            ).fetchone()[0]
            return stats


# ==================== 全局缓存实例 ====================

cache = BacktestCache()


# ==================== 独立运行入口 ====================

if __name__ == '__main__':
    import sys
    import os

    # 确保可以从项目根目录导入
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_script_dir)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

    c = BacktestCache()

    if '--stats' in sys.argv:
        stats = c.get_stats()
        print('\n📊 缓存数据库统计:')
        print(f'  集思录快照: {stats["jisilu_snapshots"]} 次, {stats["jisilu_records"]} 条记录')
        print(f'  K 线数据: {stats["kline_stocks"]} 只股票, {stats["kline_records"]} 条记录')
        print(f'  主力流向: {stats["fund_flow_records"]} 条记录')
        print(f'  行情快照: {stats["quote_records"]} 条记录')
        print(f'  涨停数据: {stats["limit_up_records"]} 条记录')
        print(f'  数据库大小: {os.path.getsize(c.db_path) / 1024:.1f} KB')
        sys.exit(0)

    if '--snapshot' in sys.argv:
        print('📥 获取集思录快照...')
        stats = c.save_jisilu_snapshot()
        print(f'  完成: {stats}')
        sys.exit(0)

    if '--kline' in sys.argv:
        idx = sys.argv.index('--kline')
        stock = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else '300622'
        days = int(sys.argv[idx + 2]) if idx + 2 < len(sys.argv) else 90
        print(f'📥 获取 {stock} K 线 ({days} 天)...')
        klines = c.ensure_kline(stock, days=days)
        print(f'  完成: {len(klines)} 条记录')
        sys.exit(0)

    if '--fund-flow' in sys.argv:
        idx = sys.argv.index('--fund-flow')
        stock = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else '300622'
        days = int(sys.argv[idx + 2]) if idx + 2 < len(sys.argv) else 120
        print(f'📥 获取 {stock} 主力流向 ({days} 天)...')
        flows = c.ensure_fund_flow(stock, days=days)
        print(f'  完成: {len(flows)} 条记录')
        sys.exit(0)

    if '--quote' in sys.argv:
        idx = sys.argv.index('--quote')
        stock = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else '300622'
        print(f'📥 获取 {stock} 实时行情...')
        quote = c.fetch_and_save_realtime_quote(stock)
        if quote:
            print(f'  价格: {quote["price"]}, PE: {quote["pe_ttm"]}, PB: {quote["pb"]}, ROE: {quote["roe"]}')
        sys.exit(0)

    # 默认: 获取集思录快照 + 显示统计
    print('📥 获取集思录快照...')
    stats = c.save_jisilu_snapshot()

    bonds = c.get_latest_jisilu_data()
    print(f'  最新快照: {len(bonds)} 只待发转债')

    db_stats = c.get_stats()
    print(f'\n📊 数据库统计:')
    print(f'  集思录: {db_stats["jisilu_snapshots"]} 次快照, {db_stats["jisilu_records"]} 条记录')
    print(f'  K 线: {db_stats["kline_stocks"]} 只股票, {db_stats["kline_records"]} 条记录')
    print(f'  主力流向: {db_stats["fund_flow_records"]} 条')
    print(f'  行情快照: {db_stats["quote_records"]} 条')
    print(f'  涨停数据: {db_stats["limit_up_records"]} 条')
