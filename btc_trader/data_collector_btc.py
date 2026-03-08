import os
import sys
import pandas as pd
import time
from datetime import datetime, timedelta

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from core.okx_api import OKXClient
from utils.utils import log_info, log_error, BASE_DIR

class DataCollectorBTC:
    def __init__(self):
        self.client = OKXClient()
        self.data_dir = os.path.join(BASE_DIR, 'data')
        os.makedirs(self.data_dir, exist_ok=True)
    
    def fetch_historical_data(self, symbol, timeframe, days=30):
        """获取历史数据，分批获取以突破API限制"""
        log_info(f"开始获取 {symbol} {timeframe} 历史数据，最近{days}天...")
        
        all_data = []
        current_time = int(datetime.now().timestamp() * 1000)
        
        # 计算需要获取的批次
        batch_size = 1000  # API限制
        total_batches = (days * 24 * 60 * 60 * 1000) // (batch_size * 5 * 60 * 1000) + 1
        
        for batch in range(total_batches):
            try:
                # 计算时间范围
                since = current_time - (batch + 1) * batch_size * 5 * 60 * 1000
                until = current_time - batch * batch_size * 5 * 60 * 1000
                
                # 获取数据
                ohlcv = self.client.exchange.fetch_ohlcv(
                    symbol, 
                    timeframe, 
                    since=since,
                    limit=batch_size
                )
                
                if ohlcv:
                    all_data.extend(ohlcv)
                    log_info(f"批次 {batch+1}/{total_batches}: 获取 {len(ohlcv)} 根K线")
                
                # 避免API限流
                time.sleep(0.5)
                
            except Exception as e:
                log_error(f"批次 {batch+1} 获取失败: {e}")
                continue
        
        # 转换为DataFrame
        if all_data:
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df.sort_index()
            df = df[~df.index.duplicated(keep='last')]
            
            log_info(f"✅ 总共获取 {len(df)} 根K线")
            log_info(f"时间范围: {df.index[0]} 到 {df.index[-1]}")
            
            return df
        else:
            log_error("未获取到任何数据")
            return None
    
    def save_data(self, df, symbol, timeframe):
        """保存数据到文件"""
        filename = f"{symbol}_{timeframe}.csv"
        filepath = os.path.join(self.data_dir, filename)
        df.to_csv(filepath)
        log_info(f"✅ 数据已保存到: {filepath}")
        return filepath
    
    def load_data(self, symbol, timeframe):
        """从文件加载数据"""
        filename = f"{symbol}_{timeframe}.csv"
        filepath = os.path.join(self.data_dir, filename)
        
        if os.path.exists(filepath):
            df = pd.read_csv(filepath, index_col=0, parse_dates=True)
            log_info(f"✅ 从文件加载 {len(df)} 根K线: {filepath}")
            return df
        else:
            log_info(f"文件不存在: {filepath}")
            return None

def collect_btc_data(days=30):
    """收集BTC历史数据"""
    collector = DataCollectorBTC()
    
    # 定义需要获取的数据
    data_configs = [
        (config.SYMBOL, '5m', days),
        (config.SYMBOL, '15m', days),
        (config.SYMBOL, '1h', days),
    ]
    
    for symbol, timeframe, days in data_configs:
        log_info(f"\n{'='*60}")
        log_info(f"处理: {symbol} {timeframe}")
        log_info(f"{'='*60}")
        
        # 获取数据
        df = collector.fetch_historical_data(symbol, timeframe, days)
        if df is not None:
            collector.save_data(df, symbol, timeframe)
    
    log_info(f"\n{'='*60}")
    log_info("BTC数据收集完成！")
    log_info(f"{'='*60}")

if __name__ == '__main__':
    collect_btc_data(days=30)
