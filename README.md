# A 股可转债分析工具

模块化设计的可转债抢权配债分析工具，支持待发转债监控、历史收益分析和潜伏策略信号跟踪。

## 目录结构

```
a-share-convertible-bond-skill/
├── README.md                        # 本文档
├── SKILL.md                         # AgentSkill 定义
├── monitor_history.json             # 监控历史记录
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
│   ├── analyze_pending.py           # 待发转债分析
│   ├── analyze_quequan_profit.py    # 抢权配债收益分析
│   ├── analyze_compact.py           # 紧凑输出
│   ├── analyze_registration_entry.py
│   ├── analyze_registration_impact.py
│   ├── analyze_registration_to_announcement.py
│   ├── analyze_t_day_exit.py
│   ├── analyze_early_signals.py
│   │
│   └── monitor/                     # 监控脚本
│       ├── monitor_latent_strategy.py   # 潜伏策略监控
│       ├── backtest_latent_strategy.py  # 潜伏策略回测
│       ├── README.md                    # 使用说明
│       └── 潜伏策略监控使用说明.md
│
├── docs/                            # 分析报告
└── reference/                       # 参考资料
    └── bond-rules.md                # 配债规则
```

## 快速开始

### 1. 潜伏策略监控（主监控）

监控上市委通过后的转债，捕捉资金提前布局信号。

```bash
# 运行一次
python scripts/monitor/monitor_latent_strategy.py --once

# 持续监控（每 60 分钟）
python scripts/monitor/monitor_latent_strategy.py

# 查看进化报告
python scripts/monitor/monitor_latent_strategy.py --report
```

详见：[scripts/monitor/README.md](scripts/monitor/README.md)

### 2. 紧凑摘要报告（推荐）

适合在聊天界面直接查看，输出简洁完整：

```bash
# 分析 2026 年全部上市转债
python scripts/analyze_compact.py

# 分析前 5 只
python scripts/analyze_compact.py --limit 5
```

### 3. 完整详细报告

包含所有策略分析 (T-3/T-2/T-1)，适合保存到文件：

```bash
# 输出到终端
python scripts/analyze_quequan_profit.py

# 保存到文件
python scripts/analyze_quequan_profit.py --output report.txt

# 分析指定年份
python scripts/analyze_quequan_profit.py --year 2025
```

### 4. 待发转债列表

从集思录获取待发转债信息，公告发布前即可发现配债机会：

```bash
# 查看待发转债
python scripts/analyze_pending.py

# 紧凑摘要
python scripts/analyze_pending.py --compact

# 查看前 5 只
python scripts/analyze_pending.py --limit 5
```

## 输出示例

### 紧凑摘要输出

```markdown
## 📊 2026 年可转债抢权配债分析 (14 只)

### 📈 股价走势
| # | 名称 | T-1 | T+1 | 涨跌 |
|---|------|-----|-----|------|
| 1 | 上 26 转债 | 31.29 | 27.89 | -10.9% ↓ |

### 💰 T-1 买入盈亏
| # | 名称 | 配债成本 | 股票盈亏 | 配债收益 | 总盈亏 |
|---|------|----------|----------|----------|--------|
| 1 | 上 26 转债 | 1,100 元 | -2040 元 | +523 元 | -1517 元 ❌ |

### 📊 统计
- T-1 胜率：7/14 (50%)
- 平均收益：-183 元
- 最佳：金 05 转债 (+1520 元)
- 最差：上 26 转债 (-1517 元)
```

## 模块说明

### lib/data_source.py - 数据源接口

```python
from lib.data_source import BondDataSource

# 自动优先集思录，失败降级东方财富
ds = BondDataSource()
bonds, source = ds.fetch_bonds(limit=10, pending_only=True)
```

或直接使用各数据源：

```python
from lib.data_source import JisiluAPI, EastmoneyAPI, SinaFinanceAPI

# 待发转债（集思录）
jsl = JisiluAPI()
pending = jsl.fetch_pending_bonds(limit=10)

# 已上市转债（东方财富）
em = EastmoneyAPI()
bonds = em.fetch_listed_bonds(limit=10)

# 股票历史价格（新浪财经）
sina = SinaFinanceAPI()
prices = sina.fetch_history('300622', days=90)
```

### lib/bond_calculator.py - 配债计算

```python
from lib.bond_calculator import BondCalculator

calc = BondCalculator(target_bonds=10, bond_price=100)

# 计算配债额度
result = calc.calculate_allocation(
    stock_code='300622',
    shares=1500,
    per_share_amount=1.6457
)

# 抢权配债分析
analysis = calc.analyze_quequan_profit(bond_info, stock_prices)
```

### lib/stock_quality.py - 股票质量评估

```python
from lib.stock_quality import StockQualityEvaluator

evaluator = StockQualityEvaluator()
quality = evaluator.evaluate('300622', prices)
# 返回 A/B/C/D 等级，基于趋势/动量/成交量/波动性
```

### lib/report.py - 报告生成

```python
from lib.report import ReportGenerator

gen = ReportGenerator()
text = gen.generate_text_report(analyses)
json_data = gen.generate_json_report(analyses)
md = gen.generate_markdown_report(analyses)
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

## 命令行参数

### analyze_compact.py

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--limit`, `-n` | 分析数量 (0=全部) | 0 |
| `--year` | 分析指定年份 | 2026 |

### analyze_quequan_profit.py

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--limit`, `-n` | 分析数量 (0=全部) | 0 |
| `--year` | 分析指定年份 | 2026 |
| `--format`, `-f` | 输出格式 (text/json/markdown) | text |
| `--output`, `-o` | 输出文件路径 | stdout |

### analyze_pending.py

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--limit`, `-n` | 分析数量 | 10 |
| `--compact` | 紧凑输出 | False |
| `--format` | 输出格式 (text/json) | text |

### monitor_latent_strategy.py

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--once` | 只运行一次 | False |
| `--interval` | 监控间隔（分钟） | 60 |
| `--report` | 显示进化报告 | False |
| `--export` | 导出数据 | False |

## 注意事项

1. **API 限流**: 在线模式会调用东方财富和新浪财经 API，建议批量获取
2. **交易日计算**: T-3/T-2/T-1/T+1 自动跳过周末和节假日
3. **数据 fallback**: 上市价格获取失败时，使用 FIRST_PROFIT 反推
4. **潜伏策略**: 前 10 个案例进化效果不明显，需要耐心积累数据

## 数据来源

| 数据源 | 用途 | 特点 |
|--------|------|------|
| 集思录 | 待发转债 | 公告发布前即可获取，推荐优先使用 |
| 东方财富 | 已上市转债列表 | 数据完整、更新及时 |
| 新浪财经 | 股票历史价格 | 支持 90 天历史 K 线 |
