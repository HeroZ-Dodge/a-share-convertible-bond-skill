# -*- coding: utf-8 -*-
"""
集思录待发转债数据获取与入库

通用模块：从集思录 API 获取待发转债数据并保存到本地 SQLite 数据库。

可独立运行，也可被其他脚本 import 调用。

Usage:
    # 独立运行
    python3 lib/fetch_bonds.py
    
    # 指定数量
    python3 lib/fetch_bonds.py --limit 200
    
    # 不保存，只查看
    python3 lib/fetch_bonds.py --dry-run
    
    # 在脚本中调用
    from lib.fetch_bonds import fetch_and_save
    bonds, stats = fetch_and_save(limit=100)
"""

import argparse
import json
import os
import sys
import sqlite3
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 确保可以从项目根目录导入
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from lib.data_source import JisiluAPI


class PendingBondsStore:
    """待发转债轻量存储。"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'data',
                'pending_bonds.db',
            )
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
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
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bond_code ON pending_bonds(bond_code)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_fetched_at ON pending_bonds(fetched_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_snapshot_date ON snapshots(snapshot_date)')
            conn.commit()

    def save_pending_bonds(self, bonds: List[Dict], source: str = 'jisilu') -> Dict[str, int]:
        if not bonds:
            return {'total': 0, 'new': 0, 'changed': 0, 'unchanged': 0}

        fetched_at = datetime.now().isoformat(timespec='seconds')
        snapshot_date = datetime.now().strftime('%Y-%m-%d')
        current_map = {
            b.get('bond_code'): json.dumps(b, ensure_ascii=False, sort_keys=True)
            for b in bonds
            if b.get('bond_code')
        }

        with self._get_conn() as conn:
            rows = conn.execute(
                '''
                SELECT bond_code, bond_name, stock_code, stock_name, progress, progress_full,
                       apply_date, record_date, apply_code, ration_code, ration, amount,
                       convert_price, rating, status, market, record_price, first_profit
                FROM pending_bonds
                WHERE fetched_at = (
                    SELECT fetched_at FROM pending_bonds
                    ORDER BY fetched_at DESC
                    LIMIT 1
                )
                '''
            ).fetchall()
            prev_map = {}
            for row in rows:
                prev_map[row['bond_code']] = json.dumps(dict(row), ensure_ascii=False, sort_keys=True)

            stats = {'total': len(bonds), 'new': 0, 'changed': 0, 'unchanged': 0}
            for b in bonds:
                code = b.get('bond_code')
                if not code:
                    continue
                if code not in prev_map:
                    stats['new'] += 1
                elif prev_map[code] != current_map[code]:
                    stats['changed'] += 1
                else:
                    stats['unchanged'] += 1

                conn.execute(
                    '''
                    INSERT OR REPLACE INTO pending_bonds (
                        bond_code, bond_name, stock_code, stock_name, progress, progress_full,
                        apply_date, record_date, apply_code, ration_code, ration, amount,
                        convert_price, rating, status, market, record_price, first_profit,
                        source, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        b.get('bond_code', ''),
                        b.get('bond_name', ''),
                        b.get('stock_code', ''),
                        b.get('stock_name', ''),
                        b.get('progress', ''),
                        b.get('progress_full', ''),
                        b.get('apply_date', ''),
                        b.get('record_date', ''),
                        b.get('apply_code', ''),
                        b.get('ration_code', ''),
                        b.get('ration', 0),
                        b.get('amount', 0),
                        b.get('convert_price', 0),
                        b.get('rating', ''),
                        b.get('status', ''),
                        b.get('market', ''),
                        b.get('record_price', 0),
                        b.get('first_profit', 0),
                        source,
                        fetched_at,
                    ),
                )

            conn.execute(
                '''
                INSERT OR REPLACE INTO snapshots (
                    snapshot_date, timestamp, source, total_count, changed_count
                ) VALUES (?, ?, ?, ?, ?)
                ''',
                (snapshot_date, fetched_at, source, len(bonds), stats['changed']),
            )
            conn.commit()
            return stats


def fetch_pending_bonds(
    limit: int = 100,
    timeout: int = 30,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> List[Dict]:
    """
    从集思录获取待发转债数据（带重试）
    
    Args:
        limit: 获取数量上限
        timeout: 单次请求超时（秒）
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）
    
    Returns:
        待发转债列表
    """
    jsl = JisiluAPI(timeout=timeout)
    
    for attempt in range(max_retries):
        if attempt > 0:
            print(f'  ⏳ 重试 {attempt}/{max_retries - 1}...')
            time.sleep(retry_delay * attempt)
        
        bonds = jsl.fetch_pending_bonds(limit=limit)
        if bonds:
            return bonds
    
    return []


def fetch_and_save(
    limit: int = 100,
    save: bool = True,
    db_path: Optional[str] = None,
) -> Tuple[List[Dict], Dict]:
    """
    获取待发转债数据并保存到数据库
    
    Args:
        limit: 获取数量上限
        save: 是否保存到数据库
        db_path: 数据库路径（默认使用默认路径）
    
    Returns:
        (bonds, stats) 元组
        - bonds: 待发转债列表
        - stats: 入库统计 {'total': N, 'new': N, 'changed': N, 'unchanged': N}
    """
    print(f'📥 从集思录获取待发转债数据 (limit={limit})...')
    bonds = fetch_pending_bonds(limit=limit)
    
    if not bonds:
        print('❌ 获取失败：集思录 API 超时')
        return [], {'total': 0, 'new': 0, 'changed': 0, 'unchanged': 0}
    
    print(f'✅ 获取到 {len(bonds)} 只转债')
    
    stats = {'total': len(bonds), 'new': 0, 'changed': 0, 'unchanged': 0}
    
    if save:
        db = PendingBondsStore(db_path)
        stats = db.save_pending_bonds(bonds, source='jisilu')
        print(f"💾 已保存到数据库 | 新增: {stats['new']}, 变化: {stats['changed']}, 未变: {stats['unchanged']}")
    
    return bonds, stats


def print_bonds_list(bonds: List[Dict], compact: bool = False):
    """
    打印待发转债列表
    
    Args:
        bonds: 待发转债列表
        compact: 紧凑模式（只显示关键信息）
    """
    if not bonds:
        print('⚠️  无待发转债数据')
        return
    
    print(f'\n📊 待发转债列表 (共 {len(bonds)} 只)')
    print(f'更新时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print()
    
    # 按进度分组
    progress_groups = {}
    for b in bonds:
        progress = b.get('progress', '').split('<')[0].strip() or '未知'
        if progress not in progress_groups:
            progress_groups[progress] = []
        progress_groups[progress].append(b)
    
    # 定义显示顺序
    order = ['申购', '同意注册', '上市委通过', '交易所受理', '股东大会通过', '董事会预案', '未知']
    
    for phase in order:
        group = progress_groups.get(phase, [])
        if not group:
            continue
        
        print(f'  【{phase}】({len(group)} 只)')
        for b in group:
            bond_name = b.get('bond_name') or 'N/A'
            stock_name = b.get('stock_name') or 'N/A'
            stock_code = b.get('stock_code') or ''
            
            if compact:
                print(f'    {stock_name} ({stock_code})')
            else:
                apply_date = b.get('apply_date') or ''
                if apply_date:
                    apply_date = f' - 申购日: {apply_date}'
                print(f'    {bond_name} - {stock_name} ({stock_code}){apply_date}')
        print()


def main():
    parser = argparse.ArgumentParser(
        description='集思录待发转债数据获取与入库',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                  # 获取并保存（默认 100 只）
  %(prog)s --limit 200      # 获取 200 只
  %(prog)s --dry-run        # 只查看，不保存
  %(prog)s --compact        # 紧凑显示模式
  %(prog)s --no-save        # 不保存到数据库
        """
    )
    
    parser.add_argument(
        '--limit', '-n',
        type=int,
        default=100,
        help='获取数量上限 (默认: 100)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='干运行模式：获取数据但不保存'
    )
    
    parser.add_argument(
        '--no-save',
        action='store_true',
        help='不保存到数据库'
    )
    
    parser.add_argument(
        '--compact',
        action='store_true',
        help='紧凑显示模式'
    )
    
    parser.add_argument(
        '--json',
        action='store_true',
        help='输出 JSON 格式'
    )
    
    args = parser.parse_args()
    
    save = not args.dry_run and not args.no_save
    bonds, stats = fetch_and_save(limit=args.limit, save=save)
    
    if args.json:
        import json
        print(json.dumps(bonds, ensure_ascii=False, indent=2))
    else:
        print_bonds_list(bonds, compact=args.compact)
    
    return bonds, stats


if __name__ == '__main__':
    main()
