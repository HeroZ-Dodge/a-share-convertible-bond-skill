# 如何查找每股配售额数据

本文档说明如何找到可转债的每股配售额数据 (`FIRST_PER_PREPLACING`)。

---

## 方法一：直接访问 API（推荐）

### 1. 打开 API URL

在浏览器中访问：

```
https://datacenter-web.eastmoney.com/api/data/v1/get?
  reportName=RPT_BOND_CB_LIST&
  columns=SECURITY_CODE,SECURITY_NAME_ABBR,CONVERT_STOCK_CODE,
          SECURITY_SHORT_NAME,ACTUAL_ISSUE_SCALE,ISSUE_PRICE,
          INITIAL_TRANSFER_PRICE,RATING,CORRECODE,
          CORRECODE_NAME_ABBR,FIRST_PER_PREPLACING&
  pageNumber=1&
  pageSize=20&
  sortTypes=-1&
  sortColumns=PUBLIC_START_DATE&
  source=WEB&
  client=WEB
```

### 2. 查看返回的 JSON 数据

返回示例：

```json
{
  "version": "...",
  "result": {
    "pages": 102,
    "data": [
      {
        "SECURITY_CODE": "123269",
        "SECURITY_NAME_ABBR": "金杨转债",
        "CONVERT_STOCK_CODE": "301210",
        "SECURITY_SHORT_NAME": "金杨精密",
        "ACTUAL_ISSUE_SCALE": 9.8,
        "ISSUE_PRICE": 100,
        "INITIAL_TRANSFER_PRICE": 39.8,
        "RATING": "AA-",
        "CORRECODE": "371210",
        "CORRECODE_NAME_ABBR": "金杨发债",
        "FIRST_PER_PREPLACING": 8.5504  ← 这就是每股配售额！
      },
      ...
    ]
  }
}
```

### 3. 关键字段说明

| 字段名 | 含义 | 示例 |
|--------|------|------|
| `SECURITY_CODE` | 债券代码 | 123269 |
| `SECURITY_NAME_ABBR` | 债券名称 | 金杨转债 |
| `CONVERT_STOCK_CODE` | 股票代码 | 301210 |
| `SECURITY_SHORT_NAME` | 股票名称 | 金杨精密 |
| `FIRST_PER_PREPLACING` | **每股配售额 (元/股)** | **8.5504** ← 关键！ |
| `CORRECODE` | 配债代码 | 371210 |
| `CORRECODE_NAME_ABBR` | 配债名称 | 金杨发债 |

---

## 方法二：通过东方财富网站查找

### 步骤 1：打开东方财富可转债页面

访问：https://data.eastmoney.com/kzz/

### 步骤 2：打开浏览器开发者工具

- Chrome/Edge: 按 `F12` 或右键 → 检查
- 切换到 **Network (网络)** 标签

### 步骤 3：筛选 API 请求

在 Filter 框中输入：
```
datacenter-web.eastmoney.com
```

### 步骤 4：查找包含 `RPT_BOND_CB_LIST` 的请求

找到类似这样的请求：
```
https://datacenter-web.eastmoney.com/api/data/v1/get?
  reportName=RPT_BOND_CB_LIST&
  columns=ALL&
  pageNumber=1&pageSize=20&
  ...
```

### 步骤 5：查看响应数据

点击请求 → 切换到 **Response (响应)** 标签 → 查看 JSON 数据

找到 `FIRST_PER_PREPLACING` 字段，这就是每股配售额！

---

## 方法三：使用 Python 脚本获取

```python
import json
import urllib.request

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': '*/*',
    'Referer': 'https://data.eastmoney.com/kzz/',
}

url = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get?"
    "reportName=RPT_BOND_CB_LIST&"
    "columns=SECURITY_CODE,SECURITY_NAME_ABBR,CONVERT_STOCK_CODE,"
    "FIRST_PER_PREPLACING,CORRECODE&"
    "pageNumber=1&pageSize=20&"
    "source=WEB&client=WEB"
)

req = urllib.request.Request(url, headers=HEADERS)
with urllib.request.urlopen(req, timeout=15) as response:
    data = json.loads(response.read().decode('utf-8'))

# 提取每股配售额
for bond in data['result']['data']:
    print(f"{bond['SECURITY_NAME_ABBR']}: "
          f"{bond.get('FIRST_PER_PREPLACING', 'N/A')} 元/股")
```

---

## 验证数据准确性

### 公式验证

每股配售额的计算公式：

```
每股配售额 (元/股) = 发行总额 (元) / 总股本 (股)
```

### 示例：金杨转债

- 发行总额：9.8 亿元 = 980,000,000 元
- 总股本：约 11,460 万股（需要查询股票基本信息）
- 每股配售额 = 980,000,000 / 114,600,000 ≈ **8.55 元/股** ✓

---

## 常见错误

### ❌ 错误 1：使用固定规则

```
每 1000 股 = 1000 元配债额度 ← 错误！
```

**实际情况**:
- 金杨转债：1000 股 = 8550 元配债额度
- 珂玛转债：1000 股 = 1720 元配债额度
- **相差 5 倍！**

### ❌ 错误 2：使用错误的字段

以下字段**不是**每股配售额：
- `ISSUE_PRICE` - 发行价格（固定 100 元）
- `INITIAL_TRANSFER_PRICE` - 转股价格
- `ACTUAL_ISSUE_SCALE` - 发行规模（亿元）

**正确字段**: `FIRST_PER_PREPLACING`

---

## 数据用途

获取每股配售额后，计算配债额度：

```python
# 正确公式
配债额度 (元) = 持股数 × 每股配售额
可配张数 = floor(配债额度 / 100)
所需资金 = 可配张数 × 100
```

### 示例计算

**金杨转债 (每股配售额 8.5504 元/股):**

| 持股数 | 配债额度 | 可配张数 | 所需资金 |
|--------|----------|----------|----------|
| 100 股 | 855.04 元 | 8 张 | 800 元 |
| 1000 股 | 8,550.40 元 | 85 张 | 8,500 元 |

**珂玛转债 (每股配售额 1.7201 元/股):**

| 持股数 | 配债额度 | 可配张数 | 所需资金 |
|--------|----------|----------|----------|
| 100 股 | 172.01 元 | 1 张 | 100 元 |
| 1000 股 | 1,720.10 元 | 17 张 | 1,700 元 |

---

## 相关 API 文档

详见：[api-docs.md](api-docs.md)

---

**最后更新**: 2026-04-21  
**数据来源**: 东方财富网数据中心
