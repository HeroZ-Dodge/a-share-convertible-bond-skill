# -*- coding: utf-8 -*-
"""
SQLite 数据库模块

使用 SQLite 存储历史数据，支持：
1. 差异更新（只保存变化的数据）
2. 高效查询
3. 数据压缩存储
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple


class SQLiteDatabase:
    """SQLite 数据库管理类"""
    
    def __init__(self, db_path: str = None):
        """
        初始化数据库
        
        Args:
            db_path: 数据库文件路径
        """
        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'data', 'bonds.db'
            )
        
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表"""
        with self._get_conn() as conn:
            # 待发转债表（差异存储）
            conn.execute('''
                CREATE TABLE IF NOT EXISTS pending_bonds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bond_code TEXT NOT NULL,
                    bond_name TEXT,
                    stock_code TEXT,
                    stock_name TEXT,
                    progress TEXT,
                    progress_full TEXT,
                    apply_date TEXT,
                    record_date TEXT,
                    apply_code TEXT,
                    ration_code TEXT,
                    ration REAL,
                    amount REAL,
                    convert_price REAL,
                    rating TEXT,
                    status TEXT,
                    market TEXT,
                    record_price REAL,
                    first_profit REAL,
                    source TEXT,
                    fetched_at TEXT,
                    UNIQUE(bond_code, fetched_at)
                )
            ''')
            
            # 快照表（记录每次获取的快照）
            conn.execute('''
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_date TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    source TEXT,
                    total_count INTEGER,
                    changed_count INTEGER,
                    UNIQUE(snapshot_date)
                )
            ''')
            
            # 信号表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT UNIQUE,
                    bond_code TEXT NOT NULL,
                    bond_name TEXT,
                    stock_code TEXT,
                    signal_type TEXT,
                    signal_date TEXT,
                    tongguo_date TEXT,
                    days_since_tongguo INTEGER,
                    signal_count INTEGER,
                    stock_quality TEXT,
                    created_at TEXT
                )
            ''')
            
            # 结果表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT,
                    bond_code TEXT NOT NULL,
                    bond_name TEXT,
                    stock_code TEXT,
                    signal_date TEXT,
                    signal_type TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    exit_date TEXT,
                    return_value REAL,
                    success INTEGER,
                    hold_days INTEGER,
                    exit_reason TEXT,
                    stock_quality TEXT,
                    days_since_tongguo INTEGER,
                    notes TEXT,
                    created_at TEXT
                )
            ''')
            
            # 创建索引
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bond_code ON pending_bonds(bond_code)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_fetched_at ON pending_bonds(fetched_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_snapshot_date ON snapshots(snapshot_date)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_signal_id ON signals(signal_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_outcome_signal_id ON outcomes(signal_id)')
            
            conn.commit()
    
    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # ==================== 待发转债存储（差异更新） ====================
    
    def save_pending_bonds(self, bonds: List[Dict], source: str = 'jisilu') -> Dict:
        """
        保存待发转债数据（差异更新）
        
        Args:
            bonds: 转债列表
            source: 数据来源
        
        Returns:
            统计信息
        """
        today = datetime.now().strftime('%Y-%m-%d')
        now = datetime.now().isoformat()
        
        stats = {
            'total': len(bonds),
            'new': 0,
            'changed': 0,
            'unchanged': 0,
        }
        
        with self._get_conn() as conn:
            # 获取最新的快照
            cursor = conn.execute(
                'SELECT id FROM snapshots WHERE snapshot_date = ? ORDER BY id DESC LIMIT 1',
                (today,)
            )
            latest_snapshot = cursor.fetchone()
            
            if latest_snapshot:
                # 已有今日快照，获取上次的数据
                latest_id = latest_snapshot['id']
                cursor = conn.execute(
                    'SELECT bond_code, progress, progress_full FROM pending_bonds WHERE id = ?',
                    (latest_id,)
                )
                # 获取所有最新记录
                cursor = conn.execute('''
                    SELECT pb1.bond_code, pb1.progress, pb1.progress_full
                    FROM pending_bonds pb1
                    INNER JOIN (
                        SELECT bond_code, MAX(id) as max_id
                        FROM pending_bonds
                        WHERE id <= ?
                        GROUP BY bond_code
                    ) pb2 ON pb1.bond_code = pb2.bond_code AND pb1.id = pb2.max_id
                ''', (latest_id,))
                
                old_data = {row['bond_code']: {
                    'progress': row['progress'],
                    'progress_full': row['progress_full'],
                } for row in cursor.fetchall()}
            else:
                old_data = {}
            
            # 检查变化
            changed_bonds = []
            
            for bond in bonds:
                bond_code = bond.get('bond_code', '')
                if not bond_code:
                    continue
                
                # 检查是否有变化
                old = old_data.get(bond_code, {})
                new_progress = bond.get('progress', '')
                new_progress_full = bond.get('progress_full', '')
                
                has_changed = (
                    old.get('progress') != new_progress or
                    old.get('progress_full') != new_progress_full
                )
                
                if has_changed or bond_code not in old_data:
                    changed_bonds.append(bond)
                    if bond_code not in old_data:
                        stats['new'] += 1
                    else:
                        stats['changed'] += 1
                else:
                    stats['unchanged'] += 1
            
            # 保存变化的数据
            for bond in changed_bonds:
                bond_code = bond.get('bond_code', '')
                if not bond_code:
                    continue
                
                conn.execute('''
                    INSERT OR REPLACE INTO pending_bonds 
                    (bond_code, bond_name, stock_code, stock_name, progress, progress_full,
                     apply_date, record_date, apply_code, ration_code, ration, amount,
                     convert_price, rating, status, market, record_price, first_profit,
                     source, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    bond_code,
                    bond.get('bond_name', ''),
                    bond.get('stock_code', ''),
                    bond.get('stock_name', ''),
                    bond.get('progress', ''),
                    bond.get('progress_full', ''),
                    bond.get('apply_date', ''),
                    bond.get('record_date', ''),
                    bond.get('apply_code', ''),
                    bond.get('ration_code', ''),
                    bond.get('ration', 0),
                    bond.get('amount', 0),
                    bond.get('convert_price', 0),
                    bond.get('rating', ''),
                    bond.get('status', ''),
                    bond.get('market', ''),
                    bond.get('record_price', 0),
                    bond.get('first_profit', 0),
                    source,
                    now,
                ))
            
            # 创建快照
            if changed_bonds:
                conn.execute('''
                    INSERT OR REPLACE INTO snapshots (snapshot_date, timestamp, source, total_count, changed_count)
                    VALUES (?, ?, ?, ?, ?)
                ''', (today, now, source, len(bonds), len(changed_bonds)))
            elif not latest_snapshot:
                # 第一次获取，也创建快照
                conn.execute('''
                    INSERT OR REPLACE INTO snapshots (snapshot_date, timestamp, source, total_count, changed_count)
                    VALUES (?, ?, ?, ?, ?)
                ''', (today, now, source, len(bonds), 0))
            
            conn.commit()
        
        return stats
    
    def get_bond_progress(self, bond_code: str) -> List[Dict]:
        """
        获取单只转债的进度变化历史
        
        Args:
            bond_code: 转债代码
        
        Returns:
            进度历史记录
        """
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT bond_code, progress, progress_full, fetched_at
                FROM pending_bonds
                WHERE bond_code = ?
                ORDER BY fetched_at
            ''', (bond_code,))
            
            return [{
                'bond_code': row['bond_code'],
                'progress': row['progress'],
                'progress_full': row['progress_full'],
                'fetched_at': row['fetched_at'],
            } for row in cursor.fetchall()]
    
    def get_latest_bonds(self) -> List[Dict]:
        """
        获取最新的转债数据
        
        Returns:
            最新转债列表
        """
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT pb1.*
                FROM pending_bonds pb1
                INNER JOIN (
                    SELECT bond_code, MAX(id) as max_id
                    FROM pending_bonds
                    GROUP BY bond_code
                ) pb2 ON pb1.bond_code = pb2.bond_code AND pb1.id = pb2.max_id
            ''')
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_bonds_by_date(self, date: str) -> List[Dict]:
        """
        获取指定日期的转债数据
        
        Args:
            date: 日期 (YYYY-MM-DD)
        
        Returns:
            转债列表
        """
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT pb1.*
                FROM pending_bonds pb1
                INNER JOIN (
                    SELECT bond_code, MAX(id) as max_id
                    FROM pending_bonds
                    WHERE fetched_at LIKE ?
                    GROUP BY bond_code
                ) pb2 ON pb1.bond_code = pb2.bond_code AND pb1.id = pb2.max_id
            ''', (f'{date}%',))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_snapshots(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """
        获取快照列表
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            快照列表
        """
        with self._get_conn() as conn:
            query = 'SELECT * FROM snapshots WHERE 1=1'
            params = []
            
            if start_date:
                query += ' AND snapshot_date >= ?'
                params.append(start_date)
            
            if end_date:
                query += ' AND snapshot_date <= ?'
                params.append(end_date)
            
            query += ' ORDER BY snapshot_date'
            
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    # ==================== 信号存储 ====================
    
    def save_signal(self, signal: Dict):
        """保存信号"""
        with self._get_conn() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO signals 
                (signal_id, bond_code, bond_name, stock_code, signal_type, signal_date,
                 tongguo_date, days_since_tongguo, signal_count, stock_quality, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                signal.get('signal_id', f"{signal['bond_code']}_{signal.get('date', '')}"),
                signal['bond_code'],
                signal.get('bond_name', ''),
                signal.get('stock_code', ''),
                signal.get('signal_type', ''),
                signal.get('date', ''),
                signal.get('tongguo_date', ''),
                signal.get('days_since_tongguo', 0),
                signal.get('signal_count', 0),
                json.dumps(signal.get('stock_quality', {}), ensure_ascii=False),
                datetime.now().isoformat(),
            ))
            conn.commit()
    
    def get_signals(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """获取信号列表"""
        with self._get_conn() as conn:
            query = 'SELECT * FROM signals WHERE 1=1'
            params = []
            
            if start_date:
                query += ' AND signal_date >= ?'
                params.append(start_date)
            
            if end_date:
                query += ' AND signal_date <= ?'
                params.append(end_date)
            
            query += ' ORDER BY signal_date'
            
            cursor = conn.execute(query, params)
            results = []
            for row in cursor.fetchall():
                d = dict(row)
                if d.get('stock_quality'):
                    d['stock_quality'] = json.loads(d['stock_quality'])
                results.append(d)
            return results
    
    # ==================== 结果存储 ====================
    
    def save_outcome(self, outcome: Dict):
        """保存结果"""
        with self._get_conn() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO outcomes 
                (signal_id, bond_code, bond_name, stock_code, signal_date, signal_type,
                 entry_price, exit_price, exit_date, return_value, success, hold_days,
                 exit_reason, stock_quality, days_since_tongguo, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                outcome.get('signal_id', ''),
                outcome['bond_code'],
                outcome.get('bond_name', ''),
                outcome.get('stock_code', ''),
                outcome.get('signal_date', ''),
                outcome.get('signal_type', ''),
                outcome.get('entry_price', 0),
                outcome.get('exit_price', 0),
                outcome.get('exit_date', ''),
                outcome.get('return', 0),
                1 if outcome.get('success', False) else 0,
                outcome.get('hold_days', 0),
                outcome.get('exit_reason', ''),
                json.dumps(outcome.get('stock_quality', {}), ensure_ascii=False),
                outcome.get('days_since_tongguo', 0),
                outcome.get('notes', ''),
                datetime.now().isoformat(),
            ))
            conn.commit()
    
    def get_outcomes(self, signal_type: str = None) -> List[Dict]:
        """获取结果列表"""
        with self._get_conn() as conn:
            query = 'SELECT * FROM outcomes WHERE 1=1'
            params = []
            
            if signal_type:
                query += ' AND signal_type = ?'
                params.append(signal_type)
            
            query += ' ORDER BY exit_date'
            
            cursor = conn.execute(query, params)
            results = []
            for row in cursor.fetchall():
                d = dict(row)
                if d.get('stock_quality'):
                    d['stock_quality'] = json.loads(d['stock_quality'])
                results.append(d)
            return results
    
    def get_outcomes_history(self, signal_type: str = None) -> List[Dict]:
        """获取结果历史（兼容 LocalDatabase 接口）"""
        return self.get_outcomes(signal_type)
    
    def get_signals_history(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """获取信号历史（兼容 LocalDatabase 接口）"""
        return self.get_signals(start_date, end_date)
    
    # ==================== 统计查询 ====================
    
    def get_stats(self) -> Dict:
        """获取数据库统计信息"""
        with self._get_conn() as conn:
            stats = {}
            
            # 快照统计
            cursor = conn.execute('SELECT COUNT(*) as count FROM snapshots')
            stats['snapshots'] = cursor.fetchone()['count']
            
            # 转债统计
            cursor = conn.execute('SELECT COUNT(DISTINCT bond_code) as count FROM pending_bonds')
            stats['unique_bonds'] = cursor.fetchone()['count']
            
            cursor = conn.execute('SELECT COUNT(*) as count FROM pending_bonds')
            stats['total_records'] = cursor.fetchone()['count']
            
            # 信号统计
            cursor = conn.execute('SELECT COUNT(*) as count FROM signals')
            stats['signals'] = cursor.fetchone()['count']
            
            # 结果统计
            cursor = conn.execute('SELECT COUNT(*) as count FROM outcomes')
            stats['outcomes'] = cursor.fetchone()['count']
            
            # 成功率
            cursor = conn.execute('SELECT COUNT(*) as total, SUM(success) as success FROM outcomes')
            row = cursor.fetchone()
            if row['total'] > 0:
                stats['success_rate'] = row['success'] / row['total'] * 100
            else:
                stats['success_rate'] = 0
            
            # 平均收益
            cursor = conn.execute('SELECT AVG(return_value) as avg_return FROM outcomes')
            row = cursor.fetchone()
            stats['avg_return'] = row['avg_return'] or 0
            
            return stats
    
    def update_evolution_stats(self) -> Dict:
        """更新进化统计（兼容 LocalDatabase 接口）"""
        return self.get_stats()
    
    def get_evolution_suggestions(self) -> List[str]:
        """获取进化建议（兼容 LocalDatabase 接口）"""
        stats = self.get_stats()
        suggestions = []
        
        if stats.get('outcomes', 0) == 0:
            return ['数据不足，需要更多监控案例']
        
        if stats.get('success_rate', 0) > 70:
            suggestions.append(f'总体成功率 {stats["success_rate"]:.1f}%，策略表现优秀！')
        elif stats.get('success_rate', 0) < 50:
            suggestions.append(f'总体成功率 {stats["success_rate"]:.1f}%，建议优化信号条件')
        
        return suggestions
    
    def export_data(self, output_file: str = None) -> str:
        """
        导出数据到 JSON 文件
        
        Args:
            output_file: 输出文件路径
        
        Returns:
            输出文件路径
        """
        if output_file is None:
            output_file = os.path.join(
                os.path.dirname(self.db_path),
                f'export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            )
        
        export_data = {
            'export_time': datetime.now().isoformat(),
            'stats': self.get_stats(),
            'snapshots': self.get_snapshots(),
            'signals': self.get_signals(),
            'outcomes': self.get_outcomes(),
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        print(f'数据已导出到：{output_file}')
        return output_file
    
    def cleanup_old_data(self, days: int = 90):
        """
        清理旧数据（保留指定天数内的数据）
        
        Args:
            days: 保留天数
        """
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        
        with self._get_conn() as conn:
            # 清理旧记录
            cursor = conn.execute(
                'DELETE FROM pending_bonds WHERE fetched_at < ?',
                (cutoff_date,)
            )
            deleted = cursor.rowcount
            
            # 清理旧快照
            conn.execute(
                'DELETE FROM snapshots WHERE snapshot_date < ?',
                ((datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d'),)
            )
            
            conn.commit()
        
        print(f'已清理 {deleted} 条旧记录')
        return deleted


# 全局数据库实例
db = SQLiteDatabase()
