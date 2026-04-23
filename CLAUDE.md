# A 股可转债买入信号挖掘 - CLAUDE.md

## 项目概述

挖掘 A 股可转债"同意注册"前的股价异动信号。通过监控转债审批进度（交易所受理 → 上市委通过 → 同意注册 → 发行公告）+ 股价走势，捕捉资金提前获知消息并布局的信号。

### 核心逻辑

历史统计显示：**同意注册前 5 天，正股平均涨幅 +4.56%，上涨概率 81.8%**

这说明有资金可能提前获知消息并提前布局。项目的核心是在同意注册这一确定性事件前，发现资金异动信号，从而跟随布局。

**注意**: 早期思路"抢权配债"已被否决。实际发现"同意注册前"是更好的时机——审批进度是确定事件，股价在同意注册前异动上涨的概率远高于配债策略。

## 技术栈

- **语言**: Python 3，纯标准库实现（urllib, sqlite3, json），无第三方依赖
- **数据存储**: SQLite (`data/bonds.db`) + JSON 文件 (`data/*.json`)
- **数据源**: 集思录 API（待发转债优先）/ 东方财富 API（降级）/ 新浪财经 API（股价）
- **运行方式**: 独立脚本 + 模块导入

## 架构关键决策

### 双数据库层
- `lib/local_database.py` — JSON 文件存储，用于信号跟踪和进化统计
- `lib/sqlite_database.py` — SQLite 存储，用于待发转债的差异增量更新
- 两者提供**相同接口**（`save_pending_bonds`, `save_signal`, `save_outcome`, `get_signals_history`, `get_outcomes_history`, `update_evolution_stats`, `get_evolution_suggestions`），部分模块依赖抽象接口可互换使用

### 唯一标识约定
- **使用 `stock_code` 作为债券唯一标识**（不是 `bond_code`），因为早期阶段债券没有 `bond_code`
- `sqlite_database.py` 中 `save_pending_bonds` 的 `UNIQUE` 约束仍使用 `(bond_code, fetched_at)`，但查询逻辑使用 `stock_code` 分组
- `bond_code` fallback：`bond.get('bond_code', '') or bond.get('stock_code', '')`

### 数据源降级链
集思录（优先，公告前即可获取）→ 东方财富（降级，已上市转债）→ 返回空列表

### 数据源统一返回格式
`BondDataSource` 对所有数据源进行标准化，统一使用这些字段名：
`bond_code`, `bond_name`, `stock_code`, `stock_name`, `listing_date`, `record_date`, `apply_date`, `apply_code`, `ration_code`, `per_share_amount`, `issue_amount`, `convert_price`, `credit_rating`, `progress`, `progress_full`, `source`

## 模块职责

| 模块 | 职责 | 关键类 |
|------|------|--------|
| `lib/data_source.py` | 三个 API 的封装 + 统一降级 | `JisiluAPI`, `EastmoneyAPI`, `SinaFinanceAPI`, `BondDataSource` |
| `lib/sqlite_database.py` | SQLite 增量存储 + 变更检测 | `SQLiteDatabase` |
| `lib/local_database.py` | JSON 文件存储 + 进化统计 | `LocalDatabase` |
| `lib/fetch_bonds.py` | 集思录数据获取 + 入库通用模块 | `fetch_and_save()` |
| `lib/stock_quality.py` | 股票质量评估 (100 分制，A/B/C/D) | `StockQualityEvaluator` |
| `lib/signal_tracker.py` | 信号跟踪 + 自动结果判定 | `SignalTracker` |
| `lib/self_evolution.py` | 参数自动优化 + 进化报告 | `SelfEvolution` |
| `lib/bond_calculator.py` | 配债额度计算 + 抢权盈亏分析 | `BondCalculator`, `QuequanAnalysis`, `AllocationResult` |
| `lib/report.py` | 报告生成 | `ReportGenerator` |
| `lib/backtest_cache.py` | 回测缓存数据库（集思录快照/K线/主力流向/行情/涨停） | `BacktestCache` |
| `lib/monitor_db.py` | 注册策略监控数据库（注册事件/持仓/每日快照） | `MonitorDB` |

## 脚本说明

| 脚本 | 用途 |
|------|------|
| `scripts/analyze_pending.py` | 从集思录获取待发转债并展示 |
| `scripts/analyze_registration_entry.py` | 同意注册后入场收益分析 |
| `scripts/analyze_registration_impact.py` | 同意注册对股价影响分析 |
| `scripts/analyze_registration_to_announcement.py` | 注册→公告期间收益分析 |
| `scripts/analyze_early_signals.py` | 同意注册前早期异动信号分析 |
| `scripts/monitor/strategy_fixed_window.py` | 固定窗口监控策略 |
| `scripts/monitor/strategy_dynamic_window.py` | 动态窗口监控策略 |
| `scripts/monitor/strategy_mixed.py` | 混合策略（固定+动态） |
| `scripts/monitor_strategy.py` | 注册+3天入场策略每日监控 | `--once` `--status` `--init-backfill` |

**注意**: README 中提到的 `monitor_latent_strategy.py` 和 `backtest_latent_strategy.py` 在当前 `scripts/monitor/` 目录中不存在，实际文件是上述三个策略脚本。

## 股票质量评分体系
总分 100 分，4 个维度：
- **趋势评分** (0-40 分): 均线排列 + 价格位置
- **动量评分** (0-30 分): 5/10/20 日涨跌幅
- **成交量评分** (0-20 分): 量价配合 + 成交量趋势
- **波动性评分** (0-10 分): 年化波动率适中为佳

评级：A(80-100), B(60-79), C(40-59), D(0-39)

## 潜伏策略信号条件
- 时间窗口：上市委通过后 25-55 天（可进化优化）
- 股价连续 2 日上涨 >2%
- 股价突破 20 日高点
- 股票质量 B 级及以上

## 关键数据约定
- 价格数据格式：`{date: {open, close, high, low, volume}}`
- 日期格式：`YYYY-MM-DD`
- 信号类型：`latent`（潜伏策略）, `entry`（入场时机）
- 进化参数存储在 `data/evolved_params.json`

## 回测脚本数据源规则
- 所有回测/分析脚本默认使用 `lib/backtest_cache.py` 的 `BacktestCache` 模块提供的数据
- 不直接在脚本中调用 API 获取历史数据，统一从缓存数据库 `data/backtest_cache.db` 读取
- 使用方式：`from lib.backtest_cache import BacktestCache` → `cache = BacktestCache()` → `cache.get_latest_jisilu_data()` / `cache.get_kline_as_dict()` 等
- 仅在缓存数据不足时，通过 `cache.ensure_kline()` / `cache.ensure_fund_flow()` 等方法自动补充

## 代码规范
- 中文注释/输出为主，代码标识符用英文
- 模块级全局实例：`db = SQLiteDatabase()`, `db = LocalDatabase()`, `tracker = SignalTracker()`, `evolution_engine = SelfEvolution()`
- 脚本通过 `sys.path.insert` 确保项目根目录在路径中，支持独立运行
- 所有文件带 `# -*- coding: utf-8 -*-` 编码声明
- 打印输出使用 emoji 图标（✅, ❌, ⚠️, 📊, 💰 等）增强可读性
