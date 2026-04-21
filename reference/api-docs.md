# 东方财富 API 接口文档

本文档沉淀了在开发 A 股可转债跟踪技能过程中发现的可用 API 接口，供后续开发参考。

---

## 一、可转债发行列表 API

### 1.1 接口说明

**用途**: 获取可转债发行信息（申购日期、登记日、发行规模、每股配售额等）

**端点**:
```
https://datacenter-web.eastmoney.com/api/data/v1/get
```

**参数**:
```
reportName=RPT_BOND_CB_LIST
columns=ALL                    # 获取全量字段，或指定字段逗号分隔
pageNumber=1                   # 页码
pageSize=100                   # 每页条数
sortTypes=-1                   # 排序方式：-1=降序，1=升序
sortColumns=PUBLIC_START_DATE  # 排序字段
source=WEB
client=WEB
```

**返回字段**: 共 72 个字段

---

### 1.2 全量字段说明

#### 基本信息 (6 个)

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| `SECURITY_CODE` | string | 110002 | 债券代码 |
| `SECUCODE` | string | 110002.SH | 债券完整代码 (含市场) |
| `SECURITY_NAME_ABBR` | string | 南山转债 | 债券简称 |
| `SECURITY_SHORT_NAME` | string | 南山铝业 | 股票简称 |
| `CONVERT_STOCK_CODE` | string | 600219 | 股票代码 |
| `TRADE_MARKET` | string | CNSESH | 交易市场 (CNSESH=沪市，CNSESZ=深市) |

#### 日期相关 (7 个)

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| `PUBLIC_START_DATE` | datetime | 2008-04-18 | 申购起始日 |
| `LISTING_DATE` | datetime | 2008-05-13 | 上市日期 |
| `RECORD_DATE_SH` | datetime | 2009-09-17 | 股权登记日 (沪市) |
| `SECURITY_START_DATE` | datetime | 2008-04-17 | 股权登记日 (通用) ⭐ |
| `VALUE_DATE` | datetime | 2008-04-18 | 起息日 |
| `EXPIRE_DATE` | datetime | 2009-09-18 | 到期日 |
| `CEASE_DATE` | datetime | 2009-09-17 | 停止交易日 |

#### 发行信息 (5 个)

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| `ACTUAL_ISSUE_SCALE` | number | 28 | 实际发行规模 (亿元) |
| `ISSUE_PRICE` | number | 100 | 发行价格 (元) |
| `ISSUE_YEAR` | string | 2008 | 发行年份 |
| `ISSUE_OBJECT` | string | ... | 发行对象说明 |
| `ISSUE_TYPE` | string | 1,4,5 | 发行类型代码 |

#### 转股信息 (6 个)

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| `INITIAL_TRANSFER_PRICE` | number | 16.89 | 初始转股价格 (元/股) ⭐ |
| `TRANSFER_PRICE` | number | - | 转股价格 |
| `CONVERT_STOCK_PRICE` | number | - | 正股价格 |
| `TRANSFER_VALUE` | number | 16.89 | 转股价值 |
| `TRANSFER_START_DATE` | datetime | 2008-10-20 | 转股起始日 |
| `TRANSFER_END_DATE` | datetime | 2009-09-17 | 转股截止日 |

#### 债券信息 (5 个)

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| `BOND_EXPIRE` | number | 1.4192 | 剩余期限 (年) |
| `RATING` | string | AA | 信用评级 ⭐ |
| `PAR_VALUE` | number | 100 | 债券面值 (元) |
| `INTEREST_RATE_EXPLAIN` | string | 第一年 1.0%... | 利率说明 |
| `PAY_INTEREST_DAY` | string | 04-18 | 付息日 |

#### 配债信息 (5 个) ⭐ **关键**

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| `CORRECODE` | string | 733219 | 配债代码 ⭐ |
| `CORRECODE_NAME_ABBR` | string | 南山发债 | 配债名称 ⭐ |
| `CORRECODEO` | string | 704219 | 原股东配债代码 |
| `CORRECODE_NAME_ABBRO` | string | 南山配债 | 原股东配债名称 |
| `FIRST_PER_PREPLACING` | number | 2.123 | **每股配售额 (元/股)** ⭐⭐⭐ |

#### 条款信息 (5 个)

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| `REDEEM_TYPE` | number | 2 | 赎回类型 |
| `REDEEM_CLAUSE` | string | ... | 赎回条款详情 |
| `RESALE_CLAUSE` | string | ... | 回售条款详情 |
| `REDEEM_TRIG_PRICE` | number | - | 赎回触发价格 |
| `RESALE_TRIG_PRICE` | number | - | 回售触发价格 |

#### 行情信息 (3 个)

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| `CONVERT_STOCK_PRICE` | number | - | 正股价格 |
| `CURRENT_BOND_PRICE` | number | - | 当前转债价格 |
| `TRANSFER_PREMIUM_RATIO` | number | 100 | 转股溢价率 (%) |

#### 其他字段 (31 个)

| 字段名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| `FIRST_PROFIT` | number | 84.82 | 每股优先配售收益 |
| `ONLINE_GENERAL_AAU` | number | 1700000 | 网上发行数量 (股) |
| `ONLINE_GENERAL_LWR` | number | 2.007 | 网上中签率 (%) |
| `PARTY_NAME` | string | 上海新世纪... | 评级机构名称 |
| `PARAM_NAME` | string | ... | 发行方式说明 |
| `BOND_COMBINE_CODE` | string | 08040500001SZZ | 债券组合代码 |
| `BOND_START_DATE` | datetime | 2008-04-24 | 债券起始日 |
| `CASHFLOW_DATE` | datetime | - | 现金流日期 |
| `CONVERT_STOCK_PRICEHQ` | number | - | 正股价格 (H 股) |
| `COUPON_IR` | number | - | 票面利率 |
| `CURRENT_BOND_PRICENEW` | number | - | 当前价格 (新) |
| `DELIST_DATE` | datetime | 2009-09-24 | 退市日期 |
| `EXECUTE_END_DATE` | datetime | - | 执行结束日期 |
| `EXECUTE_PRICE_HS` | number | - | 执行价格 (沪市) |
| `EXECUTE_PRICE_SH` | number | 103 | 执行价格 (深市) |
| `EXECUTE_REASON_HS` | number | - | 执行原因 (沪市) |
| `EXECUTE_REASON_SH` | number | 4 | 执行原因 (深市) |
| `EXECUTE_START_DATEHS` | datetime | - | 执行起始日 (沪市) |
| `EXECUTE_START_DATESH` | datetime | 2009-09-18 | 执行起始日 (深市) |
| `IB_END_DATE` | datetime | - | 网下发行截止日 |
| `IB_START_DATE` | datetime | - | 网下发行起始日 |
| `IS_CONVERT_STOCK` | string | 否 | 是否转股 |
| `IS_REDEEM` | string | 是 | 是否赎回 |
| `IS_SELLBACK` | string | 是 | 是否回售 |
| `MARKET` | string | - | 市场 |
| `NOTICE_DATE_HS` | datetime | - | 公告日期 (沪市) |
| `NOTICE_DATE_SH` | datetime | 2009-08-11 | 公告日期 (深市) |
| `PAYDAYNEW` | number | -18 | 付息日 (新) |
| `PBV_RATIO` | number | - | 市净率 |
| `PUBLIC_START_DATE_HOURS` | datetime | 2008-04-18 15:00 | 申购起始时间 (精确到小时) |
| `REMARK` | string | - | 备注 |

---

### 1.3 使用示例

#### Python 示例

```python
import json
import urllib.request

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': '*/*',
    'Referer': 'https://data.eastmoney.com/kzz/',
}

def fetch_bond_info(days=60):
    """获取可转债发行信息"""
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get?"
        "reportName=RPT_BOND_CB_LIST&"
        "columns=ALL&"
        "pageNumber=1&pageSize=100&"
        "sortTypes=-1&sortColumns=PUBLIC_START_DATE&"
        "source=WEB&client=WEB"
    )
    
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read().decode('utf-8'))
    
    if data.get('success'):
        return data['result']['data']
    return []

# 使用
bonds = fetch_bond_info()
for bond in bonds[:5]:
    print(f"{bond['SECURITY_NAME_ABBR']}: "
          f"每股配售 {bond.get('FIRST_PER_PREPLACING', 'N/A')} 元/股")
```

#### 关键字段提取

```python
# 提取关键信息
bond_info = {
    'bond_code': bond['SECURITY_CODE'],
    'bond_name': bond['SECURITY_NAME_ABBR'],
    'stock_code': bond['CONVERT_STOCK_CODE'],
    'stock_name': bond['SECURITY_SHORT_NAME'],
    'public_start_date': bond['PUBLIC_START_DATE'].split(' ')[0],
    'listing_date': bond['LISTING_DATE'].split(' ')[0] if bond.get('LISTING_DATE') else '',
    'record_date': bond['SECURITY_START_DATE'].split(' ')[0] if bond.get('SECURITY_START_DATE') else '',
    'issue_amount': bond['ACTUAL_ISSUE_SCALE'],  # 亿元
    'issue_price': bond['ISSUE_PRICE'],  # 元
    'conversion_price': bond['INITIAL_TRANSFER_PRICE'],  # 元/股
    'credit_rating': bond['RATING'],
    'allocation_code': bond['CORRECODE'],
    'allocation_name': bond['CORRECODE_NAME_ABBR'],
    'per_share_amount': bond['FIRST_PER_PREPLACING'],  # 每股配售额 ⭐
}
```

---

## 二、股票行情 API

### 2.1 股票历史 K 线

**用途**: 获取股票历史行情（日 K、周 K、月 K）

**端点**:
```
https://push2his.eastmoney.com/api/qt/stock/kline/get
```

**参数**:
```
secid={market}.{stock_code}  # 市场。股票代码 (0=深市，1=沪市)
fields1=f1,f2,f3,f4,f5,f6
fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61
klt=101          # K 线类型：101=日 K, 102=周 K, 103=月 K
fqt={adjust}     # 复权：0=不复权，1=前复权，2=后复权
beg={start_date} # 开始日期：YYYYMMDD
end={end_date}   # 结束日期：YYYYMMDD
lmt=1000         # 限制条数
```

**返回字段**:
| 字段 | 含义 | 索引 |
|------|------|------|
| f51 | 日期 | parts[0] |
| f52 | 开盘价 | parts[1] |
| f53 | 收盘价 | parts[2] |
| f54 | 最高价 | parts[3] |
| f55 | 最低价 | parts[4] |
| f56 | 成交量 (手) | parts[5] |
| f57 | 成交额 (元) | parts[6] |
| f58 | 振幅 (%) | parts[7] |
| f59 | 涨跌幅 (%) | parts[8] |
| f60 | 涨跌额 (元) | parts[9] |
| f61 | 换手率 (%) | parts[10] |

**示例代码**: 详见 `fetch_stock_history.py`

---

### 2.2 股票/转债实时行情

**用途**: 获取股票或转债当前价格、涨跌幅等

**端点**:
```
https://push2.eastmoney.com/api/qt/stock/get
```

**参数**:
```
invt=2
fltt=1
fields=f2,f3,f4,f5,f6,f7,f14
secid={market}.{code}
```

**返回字段**:
| 字段 | 含义 |
|------|------|
| f2 | 当前价格 |
| f3 | 涨跌幅 |
| f4 | 涨跌额 |
| f5 | 今开 |
| f6 | 最高 |
| f7 | 最低 |
| f14 | 名称 |

---

## 三、市场代码映射

### 3.1 股票市场

| 代码前缀 | 市场 | secid 前缀 |
|----------|------|-----------|
| 600xxx, 601xxx, 603xxx, 688xxx | 沪市 | 1. |
| 000xxx, 001xxx, 002xxx, 300xxx, 301xxx | 深市 | 0. |

### 3.2 可转债市场

| 代码前缀 | 市场 | secid 前缀 |
|----------|------|-----------|
| 110xxx, 113xxx, 118xxx | 沪市转债 | 1. |
| 123xxx, 127xxx, 128xxx | 深市转债 | 0. |

### 3.3 配债代码规律

| 股票类型 | 配债代码规律 | 示例 |
|----------|-------------|------|
| 沪市主板 (600/601) | 733/741/754 + 后 3 位 | 600219 → 733219 |
| 科创板 (688) | 718 + 后 3 位 | 688533 → 718533 |
| 深市主板 (000/001/002) | 07 + 后 4 位 | 002452 → 072452 |
| 创业板 (300/301) | 37 + 后 4 位 | 300964 → 370964 |

---

## 四、通用请求头

```python
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://data.eastmoney.com/kzz/',
}
```

---

## 五、注意事项

### 5.1 限流策略

- 东方财富 API 有频率限制，建议：
  - 单次请求间隔 >= 1 秒
  - 批量获取时使用分页，不要一次性请求过多数据
  - 添加超时设置 (timeout=15)

### 5.2 数据更新频率

- **行情数据**: 交易时段实时更新
- **发行数据**: 每日更新
- **历史 K 线**: 盘后更新 (约 18:00 后)

### 5.3 错误处理

```python
try:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read().decode('utf-8'))
        
    if not data.get('success') and 'success' in data:
        print(f"API 返回错误：{data.get('message', 'Unknown error')}")
        
except urllib.error.HTTPError as e:
    print(f"HTTP 错误：{e.code}")
except urllib.error.URLError as e:
    print(f"网络错误：{e.reason}")
except json.JSONDecodeError as e:
    print(f"JSON 解析错误：{e}")
except Exception as e:
    print(f"未知错误：{e}")
```

### 5.4 日期格式

- **请求参数**: YYYYMMDD (无分隔符)
- **返回数据**: YYYY-MM-DD HH:MM:SS (需要分割取日期部分)

---

## 六、已实现的脚本

以下脚本已实现上述 API 的封装，可直接使用：

| 脚本 | 功能 | 位置 |
|------|------|------|
| `fetch_bond_info.py` | 获取可转债发行信息 (全量 72 字段) | scripts/ |
| `fetch_stock_history.py` | 获取股票历史行情 | scripts/ |
| `calculate_allocation.py` | 计算配债额度 (使用每股配售额) | scripts/ |
| `calculate_min_shares.py` | 计算获得目标额度所需最小持股数 | scripts/ |
| `verify_listing_profit.py` | 验证已上市转债的上市收益 | scripts/ |
| `demo.py` | 完整工作流程演示 | scripts/ |

---

## 七、相关文档

- [bond-rules.md](bond-rules.md) - 配债规则说明
- [how-to-find-per-share-amount.md](how-to-find-per-share-amount.md) - 如何查找每股配售额

---

**文档维护**: 发现新 API 或新字段时请及时更新本文档。

**最后更新**: 2026-04-21
