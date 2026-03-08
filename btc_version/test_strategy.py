import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from core.position_manager import PositionManager
from config import config

pm = PositionManager()

# 测试当前市场条件下的目标仓位计算
prob = 1.0  # short_prob = 1.0
money_flow_ratio = 0.348
volatility = 0.001497
reward_risk = 1.0

print("=" * 50)
print("策略参数检查")
print("=" * 50)
print(f"THRESHOLD_LONG: {config.THRESHOLD_LONG}")
print(f"THRESHOLD_SHORT: {config.THRESHOLD_SHORT}")
print(f"POSITION_MIN: {config.POSITION_MIN}")
print(f"POSITION_MAX: {config.POSITION_MAX}")
print(f"MIN_ADJUST_AMOUNT: {config.MIN_ADJUST_AMOUNT}")
print()

print("=" * 50)
print("目标仓位计算")
print("=" * 50)
print(f"输入参数:")
print(f"  prob (short_prob): {prob}")
print(f"  money_flow_ratio: {money_flow_ratio}")
print(f"  volatility: {volatility}")
print(f"  reward_risk: {reward_risk}")
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
print(f"final_ratio (目标仓位比例): {final_ratio}")
print()

# 计算实际目标仓位
equity = 600
price = 82.42
target_position = final_ratio * equity / price
print(f"目标仓位: {target_position} SOL")
print(f"目标仓位价值: ${abs(target_position * price):.2f}")
print(f"最小调整金额: ${config.MIN_ADJUST_AMOUNT}")
print()

if abs(target_position * price) >= config.MIN_ADJUST_AMOUNT and target_position != 0:
    print("✅ 应该触发交易!")
else:
    print("❌ 不会触发交易 - 目标仓位价值小于最小调整金额")
