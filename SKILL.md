---
name: a-share-convertible-bond
description: 跟踪 A 股可转债新债发布，计算配债额度，分析抢权配债收益。使用场景：(1) 监控新债发行信息；(2) 计算配债额度和所需资金；(3) 上帝视角分析历史收益；(4) 抓取集思录/东方财富/新浪财经数据。
---

# A 股可转债分析技能

本技能用于跟踪 A 股市场可转债新债发行信息，进行抢权配债完整收益分析。

**✨ 新增功能**：从集思录获取待发转债信息，**公告发布前即可发现配债机会**！

## 快速开始

### 🎯 入场时机监控 (带股票质量评估)

```bash
# 监控入场机会 (自动筛选 B 级及以上股票)
python monitor_entry_signals.py --once

# 只筛选 A 级优质股
python monitor_entry_signals.py --once --min-rating A

# 持续监控 (每 60 分钟)
python monitor_entry_signals.py

# 禁用质量评估
python monitor_entry_signals.py --once --no-quality
```

**监控策略**:
1. 同意注册当日入场 → 持有 10 天 (预期 +3.12%, 胜率 60%)
2. 上市委通过后 10 天入场 → 持有 20 天 (预期 +3.78%, 胜率 62.5%)

**股票质量评估维度**: 趋势 (40 分) + 动量 (30 分) + 成交量 (20 分) + 波动性 (10 分)

详见：[股票质量评估使用说明.md](股票质量评估使用说明.md)

---

### 🆕 待发转债列表 (公告前即可获取)

```bash
# 查看待发转债 (集思录数据)
python analyze_pending.py

# 紧凑摘要模式 (推荐)
python analyze_pending.py --compact

# 查看前 5 只
python analyze_pending.py --limit 5

# 为第 1 只转债计算配债额度
python analyze_pending.py --calc 1
```

### 历史收益分析 (上帝视角)

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

#### 统一数据源接口 (推荐)

```python
from lib.data_source import BondDataSource

# 自动优先集思录，失败降级东方财富
ds = BondDataSource()
bonds, source = ds.fetch_bonds(limit=10, pending_only=True)

print(f"数据来源：{source}")  # 'jisilu' 或 'eastmoney'
```

#### 直接使用各数据源

```python
from lib.data_source import JisiluAPI, EastmoneyAPI, SinaFinanceAPI

# 获取待发转债 (集思录 - 公告前即可获取)
jsl = JisiluAPI()
pending_bonds = jsl.fetch_pending_bonds(limit=10)

# 获取已上市转债列表 (东方财富)
em = EastmoneyAPI()
bonds = em.fetch_listed_bonds(limit=10)

# 获取股票历史价格 (新浪财经)
sina = SinaFinanceAPI()
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

### 集思录 (待发转债) ⭐ 推荐
- URL: https://www.jisilu.cn/data/cbnew/#pre
- API: `/data/cbnew/pre_list/`
- **优势：公告发布前即可获取申购信息**
- 数据包含：申购代码、配售代码、股权登记日、每股配售额、发行规模
- 无需登录即可访问 API

### 东方财富网 (转债数据)
- URL: https://data.eastmoney.com/kzz/
- API: datacenter-web.eastmoney.com
- 数据完整、更新及时
- 适合获取已上市转债的历史数据

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
6. **数据源优先级**: 
   - 优先使用集思录 (待发转债，公告前即可获取)
   - 集思录不可用时自动降级到东方财富
   - 使用 `BondDataSource` 类可自动处理降级

## 目录结构

```
a-share-convertible-bond/
├── analyze_quequan_profit.py    # 主脚本 (历史收益分析)
├── analyze_compact.py           # 紧凑摘要 (独立脚本)
├── analyze_pending.py           # 🆕 待发转债分析 (集思录数据)
├── monitor_entry_signals.py     # 🆕 入场时机监控 (带股票质量评估)
├── test_stock_quality.py        # 股票质量评估测试脚本
├── lib/                         # 核心模块
│   ├── data_source.py           # 数据源接口 (集思录/东方财富/新浪财经)
│   ├── bond_calculator.py       # 配债计算
│   ├── report.py                # 报告生成
│   └── stock_quality.py         # 🆕 股票质量评估模块
├── reference/                   # 参考资料
│   └── bond-rules.md            # 配债规则
└── docs/                        # 🆕 使用文档
    ├── 股票质量评估使用说明.md
    └── 策略综合分析与推荐.md
```
