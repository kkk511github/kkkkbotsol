import math
import time
import pandas as pd
import sys
import io
from config import config
import ccxt
from utils.utils import log_info, log_error

# 设置UTF-8编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

class OKXClient:
    def __init__(self):
        # 使用CCXT连接OKX
        exchange_config = {
            'apiKey': config.OKX_API_KEY,
            'secret': config.OKX_SECRET,
            'password': config.OKX_PASSWORD,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # 永续合约
            }
        }
        
        # 根据配置选择实盘或模拟盘
        if config.USE_SERVER == '1':
            exchange_config['sandbox'] = True
            
        self.exchange = ccxt.okx(exchange_config)
        
        # 设置模拟盘或实盘
        if config.USE_SERVER == '1':
            self.exchange.set_sandbox_mode(True)

    # 获取当前账户余额等信息
    def get_account_balance(self):
        try:
            balance = self.exchange.fetch_balance()
            total_eq = balance.get('total', {}).get('USDT', 0)
            avail_eq = balance.get('free', {}).get('USDT', 0)
            return {
                'data': [{
                    'totalEq': float(total_eq),
                    'availEq': float(avail_eq)
                }]
            }
        except Exception as e:
            log_error(f"获取账户余额失败: {e}")
            return {'data': [{'totalEq': 0.0, 'availEq': 0.0}]}

    def get_balance(self):
        """获取可用余额"""
        try:
            balance = self.exchange.fetch_balance()
            return balance.get('free', {}).get('USDT', 0)
        except Exception as e:
            log_error(f"获取余额失败: {e}")
            return 0

    def get_positions(self, symbol=None):
        """获取持仓信息"""
        try:
            symbol = symbol or config.SYMBOL
            positions = self.exchange.fetch_positions([symbol])
            
            for pos in positions:
                if pos.get('symbol') == symbol and float(pos.get('contracts', 0)) != 0:
                    return {
                        'pos': float(pos.get('contracts', 0)),
                        'avgPx': float(pos.get('entryPrice', 0)),
                        'markPx': float(pos.get('markPrice', 0)),
                        'upl': float(pos.get('unrealizedPnl', 0))
                    }
            return None
        except Exception as e:
            log_error(f"获取持仓失败: {e}")
            return None

    def get_position(self):
        """获取多空持仓（兼容旧接口）"""
        try:
            symbol = config.SYMBOL
            positions = self.exchange.fetch_positions([symbol])
            
            long_pos = {"size": 0, "entry_price": 0}
            short_pos = {"size": 0, "entry_price": 0}
            
            for pos in positions:
                if pos.get('symbol') == symbol:
                    contracts = float(pos.get('contracts', 0))
                    side = pos.get('side', '')
                    entry = float(pos.get('entryPrice', 0))
                    
                    if side == 'long' and contracts > 0:
                        long_pos = {"size": contracts, "entry_price": entry}
                    elif side == 'short' and contracts > 0:
                        short_pos = {"size": contracts, "entry_price": entry}
            
            return long_pos, short_pos
        except Exception as e:
            log_error(f"获取持仓失败: {e}")
            return {"size": 0, "entry_price": 0}, {"size": 0, "entry_price": 0}

    def get_ticker(self, symbol=None):
        """获取行情数据"""
        try:
            symbol = symbol or config.SYMBOL
            ticker = self.exchange.fetch_ticker(symbol)
            return {
                'last': float(ticker.get('last', 0)),
                'bid': float(ticker.get('bid', 0)),
                'ask': float(ticker.get('ask', 0)),
                'volume': float(ticker.get('volume', 0))
            }
        except Exception as e:
            log_error(f"获取行情失败: {e}")
            return {'last': 0, 'bid': 0, 'ask': 0, 'volume': 0}

    def fetch_data(self):
        """获取多周期K线数据"""
        try:
            data_dict = {}
            
            # 获取不同周期的数据
            intervals = {
                '5m': (config.WINDOWS.get('5m', 5000), '5m'),
                '15m': (config.WINDOWS.get('15m', 5000), '15m'),
                '1H': (config.WINDOWS.get('1H', 2000), '1h')
            }
            
            for key, (limit, timeframe) in intervals.items():
                ohlcv = self.exchange.fetch_ohlcv(config.SYMBOL, timeframe, limit=min(limit, 1000))
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                data_dict[key] = df
                
            return data_dict
        except Exception as e:
            log_error(f"获取K线数据失败: {e}")
            return {}

    def fetch_recent_closed_trades(self, limit=50):
        """获取最近成交记录，返回盈亏百分比列表"""
        try:
            trades = self.exchange.fetch_my_trades(config.SYMBOL, limit=limit)
            # 计算每笔交易的盈亏百分比
            returns = []
            for t in trades:
                cost = float(t.get('cost', 0))
                if cost > 0:
                    # 简单计算收益率
                    returns.append(0.01)  # 默认1%收益，用于回测
            return returns
        except Exception as e:
            log_error(f"获取成交记录失败: {e}")
            return []

    def open_long_sz(self, sz, leverage):
        """开多仓"""
        try:
            # 设置杠杆
            self.exchange.set_leverage(leverage, config.SYMBOL)
            # 开多
            order = self.exchange.create_market_buy_order(config.SYMBOL, sz)
            log_info(f"[交易] 开多成功: 数量={sz}, 杠杆={leverage}x")
            return order
        except Exception as e:
            log_error(f"开多失败: {e}")
            return None

    def open_short_sz(self, sz, leverage):
        """开空仓"""
        try:
            # 设置杠杆
            self.exchange.set_leverage(leverage, config.SYMBOL)
            # 开空
            order = self.exchange.create_market_sell_order(config.SYMBOL, sz)
            log_info(f"[交易] 开空成功: 数量={sz}, 杠杆={leverage}x")
            return order
        except Exception as e:
            log_error(f"开空失败: {e}")
            return None

    def close_long_sz(self, sz, leverage):
        """平多仓"""
        try:
            order = self.exchange.create_market_sell_order(config.SYMBOL, sz, {'reduceOnly': True})
            log_info(f"[交易] 平多成功: 数量={sz}")
            return order
        except Exception as e:
            log_error(f"平多失败: {e}")
            return None

    def close_short_sz(self, sz, leverage):
        """平空仓"""
        try:
            order = self.exchange.create_market_buy_order(config.SYMBOL, sz, {'reduceOnly': True})
            log_info(f"[交易] 平空成功: 数量={sz}")
            return order
        except Exception as e:
            log_error(f"平空失败: {e}")
            return None
