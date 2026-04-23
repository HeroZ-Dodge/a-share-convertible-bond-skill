---
name: a-share-convertible-bond
description: 挖掘 A 股可转债抢权配债的股票买入信号。核心流程：从集思录获取待发转债 → 筛选处于监控窗口的标的 → 检测股价异动和资金布局信号 → 计算配债额度。使用场景：(1) 日常监控潜伏买入信号；(2) 查看待发转债列表；(3) 分析历史节点（同意注册/上市委通过）的股价规律。
---

# A 股可转债买入信号挖掘

## 核心逻辑

抢权配债的收益关键在于**何时买入正股**。统计发现：同意注册前 5 天，股价平均上涨 +4.56%，上涨概率 81.8%，说明有资金可能提前获知消息并布局。

本技能通过监控转债审批进度（交易所受理 → 上市委通过 → 同意注册 → 发行公告），在早期节点发现后持续跟踪股价走势，捕捉资金提前布局的信号。

## 工作流程

```
集思录待发转债 → 筛选上市委通过后的标的 → 持续监控股价/成交量 → 触发信号时提示
```

## 快速开始

### 🎯 日常监控（核心功能）

监控上市委通过后的转债，检测资金提前布局信号。

```bash
# 运行一次
python3 scripts/monitor/monitor_latent_strategy.py --once

# 持续监控（每 60 分钟）
python3 scripts/monitor/monitor_latent_strategy.py

# 查看进化报告
python3 scripts/monitor/monitor_latent_strategy.py --report

# 导出数据
python3 scripts/monitor/monitor_latent_strategy.py --export
```

**监控条件**（满足时触发信号）：
- 时间窗口：上市委通过后 25-55 天
- 股价连续 2 日上涨 >2%
- 股价突破 20 日高点
- 股票质量 B 级及以上（趋势 + 动量 + 成交量 + 波动性综合评估）

详见：[scripts/monitor/README.md](scripts/monitor/README.md)

---

### 📋 查看待发转债

从集思录获取待发转债列表，公告发布前即可发现机会。

```bash
python3 scripts/analyze_pending.py              # 全部
python3 scripts/analyze_pending.py --compact    # 紧凑模式
python3 scripts/analyze_pending.py --limit 5    # 前 5 只
```

---

### 📊 历史节点分析（辅助研究）

分析历史数据，理解各审批节点前后的股价规律：

```bash
# 同意注册后股价变化（不同买入/卖出时点的收益）
python3 scripts/analyze_registration_entry.py

# 同意注册对股价的影响（趋势分析）
python3 scripts/analyze_registration_impact.py

# 同意注册到发行公告期间的股价变化
python3 scripts/analyze_registration_to_announcement.py

# 同意注册前的早期异动信号
python3 scripts/analyze_early_signals.py
```

## 核心功能

### 配债额度计算

```python
from lib.bond_calculator import BondCalculator

calc = BondCalculator(target_bonds=10, bond_price=100)

# 配债额度 = 持股数 × 每股配售额
# 可配张数 = floor(配债额度 / 100)
result = calc.calculate_allocation(
    stock_code='300622',
    shares=1500,
    per_share_amount=1.6457
)
```

### 数据获取

```python
from lib.data_source import BondDataSource

# 自动优先集思录，失败降级东方财富
ds = BondDataSource()
bonds, source = ds.fetch_bonds(limit=10, pending_only=True)
```

### 股票质量评估

```python
from lib.stock_quality import StockQualityEvaluator

evaluator = StockQualityEvaluator()
quality = evaluator.evaluate('300622', prices)
# 返回 A/B/C/D 等级，基于趋势/动量/成交量/波动性
```

## 数据源

| 数据源 | 用途 | 特点 |
|--------|------|------|
| 集思录 | 待发转债 + 审批进度 | 公告发布前即可获取，推荐优先使用 |
| 东方财富 | 已上市转债列表 | 数据完整、更新及时 |
| 新浪财经 | 股票历史价格 | 支持 90 天历史 K 线 |

## 注意事项

1. **时间敏感**：从公告到登记日通常只有 3-5 个交易日
2. **T+1 交收**：T 日买入股票，T+1 日才到账
3. **破发风险**：新债上市可能跌破 100 元发行价
4. **抢权风险**：为配债买入股票可能面临股价下跌
5. **潜伏策略**：前 10 个案例进化效果不明显，需要耐心积累数据

## 目录结构

```
a-share-convertible-bond-skill/
├── SKILL.md                          # 技能定义（本文件）
├── README.md                         # 使用说明
├── monitor_history.json              # 监控历史记录
│
├── data/                             # 本地数据
│   ├── bonds.db                      # SQLite数据库
│   ├── pending_bonds_history.json    # 待发转债历史
│   ├── signals_history.json          # 信号历史
│   └── evolution_stats.json          # 进化统计
│
├── lib/                              # 核心库模块
│   ├── __init__.py
│   ├── data_source.py                # 数据源接口（集思录/东方财富/新浪财经）
│   ├── bond_calculator.py            # 配债计算模块
│   ├── report.py                     # 报告生成模块
│   ├── stock_quality.py              # 股票质量评估
│   ├── signal_tracker.py             # 信号跟踪
│   ├── self_evolution.py             # 自我进化
│   ├── sqlite_database.py            # SQLite数据库
│   └── local_database.py             # 本地数据存储
│
├── scripts/                          # 脚本
│   ├── analyze_pending.py            # 待发转债列表
│   ├── analyze_registration_entry.py # 同意注册入场分析
│   ├── analyze_registration_impact.py# 同意注册影响分析
│   ├── analyze_registration_to_announcement.py  # 注册→公告分析
│   ├── analyze_early_signals.py      # 早期信号分析
│   ├── monitor_history.json          # 监控历史
│   │
│   └── monitor/                      # 监控脚本
│       ├── monitor_latent_strategy.py    # 潜伏策略监控（主脚本）
│       ├── backtest_latent_strategy.py   # 潜伏策略回测
│       ├── README.md                     # 使用说明
│       └── 潜伏策略监控使用说明.md         # 详细文档
│
├── docs/                             # 分析报告
├── reference/                        # 参考资料
│   └── api-docs.md                   # API 文档
│
└── test_stock_quality.py             # 股票质量评估测试
```
