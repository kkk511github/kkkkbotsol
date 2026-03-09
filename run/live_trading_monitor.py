# live_trading_monitor.py
import os
import sys
import time
import joblib
import traceback
import numpy as np
import pandas as pd
import asyncio
import pytz
from datetime import datetime
from core import ml_feature_engineering, signal_engine
from core.reward_risk import RewardRiskEstimator
from core.strategy_core import StrategyCore
from utils.utils import log_info, log_error, BASE_DIR
from config import config
from core.okx_api import OKXClient
from core.position_manager import PositionManager
from core.telegram_bot import TradingTelegramBot
from core.report_generator import ReportGenerator


class LiveTrader:
    def __init__(self, client):
        self.client = client
        self.position_manager = PositionManager()

        self.MIN_HOLD_BARS = config.MIN_HOLD_BARS
        self.ADD_THRESHOLD = config.ADD_THRESHOLD
        self.MAX_REBALANCE_RATIO = config.MAX_REBALANCE_RATIO
        self.MIN_ADJUST_AMOUNT = float(config.MIN_ADJUST_AMOUNT)

        # ===== 实盘状态 =====
        self.hold_bars = 0
        self.last_bar_ts = None
        self.current_position = 0.0
        self.entry_price = 0.0
        self.running = True  # 系统运行状态标志
        self.last_signal = {}  # 存储最新信号

        # ===== 模型/特征=====
        feature_path = os.path.join(BASE_DIR, config.FEATURE_LIST_PATH) if "BASE_DIR" in globals() else config.FEATURE_LIST_PATH
        self.feature_cols = joblib.load(feature_path)

        model_paths = {n: os.path.join(BASE_DIR, p) for n, p in config.MODEL_PATHS.items()} if "BASE_DIR" in globals() else config.MODEL_PATHS
        self.models = signal_engine.load_models(model_paths)
        self.model_weights = config.MODEL_WEIGHTS

        # ===== Telegram Bot =====
        self.telegram = TradingTelegramBot(self)  # 传递trader实例
        self.report_gen = ReportGenerator()
        self.telegram_enabled = bool(os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID'))

        self.reward_risk = self._load_reward_risk()
        self.core = StrategyCore(
            self.position_manager,
            threshold_long=config.THRESHOLD_LONG,
            threshold_short=config.THRESHOLD_SHORT,
            take_profit=config.TAKE_PROFIT,
            stop_loss=config.STOP_LOSS,
            min_hold_bars=self.MIN_HOLD_BARS,
            add_threshold=self.ADD_THRESHOLD,
            max_rebalance_ratio=self.MAX_REBALANCE_RATIO,
            min_adjust_amount=self.MIN_ADJUST_AMOUNT,
            reward_risk=float(self.reward_risk),
        )

    async def start_telegram(self):
        if self.telegram_enabled:
            try:
                await self.telegram.start()
                await self.telegram.send_trade_notification(
                    "🤖 系统启动", 0, 0, 0
                )
                log_info("[系统] Telegram Bot 已启动")
            except Exception as e:
                log_error(f"[系统] Telegram Bot 启动失败: {e}")
                self.telegram_enabled = False
        else:
            log_info("[系统] Telegram Bot 未配置，跳过启动")

    def start_trading(self):
        self.running = True
        log_info("[系统] 交易系统已启动")
        return True

    def stop_trading(self):
        self.running = False
        log_info("[系统] 交易系统已停止")
        return True

    def get_system_status(self):
        status = "🟢 运行中" if self.running else "🔴 已停止"
        return {
            "running": self.running,
            "status": status,
            "symbol": config.SYMBOL,
            "leverage": config.LEVERAGE,
            "position": self.current_position,
            "entry_price": self.entry_price
        }

    def _load_reward_risk(self):
        try:
            trades = self.client.fetch_recent_closed_trades()
            rr = RewardRiskEstimator()
            rr.batch_update(trades)
            val = float(rr.estimate())
            log_info(f"[风控] 奖励风险比 reward_risk={val:.4f}")
            return val
        except Exception as e:
            log_error(f"[风控] 奖励风险比获取失败，使用默认 1.0：{e}")
            return 1.0

    def _predict_latest_probs(self, merged_df: pd.DataFrame):
        row = merged_df.iloc[-1]
        X = row[self.feature_cols].values.reshape(1, -1).astype(float)
        X = pd.DataFrame(X, columns=self.feature_cols)

        weighted_sum = np.zeros(2)
        total_weight = float(sum(self.model_weights.values()))

        for name, model in self.models.items():
            prob = model.predict_proba(X)[0]
            w = float(self.model_weights.get(name, 1.0))
            weighted_sum += prob * w

        avg = weighted_sum / max(total_weight, 1e-9)
        long_prob, short_prob = float(avg[1]), float(avg[0])
        return long_prob, short_prob

    def _get_latest_features(self):
        data_dict = self.client.fetch_data()
        merged_df = ml_feature_engineering.merge_multi_period_features(data_dict)
        merged_df = ml_feature_engineering.add_advanced_features(merged_df)

        bar_ts = merged_df.index[-1]
        price = float(merged_df["5m_close"].iloc[-1])
        money_flow_ratio = float(merged_df["money_flow_ratio"].iloc[-1])

        if "volatility_15" in merged_df.columns and pd.notna(merged_df["volatility_15"].iloc[-1]):
            volatility = float(merged_df["volatility_15"].iloc[-1])
        else:
            merged_df["log_return"] = np.log(merged_df["5m_close"] / merged_df["5m_close"].shift(1))
            volatility = float(merged_df["log_return"].rolling(96).std().iloc[-1])

        long_prob, short_prob = self._predict_latest_probs(merged_df)
        return bar_ts, price, long_prob, short_prob, money_flow_ratio, volatility

    def _get_equity(self) -> float:
        account_balance = self.client.get_account_balance()
        if account_balance and 'data' in account_balance and len(account_balance['data']) > 0:
            return float(account_balance["data"][0].get("availEq", 0) or 0)
        return 0.0

    def _sync_after_trade(self):
        pos_qty2, entry_price2 = self._get_net_position()
        if pos_qty2 == 0:
            self.hold_bars = 0
        self.core.set_state(pos_qty2, entry_price2, self.hold_bars)
        _, _, self.hold_bars = self.core.get_state()
        self.current_position = pos_qty2
        self.entry_price = entry_price2

    def _get_net_position(self):
        long_pos, short_pos = self.client.get_position()

        if long_pos["size"] > 0 and short_pos["size"] > 0:
            log_error("[异常] 检测到同时多空持仓，尝试双边平仓清理")
            self.client.close_long_sz(long_pos["size"], config.LEVERAGE)
            self.client.close_short_sz(short_pos["size"], config.LEVERAGE)
            return 0.0, 0.0

        if long_pos["size"] > 0:
            return float(long_pos["size"]), float(long_pos.get("entry_price", 0) or 0)
        if short_pos["size"] > 0:
            return -float(short_pos["size"]), float(short_pos.get("entry_price", 0) or 0)
        return 0.0, 0.0

    def _get_signal_emoji(self, long_prob, short_prob):
        if long_prob > config.THRESHOLD_LONG:
            return "📈 做多"
        elif short_prob > config.THRESHOLD_SHORT:
            return "📉 做空"
        return "➖ 观望"

    def _get_signal_strength(self, prob):
        if prob > 0.8:
            return "🔥 极强"
        elif prob > 0.65:
            return "💪 强势"
        elif prob > 0.55:
            return "👍 中等"
        return "👎 弱势"

    async def run_once_on_new_bar(self):
        bar_ts, price, long_prob, short_prob, money_flow_ratio, volatility = self._get_latest_features()

        if self.last_bar_ts is not None and bar_ts == self.last_bar_ts:
            return
        self.last_bar_ts = bar_ts

        # 转换为北京时间 (UTC+8)
        try:
            if hasattr(bar_ts, 'tz_localize'):
                # 如果是datetime对象
                if bar_ts.tzinfo is None:
                    # 没有时区信息，先本地化为UTC
                    bar_ts_utc = bar_ts.tz_localize('UTC')
                else:
                    # 有时区信息，转换为UTC
                    bar_ts_utc = bar_ts.tz_convert('UTC')
                # 转换为北京时间
                bar_ts_beijing = bar_ts_utc.tz_convert('Asia/Shanghai')
                bar_ts_display = bar_ts_beijing.strftime('%Y-%m-%d %H:%M:%S')
            else:
                # 如果是字符串或其他格式
                bar_ts_display = str(bar_ts)
        except Exception as e:
            # 转换失败，使用原始值
            bar_ts_display = str(bar_ts)

        # 获取信号信息
        signal_direction = self._get_signal_emoji(long_prob, short_prob)
        signal_strength = self._get_signal_strength(max(long_prob, short_prob))

        # 中文日志输出
        log_info(f"[信号] 新K线 {bar_ts_display} | 价格: ${price:.4f} | 方向: {signal_direction} | "
                 f"做多: {long_prob*100:.1f}% | 做空: {short_prob*100:.1f}% | "
                 f"强度: {signal_strength} | 资金流: {money_flow_ratio:.3f} | 波动率: {volatility:.4f}")

        # 更新最新信号
        self.last_signal = {
            'direction': '做多' if long_prob > short_prob else '做空' if short_prob > long_prob else '观望',
            'long_prob': long_prob * 100,
            'short_prob': short_prob * 100,
            'strength': signal_strength,
            'money_flow_ratio': money_flow_ratio,
            'volatility': volatility,
            'timestamp': bar_ts_display,
        }

        pos_qty, entry_price = self._get_net_position()
        equity = self._get_equity()

        # 获取持仓信息
        position_emoji = "📦 空仓"
        if pos_qty > 0:
            position_emoji = f"📈 做多 {abs(pos_qty):.4f} SOL"
        elif pos_qty < 0:
            position_emoji = f"📉 做空 {abs(pos_qty):.4f} SOL"

        log_info(f"[账户] 当前持仓: {position_emoji} | 可用资金: ${equity:.2f}")

        if pos_qty == 0:
            self.hold_bars = 0
        self.core.set_state(pos_qty, entry_price, self.hold_bars)

        out = self.core.on_bar(
            price=price,
            equity=equity,
            long_prob=long_prob,
            short_prob=short_prob,
            money_flow_ratio=money_flow_ratio,
            volatility=volatility,
        )

        action = out["action"]
        delta = float(out["delta_qty"])

        if action == "CLOSE":
            # 计算盈亏
            pnl = 0
            if pos_qty != 0:
                if pos_qty > 0:
                    pnl = (price - entry_price) * abs(pos_qty)
                else:
                    pnl = (entry_price - price) * abs(pos_qty)

            close_reason = "止盈/止损" if out.get('reason') == 'TP/SL' else "反向平仓"

            if pos_qty > 0:
                self.client.close_long_sz(abs(pos_qty), config.LEVERAGE)
            elif pos_qty < 0:
                self.client.close_short_sz(abs(pos_qty), config.LEVERAGE)

            self._sync_after_trade()

            # 记录交易
            action_name = f"平仓 ({close_reason})"
            self.report_gen.record_trade(action_name, price, pos_qty, pnl, long_prob, short_prob, money_flow_ratio, volatility)
            self.telegram.record_trade(action_name, price, pos_qty, pnl)

            # 发送通知
            if self.telegram_enabled:
                await self.telegram.send_trade_notification(action_name, price, pos_qty, pnl)

            pnl_emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "➖"
            log_info(f"[交易] 执行平仓 | 原因: {close_reason} | 盈亏: {pnl_emoji} ${pnl:+.2f} | 价格: ${price:.4f}")
            return

        elif action == "OPEN":
            qty = abs(delta)
            direction = "开多" if delta > 0 else "开空"

            if delta > 0:
                self.client.open_long_sz(qty, config.LEVERAGE)
            else:
                self.client.open_short_sz(qty, config.LEVERAGE)

            self._sync_after_trade()

            # 记录交易
            self.report_gen.record_trade(direction, price, delta, 0, long_prob, short_prob, money_flow_ratio, volatility)
            self.telegram.record_trade(direction, price, delta, 0)

            # 发送通知
            if self.telegram_enabled:
                await self.telegram.send_trade_notification(direction, price, delta, 0)
                await self.telegram.send_signal_alert(long_prob, short_prob, price)

            target_pct = out['target_ratio'] * 100
            log_info(f"[交易] 执行开仓 | 方向: {direction} | 目标仓位: {target_pct:.1f}% | "
                     f"数量: {qty:.4f} SOL | 价格: ${price:.4f}")
            return

        elif action == "REBALANCE":
            qty = abs(delta)
            rebalance_type = "加仓" if delta > 0 else "减仓"
            current_direction = "做多" if pos_qty > 0 else "做空"

            if delta > 0:
                self.client.open_long_sz(qty, config.LEVERAGE)
            else:
                self.client.open_short_sz(qty, config.LEVERAGE)

            self._sync_after_trade()

            # 记录交易
            action_name = f"{current_direction}{rebalance_type}"
            self.report_gen.record_trade(action_name, price, delta, 0, long_prob, short_prob, money_flow_ratio, volatility)

            log_info(f"[交易] 执行调仓 | 类型: {current_direction}{rebalance_type} | "
                     f"变化量: {abs(delta):.4f} SOL | 价格: ${price:.4f}")
            return

        elif action == "HOLD":
            self._sync_after_trade()
            hold_reason = out.get('reason', '保持')

            if 'MinHold' in hold_reason:
                log_info(f"[持仓] 保持仓位 | 原因: 最小持有期内 ({self.hold_bars}/{self.MIN_HOLD_BARS})")
            elif 'FlatNoSignal' in hold_reason:
                log_info(f"[持仓] 保持空仓 | 原因: 无明确交易信号")
            elif 'SameDirNoRebalance' in hold_reason:
                log_info(f"[持仓] 保持仓位 | 原因: 调仓条件不满足")
            else:
                log_info(f"[持仓] 保持仓位 | 原因: {hold_reason}")
            return


async def main():
    POLL_SEC = config.POLL_SEC
    client = OKXClient()
    trader = LiveTrader(client)

    # 启动Telegram Bot
    await trader.start_telegram()

    log_info("🟢 [系统] 实盘交易系统已启动，开始监控市场...")
    log_info(f"[配置] 交易品种: {config.SYMBOL} | 杠杆: {config.LEVERAGE}x | 轮询间隔: {POLL_SEC}秒")

    while True:
        try:
            # 检查系统是否运行
            if trader.running:
                await trader.run_once_on_new_bar()
            else:
                # 系统已停止，只更新状态，不执行交易
                log_info("[系统] 交易系统已暂停，等待启动...")
        except Exception as e:
            log_error(f"[错误] 实盘循环异常: {e}")
            log_error(traceback.format_exc())

        await asyncio.sleep(int(POLL_SEC))


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
