# -*- coding: utf-8 -*-
"""Shared cache bootstrap and sync helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Iterator, Optional


def ensure_jisilu_cache(
    cache,
    fetch_history: Optional[bool] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Refresh the Jisilu cache if needed and return refresh stats.

    If fetch_history is None, history is fetched once when no historical rows exist.
    """
    pending_stats = cache.ensure_jisilu_data_for_today(fetch_history=False, force=force)

    counts = cache.get_jisilu_status_counts()
    has_history = counts.get('OK', 0) > 0
    should_fetch_history = fetch_history if fetch_history is not None else not has_history

    history_stats: Dict[str, Any] = {'refreshed': False, 'total': 0, 'new': 0, 'updated': 0}
    if should_fetch_history and (force or not has_history):
        history_stats = cache.save_jisilu_data(fetch_pending=False, fetch_history=True)
        history_stats = {
            'refreshed': history_stats.get('total', 0) > 0,
            **history_stats,
        }

    return {
        'pending': pending_stats,
        'history': history_stats,
        'counts': counts,
    }


def iter_stock_codes(items: Optional[Iterable[Any]], key: str = 'stock_code') -> Iterator[str]:
    """Yield unique stock codes from strings or dict-like items."""
    seen = set()
    if not items:
        return

    for item in items:
        code = item
        if isinstance(item, dict):
            code = item.get(key)
        code = str(code).strip() if code is not None else ''
        if code and code not in seen:
            seen.add(code)
            yield code


def sync_kline_cache(cache, stock_codes: Iterable[Any], days: int = 1500, title: str = 'BaoStock K 线同步') -> Dict[str, Any]:
    """Sync K-line data for the given stock codes into the local BaoStock cache."""
    today_str = datetime.now().strftime('%Y-%m-%d')
    print(f"\n{'=' * 110}")
    print(f'{title} — {today_str}')
    print(f'{"=" * 110}')

    codes = list(iter_stock_codes(stock_codes))
    if not codes:
        print('  当前没有可同步的股票')
        return {'total': 0, 'success': 0, 'failed': 0, 'before': {}, 'after': {}}

    before = cache.market_db.get_stats()
    success = 0
    failed = 0
    for idx, stock_code in enumerate(codes, 1):
        with cache.market_db._get_conn() as conn:
            before_count = conn.execute(
                'SELECT COUNT(*) FROM stock_daily WHERE stock_code = ?',
                (stock_code,),
            ).fetchone()[0]

        rows = cache.ensure_kline(stock_code, days=days)

        with cache.market_db._get_conn() as conn:
            after_count = conn.execute(
                'SELECT COUNT(*) FROM stock_daily WHERE stock_code = ?',
                (stock_code,),
            ).fetchone()[0]

        if rows:
            success += 1
            delta = max(0, after_count - before_count)
            if delta > 0:
                print(
                    f'  [{idx}/{len(codes)}] {stock_code} -> '
                    f'缓存 {after_count} 条，本次新增 {delta} 条'
                )
            else:
                print(
                    f'  [{idx}/{len(codes)}] {stock_code} -> '
                    f'缓存 {after_count} 条，本次无新增'
                )
        else:
            failed += 1
            print(f'  [{idx}/{len(codes)}] {stock_code} -> 未同步到 K 线')

    after = cache.market_db.get_stats()
    print(f"\n  同步完成: 成功 {success} 只, 失败 {failed} 只")
    print(
        f"  BaoStock 本地库: {after.get('stock_daily_symbols', 0)} 只股票, "
        f"{after.get('stock_daily_records', 0)} 条记录"
    )
    print(f'  数据库路径: {cache.market_db.db_path}')
    return {'total': len(codes), 'success': success, 'failed': failed, 'before': before, 'after': after}


def bootstrap_runtime_cache(
    cache,
    *,
    fetch_history: Optional[bool] = None,
    stock_codes: Optional[Iterable[Any]] = None,
    sync_kline: bool = False,
    days: int = 1500,
    force_jisilu: bool = False,
) -> Dict[str, Any]:
    """Refresh Jisilu and optionally K-line caches using the same shared policy."""
    result: Dict[str, Any] = {
        'jisilu': ensure_jisilu_cache(cache, fetch_history=fetch_history, force=force_jisilu),
        'kline': None,
    }
    if sync_kline and stock_codes is not None:
        result['kline'] = sync_kline_cache(cache, stock_codes, days=days)
    return result
