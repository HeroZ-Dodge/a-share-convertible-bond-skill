---
name: a-share-convertible-bond
description: 跟踪 A 股可转债新债发行，计算配债额度，分析抢权配债收益，监控潜伏策略信号。使用场景：(1) 查看待发转债列表；(2) 计算配债额度和所需资金；(3) 历史收益分析（上帝视角）；(4) 潜伏策略监控（捕捉消息泄露信号）。
---

# A 股可转债分析技能

本技能用于跟踪 A 股市场可转债新债发行信息，进行抢权配债分析和潜伏策略监控。

## 快速开始

### 🎯 潜伏策略监控（主监控脚本）

监控上市委通过后的转债，捕捉资金提前布局信号。

```bash
# 运行一次（自动保存数据 + 信号跟踪）
python scripts/monitor/monitor_latent_strategy.py --once

# 持续监控（每 60 分钟）
python scripts/monitor/monitor_latent_strategy.py

# 查看进化报告
python scripts/monitor/monitor_latent_strategy.py --report

# 导出数据
python scripts/monitor/monitor_latent_strategy.py --export
```

**核心逻辑**：统计显示同意注册前 5 天平均涨幅 +4.56%，上涨概率 81.8%，说明有资金可能提前获知消息布局。监控信号包括：
- 时间窗口：上市委通过后 25-55 天
- 股价连续 2 日上涨 >2%
- 股价突破 20 日高点
- 股票质量 B 级及以上

详见：[scripts/monitor/README.md](scripts/monitor/README.md)

---

### 📋 待发转债列表（公告前即可获取）

从集思录获取待发转债信息，在公告发布前发现配债机会。

```bash
# 查看待发转债
python scripts/analyze_pending.py

# 紧凑摘要模式（推荐）
python scripts/analyze_pending.py --compact

# 查看前 5 只
python scripts/analyze_pending.py --limit 5

# 输出 JSON 格式
python scripts/analyze_pending.py --format json
```

---

### 📊 抢权配债历史收益分析（上帝视角）

分析已上市转债的抢权配债完整盈亏。

```bash
# 完整报告（默认 2026 年全部）
python scripts/analyze_quequan_profit.py

# 紧凑摘要
python scripts/analyze_quequan_profit.py --compact

# 分析前 5 只
python scripts/analyze_quequan_profit.py --limit 5

# 分析指定年份
python scripts/analyze_quequan_profit.py --year 2025

# 离线测试（使用内置数据）
python scripts/analyze_quequan_profit.py --offline
```

---

### 📦 紧凑输出模式

适合在聊天界面直接显示完整报告。

```bash
python scripts/analyze_compact.py              # 2026 年全部
python scripts/analyze_compact.py --limit 5    # 最近 5 只
python scripts/analyze_compact.py --offline    # 离线测试
```

---

### 🔬 其他分析脚本（按需使用）

```bash
# 同意注册后股价变化分析
python scripts/analyze_registration_entry.py

# 同意注册对股价的影响
python scripts/analyze_registration_impact.py

# 同意注册到发行公告期间的股价变化
python scripts/analyze_registration_to_announcement.py

# T 日（股权登记日）卖出策略分析
python scripts/analyze_t_day_exit.py

# 同意注册前股价异动分析（早期信号）
python scripts/analyze_early_signals.py
```

## 核心功能

### 配债额度计算

```python
from lib.bond_calculator import BondCalculator

calc = BondCalculator(target_bonds=10, bond_price=100)

# 公式：配债额度 = 持股数 × 每股配售额
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

#### 各数据源

```python
from lib.data_source import JisiluAPI, EastmoneyAPI, SinaFinanceAPI

# 待发转债（集思录 - 公告前即可获取）
jsl = JisiluAPI()
pending_bonds = jsl.fetch_pending_bonds(limit=10)

# 已上市转债列表（东方财富）
em = EastmoneyAPI()
bonds = em.fetch_listed_bonds(limit=10)

# 股票历史价格（新浪财经）
sina = SinaFinanceAPI()
prices = sina.fetch_history('300622', days=90)
```

## 配债规则

**核心规则：**
- 每股配售额因转债而异（0.98 ~ 8.55 元/股）
- 配债额度 = 持股数 × 每股配售额
- 可配张数 = floor(配债额度 / 100)
- 必须在股权登记日前 1 个交易日持有股票

## 数据源

| 数据源 | 用途 | 特点 |
|--------|------|------|
| 集思录 | 待发转债 | 公告发布前即可获取，推荐优先使用 |
| 东方财富 | 已上市转债列表 | 数据完整、更新及时 |
| 新浪财经 | 股票历史价格 | 支持 90 天历史 K 线 |

## 时间定义

| 时点 | 说明 |
|------|------|
| T-3 | 股权登记日前 3 个交易日 |
| T-2 | 股权登记日前 2 个交易日 |
| T-1 | 股权登记日前 1 个交易日（最后买入时机） |
| T | 股权登记日 |
| T+1 | 股权登记日后 1 个交易日（卖出时机） |

## 注意事项

1. **时间敏感**：从公告到登记日通常只有 3-5 个交易日
2. **T+1 交收**：T 日买入股票，T+1 日才到账
3. **配债成本**：根据每股配售额动态计算，非固定值
4. **破发风险**：新债上市可能跌破 100 元发行价
5. **抢权风险**：为配债买入股票可能面临股价下跌

## 目录结构

```
a-share-convertible-bond-skill/
├── SKILL.md                          # 技能定义（本文件）
├── monitor_history.json              # 监控历史记录
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
│   ├── analyze_pending.py            # 待发转债分析
│   ├── analyze_quequan_profit.py     # 抢权配债收益分析
│   ├── analyze_compact.py            # 紧凑输出
│   ├── analyze_registration_entry.py # 同意注册入场分析
│   ├── analyze_registration_impact.py# 同意注册影响分析
│   ├── analyze_registration_to_announcement.py  # 注册→公告分析
│   ├── analyze_t_day_exit.py         # T 日卖出策略
│   ├── analyze_early_signals.py      # 早期信号分析
│   │
│   └── monitor/                      # 监控脚本
│       ├── monitor_latent_strategy.py    # 潜伏策略监控（主脚本）
│       ├── backtest_latent_strategy.py   # 潜伏策略回测
│       ├── README.md                     # 使用说明
│       └── 潜伏策略监控使用说明.md         # 详细文档
│
├── docs/                             # 分析报告
│   ├── 策略综合分析与推荐.md
│   ├── 可转债抢权配债分析报告_2025-2026.md
│   ├── 可转债抢权配债分析_T日卖出策略_2025-2026.md
│   ├── 上帝视角回测_同意注册前后策略对比.md
│   ├── 最优策略回测报告_上市委通过监控.md
│   ├── 可转债同意注册前提前布局策略.md
│   ├── 可转债同意注册后股价变化分析_2025-2026.md
│   ├── 可转债上市委通过后股价变化分析_2025-2026.md
│   ├── 潜伏策略_消息泄露信号挖掘.md
│   ├── 潜伏策略自我进化功能总结.md
│   ├── 潜伏策略监控优化总结.md
│   ├── 入场监控脚本整理.md
│   ├── 信号跟踪系统设计.md
│   ├── SQLite数据库迁移总结.md
│   ├── 潜伏策略文件整理.md
│   ├── 文件整理总结.md
│   └── 目录结构说明.md
│
└── reference/                        # 参考资料
    └── bond-rules.md                 # 配债规则
```
