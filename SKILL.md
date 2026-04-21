---
name: a-share-convertible-bond
description: 跟踪 A 股可转债新债发布，计算配债额度，分析抢权配债收益。使用场景：(1) 监控新债发行信息；(2) 计算配债额度和所需资金；(3) 上帝视角分析历史收益；(4) 抓取东方财富/新浪财经数据。
---

# A 股可转债分析技能

本技能用于跟踪 A 股市场可转债新债发行信息，进行抢权配债完整收益分析。

## 快速开始

### 默认：输出完整报告

```bash
python analyze_quequan_profit.py
```

**自动检测输出长度**：
- 如果报告较短 → 直接显示完整报告
- 如果报告较长 (>200 行) → 显示完整报告 + 提示使用紧凑模式

### 紧凑摘要模式 (推荐用于聊天)

```bash
python analyze_quequan_profit.py --compact
```

输出包含：
- 股价走势 (T-1 → T+1)
- T-1 买入完整盈亏 (全部数据)
- 统计汇总

### 命令行参数

```bash
# 完整报告 (默认)
python analyze_quequan_profit.py

# 紧凑摘要 (适合聊天界面)
python analyze_quequan_profit.py --compact

# 分析前 5 只
python analyze_quequan_profit.py --limit 5

# 分析指定年份
python analyze_quequan_profit.py --year 2025

# 保存到文件
python analyze_quequan_profit.py --output report.txt

# 离线测试
python analyze_quequan_profit.py --offline
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

### 抢权配债分析 (上帝视角)

```python
# 分析 T-3/T-2/T-1 买入，T+1 卖出的完整盈亏
analysis = calc.analyze_quequan_profit(bond_info, stock_prices)
```

### 数据获取

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

## 配债规则

详见 [reference/bond-rules.md](reference/bond-rules.md)

**核心规则:**
- 每股配售额因转债而异 (0.98 ~ 8.55 元/股)
- 配债额度 = 持股数 × 每股配售额
- 可配张数 = floor(配债额度 / 100)
- 必须在股权登记日前 1 个交易日持有股票

## 数据源

### 东方财富网 (转债数据)
- URL: https://data.eastmoney.com/kzz/
- API: datacenter-web.eastmoney.com
- 数据完整、更新及时

### 新浪财经 (股票历史价格)
- URL: http://money.finance.sina.com.cn/
- API: quotes_service/api/json_v2.php
- 支持 90 天历史 K 线

## 时间定义

| 时点 | 说明 |
|------|------|
| T-3 | 股权登记日前 3 个交易日 |
| T-2 | 股权登记日前 2 个交易日 |
| T-1 | 股权登记日前 1 个交易日 (最后买入时机) |
| T | 股权登记日 |
| T+1 | 股权登记日后 1 个交易日 (卖出时机) |

## 注意事项

1. **时间敏感**: 从公告到登记日通常只有 3-5 个交易日
2. **T+1 交收**: T 日买入股票，T+1 日才到账
3. **配债成本**: 根据每股配售额动态计算，非固定值
4. **破发风险**: 新债上市可能跌破 100 元发行价
5. **抢权风险**: 为配债买入股票可能面临股价下跌

## 目录结构

```
a-share-convertible-bond/
├── analyze_quequan_profit.py    # 主脚本 (完整报告 + 紧凑模式)
├── analyze_compact.py           # 紧凑摘要 (独立脚本)
├── lib/                         # 核心模块
│   ├── data_source.py           # 数据源接口
│   ├── bond_calculator.py       # 配债计算
│   └── report.py                # 报告生成
└── reference/                   # 参考资料
    └── bond-rules.md            # 配债规则
```
