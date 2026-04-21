# A 股可转债分析工具

模块化设计的可转债抢权配债分析工具。

## 目录结构

```
a-share-convertible-bond/
├── README.md                        # 本文档
├── SKILL.md                         # AgentSkill 定义
├── analyze_quequan_profit.py        # 完整报告脚本
├── analyze_compact.py               # 紧凑摘要脚本
├── lib/                             # 核心模块
│   ├── __init__.py
│   ├── data_source.py               # 数据源接口
│   ├── bond_calculator.py           # 配债计算
│   └── report.py                    # 报告生成
└── reference/                       # 参考资料
    ├── bond-rules.md                # 配债规则
    ├── api-docs.md                  # API 文档
    └── how-to-find-per-share-amount.md
```

## 快速开始

### 1. 紧凑摘要报告 (推荐)

适合在聊天界面直接查看，输出简洁完整：

```bash
# 分析 2026 年全部上市转债
python3 analyze_compact.py

# 分析前 5 只
python3 analyze_compact.py --limit 5

# 离线测试
python3 analyze_compact.py --offline
```

### 2. 完整详细报告

包含所有策略分析 (T-3/T-2/T-1)，适合保存到文件：

```bash
# 输出到终端
python3 analyze_quequan_profit.py

# 保存到文件
python3 analyze_quequan_profit.py --output report.txt

# 分析指定年份
python3 analyze_quequan_profit.py --year 2025
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
from lib.data_source import EastmoneyAPI, SinaFinanceAPI

em = EastmoneyAPI()
sina = SinaFinanceAPI()

# 获取转债列表
bonds = em.fetch_listed_bonds(limit=10)

# 获取股票历史价格
prices = sina.fetch_history('300622', days=90)

# 获取上市价格
listing_close = em.fetch_bond_listing_price('118050', '2026-04-14')
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

# 进行抢权配债分析
analysis = calc.analyze_quequan_profit(bond_info, stock_prices)
```

### lib/report.py - 报告生成

```python
from lib.report import ReportGenerator

gen = ReportGenerator()

# 文本报告
text = gen.generate_text_report(analyses)

# JSON 报告
json_data = gen.generate_json_report(analyses)

# Markdown报告
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
| `--offline` | 离线测试模式 | False |

### analyze_quequan_profit.py

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--limit`, `-n` | 分析数量 (0=全部) | 0 |
| `--year` | 分析指定年份 | 2026 |
| `--offline` | 离线测试模式 | False |
| `--format`, `-f` | 输出格式 (text/json/markdown) | text |
| `--output`, `-o` | 输出文件路径 | stdout |

## 注意事项

1. **API 限流**: 在线模式会调用东方财富和新浪财经 API，建议批量获取
2. **交易日计算**: T-3/T-2/T-1/T+1 自动跳过周末和节假日
3. **数据 fallback**: 上市价格获取失败时，使用 FIRST_PROFIT 反推
4. **离线测试**: 开发调试建议使用 `--offline` 模式

## 数据来源

- **转债发行信息**: 东方财富 datacenter-web.eastmoney.com
- **上市价格**: 东方财富 push2his.eastmoney.com
- **股票历史价格**: 新浪财经 money.finance.sina.com.cn
