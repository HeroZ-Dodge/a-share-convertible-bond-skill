---
name: a-share-convertible-bond
description: 处理 A 股可转债注册前信号监控、买入提示、持仓退出和多策略回测，核心入口是 scripts/pre_reg_monitor.py 与 scripts/monitor_multi_strategy.py。
---

# A 股可转债注册前信号监控

这个 skill 只围绕两个脚本工作：

- `scripts/pre_reg_monitor.py`
- `scripts/monitor_multi_strategy.py`

它们共同覆盖：

- 注册前信号扫描
- D+1 买入逻辑
- 持仓止盈止损/注册日退出
- 单策略与多策略回测
- 理论信号和实际交易记录对比

## 使用范围

当用户要做下面这些事时使用这个 skill：

- 扫描“上市委通过 -> 同意注册”期间的正股异动
- 依据收盘价、成交量和均线因子判断买点
- 对单策略或多策略做历史回测
- 记录、查询或对比理论买卖信号

不要把这个 skill 当成通用的可转债研究文档。优先围绕这两个脚本现有能力工作。

## 主要入口

### `scripts/pre_reg_monitor.py`

单套注册前策略脚本，关注“上市委通过 -> 同意注册”区间。

常用模式：

```bash
python3 scripts/pre_reg_monitor.py --scan
python3 scripts/pre_reg_monitor.py --backtest
python3 scripts/pre_reg_monitor.py --backtest --limit 100
python3 scripts/pre_reg_monitor.py --backtest --strategy mom_recover
```

脚本内置的策略因子基于 K 线数据，不使用注册日之后的信息。

### `scripts/monitor_multi_strategy.py`

多策略组合脚本，策略从 `lib/strategies.py` 读取，支持监控、数据库同步和回测。

常用模式：

```bash
python3 scripts/monitor_multi_strategy.py
python3 scripts/monitor_multi_strategy.py --scan
python3 scripts/monitor_multi_strategy.py --hold
python3 scripts/monitor_multi_strategy.py --combo
python3 scripts/monitor_multi_strategy.py --status
python3 scripts/monitor_multi_strategy.py --backtest
python3 scripts/monitor_multi_strategy.py --backtest --combo
python3 scripts/monitor_multi_strategy.py --backtest --combo all
python3 scripts/monitor_multi_strategy.py --sync-db
python3 scripts/monitor_multi_strategy.py --compare CODE
python3 scripts/monitor_multi_strategy.py --buy CODE DATE PRICE [REG_DATE]
python3 scripts/monitor_multi_strategy.py --sell CODE DATE PRICE [REG_DATE]
```

## 工作流程

1. 从集思录等数据源读取待发或已注册转债。
2. 解析 `progress_full` 中的“上市委通过”和“同意注册”日期。
3. 用 `close`、`volume`、均线偏离、动量等因子判断是否触发策略。
4. 监控模式下，输出触发标的、策略命中情况和退出状态。
5. 回测模式下，按脚本定义的 D+1 买入、D+9 或 TP/SL 退出规则统计收益。

## 处理原则

- 直接复用脚本现有参数和输出格式，不要虚构额外命令。
- 因子计算要遵守无未来函数原则。
- 如果要改策略条件，优先改 `lib/strategies.py` 或脚本对应的策略定义，再同步调整 skill 描述。
- 如果用户请求的是历史分析、监控逻辑或回测结果，就优先查看这两个脚本，而不是扩展到其他未定义功能。
