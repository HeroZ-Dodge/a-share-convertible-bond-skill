# A 股可转债买入信号挖掘

挖掘可转债抢权配债的正股买入时机。通过监控转债审批进度（交易所受理 → 上市委通过 → 同意注册 → 发行公告），在早期节点发现后持续跟踪股价走势，捕捉资金提前布局的信号。

## 目录结构

```
a-share-convertible-bond-skill/
├── README.md                        # 本文档
├── SKILL.md                         # AgentSkill 定义
├── monitor_history.json             # 监控历史记录
│
├── data/                            # 本地数据
│   ├── bonds.db
│   ├── pending_bonds_history.json
│   ├── signals_history.json
│   └── evolution_stats.json
│
├── lib/                             # 核心模块
│   ├── __init__.py
│   ├── data_source.py               # 数据源接口（集思录/东方财富/新浪财经）
│   ├── bond_calculator.py           # 配债计算
│   ├── report.py                    # 报告生成
│   ├── stock_quality.py             # 股票质量评估
│   ├── signal_tracker.py            # 信号跟踪
│   ├── self_evolution.py            # 自我进化
│   ├── sqlite_database.py           # SQLite数据库
│   └── local_database.py            # 本地数据存储
│
├── scripts/                         # 脚本
│   ├── analyze_pending.py           # 待发转债列表
│   ├── analyze_registration_entry.py
│   ├── analyze_registration_impact.py
│   ├── analyze_registration_to_announcement.py
│   ├── analyze_early_signals.py
│   ├── monitor_history.json
│   │
│   └── monitor/                     # 监控脚本
│       ├── monitor_latent_strategy.py   # 潜伏策略监控
│       ├── backtest_latent_strategy.py  # 潜伏策略回测
│       ├── README.md                    # 使用说明
│       └── 潜伏策略监控使用说明.md
│
├── docs/                            # 分析报告
├── reference/                       # 参考资料
│   └── api-docs.md
│
└── test_stock_quality.py            # 股票质量评估测试
```

## 快速开始

### 1. 潜伏策略监控（核心功能）

监控上市委通过后的转债，检测资金提前布局信号。

**核心逻辑**：统计显示同意注册前 5 天平均涨幅 +4.56%，上涨概率 81.8%，说明有资金可能提前获知消息布局。

```bash
# 运行一次
python3 scripts/monitor/monitor_latent_strategy.py --once

# 持续监控（每 60 分钟）
python3 scripts/monitor/monitor_latent_strategy.py

# 查看进化报告
python3 scripts/monitor/monitor_latent_strategy.py --report
```

触发信号的条件：
- 时间窗口：上市委通过后 25-55 天
- 股价连续 2 日上涨 >2%
- 股价突破 20 日高点
- 股票质量 B 级及以上

详见：[scripts/monitor/README.md](scripts/monitor/README.md)

### 2. 查看待发转债

从集思录获取待发转债列表，公告发布前即可发现机会：

```bash
# 查看待发转债
python3 scripts/analyze_pending.py

# 紧凑摘要
python3 scripts/analyze_pending.py --compact

# 查看前 5 只
python3 scripts/analyze_pending.py --limit 5
```

### 3. 历史节点分析（辅助研究）

```bash
# 同意注册后股价变化
python3 scripts/analyze_registration_entry.py

# 同意注册对股价的影响
python3 scripts/analyze_registration_impact.py

# 同意注册到发行公告期间的股价变化
python3 scripts/analyze_registration_to_announcement.py

# 同意注册前的早期异动信号
python3 scripts/analyze_early_signals.py
```

## 模块说明

### lib/data_source.py - 数据源接口

```python
from lib.data_source import BondDataSource

# 自动优先集思录，失败降级东方财富
ds = BondDataSource()
bonds, source = ds.fetch_bonds(limit=10, pending_only=True)
```

### lib/bond_calculator.py - 配债计算

```python
from lib.bond_calculator import BondCalculator

calc = BondCalculator(target_bonds=10, bond_price=100)

# 配债额度 = 持股数 × 每股配售额
result = calc.calculate_allocation(
    stock_code='300622',
    shares=1500,
    per_share_amount=1.6457
)
```

### lib/stock_quality.py - 股票质量评估

```python
from lib.stock_quality import StockQualityEvaluator

evaluator = StockQualityEvaluator()
quality = evaluator.evaluate('300622', prices)
# 返回 A/B/C/D 等级，基于趋势/动量/成交量/波动性
```

## 配债计算公式

```python
# 配债额度 = 持股数 × 每股配售额
配债额度 (元) = shares × per_share_amount

# 可配张数 = floor(配债额度 / 100)
可配张数 = int(配债额度 / 100)

# 配债成本 = 可配张数 × 100 元
配债成本 = 可配张数 × 100
```

**注意**: 每股配售额因转债而异，差异巨大 (0.98 ~ 8.55 元/股)，必须动态计算！

## 数据来源

| 数据源 | 用途 | 特点 |
|--------|------|------|
| 集思录 | 待发转债 + 审批进度 | 公告发布前即可获取，推荐优先使用 |
| 东方财富 | 已上市转债列表 | 数据完整、更新及时 |
| 新浪财经 | 股票历史价格 | 支持 90 天历史 K 线 |

## 注意事项

1. **API 限流**: 在线模式会调用东方财富和新浪财经 API，建议批量获取
2. **交易日计算**: T-3/T-2/T-1/T+1 自动跳过周末和节假日
3. **数据 fallback**: 上市价格获取失败时，使用 FIRST_PROFIT 反推
4. **潜伏策略**: 前 10 个案例进化效果不明显，需要耐心积累数据
5. **破发风险**: 新债上市可能跌破 100 元发行价
6. **抢权风险**: 为配债买入股票可能面临股价下跌
