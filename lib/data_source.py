# -*- coding: utf-8 -*-
"""
数据源接口模块

提供从不同数据源获取可转债和股票数据的统一接口。

支持的数据源:
- 集思录 (待发转债、申购信息) - **公告前即可获取**
- 东方财富网 (转债发行信息、上市价格)
- 新浪财经 (股票历史 K 线)

Usage:
    from lib.data_source import JisiluAPI, EastmoneyAPI, SinaFinanceAPI
    
    # 获取待发转债列表 (公告前)
    jsl = JisiluAPI()
    bonds = jsl.fetch_pending_bonds(limit=10)
    
    # 获取已上市转债列表
    em = EastmoneyAPI()
    bonds = em.fetch_listed_bonds(limit=10)
    
    # 获取股票历史价格
    sina = SinaFinanceAPI()
    prices = sina.fetch_history('300622', days=90)
"""

import json
import urllib.request
import urllib.error
import codecs
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


# ==================== 通用配置 ====================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': 'https://data.eastmoney.com/kzz/',
    'Connection': 'keep-alive',
}

SINA_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
}

JISILU_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': 'https://www.jisilu.cn/data/cbnew/',
    'X-Requested-With': 'XMLHttpRequest',
}


# ==================== 东方财富 API ====================

class EastmoneyAPI:
    """东方财富网数据接口"""
    
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
    
    def _request(self, url: str, headers: dict = HEADERS) -> Optional[dict]:
        """发送 HTTP 请求"""
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"API 请求失败：{url[:100]}... - {e}")
            return None
    
    def fetch_listed_bonds(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取已上市转债列表
        
        Args:
            limit: 返回数量限制
            
        Returns:
            转债列表，每项包含:
            - bond_code: 债券代码
            - bond_name: 债券名称
            - stock_code: 股票代码
            - stock_name: 股票名称
            - listing_date: 上市日期
            - record_date: 股权登记日
            - credit_rating: 信用评级
            - per_share_amount: 每股配售额
            - first_profit: 每签获利
        """
        url = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get?"
            "reportName=RPT_BOND_CB_LIST&"
            "columns=ALL&"
            "pageNumber=1&pageSize=100&"
            "sortTypes=-1&sortColumns=PUBLIC_START_DATE&"
            "source=WEB&client=WEB"
        )
        
        data = self._request(url)
        if not data or not data.get('success'):
            return []
        
        bonds_data = data.get('result', {}).get('data', [])
        listed = [b for b in bonds_data if b.get('LISTING_DATE')]
        
        # 标准化字段
        result = []
        for b in listed[:limit]:
            result.append({
                'bond_code': b.get('SECURITY_CODE', ''),
                'bond_name': b.get('SECURITY_NAME_ABBR', ''),
                'stock_code': b.get('CONVERT_STOCK_CODE', ''),
                'stock_name': b.get('SECURITY_SHORT_NAME', ''),
                'listing_date': b.get('LISTING_DATE', '').split(' ')[0],
                'record_date': b.get('SECURITY_START_DATE', '').split(' ')[0],
                'credit_rating': b.get('RATING', ''),
                'issue_amount': b.get('ACTUAL_ISSUE_SCALE', 0),
                'per_share_amount': b.get('FIRST_PER_PREPLACING', 0),
                'first_profit': b.get('FIRST_PROFIT', 0),
            })
        
        return result
    
    def fetch_bond_listing_price(self, bond_code: str, listing_date: str) -> Optional[float]:
        """
        获取转债上市首日收盘价
        
        Args:
            bond_code: 债券代码
            listing_date: 上市日期 (YYYY-MM-DD)
            
        Returns:
            上市收盘价，获取失败返回 None
        """
        import gzip
        
        market = '1' if bond_code.startswith('11') else '0'
        date_str = listing_date.replace('-', '')
        
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            f"secid={market}.{bond_code}&"
            f"fields1=f1,f2,f3,f4,f5,f6&"
            f"fields2=f51,f52,f53,f54,f55,f56&"
            f"klt=101&fqt=0&"
            f"beg={date_str}&end={date_str}&"
            f"lmt=5"
        )
        
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw_data = response.read()
                # 处理 gzip 压缩
                if response.headers.get('Content-Encoding') == 'gzip' or raw_data[:2] == b'\x1f\x8b':
                    raw_data = gzip.decompress(raw_data)
                data = json.loads(raw_data.decode('utf-8'))
                
                if data and data.get('data') and data['data'].get('klines'):
                    kline = data['data']['klines'][0]
                    parts = kline.split(',')
                    if len(parts) >= 3:
                        return float(parts[2])  # 收盘价
        except Exception as e:
            print(f"获取上市价格失败 {bond_code}: {e}")
        
        return None


# ==================== 新浪财经 API ====================

class SinaFinanceAPI:
    """新浪财经数据接口"""
    
    def __init__(self, timeout: int = 20):
        self.timeout = timeout
    
    def _get_market_prefix(self, stock_code: str) -> str:
        """获取市场前缀"""
        if stock_code.startswith('6'):
            return 'sh'  # 沪市
        else:
            return 'sz'  # 深市/创业板
    
    def fetch_history(self, stock_code: str, days: int = 90) -> Dict[str, Dict[str, float]]:
        """
        获取股票历史 K 线数据
        
        Args:
            stock_code: 股票代码 (6 位数字)
            days: 获取天数
            
        Returns:
            字典：{日期：{open, close, high, low, volume}}
            例如：{'2026-03-17': {'open': 30.5, 'close': 31.2, ...}}
        """
        market = self._get_market_prefix(stock_code)
        symbol = f'{market}{stock_code}'
        
        url = (
            f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={days}"
        )
        
        try:
            req = urllib.request.Request(url, headers=SINA_HEADERS)
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                # 新浪财经返回 GBK 编码
                reader = codecs.getreader('gbk')
                data = json.load(reader(response))
            
            if not isinstance(data, list):
                return {}
            
            # 解析数据
            result = {}
            for day in data:
                date = day.get('day', '')
                result[date] = {
                    'open': float(day.get('open', 0)),
                    'close': float(day.get('close', 0)),
                    'high': float(day.get('high', 0)),
                    'low': float(day.get('low', 0)),
                    'volume': float(day.get('volume', 0)),
                }
            
            return result
            
        except Exception as e:
            print(f"获取股票 {stock_code} 历史数据失败：{e}")
            return {}
    
    def fetch_current_price(self, stock_code: str) -> Optional[float]:
        """
        获取股票当前价格
        
        Args:
            stock_code: 股票代码
            
        Returns:
            当前价格，获取失败返回 None
        """
        market = self._get_market_prefix(stock_code)
        symbol = f'{market}{stock_code}'
        
        url = f"https://hq.sinajs.cn/list={symbol}"
        
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read().decode('gbk')
                # 格式：var hq_str_sh600000="浦发银行，8.50,..."
                parts = content.split('"')[1].split(',')
                if len(parts) >= 4:
                    return float(parts[3])  # 当前价
        except Exception as e:
            print(f"获取股票 {stock_code} 当前价格失败：{e}")
        
        return None


# ==================== 集思录 API ====================

class JisiluAPI:
    """
    集思录数据接口
    
    优势：
    - 可在公告发布前获取待发转债信息
    - 数据完整：包含申购代码、配售代码、股权登记日、每股配售额等
    - 无需登录即可访问 API
    
    API 文档：https://www.jisilu.cn/data/cbnew/#pre
    """
    
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.base_url = 'https://www.jisilu.cn/data/cbnew/'
    
    def _request(self, url: str, headers: dict = JISILU_HEADERS) -> Optional[dict]:
        """发送 HTTP 请求"""
        import gzip
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw_data = response.read()
                # 处理 gzip 压缩
                if response.headers.get('Content-Encoding') == 'gzip' or raw_data[:2] == b'\x1f\x8b':
                    raw_data = gzip.decompress(raw_data)
                return json.loads(raw_data.decode('utf-8'))
        except Exception as e:
            print(f"集思录 API 请求失败：{url[:100]}... - {e}")
            return None
    
    def fetch_pending_bonds(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取待发转债列表 (公告前即可获取)
        
        Args:
            limit: 返回数量限制
            
        Returns:
            待发转债列表，每项包含:
            - bond_code: 债券代码
            - bond_name: 债券名称
            - stock_code: 股票代码
            - stock_name: 股票名称
            - apply_date: 申购日期
            - apply_code: 申购代码
            - ration_code: 配售代码
            - record_date: 股权登记日
            - ration: 每股配售额 (元/股)
            - amount: 发行规模 (亿元)
            - convert_price: 转股价
            - rating: 信用评级
            - progress: 当前进度
        """
        import time
        timestamp = int(time.time())
        url = f"{self.base_url}pre_list/?___t={timestamp}"
        
        data = self._request(url)
        if not data or not data.get('rows'):
            return []
        
        rows = data.get('rows', [])
        
        result = []
        for row in rows[:limit]:
            cell = row.get('cell', {})
            result.append({
                'bond_code': cell.get('bond_id', ''),
                'bond_name': cell.get('bond_nm', ''),
                'stock_code': cell.get('stock_id', ''),
                'stock_name': cell.get('stock_nm', ''),
                'apply_date': cell.get('apply_date', ''),
                'apply_code': cell.get('apply_cd', ''),
                'ration_code': cell.get('ration_cd', ''),
                'record_date': cell.get('record_dt', ''),
                'record_price': cell.get('record_price', 0),
                'ration': cell.get('ration', 0),
                'amount': cell.get('amount', 0),
                'convert_price': cell.get('convert_price', 0),
                'rating': cell.get('rating_cd', ''),
                'progress': cell.get('progress_nm', ''),
                'progress_full': cell.get('progress_full', ''),
                'status': cell.get('status_cd', ''),
                'market': cell.get('margin_flg', ''),
            })
        
        return result
    
    def fetch_bond_detail(self, bond_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单只转债详细信息
        
        Args:
            bond_id: 债券 ID (如 123269)
            
        Returns:
            转债详细信息字典
        """
        bonds = self.fetch_pending_bonds(limit=200)
        for bond in bonds:
            if bond['bond_code'] == bond_id or bond['bond_name'] == bond_id:
                return bond
        return None


# ==================== 统一数据源 (带降级) ====================

class BondDataSource:
    """
    统一转债数据源接口
    
    优先级:
    1. 集思录 (待发转债、申购信息) - 公告前即可获取
    2. 东方财富 (已上市转债) - 降级备用
    
    自动处理不同数据源的格式差异，返回统一格式的数据。
    """
    
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.jisilu = JisiluAPI(timeout=timeout)
        self.eastmoney = EastmoneyAPI(timeout=timeout)
        self._source_used = None  # 记录本次使用的数据源
    
    @property
    def last_source(self) -> str:
        """返回上次成功获取数据的数据源名称"""
        return self._source_used or 'none'
    
    def fetch_bonds(self, limit: int = 50, pending_only: bool = False, max_retries: int = 2) -> List[Dict[str, Any]]:
        """
        获取转债列表 (优先集思录，失败降级东方财富)
        
        Args:
            limit: 返回数量限制
            pending_only: True=只获取待发转债，False=获取已上市转债
            max_retries: 集思录失败重试次数
            
        Returns:
            统一格式的转债列表
        """
        # 待发转债模式：优先集思录
        if pending_only or True:  # 始终优先尝试集思录
            for attempt in range(max_retries):
                if attempt > 0:
                    import time
                    time.sleep(0.5 * attempt)  # 重试前等待
                
                bonds = self.jisilu.fetch_pending_bonds(limit=limit)
                if bonds and len(bonds) > 0:
                    self._source_used = 'jisilu'
                    return self._normalize_jisilu_bonds(bonds)
        
        # 降级到东方财富 (仅当集思录完全不可用时)
        bonds = self.eastmoney.fetch_listed_bonds(limit=limit)
        if bonds:
            self._source_used = 'eastmoney'
            return self._normalize_eastmoney_bonds(bonds)
        
        self._source_used = 'none'
        return []
    
    def _normalize_jisilu_bonds(self, bonds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        标准化集思录数据格式
        
        集思录字段:
        - bond_code, bond_name, stock_code, stock_name
        - apply_date, apply_code, ration_code, record_date
        - ration (每股配售额), amount (发行规模)
        - convert_price, rating, progress
        """
        result = []
        for b in bonds:
            result.append({
                # 基础信息
                'bond_code': b.get('bond_code', ''),
                'bond_name': b.get('bond_name', ''),
                'stock_code': b.get('stock_code', ''),
                'stock_name': b.get('stock_name', ''),
                
                # 日期信息
                'listing_date': None,  # 集思录待发转债无上市日期
                'record_date': b.get('record_date', ''),
                'apply_date': b.get('apply_date', ''),
                
                # 代码信息
                'apply_code': b.get('apply_code', ''),
                'ration_code': b.get('ration_code', ''),
                
                # 配售信息
                'per_share_amount': b.get('ration', 0),  # 每股配售额
                'issue_amount': b.get('amount', 0),       # 发行规模 (亿元)
                'convert_price': b.get('convert_price', 0),
                
                # 其他
                'credit_rating': b.get('rating', ''),
                'progress': b.get('progress', ''),
                'source': 'jisilu',
                
                # 集思录特有字段
                'record_price': b.get('record_price', 0),
                'progress_full': b.get('progress_full', ''),
            })
        return result
    
    def _normalize_eastmoney_bonds(self, bonds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        标准化东方财富数据格式
        
        东方财富字段:
        - bond_code, bond_name, stock_code, stock_name
        - listing_date, record_date
        - per_share_amount, issue_amount
        - credit_rating
        """
        result = []
        for b in bonds:
            result.append({
                # 基础信息
                'bond_code': b.get('bond_code', ''),
                'bond_name': b.get('bond_name', ''),
                'stock_code': b.get('stock_code', ''),
                'stock_name': b.get('stock_name', ''),
                
                # 日期信息
                'listing_date': b.get('listing_date', ''),
                'record_date': b.get('record_date', ''),
                'apply_date': None,  # 东方财富无申购日期
                
                # 代码信息
                'apply_code': '',
                'ration_code': '',
                
                # 配售信息
                'per_share_amount': b.get('per_share_amount', 0),
                'issue_amount': b.get('issue_amount', 0),
                'convert_price': 0,  # 东方财富需要额外获取
                
                # 其他
                'credit_rating': b.get('credit_rating', ''),
                'progress': '',
                'source': 'eastmoney',
                
                # 东方财富特有字段
                'first_profit': b.get('first_profit', 0),
            })
        return result
    
    def fetch_with_fallback(self, limit: int = 50) -> tuple:
        """
        获取转债列表，返回数据和使用的数据源
        
        Args:
            limit: 数量限制
            
        Returns:
            (bonds_list, source_name) 元组
            source_name: 'jisilu' | 'eastmoney' | 'none'
        """
        bonds = self.fetch_bonds(limit=limit)
        return bonds, self._source_used


# ==================== 工具函数 ====================

def find_trading_day(prices: Dict[str, Any], base_date: str, offset: int) -> Optional[str]:
    """
    查找偏移后的交易日日期
    
    Args:
        prices: 股价数据 {date: {...}}
        base_date: 基准日期 (YYYY-MM-DD)
        offset: 偏移天数 (负数=向前，正数=向后)
        
    Returns:
        找到的交易日日期字符串，找不到返回 None
    """
    sorted_dates = sorted(prices.keys())
    if not sorted_dates:
        return None
    
    # 找到基准日期的索引
    base_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= base_date:
            base_idx = i
            break
    
    if base_idx is None:
        base_idx = len(sorted_dates) - 1
    
    # 计算目标索引
    target_idx = base_idx + offset
    if offset < 0:
        target_idx = base_idx - abs(offset)
    
    if 0 <= target_idx < len(sorted_dates):
        return sorted_dates[target_idx]
    return None


def get_price_on_date(prices: Dict[str, Dict[str, float]], date: str, key: str = 'close') -> float:
    """
    获取指定日期的价格
    
    Args:
        prices: 股价数据
        date: 日期字符串
        key: 价格类型 (close/open/high/low)
        
    Returns:
        价格值，找不到返回 0
    """
    if date in prices:
        return prices[date].get(key, 0)
    return 0.0
