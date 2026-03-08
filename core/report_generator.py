import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd
from config import config

class ReportGenerator:
    def __init__(self):
        self.data_dir = "data"
        os.makedirs(self.data_dir, exist_ok=True)
        self.trades_file = os.path.join(self.data_dir, "trades.json")
        self.daily_stats_file = os.path.join(self.data_dir, "daily_stats.json")
        self._init_storage()
        
    def _init_storage(self):
        if not os.path.exists(self.trades_file):
            with open(self.trades_file, 'w') as f:
                json.dump([], f)
        if not os.path.exists(self.daily_stats_file):
            with open(self.daily_stats_file, 'w') as f:
                json.dump({}, f)
    
    def record_trade(self, action: str, price: float, size: float, pnl: float = 0, 
                     long_prob: float = 0, short_prob: float = 0, 
                     money_flow: float = 0, volatility: float = 0):
        trade = {
            'timestamp': datetime.now().isoformat(),
            'date': datetime.now().strftime('%Y-%m-%d'),
            'time': datetime.now().strftime('%H:%M:%S'),
            'action': action,
            'symbol': config.SYMBOL,
            'price': price,
            'size': abs(size),
            'direction': 'LONG' if size > 0 else 'SHORT' if size < 0 else 'FLAT',
            'pnl': pnl,
            'long_prob': long_prob,
            'short_prob': short_prob,
            'money_flow': money_flow,
            'volatility': volatility
        }
        
        trades = self._load_trades()
        trades.append(trade)
        self._save_trades(trades)
        
        # 更新每日统计
        self._update_daily_stats(trade)
        
        return trade
    
    def _load_trades(self) -> List[Dict]:
        try:
            with open(self.trades_file, 'r') as f:
                return json.load(f)
        except:
            return []
    
    def _save_trades(self, trades: List[Dict]):
        with open(self.trades_file, 'w') as f:
            json.dump(trades, f, indent=2)
    
    def _update_daily_stats(self, trade: Dict):
        date = trade['date']
        stats = self._load_daily_stats()
        
        if date not in stats:
            stats[date] = {
                'date': date,
                'trade_count': 0,
                'win_count': 0,
                'loss_count': 0,
                'total_pnl': 0,
                'long_count': 0,
                'short_count': 0,
                'max_profit': 0,
                'max_loss': 0
            }
        
        day_stats = stats[date]
        day_stats['trade_count'] += 1
        day_stats['total_pnl'] += trade['pnl']
        
        if trade['pnl'] > 0:
            day_stats['win_count'] += 1
            day_stats['max_profit'] = max(day_stats['max_profit'], trade['pnl'])
        elif trade['pnl'] < 0:
            day_stats['loss_count'] += 1
            day_stats['max_loss'] = min(day_stats['max_loss'], trade['pnl'])
        
        if trade['direction'] == 'LONG':
            day_stats['long_count'] += 1
        elif trade['direction'] == 'SHORT':
            day_stats['short_count'] += 1
        
        self._save_daily_stats(stats)
    
    def _load_daily_stats(self) -> Dict:
        try:
            with open(self.daily_stats_file, 'r') as f:
                return json.load(f)
        except:
            return {}
    
    def _save_daily_stats(self, stats: Dict):
        with open(self.daily_stats_file, 'w') as f:
            json.dump(stats, f, indent=2)
    
    def get_pnl_report(self, period: str = 'all') -> Dict:
        trades = self._load_trades()
        
        if not trades:
            return {
                'period': period,
                'total_trades': 0,
                'total_pnl': 0,
                'win_rate': 0,
                'avg_profit': 0,
                'avg_loss': 0,
                'max_drawdown': 0
            }
        
        # 根据时间段筛选
        now = datetime.now()
        if period == 'daily':
            start_date = now.strftime('%Y-%m-%d')
            trades = [t for t in trades if t['date'] == start_date]
        elif period == 'weekly':
            week_start = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d')
            trades = [t for t in trades if t['date'] >= week_start]
        elif period == 'monthly':
            month_start = now.replace(day=1).strftime('%Y-%m-%d')
            trades = [t for t in trades if t['date'] >= month_start]
        
        if not trades:
            return {
                'period': period,
                'total_trades': 0,
                'total_pnl': 0,
                'win_rate': 0,
                'avg_profit': 0,
                'avg_loss': 0,
                'max_drawdown': 0
            }
        
        total_pnl = sum(t['pnl'] for t in trades)
        win_trades = [t for t in trades if t['pnl'] > 0]
        loss_trades = [t for t in trades if t['pnl'] < 0]
        
        # 计算最大回撤
        cumulative = 0
        max_drawdown = 0
        peak = 0
        for t in trades:
            cumulative += t['pnl']
            if cumulative > peak:
                peak = cumulative
            drawdown = peak - cumulative
            max_drawdown = max(max_drawdown, drawdown)
        
        return {
            'period': period,
            'total_trades': len(trades),
            'win_count': len(win_trades),
            'loss_count': len(loss_trades),
            'total_pnl': round(total_pnl, 2),
            'win_rate': round(len(win_trades) / len(trades) * 100, 2) if trades else 0,
            'avg_profit': round(sum(t['pnl'] for t in win_trades) / len(win_trades), 2) if win_trades else 0,
            'avg_loss': round(sum(t['pnl'] for t in loss_trades) / len(loss_trades), 2) if loss_trades else 0,
            'max_profit': round(max(t['pnl'] for t in trades), 2) if trades else 0,
            'max_loss': round(min(t['pnl'] for t in trades), 2) if trades else 0,
            'max_drawdown': round(max_drawdown, 2)
        }
    
    def get_position_report(self, current_position: float, entry_price: float, 
                           current_price: float, balance: float) -> Dict:
        if current_position == 0:
            return {
                'status': 'FLAT',
                'position': 0,
                'direction': None,
                'entry_price': 0,
                'current_price': current_price,
                'unrealized_pnl': 0,
                'unrealized_pnl_pct': 0,
                'balance': balance
            }
        
        direction = 'LONG' if current_position > 0 else 'SHORT'
        
        if direction == 'LONG':
            unrealized_pnl = (current_price - entry_price) * abs(current_position)
        else:
            unrealized_pnl = (entry_price - current_price) * abs(current_position)
        
        unrealized_pnl_pct = (unrealized_pnl / (abs(current_position) * entry_price)) * 100
        
        return {
            'status': 'HOLDING',
            'position': abs(current_position),
            'direction': direction,
            'entry_price': entry_price,
            'current_price': current_price,
            'unrealized_pnl': round(unrealized_pnl, 2),
            'unrealized_pnl_pct': round(unrealized_pnl_pct, 2),
            'balance': balance,
            'position_value': abs(current_position) * current_price
        }
    
    def get_signal_report(self, long_prob: float, short_prob: float, 
                         money_flow: float, volatility: float) -> Dict:
        signal_strength = max(long_prob, short_prob)
        
        if long_prob > config.THRESHOLD_LONG:
            signal = 'LONG'
            confidence = long_prob
        elif short_prob > config.THRESHOLD_SHORT:
            signal = 'SHORT'
            confidence = short_prob
        else:
            signal = 'NEUTRAL'
            confidence = 0
        
        return {
            'signal': signal,
            'confidence': round(confidence * 100, 2),
            'long_prob': round(long_prob * 100, 2),
            'short_prob': round(short_prob * 100, 2),
            'money_flow': round(money_flow, 4),
            'volatility': round(volatility, 4),
            'strength': '强' if signal_strength > 0.8 else '中' if signal_strength > 0.6 else '弱'
        }
    
    def generate_daily_summary(self) -> str:
        today = datetime.now().strftime('%Y-%m-%d')
        stats = self._load_daily_stats()
        
        if today not in stats:
            return f"📅 {today} 暂无交易记录"
        
        day = stats[today]
        win_rate = (day['win_count'] / day['trade_count'] * 100) if day['trade_count'] > 0 else 0
        
        return f"""📊 今日交易总结 ({today})

📈 交易统计:
• 总交易次数: {day['trade_count']}
• 做多次数: {day['long_count']}
• 做空次数: {day['short_count']}
• 盈利次数: {day['win_count']} ✅
• 亏损次数: {day['loss_count']} ❌
• 胜率: {win_rate:.1f}%

💰 盈亏情况:
• 当日盈亏: ${day['total_pnl']:+.2f}
• 最大盈利: ${day['max_profit']:+.2f}
• 最大亏损: ${day['max_loss']:+.2f}
"""
