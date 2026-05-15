# -*- coding: utf-8 -*-
"""
BaoStock 专用股票行情数据库。

目标：
- 只使用 baostock 作为唯一数据源
- 按需加载，不做全市场全量灌库
- 以 (stock_code, trade_date) 为唯一键，避免重复和多源混存
- 提供当前项目需要的 K 线读取接口
"""

import os
import atexit
import sqlite3
import time
import threading
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

_latest_trade_date_cache: Dict[str, Any] = {'time': 0.0, 'date': ''}
_bs_session_lock = threading.Lock()


class BaoStockMarketDB:
    """仅保存 baostock 行情数据的本地 SQLite 存储。"""

    def __init__(
        self,
        db_path: Optional[str] = None,
        adjustflag: str = '3',
        min_initial_days: int = 1500,
    ) -> None:
        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'data', 'baostock_market.db',
            )
        self.db_path = db_path
        self.adjustflag = adjustflag
        self.min_initial_days = min_initial_days
        self._bs = None
        self._bs_logged_in = False
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
        atexit.register(self.close_session)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS stock_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'baostock',
                    adjustflag TEXT NOT NULL DEFAULT '3',
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    preclose REAL,
                    volume REAL,
                    amount REAL,
                    turn REAL,
                    tradestatus TEXT,
                    pctChg REAL,
                    isST TEXT,
                    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, trade_date)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_stock_daily_code_date ON stock_daily(stock_code, trade_date)')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS trade_calendar (
                    trade_date TEXT PRIMARY KEY,
                    is_trading_day INTEGER NOT NULL DEFAULT 1,
                    source TEXT NOT NULL DEFAULT 'baostock',
                    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_trade_calendar_date ON trade_calendar(trade_date)')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sync_state (
                    stock_code TEXT PRIMARY KEY,
                    last_trade_date TEXT,
                    last_fetch_at TEXT,
                    row_count INTEGER DEFAULT 0,
                    adjustflag TEXT NOT NULL DEFAULT '3'
                )
            ''')
            conn.commit()

    @staticmethod
    def _to_baostock_code(stock_code: str) -> str:
        prefix = 'sh' if stock_code.startswith(('6', '9')) else 'sz'
        return f'{prefix}.{stock_code}'

    def _get_bs(self):
        """懒加载并复用同一个 baostock 会话。"""
        with _bs_session_lock:
            if self._bs is not None and self._bs_logged_in:
                return self._bs

            import baostock as bs

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                lg = bs.login()
            if lg.error_code != '0':
                raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")

            self._bs = bs
            self._bs_logged_in = True
            return self._bs

    def close_session(self) -> None:
        """统一关闭 baostock 会话。"""
        with _bs_session_lock:
            if self._bs is not None and self._bs_logged_in:
                try:
                    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                        self._bs.logout()
                except Exception:
                    pass
            self._bs = None
            self._bs_logged_in = False

    def _fetch_trade_dates(self, start_date: str, end_date: str) -> List[str]:
        try:
            bs = self._get_bs()
        except RuntimeError:
            return []
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rs = bs.query_trade_dates(start_date=start_date, end_date=end_date)
        if rs.error_code != '0':
            return []

        result = []
        while rs.next():
            row = rs.get_row_data()
            if len(row) >= 2 and row[1] == '1':
                result.append(row[0])
        return result

    def _fetch_kline(self, stock_code: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        try:
            bs = self._get_bs()
        except RuntimeError:
            return []

        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rs = bs.query_history_k_data_plus(
                self._to_baostock_code(stock_code),
                'date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST',
                start_date=start_date,
                end_date=end_date,
                frequency='d',
                adjustflag=self.adjustflag,
            )
        if rs.error_code != '0':
            return []

        result = []
        fields = list(rs.fields)
        while rs.next():
            raw = dict(zip(fields, rs.get_row_data()))
            try:
                result.append({
                    'trade_date': raw.get('date', ''),
                    'open': float(raw.get('open', 0) or 0),
                    'high': float(raw.get('high', 0) or 0),
                    'low': float(raw.get('low', 0) or 0),
                    'close': float(raw.get('close', 0) or 0),
                    'preclose': float(raw.get('preclose', 0) or 0),
                    'volume': float(raw.get('volume', 0) or 0),
                    'amount': float(raw.get('amount', 0) or 0),
                    'adjustflag': str(raw.get('adjustflag', self.adjustflag) or self.adjustflag),
                    'turn': float(raw.get('turn', 0) or 0),
                    'tradestatus': str(raw.get('tradestatus', '1') or '1'),
                    'pctChg': float(raw.get('pctChg', 0) or 0),
                    'isST': str(raw.get('isST', '0') or '0'),
                })
            except (TypeError, ValueError):
                continue
        return result

    def _store_rows(self, stock_code: str, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0

        trade_dates = [r['trade_date'] for r in rows if r.get('trade_date')]
        with self._get_conn() as conn:
            for row in rows:
                conn.execute(
                    '''
                    INSERT OR REPLACE INTO stock_daily
                    (stock_code, trade_date, source, adjustflag, open, high, low, close,
                     preclose, volume, amount, turn, tradestatus, pctChg, isST, fetched_at)
                    VALUES (?, ?, 'baostock', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ''',
                    (
                        stock_code,
                        row['trade_date'],
                        row.get('adjustflag', self.adjustflag),
                        row.get('open', 0),
                        row.get('high', 0),
                        row.get('low', 0),
                        row.get('close', 0),
                        row.get('preclose', 0),
                        row.get('volume', 0),
                        row.get('amount', 0),
                        row.get('turn', 0),
                        row.get('tradestatus', '1'),
                        row.get('pctChg', 0),
                        row.get('isST', '0'),
                    ),
                )

            for trade_date in trade_dates:
                conn.execute(
                    '''
                    INSERT OR REPLACE INTO trade_calendar
                    (trade_date, is_trading_day, source, fetched_at)
                    VALUES (?, 1, 'baostock', CURRENT_TIMESTAMP)
                    ''',
                    (trade_date,),
                )

            last_trade_date = max(trade_dates) if trade_dates else ''
            conn.execute(
                '''
                INSERT OR REPLACE INTO sync_state
                (stock_code, last_trade_date, last_fetch_at, row_count, adjustflag)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
                ''',
                (stock_code, last_trade_date, len(rows), self.adjustflag),
            )
            conn.commit()

        if trade_dates:
            global _latest_trade_date_cache
            if not _latest_trade_date_cache['date'] or trade_dates[-1] > _latest_trade_date_cache['date']:
                _latest_trade_date_cache = {'time': time.time(), 'date': trade_dates[-1]}
        return len(rows)

    def _get_local_rows(self, stock_code: str) -> List[sqlite3.Row]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                '''
                SELECT *
                FROM stock_daily
                WHERE stock_code = ?
                ORDER BY trade_date DESC, fetched_at DESC
                ''',
                (stock_code,),
            )
            return cursor.fetchall()

    def get_latest_trading_date(self) -> str:
        """返回最新交易日。"""
        global _latest_trade_date_cache
        now = time.time()
        if _latest_trade_date_cache['time'] and now - _latest_trade_date_cache['time'] < 1800:
            return _latest_trade_date_cache['date']

        with self._get_conn() as conn:
            row = conn.execute(
                '''
                SELECT trade_date
                FROM trade_calendar
                WHERE is_trading_day = 1
                ORDER BY trade_date DESC
                LIMIT 1
                '''
            ).fetchone()
        if row and row['trade_date']:
            result = row['trade_date']
            _latest_trade_date_cache = {'time': now, 'date': result}
            return result

        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        trade_dates = self._fetch_trade_dates(start_date, end_date)
        if trade_dates:
            with self._get_conn() as conn:
                for trade_date in trade_dates:
                    conn.execute(
                        '''
                        INSERT OR REPLACE INTO trade_calendar
                        (trade_date, is_trading_day, source, fetched_at)
                        VALUES (?, 1, 'baostock', CURRENT_TIMESTAMP)
                        ''',
                        (trade_date,),
                    )
                conn.commit()
            result = trade_dates[-1]
            _latest_trade_date_cache = {'time': now, 'date': result}
            return result

        _latest_trade_date_cache = {'time': now, 'date': ''}
        return ''

    def ensure_kline(self, stock_code: str, days: int = 90, refresh: bool = True) -> List[Dict[str, Any]]:
        """
        按需确保单只股票的 K 线可用。

        规则：
        - 本地为空时，按需回填一个足够覆盖 days 的历史窗口
        - 本地存在时，只补最新缺口
        - refresh=False 时不主动检查最新交易日，只读取本地并在必要时补初始窗口
        """
        local_rows = self._get_local_rows(stock_code)
        if not local_rows:
            end_date = self.get_latest_trading_date() or datetime.now().strftime('%Y-%m-%d')
            lookback_days = max(days * 3, self.min_initial_days)
            start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
            rows = self._fetch_kline(stock_code, start_date, end_date)
            if rows:
                self._store_rows(stock_code, rows)
                return self.get_kline_data(stock_code, days=days)
            return []

        if refresh:
            latest_trade_date = self.get_latest_trading_date()
            local_latest = local_rows[0]['trade_date']
            if latest_trade_date and local_latest < latest_trade_date:
                start_date = (datetime.fromisoformat(local_latest) + timedelta(days=1)).strftime('%Y-%m-%d')
                rows = self._fetch_kline(stock_code, start_date, latest_trade_date)
                if rows:
                    self._store_rows(stock_code, rows)

        return self.get_kline_data(stock_code, days=days)

    def get_kline_data(self, stock_code: str, days: int = 90) -> List[Dict[str, Any]]:
        """获取 K 线数据列表。"""
        with self._get_conn() as conn:
            cursor = conn.execute(
                '''
                SELECT *
                FROM stock_daily
                WHERE stock_code = ?
                ORDER BY trade_date DESC
                LIMIT ?
                ''',
                (stock_code, days),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_kline_as_dict(
        self,
        stock_code: str,
        days: int = 90,
        as_of_date: Optional[str] = None,
        refresh: bool = True,
    ) -> Dict[str, Dict[str, float]]:
        """
        获取 K 线数据并转换为 {date: {open, close, ...}} 格式。

        当 as_of_date 指向最新交易日时，自动回退到上一完整交易日，
        适合盘中场景。
        """
        rows = self.ensure_kline(stock_code, days=days, refresh=refresh)
        if not rows:
            return {}

        if as_of_date and rows and rows[0]['trade_date'] == as_of_date:
            rows = rows[1:]

        rows = rows[:days] if days > 0 else rows

        result: Dict[str, Dict[str, float]] = {}
        for row in reversed(rows):
            d = dict(row)
            pct_chg = d.get('pctChg', 0) or 0
            turn = d.get('turn', 0) or 0
            result[d['trade_date']] = {
                'open': d.get('open', 0),
                'close': d.get('close', 0),
                'high': d.get('high', 0),
                'low': d.get('low', 0),
                'volume': d.get('volume', 0),
                'amount': d.get('amount', 0),
                'amplitude': 0,
                'change_pct': pct_chg,
                'change_amount': (d.get('close', 0) - d.get('preclose', 0)) if d.get('preclose') else 0,
                'turnover_rate': turn,
                'preclose': d.get('preclose', 0),
                'adjustflag': d.get('adjustflag', self.adjustflag),
                'tradestatus': d.get('tradestatus', '1'),
                'pctChg': pct_chg,
                'turn': turn,
                'isST': d.get('isST', '0'),
            }
        return result

    def get_stock_data(self, stock_code: str, days: int = 90) -> Dict[str, Any]:
        """一键获取股票核心缓存数据。"""
        return {
            'klines': self.get_kline_as_dict(stock_code, days=days),
            'latest_trade_date': self.get_latest_trading_date(),
        }

    def ensure_all_stock_data(self, stock_code: str, days: int = 90) -> None:
        """确保股票日线与交易日历已缓存。"""
        self.ensure_kline(stock_code, days=days)
        self.get_latest_trading_date()

    def get_local_symbols(self) -> List[str]:
        """返回本地已缓存的股票代码列表。"""
        with self._get_conn() as conn:
            rows = conn.execute(
                'SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code'
            ).fetchall()
        return [row[0] for row in rows]

    def get_stats(self) -> Dict[str, int]:
        """数据库统计信息。"""
        with self._get_conn() as conn:
            stats: Dict[str, int] = {}
            stats['stock_daily_records'] = conn.execute('SELECT COUNT(*) FROM stock_daily').fetchone()[0]
            stats['stock_daily_symbols'] = conn.execute('SELECT COUNT(DISTINCT stock_code) FROM stock_daily').fetchone()[0]
            stats['trade_calendar_records'] = conn.execute('SELECT COUNT(*) FROM trade_calendar').fetchone()[0]
            stats['sync_state_records'] = conn.execute('SELECT COUNT(*) FROM sync_state').fetchone()[0]
            return stats
