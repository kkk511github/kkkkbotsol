# core/strategy_core.py
import numpy as np
from config import config

class StrategyCore:

    def __init__(
        self,
        position_manager,
        *,
        threshold_long: float,
        threshold_short: float,
        take_profit: float,
        stop_loss: float,
        min_hold_bars: int = 8,
        add_threshold: float = 0.15,
        max_rebalance_ratio: float = 0.3,
        min_adjust_amount: float = 10.0,
        reward_risk: float = 1.0,
    ):
        self.pm = position_manager

        self.threshold_long = float(threshold_long)
        self.threshold_short = float(threshold_short)
        self.take_profit = float(take_profit)
        self.stop_loss = float(stop_loss)

        self.min_hold_bars = int(min_hold_bars)
        self.add_threshold = float(add_threshold)
        self.max_rebalance_ratio = float(max_rebalance_ratio)
        self.min_adjust_amount = float(min_adjust_amount)

        self.reward_risk = float(reward_risk)

        self.position = 0.0
        self.entry_price = 0.0
        self.hold_bars = 0
        self.peak_price = 0.0  # 移动止损：跟踪最高价格
        self.trailing_stop_pct = 0.03  # 移动止损回撤比例 3%
        self.break_even_pct = 0.02  # 保本止损：盈利2%后启动

    def set_state(self, position: float, entry_price: float, hold_bars: int = None):
        self.position = float(position)
        self.entry_price = float(entry_price)
        if hold_bars is not None:
            self.hold_bars = int(hold_bars)
        # 重置移动止损跟踪价格
        if position == 0:
            self.peak_price = 0.0
        elif self.peak_price == 0.0:
            self.peak_price = float(entry_price)

    def get_state(self):
        return self.position, self.entry_price, self.hold_bars

    def on_bar(
        self,
        *,
        price: float,
        equity: float,
        long_prob: float,
        short_prob: float,
        money_flow_ratio: float,
        volatility: float,
    ):
        """
        单根 5m bar 决策一次（与回测一致）
        """
        price = float(price)
        equity = float(equity)
        pos = float(self.position)

        # ======================
        # 1) 持仓 -> 止盈止损（含移动止损和保本止损）
        # ======================
        if pos != 0:
            pnl_pct = (price - self.entry_price) / self.entry_price if pos > 0 else (self.entry_price - price) / self.entry_price
            
            # 更新最高价格（用于移动止损）
            if pos > 0:  # 做多
                if price > self.peak_price:
                    self.peak_price = price
            else:  # 做空
                if price < self.peak_price or self.peak_price == 0:
                    self.peak_price = price
            
            # 1.1 固定止盈止损
            if pnl_pct >= self.take_profit or pnl_pct <= -self.stop_loss:
                delta_qty = -pos
                self.position = 0.0
                self.entry_price = 0.0
                self.hold_bars = 0
                self.peak_price = 0.0
                return {
                    "action": "CLOSE",
                    "delta_qty": delta_qty,
                    "target_ratio": 0.0,
                    "target_position": 0.0,
                    "reason": "TP/SL",
                }
            
            # 1.2 移动止损：盈利超过保本阈值后启动
            if pnl_pct >= self.break_even_pct:
                # 计算从最高点的回撤
                if pos > 0:  # 做多
                    drawdown_from_peak = (self.peak_price - price) / self.peak_price
                else:  # 做空
                    drawdown_from_peak = (price - self.peak_price) / self.peak_price
                
                # 如果回撤超过阈值，触发移动止损
                if drawdown_from_peak >= self.trailing_stop_pct:
                    delta_qty = -pos
                    self.position = 0.0
                    self.entry_price = 0.0
                    self.hold_bars = 0
                    self.peak_price = 0.0
                    return {
                        "action": "CLOSE",
                        "delta_qty": delta_qty,
                        "target_ratio": 0.0,
                        "target_position": 0.0,
                        "reason": "TrailingStop",
                    }

        # ======================
        # 2) 计算目标仓位档位
        # ======================
        target_ratio = 0.0

        if long_prob > self.threshold_long:
            target_ratio = float(self.pm.calculate_target_ratio(long_prob, money_flow_ratio, volatility, self.reward_risk))
        elif short_prob > self.threshold_short:
            target_ratio = -float(self.pm.calculate_target_ratio(short_prob, money_flow_ratio, volatility, self.reward_risk))

        # 计算目标名义金额（考虑杠杆）
        # target_ratio 是占本金的比例，乘以杠杆得到名义仓位
        target_notional = target_ratio * equity * config.LEVERAGE
        target_position = target_notional / price

        # ======================
        # 3) 空仓 -> 只允许开仓
        # ======================
        if pos == 0:
            if abs(target_notional) >= self.min_adjust_amount and target_position != 0:
                self.position = target_position
                self.entry_price = price
                self.hold_bars = 0
                self.peak_price = price  # 初始化移动止损跟踪价格
                return {
                    "action": "OPEN",
                    "delta_qty": target_position,
                    "target_ratio": target_ratio,
                    "target_position": target_position,
                    "reason": "OpenFromFlat",
                }
            return {
                "action": "HOLD",
                "delta_qty": 0.0,
                "target_ratio": target_ratio,
                "target_position": target_position,
                "reason": "FlatNoSignal",
            }

        # ======================
        # 4) 持仓 -> 最小持有期
        # ======================
        self.hold_bars += 1
        if self.hold_bars < self.min_hold_bars:
            return {
                "action": "HOLD",
                "delta_qty": 0.0,
                "target_ratio": target_ratio,
                "target_position": target_position,
                "reason": f"MinHold({self.hold_bars}/{self.min_hold_bars})",
            }

        # ======================
        # 5) 同方向 -> 分段加 / 减仓
        # ======================
        same_direction = (pos > 0 and target_position > 0) or (pos < 0 and target_position < 0)

        if same_direction:
            # 计算仓位差异（币的数量）
            delta = target_position - pos
            
            # 限制单次调仓幅度
            max_delta = self.max_rebalance_ratio * abs(pos)
            delta = float(np.clip(delta, -max_delta, max_delta))

            # 检查是否满足最小调整金额
            if abs(delta * price) >= self.min_adjust_amount:
                self.position = pos + delta
                return {
                    "action": "REBALANCE",
                    "delta_qty": delta,
                    "target_ratio": target_ratio,
                    "target_position": target_position,
                    "reason": "SameDirRebalance",
                }

            return {
                "action": "HOLD",
                "delta_qty": 0.0,
                "target_ratio": target_ratio,
                "target_position": target_position,
                "reason": "SameDirNoRebalance",
            }

        # ======================
        # 6) 反向信号 -> 必须先清仓
        # ======================
        if abs(target_position) > 0:
            delta_qty = -pos
            self.position = 0.0
            self.entry_price = 0.0
            self.hold_bars = 0
            return {
                "action": "CLOSE",
                "delta_qty": delta_qty,
                "target_ratio": target_ratio,
                "target_position": target_position,
                "reason": "ReverseClose",
            }

        return {
            "action": "HOLD",
            "delta_qty": 0.0,
            "target_ratio": target_ratio,
            "target_position": target_position,
            "reason": "NoSignalKeep",
        }
