#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动同步集思录历史数据到本地缓存。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.backtest_cache import BacktestCache


def main() -> None:
    cache = BacktestCache()
    print("📥 开始同步集思录历史数据 (history=Y)...")
    stats = cache.save_jisilu_data(fetch_pending=False, fetch_history=True)
    print(
        "✅ 同步完成: "
        f"total={stats.get('total', 0)}, "
        f"new={stats.get('new', 0)}, "
        f"updated={stats.get('updated', 0)}"
    )

    status_counts = cache.get_jisilu_status_counts()
    print(f"📊 status_cd 统计: {status_counts}")
    print(f"📦 数据库: {cache.db_path}")


if __name__ == '__main__':
    main()
