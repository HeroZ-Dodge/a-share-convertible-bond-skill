# -*- coding: utf-8 -*-
"""
测试 save_pending_bonds 修复：确保所有债券（包括没有 bond_code 的早期阶段债券）都能正确保存
"""

import os
import sys
import tempfile
import sqlite3

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from lib.sqlite_database import SQLiteDatabase


def _make_bond(bond_code, stock_code, bond_name='TestBond', stock_name='TestStock', progress='申购', progress_full='申购'):
    return {
        'bond_code': bond_code,
        'bond_name': bond_name,
        'stock_code': stock_code,
        'stock_name': stock_name,
        'progress': progress,
        'progress_full': progress_full,
        'apply_date': '2026-01-15',
        'record_date': '2026-01-14',
        'apply_code': '301xxx',
        'ration_code': '301xxx',
        'ration': 1.0,
        'amount': 5.0,
        'convert_price': 15.0,
        'rating': 'AA',
        'status': '1',
        'market': '1',
        'record_price': 20.0,
        'first_profit': 100,
    }


def test_all_bonds_saved():
    """测试所有债券（包括无 bond_code 的）都能被保存"""
    db_path = os.path.join(tempfile.mkdtemp(), 'test.db')
    db = SQLiteDatabase(db_path)

    bonds = [
        _make_bond(bond_code='123456', stock_code='300001', progress='申购'),
        _make_bond(bond_code='',    stock_code='300002', progress='同意注册'),  # 早期阶段，无 bond_code
        _make_bond(bond_code='',    stock_code='300003', progress='上市委通过'),  # 早期阶段，无 bond_code
        _make_bond(bond_code='123457', stock_code='300004', progress='申购'),
        _make_bond(bond_code='',    stock_code='300005', progress='交易所受理'),  # 早期阶段，无 bond_code
    ]

    stats = db.save_pending_bonds(bonds, source='jisilu')

    # 验证统计
    total_saved = stats['new'] + stats['changed'] + stats['unchanged']
    assert total_saved == len(bonds), f"预期处理 {len(bonds)} 只，实际处理 {total_saved} 只 (new={stats['new']}, changed={stats['changed']}, unchanged={stats['unchanged']})"
    assert stats['new'] == len(bonds), f"预期新增 {len(bonds)} 只，实际新增 {stats['new']} 只"

    # 验证数据库中确实有所有记录
    conn = sqlite3.connect(db_path)
    cursor = conn.execute('SELECT COUNT(DISTINCT stock_code) FROM pending_bonds')
    distinct_stock_codes = cursor.fetchone()[0]
    cursor = conn.execute('SELECT COUNT(*) FROM pending_bonds')
    total_records = cursor.fetchone()[0]

    assert distinct_stock_codes == len(bonds), f"数据库中 stock_code 去重后应为 {len(bonds)}，实际为 {distinct_stock_codes}"
    assert total_records == len(bonds), f"数据库中记录数应为 {len(bonds)}，实际为 {total_records}"

    # 验证无 bond_code 的债券也有 fallback bond_code
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT stock_code, bond_code FROM pending_bonds WHERE stock_code IN ('300002', '300003', '300005')")
    for row in cursor.fetchall():
        assert row['bond_code'] != '', f"stock_code={row['stock_code']} 的 bond_code 不应为空"
        assert row['bond_code'] == row['stock_code'], f"stock_code={row['stock_code']} 的 bond_code 应 fallback 为 stock_code"

    conn.close()
    print('PASS: test_all_bonds_saved')


def test_no_duplicate_on_second_save():
    """测试重复保存相同数据不会产生重复记录"""
    db_path = os.path.join(tempfile.mkdtemp(), 'test.db')
    db = SQLiteDatabase(db_path)

    bonds = [
        _make_bond(bond_code='123456', stock_code='300001', progress='申购'),
        _make_bond(bond_code='',    stock_code='300002', progress='同意注册'),
        _make_bond(bond_code='',    stock_code='300003', progress='上市委通过'),
    ]

    # 第一次保存
    stats1 = db.save_pending_bonds(bonds, source='jisilu')
    assert stats1['new'] == 3, f"第一次应新增 3 只，实际 {stats1['new']}"

    # 第二次保存相同数据
    stats2 = db.save_pending_bonds(bonds, source='jisilu')
    assert stats2['unchanged'] == 3, f"第二次应全部未变，实际 unchanged={stats2['unchanged']}, new={stats2['new']}, changed={stats2['changed']}"

    # 验证数据库无重复
    conn = sqlite3.connect(db_path)
    cursor = conn.execute('SELECT COUNT(*) FROM pending_bonds')
    total = cursor.fetchone()[0]
    assert total == 3, f"重复保存后记录数应为 3，实际为 {total}"
    conn.close()

    print('PASS: test_no_duplicate_on_second_save')


def test_progress_change_detected():
    """测试能正确检测到进度变化"""
    db_path = os.path.join(tempfile.mkdtemp(), 'test.db')
    db = SQLiteDatabase(db_path)

    bonds_v1 = [
        _make_bond(bond_code='', stock_code='300002', progress='同意注册'),
    ]
    stats1 = db.save_pending_bonds(bonds_v1, source='jisilu')
    assert stats1['new'] == 1

    bonds_v2 = [
        _make_bond(bond_code='', stock_code='300002', progress='上市委通过'),
    ]
    stats2 = db.save_pending_bonds(bonds_v2, source='jisilu')
    assert stats2['changed'] == 1, f"进度变化应被检测到，实际 changed={stats2['changed']}"

    # 验证数据库中有两条记录（变更追踪）
    conn = sqlite3.connect(db_path)
    cursor = conn.execute('SELECT COUNT(*) FROM pending_bonds')
    total = cursor.fetchone()[0]
    assert total == 2, f"进度变化后应有 2 条记录，实际为 {total}"
    conn.close()

    print('PASS: test_progress_change_detected')


def test_mixed_bonds_with_and_without_code():
    """测试混合场景：100 只转债中只有 4 只有 bond_code（模拟真实情况）"""
    db_path = os.path.join(tempfile.mkdtemp(), 'test.db')
    db = SQLiteDatabase(db_path)

    bonds = []
    # 4 只有 bond_code 的（申购等后期阶段）
    for i, code in enumerate(['123001', '123002', '123003', '123004']):
        bonds.append(_make_bond(bond_code=code, stock_code=f'30000{i+1}', progress='申购'))

    # 96 只没有 bond_code 的（早期阶段）
    for i in range(96):
        bonds.append(_make_bond(bond_code='', stock_code=f'300{10+i:03d}', progress='同意注册'))

    assert len(bonds) == 100, f"测试数据应为 100 只，实际 {len(bonds)}"

    stats = db.save_pending_bonds(bonds, source='jisilu')

    # 应该全部处理
    total_processed = stats['new'] + stats['changed'] + stats['unchanged']
    assert total_processed == 100, f"应处理 100 只，实际处理 {total_processed} 只 (new={stats['new']}, changed={stats['changed']}, unchanged={stats['unchanged']})"
    assert stats['new'] == 100, f"应新增 100 只，实际新增 {stats['new']} 只"

    # 验证数据库
    conn = sqlite3.connect(db_path)
    cursor = conn.execute('SELECT COUNT(DISTINCT stock_code) FROM pending_bonds')
    assert cursor.fetchone()[0] == 100, "数据库中应有 100 只不同的债券"

    # 验证没有 bond_code 的 96 只也正确保存了（bond_code fallback 到 stock_code）
    cursor = conn.execute("SELECT COUNT(*) FROM pending_bonds WHERE bond_code = ''")
    empty_bond_code_count = cursor.fetchone()[0]
    assert empty_bond_code_count == 0, f"不应有 bond_code 为空的记录，实际有 {empty_bond_code_count} 条"

    conn.close()
    print('PASS: test_mixed_bonds_with_and_without_code')


def test_no_duplicate_when_bond_code_appears_later():
    """测试场景：第一次保存时 bond_code 为空，第二次保存时 bond_code 有值

    这是真实场景的复现：
    - 4 只债券（300964, 301210, 301611, 603290）既有 bond_code 又有 stock_code
    - 第一次保存时 bond_code 为空，使用 stock_code 作为标识
    - 第二次保存时 bond_code 有值，stock_code 已存在，不应重复插入
    """
    db_path = os.path.join(tempfile.mkdtemp(), 'test.db')
    db = SQLiteDatabase(db_path)

    # 第一次：bond_code 为空
    bonds_v1 = [
        _make_bond(bond_code='', stock_code='300964', progress='申购'),
        _make_bond(bond_code='', stock_code='301210', progress='申购'),
        _make_bond(bond_code='', stock_code='301611', progress='申购'),
        _make_bond(bond_code='', stock_code='603290', progress='申购'),
    ]

    stats1 = db.save_pending_bonds(bonds_v1, source='jisilu')
    assert stats1['new'] == 4, f"第一次应新增 4 只，实际 new={stats1['new']}"

    # 第二次：bond_code 有值（真实场景：数据源后来补充了 bond_code）
    bonds_v2 = [
        _make_bond(bond_code='123001', stock_code='300964', progress='申购'),
        _make_bond(bond_code='123002', stock_code='301210', progress='申购'),
        _make_bond(bond_code='123003', stock_code='301611', progress='申购'),
        _make_bond(bond_code='127790', stock_code='603290', progress='申购'),
    ]

    stats2 = db.save_pending_bonds(bonds_v2, source='jisilu')
    assert stats2['unchanged'] == 4, (
        f"第二次保存相同进度应全部 unchanged，实际 unchanged={stats2['unchanged']}, "
        f"new={stats2['new']}, changed={stats2['changed']}"
    )

    # 验证数据库无重复记录
    conn = sqlite3.connect(db_path)
    cursor = conn.execute('SELECT COUNT(*) FROM pending_bonds')
    total = cursor.fetchone()[0]
    assert total == 4, f"重复保存后记录数应为 4，实际为 {total}"

    cursor = conn.execute('SELECT COUNT(DISTINCT stock_code) FROM pending_bonds')
    distinct = cursor.fetchone()[0]
    assert distinct == 4, f"distinct stock_code 应为 4，实际为 {distinct}"
    conn.close()

    print('PASS: test_no_duplicate_when_bond_code_appears_later')


def test_full_scenario_new_then_identical():
    """完整场景：100 只转债，第一次 new=100，第二次相同数据应为 unchanged=100"""
    db_path = os.path.join(tempfile.mkdtemp(), 'test.db')
    db = SQLiteDatabase(db_path)

    bonds = []
    # 100 只转债混合
    for i in range(100):
        bond_code = f'123{i:03d}' if i < 4 else ''  # 前 4 只有 bond_code
        bonds.append(_make_bond(bond_code=bond_code, stock_code=f'300{i:04d}', progress='申购'))

    stats1 = db.save_pending_bonds(bonds, source='jisilu')
    assert stats1['new'] == 100, f"第一次应新增 100 只，实际 new={stats1['new']}"

    # 第二次保存完全相同的数据
    stats2 = db.save_pending_bonds(bonds, source='jisilu')
    assert stats2['unchanged'] == 100, (
        f"第二次应全部 unchanged，实际 unchanged={stats2['unchanged']}, "
        f"new={stats2['new']}, changed={stats2['changed']}"
    )

    conn = sqlite3.connect(db_path)
    cursor = conn.execute('SELECT COUNT(*) FROM pending_bonds')
    assert cursor.fetchone()[0] == 100, f"记录数应为 100，实际为 {cursor.fetchone()[0]}"
    conn.close()

    print('PASS: test_full_scenario_new_then_identical')


if __name__ == '__main__':
    test_all_bonds_saved()
    test_no_duplicate_on_second_save()
    test_progress_change_detected()
    test_mixed_bonds_with_and_without_code()
    test_no_duplicate_when_bond_code_appears_later()
    test_full_scenario_new_then_identical()
    print('\nAll tests passed!')
