import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from config import config
from core.okx_api import OKXClient
from core.report_generator import ReportGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TradingTelegramBot:
    def __init__(self, trader=None):
        self.trader = trader  # 保存trader实例
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.client = OKXClient()
        self.report_gen = ReportGenerator()
        self.trade_history: List[Dict] = []
        self.daily_pnl = 0.0
        self.initial_balance = config.INITIAL_BALANCE
        self.current_balance = config.INITIAL_BALANCE
        self.application = None
        
    async def start(self):
        if not self.token or not self.chat_id:
            logger.warning("Telegram配置不完整，跳过启动")
            return
            
        self.application = Application.builder().token(self.token).build()
        
        # 添加命令处理器
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("status", self.cmd_status))
        self.application.add_handler(CommandHandler("pnl", self.cmd_pnl))
        self.application.add_handler(CommandHandler("position", self.cmd_position))
        self.application.add_handler(CommandHandler("history", self.cmd_history))
        self.application.add_handler(CommandHandler("system", self.cmd_system))
        self.application.add_handler(CommandHandler("help", self.cmd_help))
        
        # 添加回调处理器
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # 启动bot
        await self.application.initialize()
        await self.application.start()
        # 启动轮询监听
        await self.application.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram Bot 已启动")
        
    async def stop(self):
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        status_msg = self._get_system_status()
        keyboard = [
            [InlineKeyboardButton("📊 实时状态", callback_data='status')],
            [InlineKeyboardButton("💰 盈亏统计", callback_data='pnl_menu')],
            [InlineKeyboardButton("📈 持仓详情", callback_data='position')],
            [InlineKeyboardButton("📜 交易历史", callback_data='history')],
            [InlineKeyboardButton("⚙️ 系统控制", callback_data='system_control')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🤖 *量化交易系统监控面板*\n\n"
            f"{status_msg}\n\n"
            f"选择下方选项查看详细信息：",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    def _get_system_status(self):
        if self.trader:
            status = self.trader.get_system_status()
            return (f"📊 *系统状态*\n\n"
                    f"状态: {status['status']}\n"
                    f"品种: {status['symbol']}\n"
                    f"杠杆: {status['leverage']}x\n"
                    f"持仓: {status['position']:.4f}\n"
                    f"入场价: ${status['entry_price']:.4f}")
        else:
            return "📊 *系统状态*\n\n状态: 🔴 未连接"

    async def cmd_system(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.trader:
            await update.message.reply_text("❌ 系统未连接")
            return

        status = self.trader.get_system_status()
        status_emoji = "🟢" if status['running'] else "🔴"
        
        keyboard = [
            [InlineKeyboardButton(f"{status_emoji} {'停止交易' if status['running'] else '启动交易'}", 
                                  callback_data='toggle_trading')],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data='main_menu')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        msg = (f"⚙️ *系统控制面板*\n\n"
               f"状态: {status['status']}\n"
               f"品种: {status['symbol']}\n"
               f"杠杆: {status['leverage']}x\n"
               f"当前持仓: {status['position']:.4f}\n"
               f"入场价格: ${status['entry_price']:.4f}")
        
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = await self._get_status_message()
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    async def cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("📊 实时盈亏", callback_data='pnl_realtime')],
            [InlineKeyboardButton("📅 当日盈亏", callback_data='pnl_daily')],
            [InlineKeyboardButton("📆 本周盈亏", callback_data='pnl_weekly')],
            [InlineKeyboardButton("📈 本月盈亏", callback_data='pnl_monthly')],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data='main_menu')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "💰 *盈亏统计面板*\n\n请选择时间维度：",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    async def cmd_position(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = await self._get_position_message()
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = self._get_history_message()
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
🤖 *交易机器人命令列表*

/start - 启动主菜单
/status - 查看实时状态
/pnl - 查看盈亏统计
/position - 查看持仓详情
/history - 查看交易历史
/help - 显示此帮助信息

💡 提示：使用按钮菜单操作更便捷！
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
        
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == 'status':
            msg = await self._get_status_message()
            keyboard = [[InlineKeyboardButton("🔙 返回", callback_data='main_menu')]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
        elif query.data == 'pnl_menu':
            keyboard = [
                [InlineKeyboardButton("📊 实时盈亏", callback_data='pnl_realtime')],
                [InlineKeyboardButton("📅 当日盈亏", callback_data='pnl_daily')],
                [InlineKeyboardButton("📆 本周盈亏", callback_data='pnl_weekly')],
                [InlineKeyboardButton("📈 本月盈亏", callback_data='pnl_monthly')],
                [InlineKeyboardButton("🔙 返回", callback_data='main_menu')],
            ]
            await query.edit_message_text(
                "💰 *盈亏统计面板*\n\n请选择时间维度：",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        elif query.data == 'pnl_realtime':
            msg = await self._get_realtime_pnl()
            keyboard = [[InlineKeyboardButton("🔙 返回", callback_data='pnl_menu')]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
        elif query.data == 'pnl_daily':
            msg = await self._get_daily_pnl()
            keyboard = [[InlineKeyboardButton("🔙 返回", callback_data='pnl_menu')]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
        elif query.data == 'pnl_weekly':
            msg = await self._get_weekly_pnl()
            keyboard = [[InlineKeyboardButton("🔙 返回", callback_data='pnl_menu')]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
        elif query.data == 'pnl_monthly':
            msg = await self._get_monthly_pnl()
            keyboard = [[InlineKeyboardButton("🔙 返回", callback_data='pnl_menu')]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
        elif query.data == 'position':
            msg = await self._get_position_message()
            keyboard = [[InlineKeyboardButton("🔄 刷新", callback_data='position')],
                       [InlineKeyboardButton("🔙 返回", callback_data='main_menu')]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
        elif query.data == 'history':
            msg = self._get_history_message()
            keyboard = [[InlineKeyboardButton("🔙 返回", callback_data='main_menu')]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
        elif query.data == 'system_control':
            if not self.trader:
                await query.edit_message_text("❌ 系统未连接", parse_mode='Markdown')
                return

            status = self.trader.get_system_status()
            status_emoji = "🟢" if status['running'] else "🔴"
            
            keyboard = [
                [InlineKeyboardButton(f"{status_emoji} {'停止交易' if status['running'] else '启动交易'}", 
                                      callback_data='toggle_trading')],
                [InlineKeyboardButton("🔙 返回主菜单", callback_data='main_menu')],
            ]
            msg = (f"⚙️ *系统控制面板*\n\n"
                   f"状态: {status['status']}\n"
                   f"品种: {status['symbol']}\n"
                   f"杠杆: {status['leverage']}x\n"
                   f"当前持仓: {status['position']:.4f}\n"
                   f"入场价格: ${status['entry_price']:.4f}")
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
        elif query.data == 'toggle_trading':
            if not self.trader:
                await query.edit_message_text("❌ 系统未连接", parse_mode='Markdown')
                return

            status = self.trader.get_system_status()
            if status['running']:
                self.trader.stop_trading()
                new_status = "🔴 已停止"
                action = "停止"
            else:
                self.trader.start_trading()
                new_status = "🟢 运行中"
                action = "启动"
            
            status_emoji = "🟢" if self.trader.get_system_status()['running'] else "🔴"
            keyboard = [
                [InlineKeyboardButton(f"{status_emoji} {'停止交易' if self.trader.get_system_status()['running'] else '启动交易'}", 
                                      callback_data='toggle_trading')],
                [InlineKeyboardButton("🔙 返回主菜单", callback_data='main_menu')],
            ]
            msg = (f"⚙️ *系统控制面板*\n\n"
                   f"✅ 交易系统已{action}\n\n"
                   f"状态: {new_status}\n"
                   f"品种: {status['symbol']}\n"
                   f"杠杆: {status['leverage']}x\n"
                   f"当前持仓: {status['position']:.4f}\n"
                   f"入场价格: ${status['entry_price']:.4f}")
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
        elif query.data == 'main_menu':
            status_msg = self._get_system_status()
            keyboard = [
                [InlineKeyboardButton("📊 实时状态", callback_data='status')],
                [InlineKeyboardButton("💰 盈亏统计", callback_data='pnl_menu')],
                [InlineKeyboardButton("📈 持仓详情", callback_data='position')],
                [InlineKeyboardButton("📜 交易历史", callback_data='history')],
                [InlineKeyboardButton("⚙️ 系统控制", callback_data='system_control')],
            ]
            await query.edit_message_text(
                f"🤖 *量化交易系统监控面板*\n\n"
                f"{status_msg}\n\n"
                f"选择下方选项查看详细信息：",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
    async def _get_status_message(self) -> str:
        try:
            ticker = self.client.get_ticker(config.SYMBOL)
            price = float(ticker['last'])
            
            return (
                f"📊 *实时市场状态*\n\n"
                f"💎 交易品种: `{config.SYMBOL}`\n"
                f"💰 当前价格: `${price:.4f}`\n"
                f"📈 杠杆倍数: `{config.LEVERAGE}x`\n"
                f"⏰ 更新时间: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
                f"🤖 系统状态: 🟢 运行中"
            )
        except Exception as e:
            return f"❌ 获取状态失败: {str(e)}"
            
    async def _get_position_message(self) -> str:
        try:
            pos = self.client.get_positions(config.SYMBOL)
            balance = self.client.get_balance()
            
            if not pos or float(pos.get('pos', 0)) == 0:
                return (
                    f"📈 *持仓详情*\n\n"
                    f"💼 当前持仓: *空仓*\n"
                    f"💰 账户余额: `${float(balance):.2f}`\n"
                    f"⏰ 更新时间: `{datetime.now().strftime('%H:%M:%S')}`"
                )
            
            pos_size = float(pos.get('pos', 0))
            pos_side = "做多 📈" if pos_size > 0 else "做空 📉"
            entry_price = float(pos.get('avgPx', 0))
            mark_price = float(pos.get('markPx', 0))
            pnl = float(pos.get('upl', 0))
            pnl_pct = (pnl / (abs(pos_size) * entry_price)) * 100
            
            return (
                f"📈 *持仓详情*\n\n"
                f"📊 方向: *{pos_side}*\n"
                f"📦 持仓数量: `{abs(pos_size):.4f} SOL`\n"
                f"💵 开仓价格: `${entry_price:.4f}`\n"
                f"🏷️ 标记价格: `${mark_price:.4f}`\n"
                f"💰 未实现盈亏: `${pnl:.2f} ({pnl_pct:+.2f}%)`\n"
                f"💎 账户余额: `${float(balance):.2f}`\n"
                f"⏰ 更新时间: `{datetime.now().strftime('%H:%M:%S')}`"
            )
        except Exception as e:
            return f"❌ 获取持仓失败: {str(e)}"
            
    async def _get_realtime_pnl(self) -> str:
        try:
            balance = float(self.client.get_balance())
            total_pnl = balance - self.initial_balance
            total_pnl_pct = (total_pnl / self.initial_balance) * 100
            
            return (
                f"📊 *实时盈亏统计*\n\n"
                f"💰 初始资金: `${self.initial_balance:.2f}`\n"
                f"💎 当前资金: `${balance:.2f}`\n"
                f"📈 累计盈亏: `${total_pnl:+.2f} ({total_pnl_pct:+.2f}%)`\n"
                f"📅 今日盈亏: `${self.daily_pnl:+.2f}`\n"
                f"⏰ 更新时间: `{datetime.now().strftime('%H:%M:%S')}`"
            )
        except Exception as e:
            return f"❌ 获取盈亏失败: {str(e)}"
            
    async def _get_daily_pnl(self) -> str:
        today = datetime.now().date()
        today_trades = [t for t in self.trade_history if t.get('date') == today]
        
        if not today_trades:
            return (
                f"📅 *当日盈亏*\n\n"
                f"📊 交易次数: 0\n"
                f"💰 当日盈亏: $0.00\n"
                f"📝 今日暂无交易记录"
            )
        
        daily_pnl = sum(t.get('pnl', 0) for t in today_trades)
        win_count = sum(1 for t in today_trades if t.get('pnl', 0) > 0)
        loss_count = len(today_trades) - win_count
        
        return (
            f"📅 *当日盈亏统计*\n\n"
            f"📊 交易次数: {len(today_trades)}\n"
            f"✅ 盈利次数: {win_count}\n"
            f"❌ 亏损次数: {loss_count}\n"
            f"💰 当日盈亏: `${daily_pnl:+.2f}`\n"
            f"🎯 胜率: {(win_count/len(today_trades)*100):.1f}%"
        )
        
    async def _get_weekly_pnl(self) -> str:
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday())
        week_trades = [t for t in self.trade_history if t.get('date', today) >= week_start]
        
        weekly_pnl = sum(t.get('pnl', 0) for t in week_trades)
        
        return (
            f"📆 *本周盈亏统计*\n\n"
            f"📅 统计周期: {week_start} 至 {today}\n"
            f"📊 交易次数: {len(week_trades)}\n"
            f"💰 本周盈亏: `${weekly_pnl:+.2f}`\n"
            f"📈 日均盈亏: `${weekly_pnl/7:.2f}`"
        )
        
    async def _get_monthly_pnl(self) -> str:
        today = datetime.now().date()
        month_trades = [t for t in self.trade_history if t.get('date', today).month == today.month]
        
        monthly_pnl = sum(t.get('pnl', 0) for t in month_trades)
        
        return (
            f"📈 *本月盈亏统计*\n\n"
            f"📅 统计月份: {today.strftime('%Y年%m月')}\n"
            f"📊 交易次数: {len(month_trades)}\n"
            f"💰 本月盈亏: `${monthly_pnl:+.2f}`\n"
            f"📅 日均盈亏: `${monthly_pnl/today.day:.2f}`"
        )
        
    def _get_history_message(self) -> str:
        if not self.trade_history:
            return (
                f"📜 *交易历史*\n\n"
                f"📝 暂无交易记录\n\n"
                f"系统正在运行中，等待交易信号..."
            )
        
        recent_trades = self.trade_history[-10:]  # 最近10笔
        msg = "📜 *最近交易记录*\n\n"
        
        for i, trade in enumerate(reversed(recent_trades), 1):
            emoji = "✅" if trade.get('pnl', 0) > 0 else "❌"
            msg += f"{i}. {emoji} {trade.get('time', 'N/A')} {trade.get('action', 'N/A')} {trade.get('pnl', 0):+.2f}\n"
        
        return msg
        
    async def send_trade_notification(self, action: str, price: float, size: float, pnl: float = 0):
        if not self.token or not self.chat_id:
            return
            
        emoji = "🟢" if "开多" in action else "🔴" if "开空" in action else "⚪"
        pnl_text = f"💰 盈亏: `${pnl:+.2f}`\n" if pnl != 0 else ""
        
        message = (
            f"{emoji} *交易执行通知*\n\n"
            f"📊 操作: {action}\n"
            f"💎 品种: {config.SYMBOL}\n"
            f"💰 价格: `${price:.4f}`\n"
            f"📦 数量: `{abs(size):.4f} SOL`\n"
            f"{pnl_text}"
            f"⏰ 时间: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        
        try:
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"发送交易通知失败: {e}")
            
    async def send_signal_alert(self, long_prob: float, short_prob: float, price: float):
        if not self.token or not self.chat_id:
            return
            
        signal = "做多 📈" if long_prob > short_prob else "做空 📉"
        strength = max(long_prob, short_prob)
        
        message = (
            f"📊 *交易信号提醒*\n\n"
            f"💎 品种: {config.SYMBOL}\n"
            f"💰 当前价格: `${price:.4f}`\n"
            f"📈 做多概率: `{long_prob*100:.1f}%`\n"
            f"📉 做空概率: `{short_prob*100:.1f}%`\n"
            f"🎯 建议方向: *{signal}*\n"
            f"💪 信号强度: `{strength*100:.1f}%`\n"
            f"⏰ 时间: `{datetime.now().strftime('%H:%M:%S')}`"
        )
        
        try:
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"发送信号提醒失败: {e}")
            
    def record_trade(self, action: str, price: float, size: float, pnl: float = 0):
        trade = {
            'date': datetime.now().date(),
            'time': datetime.now().strftime('%H:%M:%S'),
            'action': action,
            'price': price,
            'size': size,
            'pnl': pnl
        }
        self.trade_history.append(trade)
        
        # 更新当日盈亏
        if pnl != 0:
            self.daily_pnl += pnl
            
    def update_balance(self, balance: float):
        self.current_balance = balance
