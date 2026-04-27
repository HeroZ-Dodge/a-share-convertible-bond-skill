# A 股可转债买入信号挖掘

## 项目概述

同意注册可以通过公告

监控转债审批进度 + 股价走势，发现"同意注册"前的资金异动信号，挖掘后续10个交易日内的交易策略。

## 技术栈

- Python 3，纯标准库（urllib, sqlite3, json），无第三方依赖
- 数据源：集思录 → 东方财富 → 空列表（降级链）
- 运行：独立脚本 + 模块导入

## 文件组织规则

### `scripts/` 目录
- **根目录**: 仅 `monitor_multi_strategy.py`（多策略组合监控+回测主入口）
- **`strategies/`**: 已采纳策略的独立脚本（每个策略一个文件，可独立运行）
- **`archive/`**: 历史调试/挖掘/分析脚本（归档，不参与日常运行）
- 新增策略脚本放入 `strategies/`，调试脚本用完移入 `archive/`

### `lib/` 模块
- `data_source.py` — API 封装 + 统一降级
- `sqlite_database.py` — SQLite 增量存储 + 变更检测
- `local_database.py` — JSON 文件存储
- `backtest_cache.py` — 回测缓存数据库（集思录快照/K线/主力流向/行情/涨停）
- `strategies.py` — **已验证策略注册中心**（策略条件的唯一来源）
- 其他：`fetch_bonds.py`, `stock_quality.py`, `signal_tracker.py`, `self_evolution.py`, `bond_calculator.py`, `report.py`, `monitor_db.py`

### 策略管理规则
- 所有策略条件统一定义在 `lib/strategies.py`
- 监控/回测脚本从 `registry` 加载策略，不在脚本内联定义
- 新增策略：先用独立脚本验证 → 通过后在 `lib/strategies.py` 注册一行
- 添加方式：`registry.register(Strategy(key, label, condition_fn, best_exit, sharpe))`
- 禁用策略：`registry.disable(['KEY'])`

### 回测/分析脚本数据源
- 统一使用 `BacktestCache` 从 `data/backtest_cache.db` 读取
- 不直接调 API 获取历史数据，仅在缓存不足时自动补充

## 架构关键约定

- **唯一标识**: 使用 `stock_code`（不是 `bond_code`），早期债券无 `bond_code`
- **BondDataSource 统一字段**: `bond_code`, `bond_name`, `stock_code`, `stock_name`, `listing_date`, `record_date`, `apply_date`, `apply_code`, `ration_code`, `per_share_amount`, `issue_amount`, `convert_price`, `credit_rating`, `progress`, `progress_full`, `source`
- **价格数据格式**: `{date: {open, close, high, low, volume}}`，日期 `YYYY-MM-DD`
- **回测 K 线**: 统一 `days=1500`（约 5.8 年覆盖）
- **find_idx**: 用 `d <= target`（注册日落在周末时映射到上周五，用 `d >= target` 会错到下周）

## 策略挖掘原则

回测数据用最近 50 100 200 条数据 --limit

挖掘策略时，可以探索新的因子，不用受限于目前已有的因子。如果没有你想要的因子数据，主动询问提出需要更多数据的要求。

### 策略核心指标：
胜率、夏普、信号发现概率、平局收益、年化

### 可执行性约束
- **买入信号**：T 日开盘前即可判断。基于 T-1 及更早的收盘数据（价格/成交量/均线）。买入时机不限于 D+1，可以自由选择（如注册日当天、D+2 等），只要信号可执行
- **卖出信号**：T 日收盘后判断，T+1 开盘执行
- **买入窗口**：可在注册后任意交易日买入（D+1 ~ D+N 甚至注册日前），只要信号基于 T-1 及更早数据可判断
- **卖出窗口**：买入后至 D+10 内任意时间卖出
- **关键陷阱**：需要收盘确认的信号（如"当日收涨>1%"），回测时必须用次日开盘买入，验证跳空后仍有效

### 信号频率要求
- **最低信号率**: ≥15%（样本中至少 15% 触发，年均≥10 次）
- **取舍**: 夏普>0.35 且信号率>15% 优于 夏普>0.5 但信号率<10%
- 注册事件是稀有事件（年均约 60 只），过严条件会压缩信号到不实用
- **信号率参考**: deep_pullback(~8%), shallow_pullback(~10%), reversal_end(~17%), broad_momentum(~48%)

### 当前可用因子
| 因子 | 含义 | 来源 |
|------|------|------|
| pre3 | 注册日前3日涨幅 | K线 |
| pre5 | 注册日前5日涨幅 | K线 |
| pre7 | 注册日前7日涨幅 | K线 |
| mom10 | 注册日前10日涨幅 | K线 |
| mom20 | 注册日前20日涨幅 | K线 |
| rc | 注册日涨跌幅 | K线 |
| vol_ratio5 | 注册日量/近5日均量 | K线 |
| vol_ratio3 | 注册日量/近3日均量 | K线 |
| vol_ratio10 | 注册日量/近10日均量 | K线 |
| consec_up | 注册日前连续上涨天数 | K线 |
| consec_down | 注册日前连续下跌天数 | K线 |
| ma5_pct | 价格 vs MA5 偏离% | K线 |
| ma10_pct | 价格 vs MA10 偏离% | K线 |
| ma20_pct | 价格 vs MA20 偏离% | K线 |
| atr14_pct | 14日真实波幅% | K线 |

### 已踩坑
1. **BD 策略向前观察偏差**: 收盘确认信号次日开盘买入夏普 0.00（跳空高开吃光利润）
2. **vol_ratio5 是关键过滤器**: 无缩量条件的策略跨 limit 严重衰减（L=100 sh=+0.81 → 全量 sh=+0.25）
3. **rc>0 代价**: 提升夏普 +0.10~0.15 但样本减半

## 代码规范
- 中文注释/输出，英文标识符
- `# -*- coding: utf-8 -*-` 编码声明
- 脚本通过 `sys.path.insert` 确保项目根目录在路径中
- 使用 emoji 图标（✅, ❌, ⚠️, 📊 等）增强输出可读性
