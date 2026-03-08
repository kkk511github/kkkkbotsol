import os
import sys
import pandas as pd
import numpy as np
from core import ml_feature_engineering, okx_api
from config import config

# 获取数据
client = okx_api.OKXClient()

# 获取2周数据
from datetime import datetime, timedelta
total_needed = 4032  # 2周数据
all_ohlcv = []
end_time = datetime.now()

print("获取历史数据...")
while len(all_ohlcv) < total_needed:
    limit = min(1000, total_needed - len(all_ohlcv))
    since = int((end_time - timedelta(minutes=5*limit)).timestamp() * 1000)
    
    try:
        ohlcv = client.exchange.fetch_ohlcv(config.SYMBOL, '5m', since=since, limit=limit)
        if len(ohlcv) == 0:
            break
        all_ohlcv = ohlcv + all_ohlcv
        end_time = datetime.fromtimestamp(ohlcv[0][0] / 1000)
    except Exception as e:
        print(f"获取数据失败: {e}")
        break

print(f"成功获取 {len(all_ohlcv)} 根K线数据")

# 数据处理
df_5m = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
df_5m['timestamp'] = pd.to_datetime(df_5m['timestamp'], unit='ms')
df_5m.set_index('timestamp', inplace=True)
df_5m = df_5m[~df_5m.index.duplicated(keep='first')]
df_5m.columns = ['open', 'high', 'low', 'close', 'volume']

# 特征工程
all_data = {
    '5m': df_5m.copy(),
    '15m': df_5m.copy(),
    '1H': df_5m.copy()
}

merged_df = ml_feature_engineering.merge_multi_period_features(all_data)
merged_df = ml_feature_engineering.add_advanced_features(merged_df)

print(f"数据形状: {merged_df.shape}")

# 加载模型
import joblib
from core.predict import load_models

models = load_models()
print(f"加载的模型: {list(models.keys())}")

# 预测概率
from core.signal_engine import SignalEngine
signal_engine = SignalEngine()

print("\n计算信号概率...")
probs = []
for i in range(len(merged_df)):
    row = merged_df.iloc[i]
    prob = signal_engine.get_signal(row)
    probs.append(prob)

# 分析概率分布
probs_df = pd.DataFrame(probs, columns=['long_prob', 'short_prob'])
print("\n概率分布统计:")
print(f"多头概率均值: {probs_df['long_prob'].mean():.4f}")
print(f"多头概率中位数: {probs_df['long_prob'].median():.4f}")
print(f"多头概率最大值: {probs_df['long_prob'].max():.4f}")
print(f"多头概率最小值: {probs_df['long_prob'].min():.4f}")
print(f"\n空头概率均值: {probs_df['short_prob'].mean():.4f}")
print(f"空头概率中位数: {probs_df['short_prob'].median():.4f}")
print(f"空头概率最大值: {probs_df['short_prob'].max():.4f}")
print(f"空头概率最小值: {probs_df['short_prob'].min():.4f}")

# 统计不同阈值下的信号数量
print("\n不同阈值下的信号数量:")
thresholds = [0.5, 0.6, 0.7, 0.75, 0.8, 0.84, 0.9]
for threshold in thresholds:
    long_count = (probs_df['long_prob'] > threshold).sum()
    short_count = (probs_df['short_prob'] > threshold).sum()
    print(f"阈值 {threshold:.2f}: 多头信号 {long_count}, 空头信号 {short_count}")

print("\n分析完成！")