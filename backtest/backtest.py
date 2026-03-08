import os
from datetime import datetime
import csv
import joblib
import traceback
from core.strategy_core import StrategyCore
import time
import numpy as np
import pandas as pd
from tqdm import tqdm
from core import position_manager, okx_api, ml_feature_engineering, signal_engine
from config import config
from core.reward_risk import RewardRiskEstimator
from utils.utils import log_info, log_error,LOGS_DIR


class Backtester:
    def __init__(self, interval, window):
        self.interval = interval
        self.window = window
        self.in_high_conf = False
        self.hold_bars = 0
        self.peak_price = None

        # 拉取多周期数据以及计算reward_risk
        self.data_dict,self.reward_risk = self._load_data()

        # 特征工程
        merged_df = ml_feature_engineering.merge_multi_period_features(self.data_dict)
        merged_df = ml_feature_engineering.add_advanced_features(merged_df)
        self.data = merged_df

        # 读取训练时的特征列表
        self.feature_cols = joblib.load(config.FEATURE_LIST_PATH)

        # 加载模型与权重
        self.models = signal_engine.load_models(config.MODEL_PATHS)
        self.model_weights = config.MODEL_WEIGHTS

        # 初始化仓位和资金
        self.position = 0
        self.entry_price = 0
        self.balance = config.INITIAL_BALANCE
        self.max_balance = self.balance
        self.trade_log = []
        self.fee_rate = config.FEE_RATE

        # 初始化 position_manager
        self.position_manager = position_manager.PositionManager()
        # ✅ 统一核心策略（以回测为准）
        self.core = StrategyCore(
            self.position_manager,
            threshold_long=config.THRESHOLD_LONG,
            threshold_short=config.THRESHOLD_SHORT,
            take_profit=config.TAKE_PROFIT,
            stop_loss=config.STOP_LOSS,
            min_hold_bars=config.MIN_HOLD_BARS,
            add_threshold=config.ADD_THRESHOLD,
            max_rebalance_ratio=config.MAX_REBALANCE_RATIO,
            min_adjust_amount=float(config.MIN_ADJUST_AMOUNT),
            reward_risk=float(self.reward_risk),
        )

    def _load_data(self):
        log_info(f"从OKX拉取历史数据: {self.interval}, {self.window}根K线")
        client = okx_api.OKXClient()
        trades = client.fetch_recent_closed_trades()
        rr_estimator=RewardRiskEstimator()
        rr_estimator.batch_update(trades)
        reward_risk = rr_estimator.estimate()

        # 直接使用5分钟数据，获取更多历史数据
        import pandas as pd
        
        # 2周数据 = 14天 * 24小时 * 12根/小时 = 4032根K线
        # OKX API限制每次最多1000根，需要分批获取
        total_needed = min(self.window, 4032)  # 最多2周数据
        all_ohlcv = []
        
        # 计算起始时间（2周前）
        from datetime import datetime, timedelta
        end_time = datetime.now()
        
        # 分批获取数据，每次最多1000根
        while len(all_ohlcv) < total_needed:
            limit = min(1000, total_needed - len(all_ohlcv))
            since = int((end_time - timedelta(minutes=5*limit)).timestamp() * 1000)
            
            try:
                ohlcv = client.exchange.fetch_ohlcv(config.SYMBOL, '5m', since=since, limit=limit)
                if len(ohlcv) == 0:
                    break
                all_ohlcv = ohlcv + all_ohlcv  # 新数据在前面
                end_time = datetime.fromtimestamp(ohlcv[0][0] / 1000)
            except Exception as e:
                log_error(f"获取数据失败: {e}")
                break
        
        df_5m = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_5m['timestamp'] = pd.to_datetime(df_5m['timestamp'], unit='ms')
        df_5m.set_index('timestamp', inplace=True)
        df_5m = df_5m[~df_5m.index.duplicated(keep='first')]  # 去重
        
        # 重命名列为标准格式
        df_5m.columns = ['open', 'high', 'low', 'close', 'volume']
        
        # 为了兼容多周期特征工程，使用相同的5分钟数据作为所有周期
        all_data = {
            '5m': df_5m.copy(),
            '15m': df_5m.copy(),
            '1H': df_5m.copy()
        }
        
        log_info(f"成功获取 {len(df_5m)} 根K线数据，时间范围: {df_5m.index[0]} 到 {df_5m.index[-1]}")
        
        return all_data, reward_risk


    def run_backtest(self):
        # 调试信息
        log_info(f"数据形状: {self.data.shape}")
        log_info(f"数据列: {list(self.data.columns)}")
        log_info(f"特征列: {self.feature_cols}")
        
        # 检查特征列是否存在
        missing_cols = [col for col in self.feature_cols if col not in self.data.columns]
        if missing_cols:
            log_error(f"缺失的特征列: {missing_cols}")
            # 使用可用的列进行预测
            available_cols = [col for col in self.feature_cols if col in self.data.columns]
            self.feature_cols = available_cols
            log_info(f"使用可用的特征列: {available_cols}")

        # ========== 预计算信号 ==========
        probs = self.data.apply(self._predict_row, axis=1)
        if isinstance(probs, pd.DataFrame) and probs.shape[1] >= 2:
            self.data['long_prob'] = probs.iloc[:, 0]
            self.data['short_prob'] = probs.iloc[:, 1]
        elif isinstance(probs, pd.Series):
            # 如果返回的是Series，可能是(long_prob, short_prob)元组
            probs_df = pd.DataFrame(probs.tolist(), index=probs.index, columns=['long_prob', 'short_prob'])
            self.data['long_prob'] = probs_df['long_prob']
            self.data['short_prob'] = probs_df['short_prob']
        else:
            log_error(f"预测结果类型错误: {type(probs)}, 形状: {probs.shape if hasattr(probs, 'shape') else 'N/A'}")
            self.data['long_prob'] = 0.5
            self.data['short_prob'] = 0.5

        for i in tqdm(range(len(self.data))):
            row = self.data.iloc[i]
            price = row['5m_close']
            long_prob = row['long_prob']
            short_prob = row['short_prob']
            money_flow_ratio = row['money_flow_ratio']
            volatility = row['volatility_15']

            if pd.isna(volatility):
                continue
            volatility = float(volatility)

            # ===== 将回测状态同步进 core =====
            self.core.set_state(self.position, self.entry_price, self.hold_bars)

            out = self.core.on_bar(
                price=price,
                equity=self.balance,
                long_prob=long_prob,
                short_prob=short_prob,
                money_flow_ratio=money_flow_ratio,
                volatility=volatility,
            )

            action = out["action"]
            delta = float(out["delta_qty"])

            if action == "CLOSE":
                pos_to_close = self.position
                entry_price = self.entry_price

                profit = (price - entry_price) * pos_to_close
                self.balance += profit - abs(pos_to_close * price * self.fee_rate)

                act = "平仓" if out.get("reason") == "TP/SL" else "反向平仓"
                self.trade_log.append((row.name, act, price, pos_to_close, self.balance))

            elif action == "OPEN":
                new_pos, _, _ = self.core.get_state()
                self.balance -= abs(new_pos * price * self.fee_rate)

                act = "开多" if new_pos > 0 else "开空"
                self.trade_log.append((row.name, act, price, new_pos, self.balance))

            elif action == "REBALANCE":
                new_pos, _, _ = self.core.get_state()
                self.balance -= abs(delta * price * self.fee_rate)

                act = "加多" if delta > 0 else "减多"
                self.trade_log.append((row.name, act, price, new_pos, self.balance))

            self.position, self.entry_price, self.hold_bars = self.core.get_state()
            self.max_balance = max(self.max_balance, self.balance)


        self._summary()

    def _predict_row(self, row):
        """
        复用实盘信号融合逻辑，保持一致性
        """
        try:
            X_row = row[self.feature_cols].values.reshape(1, -1).astype(float)
            X_row = pd.DataFrame(X_row, columns=self.feature_cols)

            weighted_sum = np.zeros(2)
            total_weight = sum(self.model_weights.values())

            for name, model in self.models.items():
                prob = model.predict_proba(X_row)[0]
                weight = self.model_weights.get(name, 1.0)
                weighted_sum += prob * weight

            avg_pred = weighted_sum / total_weight
            long_prob, short_prob = float(avg_pred[1]), float(avg_pred[0])
            return pd.Series([long_prob, short_prob], index=['long_prob', 'short_prob'])
        except Exception as e:
            # 如果预测失败，返回中性信号
            return pd.Series([0.5, 0.5], index=['long_prob', 'short_prob'])

    def _summary(self):
        pnl = self.balance - config.INITIAL_BALANCE
        drawdown = (self.balance - self.max_balance) / self.max_balance
        
        # 计算胜率
        wins = 0
        losses = 0
        win_pnl = 0
        loss_pnl = 0
        
        for i in range(len(self.trade_log)):
            timestamp, action, price, position, balance = self.trade_log[i]
            # 平仓交易（包含"平仓"或"反向平仓"）
            if "平仓" in action and i > 0:
                # 找到对应的开仓记录
                for j in range(i-1, -1, -1):
                    prev_timestamp, prev_action, prev_price, prev_position, prev_balance = self.trade_log[j]
                    if "开多" in prev_action or "开空" in prev_action:
                        # 计算盈亏
                        if "开多" in prev_action:
                            trade_pnl = (price - prev_price) * abs(prev_position)
                        else:  # 开空
                            trade_pnl = (prev_price - price) * abs(prev_position)
                        
                        # 扣除手续费
                        trade_pnl -= abs(prev_position * price * self.fee_rate * 2)  # 开仓+平仓手续费
                        
                        if trade_pnl > 0:
                            wins += 1
                            win_pnl += trade_pnl
                        else:
                            losses += 1
                            loss_pnl += trade_pnl
                        break
        
        total_closed = wins + losses
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
        profit_factor = abs(win_pnl / loss_pnl) if loss_pnl != 0 else 0

        log_info("回测完成 ✅")
        log_info(f"最终资金: {self.balance:.2f} USDT")
        log_info(f"累计收益: {pnl:.2f} USDT ({pnl / config.INITIAL_BALANCE * 100:.2f}%)")
        log_info(f"最大回撤: {drawdown * 100:.2f}%")
        log_info(f"交易次数: {len(self.trade_log)}")
        log_info(f"已平仓交易: {total_closed}")
        log_info(f"盈利次数: {wins}")
        log_info(f"亏损次数: {losses}")
        log_info(f"胜率: {win_rate:.1f}%")
        log_info(f"盈利总额: {win_pnl:.2f} USDT")
        log_info(f"亏损总额: {loss_pnl:.2f} USDT")
        log_info(f"盈亏比: {profit_factor:.2f}")
        log_info(f"交易记录示例: {self.trade_log[-5:]}")
        self.dump_trade_log_to_csv(pnl,drawdown, win_rate, wins, losses, win_pnl, loss_pnl, profit_factor)

    def dump_trade_log_to_csv(self,pnl, drawdown, win_rate=0, wins=0, losses=0, win_pnl=0, loss_pnl=0, profit_factor=0):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backtest_log_path = os.path.join(LOGS_DIR, f"backtest_{self.interval}_{ts}.csv")
        with open(backtest_log_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "action", "price",  "position","balance"])

            writer.writerows([
                (t, a, round(p, 4), round(pos, 4),round(b, 2))
                for (t, a, p,pos, b) in self.trade_log
            ])
            writer.writerow([])
            writer.writerow(["# Summary"])
            writer.writerow(["Final Balance", round(self.balance, 2)])
            writer.writerow(["PnL (USDT)", round(pnl, 2)])
            writer.writerow([
                "Return (%)",
                round(pnl / config.INITIAL_BALANCE * 100, 2)
            ])
            writer.writerow([
                "Max Drawdown (%)",
                round(drawdown * 100, 2)
            ])
            writer.writerow([
                "Trade Count",
                len(self.trade_log)
            ])
            writer.writerow(["Win Rate (%)", round(win_rate, 2)])
            writer.writerow(["Wins", wins])
            writer.writerow(["Losses", losses])
            writer.writerow(["Win PnL", round(win_pnl, 2)])
            writer.writerow(["Loss PnL", round(loss_pnl, 2)])
            writer.writerow(["Profit Factor", round(profit_factor, 2)])



if __name__ == '__main__':
    try:
        log_info(f"\n==== 开始多周期融合回测 (5m+15m+1H) ====")
        log_info(f"初始本金: {config.INITIAL_BALANCE} USDT")
        log_info(f"交易品种: {config.SYMBOL}")
        log_info(f"杠杆: {config.LEVERAGE}x")
        
        # 使用7天的数据 (5分钟K线，每天288根，7天约2016根)
        window_7d = 2016
        backtester = Backtester(interval="5m", window=window_7d)
        backtester.run_backtest()
    except Exception as e:
        log_error(traceback.format_exc())
