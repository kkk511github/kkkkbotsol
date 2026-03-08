import os
import joblib
import numpy as np
import pandas as pd
from config import config
from core import ml_feature_engineering, signal_engine
from core.position_manager import PositionManager
from core.strategy_core import StrategyCore
from core.okx_api import OKXClient
from core.reward_risk import RewardRiskEstimator

print("=" * 60)
print("实盘系统诊断测试")
print("=" * 60)

# 1. 检查模型加载
print("\n1. 模型加载检查")
feature_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config.FEATURE_LIST_PATH)
feature_cols = joblib.load(feature_path)
print(f"特征列表加载成功: {len(feature_cols)} 个特征")

model_paths = {n: os.path.join(os.path.dirname(os.path.abspath(__file__)), p) for n, p in config.MODEL_PATHS.items()}
models = signal_engine.load_models(model_paths)
print(f"模型加载成功: {list(models.keys())}")

# 2. 获取最新数据
print("\n2. 获取市场数据")
client = OKXClient()
data_dict = client.fetch_data()
merged_df = ml_feature_engineering.merge_multi_period_features(data_dict)
merged_df = ml_feature_engineering.add_advanced_features(merged_df)

row = merged_df.iloc[-1]
price = float(merged_df["5m_close"].iloc[-1])
money_flow_ratio = float(merged_df["money_flow_ratio"].iloc[-1])
volatility = float(merged_df["volatility_15"].iloc[-1]) if "volatility_15" in merged_df.columns else 0.001

print(f"当前价格: ${price}")
print(f"资金流比率: {money_flow_ratio}")
print(f"波动率: {volatility}")

# 3. 模型预测
print("\n3. 模型预测")
X = row[feature_cols].values.reshape(1, -1).astype(float)
X = pd.DataFrame(X, columns=feature_cols)

weighted_sum = np.zeros(2)
total_weight = float(sum(config.MODEL_WEIGHTS.values()))

for name, model in models.items():
    prob = model.predict_proba(X)[0]
    w = float(config.MODEL_WEIGHTS.get(name, 1.0))
    print(f"  {name}: prob[0]={prob[0]:.4f}, prob[1]={prob[1]:.4f}, weight={w}")
    weighted_sum += prob * w

avg = weighted_sum / max(total_weight, 1e-9)
long_prob, short_prob = float(avg[1]), float(avg[0])

print(f"\n融合结果:")
print(f"  avg[0] (做空概率): {avg[0]:.4f}")
print(f"  avg[1] (做多概率): {avg[1]:.4f}")
print(f"  long_prob: {long_prob:.4f}")
print(f"  short_prob: {short_prob:.4f}")

# 4. 策略判断
print("\n4. 策略判断")
print(f"THRESHOLD_LONG: {config.THRESHOLD_LONG}")
print(f"THRESHOLD_SHORT: {config.THRESHOLD_SHORT}")

if long_prob > config.THRESHOLD_LONG:
    print(f"满足做多条件: {long_prob} > {config.THRESHOLD_LONG}")
elif short_prob > config.THRESHOLD_SHORT:
    print(f"满足做空条件: {short_prob} > {config.THRESHOLD_SHORT}")
else:
    print(f"不满足任何条件")
    print(f"  long_prob ({long_prob}) <= {config.THRESHOLD_LONG}")
    print(f"  short_prob ({short_prob}) <= {config.THRESHOLD_SHORT}")

# 5. 仓位计算
print("\n5. 仓位计算")
pm = PositionManager()
reward_risk = 1.0

try:
    trades = client.fetch_recent_closed_trades()
    rr = RewardRiskEstimator()
    rr.batch_update(trades)
    reward_risk = float(rr.estimate())
except:
    pass

print(f"reward_risk: {reward_risk}")

if short_prob > config.THRESHOLD_SHORT:
    target_ratio = pm.calculate_target_ratio(short_prob, money_flow_ratio, volatility, reward_risk)
    print(f"target_ratio: {target_ratio}")
    
    equity = 600
    target_position = -target_ratio * equity / price
    position_value = abs(target_position * price)
    
    print(f"目标仓位: {target_position:.4f} SOL")
    print(f"仓位价值: ${position_value:.2f}")
    print(f"最小调整金额: ${config.MIN_ADJUST_AMOUNT}")
    
    if position_value >= config.MIN_ADJUST_AMOUNT:
        print("应该触发交易!")
    else:
        print("不满足最小调整金额")
