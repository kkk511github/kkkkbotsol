from core.position_manager import PositionManager
from config import config

pm = PositionManager()

# 当前市场参数
prob = 0.864
money_flow_ratio = 0.015
volatility = 0.002482
reward_risk = 1.0
price = 82.39
equity = 600

print("=" * 60)
print("仓位计算调试")
print("=" * 60)
print(f"输入参数:")
print(f"  prob: {prob}")
print(f"  money_flow_ratio: {money_flow_ratio}")
print(f"  volatility: {volatility}")
print(f"  reward_risk: {reward_risk}")
print(f"  price: ${price}")
print(f"  equity: ${equity}")
print()

# 分步计算
signal_strength = max(0, prob - 0.5) * 2
print(f"signal_strength: {signal_strength}")

kelly_weight = pm.kelly_fraction(prob, reward_risk)
print(f"kelly_weight: {kelly_weight}")

multi_factor = pm.multi_factor_score(prob, money_flow_ratio, volatility)
print(f"multi_factor: {multi_factor}")

blended_ratio = config.POSITION_MIN + signal_strength * (config.POSITION_MAX - config.POSITION_MIN)
print(f"blended_ratio: {blended_ratio}")

final_ratio = blended_ratio * kelly_weight * multi_factor
print(f"final_ratio: {final_ratio}")
print()

# 计算目标仓位
target_position = final_ratio * equity / price
position_value = abs(target_position * price)

print(f"目标仓位: {target_position:.4f} SOL")
print(f"仓位价值: ${position_value:.2f}")
print(f"最小调整金额: ${config.MIN_ADJUST_AMOUNT}")
print()

if position_value >= config.MIN_ADJUST_AMOUNT:
    print("✅ 应该触发交易!")
else:
    print("❌ 不会触发交易 - 目标仓位价值小于最小调整金额")
    print(f"  需要 >= ${config.MIN_ADJUST_AMOUNT}, 实际 ${position_value:.2f}")
