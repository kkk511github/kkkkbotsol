import sys
import io
import os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from config import config
import okx.MarketData as Market

print("测试OKX API连接...")
print(f"API Key: {config.OKX_API_KEY}")
print(f"USE_SERVER: {config.USE_SERVER}")

try:
    market_api = Market.MarketAPI(
        config.OKX_API_KEY, 
        config.OKX_SECRET, 
        config.OKX_PASSWORD, 
        use_server_time=True, 
        flag=config.USE_SERVER
    )
    
    print("\n尝试获取K线数据...")
    response = market_api.get_candlesticks(
        instId='SOL-USDT-SWAP',
        bar='5m',
        limit=10
    )
    
    print(f"✅ API连接成功！")
    print(f"获取到 {len(response['data'])} 条K线数据")
    
    if response['data']:
        print(f"\n最新K线数据示例:")
        latest = response['data'][0]
        print(f"时间戳: {latest[0]}")
        print(f"开盘价: {latest[1]}")
        print(f"最高价: {latest[2]}")
        print(f"最低价: {latest[3]}")
        print(f"收盘价: {latest[4]}")
        print(f"成交量: {latest[5]}")
        
except Exception as e:
    print(f"❌ API连接失败: {e}")
    import traceback
    traceback.print_exc()
