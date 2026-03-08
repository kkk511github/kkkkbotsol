import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from backtest.backtest import Backtester

def test_btc():
    """测试BTC交易"""
    
    print(f"{'='*60}")
    print("BTC回测测试")
    print(f"{'='*60}")
    print(f"交易品种: {config.SYMBOL}")
    print(f"杠杆: {config.LEVERAGE}x")
    print(f"止盈: {config.TAKE_PROFIT*100}%")
    print(f"止损: {config.STOP_LOSS*100}%")
    print(f"仓位上限: {config.POSITION_MAX*100}%")
    print(f"做多阈值: {config.THRESHOLD_LONG}")
    print(f"做空阈值: {config.THRESHOLD_SHORT}")
    print(f"{'='*60}\n")
    
    try:
        # 运行回测
        backtester = Backtester(interval="5m", window=1000)
        backtester.run_backtest()
        
        # 获取结果
        final_balance = backtester.balance
        initial_balance = config.INITIAL_BALANCE
        pnl = final_balance - initial_balance
        pnl_pct = (pnl / initial_balance) * 100
        max_drawdown = backtester.max_drawdown if hasattr(backtester, 'max_drawdown') else 0
        trade_count = len(backtester.trade_log)
        
        print(f"\n{'='*60}")
        print("BTC回测结果")
        print(f"{'='*60}")
        print(f"初始资金: {initial_balance:.2f} USDT")
        print(f"最终资金: {final_balance:.2f} USDT")
        print(f"累计收益: {pnl:+.2f} USDT ({pnl_pct:+.2f}%)")
        print(f"最大回撤: {max_drawdown:.2f}%")
        print(f"交易次数: {trade_count}")
        
        if trade_count > 0:
            print(f"\n最近5笔交易:")
            for trade in backtester.trade_log[-5:]:
                print(f"  {trade[0]} | {trade[1]} | 价格: ${trade[2]:.2f} | 仓位: {trade[3]:.4f}")
        
        return {
            'symbol': 'BTC',
            'final_balance': final_balance,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'trade_count': trade_count,
            'max_drawdown': max_drawdown
        }
        
    except Exception as e:
        print(f"❌ BTC回测失败: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == '__main__':
    result = test_btc()
