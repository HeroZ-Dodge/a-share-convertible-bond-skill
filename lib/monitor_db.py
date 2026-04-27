# -*- coding: utf-8 -*-
"""
监控数据库模块

管理注册+3天入场策略的完整生命周期：
- 注册事件（同意注册）
- 持仓管理（买入→卖出）
- 每日监控快照

用法:
    from lib.monitor_db import MonitorDB

    db = MonitorDB()
    db.record_registration({...})
    db.create_position({...}, source='real')
    db.execute_buy(position_id, buy_date, buy_price)
    db.execute_sell(position_id, sell_date, sell_price, 'hold_7d')
"""

import os
import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Optional, Any


class MonitorDB:
    """监控数据库管理"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'data', 'monitor.db'
            )
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS registration_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT,
                    bond_code TEXT,
                    bond_name TEXT,
                    registration_date TEXT NOT NULL,
                    tongguo_date TEXT,
                    days_tongguo_to_reg INTEGER,
                    registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, registration_date)
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id TEXT UNIQUE NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT,
                    bond_code TEXT,
                    bond_name TEXT,
                    registration_date TEXT NOT NULL,
                    planned_buy_date TEXT,
                    planned_sell_date TEXT,
                    actual_buy_date TEXT,
                    actual_buy_price REAL,
                    buy_reason TEXT DEFAULT 'registration+3d',
                    stock_quality_rating TEXT,
                    stock_quality_score REAL,
                    actual_sell_date TEXT,
                    actual_sell_price REAL,
                    sell_reason TEXT,
                    hold_days INTEGER,
                    return_pct REAL,
                    success INTEGER,
                    notes TEXT,
                    status TEXT DEFAULT 'scheduled',
                    source TEXT DEFAULT 'real',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS daily_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_date TEXT UNIQUE NOT NULL,
                    total_registered INTEGER,
                    new_registrations INTEGER,
                    buy_signals INTEGER,
                    sell_signals INTEGER,
                    active_positions INTEGER,
                    closed_positions INTEGER,
                    data TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.execute('CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_positions_stock ON positions(stock_code)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_positions_planned_buy ON positions(planned_buy_date)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_positions_planned_sell ON positions(planned_sell_date)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_reg_date ON registration_events(registration_date)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_positions_source ON positions(source)')

            conn.commit()

        # 迁移旧表：如果缺少 source 字段则添加
        self._migrate_add_source_column()

    def _migrate_add_source_column(self):
        with self._get_conn() as conn:
            columns = conn.execute('PRAGMA table_info(positions)').fetchall()
            has_source = any(col['name'] == 'source' for col in columns)
            if not has_source:
                conn.execute('ALTER TABLE positions ADD COLUMN source TEXT DEFAULT \'real\'')
                # 把已有的旧数据标记为 backfill
                conn.execute('''
                    UPDATE positions SET source = 'backfill'
                    WHERE source IS NULL OR source = ''
                ''')
                conn.commit()

    # ============================================================
    # 注册事件
    # ============================================================

    def record_registration(self, event: Dict) -> bool:
        """
        记录注册事件

        Args:
            event: {stock_code, stock_name, bond_code, bond_name,
                    registration_date, tongguo_date, days_tongguo_to_reg}

        Returns:
            True if new registration (not duplicate)
        """
        with self._get_conn() as conn:
            try:
                conn.execute('''
                    INSERT INTO registration_events
                    (stock_code, stock_name, bond_code, bond_name,
                     registration_date, tongguo_date, days_tongguo_to_reg)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    event.get('stock_code', ''),
                    event.get('stock_name', ''),
                    event.get('bond_code', ''),
                    event.get('bond_name', ''),
                    event.get('registration_date', ''),
                    event.get('tongguo_date', ''),
                    event.get('days_tongguo_to_reg'),
                ))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_registration_events(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """查询注册事件，支持日期范围过滤"""
        with self._get_conn() as conn:
            query = 'SELECT * FROM registration_events WHERE 1=1'
            params = []
            if start_date:
                query += ' AND registration_date >= ?'
                params.append(start_date)
            if end_date:
                query += ' AND registration_date <= ?'
                params.append(end_date)
            query += ' ORDER BY registration_date DESC'
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_registration_by_stock(self, stock_code: str) -> Optional[Dict]:
        """获取某只股票最新的注册事件"""
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT * FROM registration_events
                WHERE stock_code = ?
                ORDER BY registration_date DESC
                LIMIT 1
            ''', (stock_code,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # ============================================================
    # 持仓管理
    # ============================================================

    def create_position(self, position: Dict, source: str = 'real') -> str:
        """
        创建新的持仓

        Args:
            position: {position_id, stock_code, stock_name, bond_code, bond_name,
                       registration_date, planned_buy_date, planned_sell_date}
            source: 'real'（真实监控）或 'backfill'（历史回填）

        Returns:
            position_id
        """
        position_id = position['position_id']
        with self._get_conn() as conn:
            try:
                conn.execute('''
                    INSERT INTO positions
                    (position_id, stock_code, stock_name, bond_code, bond_name,
                     registration_date, planned_buy_date, planned_sell_date, status, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)
                ''', (
                    position_id,
                    position.get('stock_code', ''),
                    position.get('stock_name', ''),
                    position.get('bond_code', ''),
                    position.get('bond_name', ''),
                    position.get('registration_date', ''),
                    position.get('planned_buy_date', ''),
                    position.get('planned_sell_date', ''),
                    source,
                ))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
        return position_id

    def get_positions_due_to_buy(self, trade_date: str) -> List[Dict]:
        """获取计划买入日期 <= trade_date 的 scheduled 持仓（只查 real）"""
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT * FROM positions
                WHERE status = 'scheduled'
                  AND source = 'real'
                  AND planned_buy_date <= ?
                ORDER BY planned_buy_date
            ''', (trade_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_positions_due_to_sell(self, trade_date: str) -> List[Dict]:
        """获取计划卖出日期 <= trade_date 的 active 持仓"""
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT * FROM positions
                WHERE status = 'active'
                  AND source = 'real'
                  AND planned_sell_date <= ?
                ORDER BY planned_sell_date
            ''', (trade_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_active_positions(self) -> List[Dict]:
        """获取所有 active 持仓（只查 real）"""
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT * FROM positions
                WHERE status = 'active'
                  AND source = 'real'
                ORDER BY actual_buy_date
            ''')
            return [dict(row) for row in cursor.fetchall()]

    def get_scheduled_positions(self) -> List[Dict]:
        """获取所有 scheduled 持仓（只查 real）"""
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT * FROM positions
                WHERE status = 'scheduled'
                  AND source = 'real'
                ORDER BY planned_buy_date
            ''')
            return [dict(row) for row in cursor.fetchall()]

    def get_backfill_positions(self) -> List[Dict]:
        """获取 backfill 持仓（用于显示）"""
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT * FROM positions
                WHERE source = 'backfill'
                ORDER BY registration_date
            ''')
            return [dict(row) for row in cursor.fetchall()]

    def execute_buy(self, position_id: str, buy_date: str, buy_price: float,
                    quality_rating: str = None, quality_score: float = None) -> None:
        """执行买入，将 scheduled → active"""
        with self._get_conn() as conn:
            conn.execute('''
                UPDATE positions SET
                    actual_buy_date = ?,
                    actual_buy_price = ?,
                    stock_quality_rating = ?,
                    stock_quality_score = ?,
                    status = 'active',
                    updated_at = ?
                WHERE position_id = ?
            ''', (buy_date, buy_price, quality_rating, quality_score,
                  datetime.now().isoformat(), position_id))
            conn.commit()

    def execute_sell(self, position_id: str, sell_date: str, sell_price: float,
                     sell_reason: str, notes: str = '') -> Dict:
        """
        执行卖出，计算收益
        Returns: 更新后的持仓数据
        """
        pos = self.get_position(position_id)
        if not pos:
            raise ValueError(f'Position not found: {position_id}')

        buy_price = pos['actual_buy_price']
        if buy_price and buy_price > 0:
            return_pct = ((sell_price - buy_price) / buy_price) * 100
        else:
            return_pct = 0

        success = 1 if return_pct > 0 else 0
        hold_days = pos['hold_days'] or 0
        if pos['actual_buy_date'] and sell_date:
            try:
                buy_dt = datetime.strptime(pos['actual_buy_date'], '%Y-%m-%d')
                sell_dt = datetime.strptime(sell_date, '%Y-%m-%d')
                hold_days = (sell_dt - buy_dt).days
            except ValueError:
                pass

        with self._get_conn() as conn:
            conn.execute('''
                UPDATE positions SET
                    actual_sell_date = ?,
                    actual_sell_price = ?,
                    sell_reason = ?,
                    hold_days = ?,
                    return_pct = ?,
                    success = ?,
                    notes = ?,
                    status = 'closed',
                    updated_at = ?
                WHERE position_id = ?
            ''', (sell_date, sell_price, sell_reason, hold_days, return_pct,
                  success, notes, datetime.now().isoformat(), position_id))
            conn.commit()

        return self.get_position(position_id)

    def mark_missed(self, position_id: str, reason: str) -> None:
        """标记持仓为 missed（如质量过滤未通过）"""
        with self._get_conn() as conn:
            conn.execute('''
                UPDATE positions SET
                    status = 'missed',
                    notes = ?,
                    updated_at = ?
                WHERE position_id = ?
            ''', (reason, datetime.now().isoformat(), position_id))
            conn.commit()

    def get_position(self, position_id: str) -> Optional[Dict]:
        """获取单个持仓"""
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT * FROM positions WHERE position_id = ?
            ''', (position_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_closed_positions(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """获取已平仓持仓（只查 real）"""
        with self._get_conn() as conn:
            query = '''SELECT * FROM positions
                       WHERE status = 'closed' AND source = 'real' '''
            params = []
            if start_date:
                query += ' AND actual_sell_date >= ?'
                params.append(start_date)
            if end_date:
                query += ' AND actual_sell_date <= ?'
                params.append(end_date)
            query += ' ORDER BY actual_sell_date DESC'
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_position_stats(self) -> Dict:
        """
        计算已平仓持仓的统计信息（只统计 source='real' 的真实数据）
        """
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT
                    COUNT(*) as total,
                    COALESCE(SUM(success), 0) as wins,
                    AVG(return_pct) as avg_return,
                    MAX(return_pct) as best,
                    MIN(return_pct) as worst,
                    AVG(hold_days) as avg_hold_days
                FROM positions
                WHERE status = 'closed'
                  AND source = 'real'
                  AND return_pct IS NOT NULL
            ''')
            row = cursor.fetchone()
            if not row or row['total'] == 0:
                return {
                    'total': 0, 'wins': 0, 'losses': 0,
                    'win_rate': 0, 'avg_return': 0,
                    'best': 0, 'worst': 0, 'avg_hold_days': 0,
                }
            total = row['total']
            wins = row['wins'] or 0
            return {
                'total': total,
                'wins': wins,
                'losses': total - wins,
                'win_rate': (wins / total * 100) if total > 0 else 0,
                'avg_return': row['avg_return'] or 0,
                'best': row['best'] or 0,
                'worst': row['worst'] or 0,
                'avg_hold_days': row['avg_hold_days'] or 0,
            }

    # ============================================================
    # 每日快照
    # ============================================================

    def save_daily_snapshot(self, snapshot: Dict) -> None:
        """保存每日监控快照"""
        with self._get_conn() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO daily_snapshots
                (snapshot_date, total_registered, new_registrations,
                 buy_signals, sell_signals, active_positions,
                 closed_positions, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                snapshot.get('snapshot_date', ''),
                snapshot.get('total_registered', 0),
                snapshot.get('new_registrations', 0),
                snapshot.get('buy_signals', 0),
                snapshot.get('sell_signals', 0),
                snapshot.get('active_positions', 0),
                snapshot.get('closed_positions', 0),
                json.dumps(snapshot.get('data', {}), ensure_ascii=False),
            ))
            conn.commit()

    def get_daily_snapshots(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """查询每日快照"""
        with self._get_conn() as conn:
            query = 'SELECT * FROM daily_snapshots WHERE 1=1'
            params = []
            if start_date:
                query += ' AND snapshot_date >= ?'
                params.append(start_date)
            if end_date:
                query += ' AND snapshot_date <= ?'
                params.append(end_date)
            query += ' ORDER BY snapshot_date DESC'
            cursor = conn.execute(query, params)
            results = []
            for row in cursor.fetchall():
                d = dict(row)
                if d.get('data'):
                    d['data'] = json.loads(d['data'])
                results.append(d)
            return results

    def get_latest_snapshot(self) -> Optional[Dict]:
        """获取最新快照"""
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT * FROM daily_snapshots
                ORDER BY snapshot_date DESC LIMIT 1
            ''')
            row = cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get('data'):
                d['data'] = json.loads(d['data'])
            return d

    # ============================================================
    # 工具方法
    # ============================================================

    def get_all_monitoring_data(self) -> Dict:
        """获取所有监控数据（用于报告生成）"""
        return {
            'registrations': self.get_registration_events(),
            'scheduled': self.get_scheduled_positions(),
            'active': self.get_active_positions(),
            'closed': self.get_closed_positions(),
            'backfill': self.get_backfill_positions(),
            'stats': self.get_position_stats(),
            'latest_snapshot': self.get_latest_snapshot(),
        }

    def export_to_json(self, output_path: str = None) -> str:
        """导出数据到 JSON 文件"""
        if output_path is None:
            output_path = os.path.join(
                os.path.dirname(self.db_path),
                f'monitor_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            )
        data = self.get_all_monitoring_data()
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return output_path

    def reset_backfill_data(self) -> Dict:
        """
        清理所有 backfill 数据（注册事件 + 持仓），为重新回填做准备

        Returns:
            {registrations_deleted, positions_deleted}
        """
        with self._get_conn() as conn:
            r1 = conn.execute(
                "DELETE FROM registration_events WHERE id IN ("
                "  SELECT re.id FROM registration_events re "
                "  LEFT JOIN positions p ON re.stock_code = p.stock_code "
                "     AND re.registration_date = p.registration_date "
                "  WHERE p.source = 'backfill' OR p.id IS NULL"
                ")"
            ).rowcount
            r2 = conn.execute(
                "DELETE FROM positions WHERE source = 'backfill'"
            ).rowcount
            conn.commit()
            return {
                'registrations_deleted': r1,
                'positions_deleted': r2,
            }


# 全局实例
monitor_db = MonitorDB()
