# -*- coding: utf-8 -*-
"""
已验证策略注册中心

所有监控/回测脚本的策略条件唯一来源。
策略从独立脚本验证后，纳入此处统一管理。

新增策略：
    from lib.strategies import registry, Strategy
    registry.register(Strategy(
        key='NEW1', label='条件描述', condition=lambda f: ...,
        best_exit='TP5/SL5', sharpe='+0.xx',
    ))

禁用/启用：
    from lib.strategies import registry
    registry.disable('deep_pullback')
    registry.enable('deep_pullback')
"""
from __future__ import annotations


class Strategy:
    """策略定义"""

    __slots__ = ('key', 'label', 'display_name', 'condition', 'best_exit', 'sharpe')

    def __init__(self, key: str, label: str, condition,
                 best_exit: str = '', sharpe: str = '', display_name: str = ''):
        self.key = key
        self.label = label
        self.display_name = display_name
        self.condition = condition
        self.best_exit = best_exit
        self.sharpe = sharpe

    def __repr__(self):
        return f"Strategy({self.key}, {self.label})"

    def matches(self, factors: dict) -> bool:
        """判断因子是否满足策略条件"""
        return self.condition(factors)


class StrategyRegistry:
    """策略注册中心，支持动态启用/禁用"""

    def __init__(self):
        self._strategies: dict[str, Strategy] = {}
        self._disabled: set[str] = set()
        self._order: list[str] = []

    def register(self, s: Strategy):
        """注册策略"""
        self._strategies[s.key] = s
        if s.key not in self._order:
            self._order.append(s.key)

    def unregister(self, key: str):
        """移除策略"""
        self._strategies.pop(key, None)
        if key in self._order:
            self._order.remove(key)

    def get(self, key: str) -> Strategy | None:
        return self._strategies.get(key)

    def all(self) -> list[Strategy]:
        """所有已注册策略（按注册顺序）"""
        return [self._strategies[k] for k in self._order if k in self._strategies]

    def active(self) -> list[Strategy]:
        """已启用策略（排除已禁用的）"""
        return [s for s in self.all() if s.key not in self._disabled]

    def active_keys(self) -> list[str]:
        """已启用策略的 key"""
        return [k for k in self._order if k in self._strategies and k not in self._disabled]

    def disable(self, keys):
        """禁用策略"""
        self._disabled.update(keys)

    def enable(self, keys):
        """启用策略"""
        self._disabled.difference_update(keys)

    def is_active(self, key: str) -> bool:
        return key in self._strategies and key not in self._disabled


# ========== 已验证策略 ==========
# 格式: key, label(条件), display_name(显示名), condition, best_exit, sharpe
# 条件基于注册日收盘因子，D+1 开盘买入
# key 命名规则: 短英文，直观反映策略特征（回调深度/动量方向/成交量）

_VERIFIED = [
    # 深跌(≥2%) + 弱势 + 缩量 → 跌透企稳信号
    Strategy('deep_pullback', 'pre3<=-2+mom10<=-1+vol<=0.8',
             display_name='深调缩量企稳',
             condition=lambda f: f['pre3'] <= -2 and f['mom10'] <= -1 and f['vol_ratio5'] <= 0.8,
             best_exit='TP5/SL5', sharpe='+1.09'),

    # 浅调(≤2%) + 弱势 + 缩量 → 调整结束信号
    Strategy('shallow_pullback', 'pre3<=2+mom10<=-1+vol<=0.8',
             display_name='浅调缩量企稳',
             condition=lambda f: f['pre3'] <= 2 and f['mom10'] <= -1 and f['vol_ratio5'] <= 0.8,
             best_exit='TP5/SL5', sharpe='+0.70'),

    # 动量正向 + 注册日收涨 → 动量确认信号
    Strategy('up_momentum', 'pre3<=2+mom10<5+rc>0',
             display_name='正向动量收阳',
             condition=lambda f: f['pre3'] <= 2 and f['mom10'] < 5 and f['rc'] > 0,
             best_exit='TP5/SL5', sharpe='+0.81'),

    # 宽动量 + 缩量 → 高命中率缩量信号
    Strategy('high_signal', 'pre3<=2+mom10<=3+vol<=0.8',
             display_name='宽幅缩量信号',
             condition=lambda f: f['pre3'] <= 2 and f['mom10'] <= 3 and f['vol_ratio5'] <= 0.8,
             best_exit='TP5/SL5', sharpe='+0.54'),

    # 动量正向 + 收涨 + 缩量 → 紧幅动量确认信号
    Strategy('tight_momentum', 'pre3<=2+mom10<5+rc>0+vol<=0.8',
             display_name='紧幅动量收阳',
             condition=lambda f: f['pre3'] <= 2 and f['mom10'] < 5 and f['rc'] > 0 and f['vol_ratio5'] <= 0.8,
             best_exit='TP5/SL5', sharpe='+0.61'),

    # 宽动量，无缩量 → 广覆盖基础信号
    Strategy('broad_momentum', 'pre3<=2+mom10<5',
             display_name='宽幅动量信号',
             condition=lambda f: f['pre3'] <= 2 and f['mom10'] < 5,
             best_exit='D+9', sharpe='+0.45'),

    # 回调结束：3日跌≥1.5% 但连续下跌已停止 → 企稳反转信号
    Strategy('reversal_end', 'pre3<=-1.5+consec_down<=1',
             display_name='回调结束企稳',
             condition=lambda f: f['pre3'] <= -1.5 and f['consec_down'] <= 1,
             best_exit='TP5/SL5', sharpe='+0.40'),
]


def _register_defaults():
    """模块加载时自动注册"""
    for s in _VERIFIED:
        registry.register(s)


# 全局实例
registry = StrategyRegistry()
_register_defaults()
