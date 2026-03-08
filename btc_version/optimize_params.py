import os
import sys
import pandas as pd
from config import config
from backtest.backtest import Backtester

def optimize_parameters():
    """系统优化策略参数"""
    
    # 测试参数组合
    test_configs = [
        # (止盈, 止损, 仓位上限, 交易阈值, 调仓阈值, 最小调仓)
        
        # 配置1: 当前配置（基准）
        (0.02, 0.01, 0.3, 0.55, 0.45, 0.15, 50),
        
        # 配置2: 更宽松的止盈止损
        (0.03, 0.015, 0.3, 0.55, 0.45, 0.15, 50),
        
        # 配置3: 更严格的止盈止损
        (0.015, 0.008, 0.3, 0.55, 0.45, 0.15, 50),
        
        # 配置4: 提高仓位上限
        (0.02, 0.01, 0.5, 0.55, 0.45, 0.15, 50),
        
        # 配置5: 降低交易阈值（更频繁）
        (0.02, 0.01, 0.3, 0.52, 0.48, 0.15, 50),
        
        # 配置6: 提高交易阈值（更保守）
        (0.02, 0.01, 0.3, 0.58, 0.42, 0.15, 50),
        
        # 配置7: 提高调仓阈值（减少调仓）
        (0.02, 0.01, 0.3, 0.55, 0.45, 0.25, 50),
        
        # 配置8: 提高最小调仓金额
        (0.02, 0.01, 0.3, 0.55, 0.45, 0.15, 100),
        
        # 配置9: 综合优化1
        (0.025, 0.012, 0.4, 0.53, 0.47, 0.2, 80),
        
        # 配置10: 综合优化2
        (0.018, 0.009, 0.35, 0.57, 0.43, 0.18, 70),
    ]
    
    results = []
    
    for i, (tp, sl, max_pos, thresh_long, thresh_short, add_thresh, min_adj) in enumerate(test_configs, 1):
        print(f"\n{'='*60}")
        print(f"测试配置 {i}/{len(test_configs)}")
        print(f"{'='*60}")
        print(f"止盈: {tp*100:.1f}% | 止损: {sl*100:.1f}%")
        print(f"仓位上限: {max_pos*100:.0f}% | 做多阈值: {thresh_long}")
        print(f"做空阈值: {thresh_short} | 调仓阈值: {add_thresh}")
        print(f"最小调仓: {min_adj} USDT")
        
        # 临时修改配置
        original_tp = config.TAKE_PROFIT
        original_sl = config.STOP_LOSS
        original_max_pos = config.POSITION_MAX
        original_thresh_long = config.THRESHOLD_LONG
        original_thresh_short = config.THRESHOLD_SHORT
        original_add_thresh = config.ADD_THRESHOLD
        original_min_adj = config.MIN_ADJUST_AMOUNT
        
        config.TAKE_PROFIT = tp
        config.STOP_LOSS = sl
        config.POSITION_MAX = max_pos
        config.THRESHOLD_LONG = thresh_long
        config.THRESHOLD_SHORT = thresh_short
        config.ADD_THRESHOLD = add_thresh
        config.MIN_ADJUST_AMOUNT = min_adj
        
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
            
            results.append({
                'config': i,
                'take_profit': tp,
                'stop_loss': sl,
                'max_position': max_pos,
                'threshold_long': thresh_long,
                'threshold_short': thresh_short,
                'add_threshold': add_thresh,
                'min_adjust': min_adj,
                'final_balance': final_balance,
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'max_drawdown': max_drawdown,
                'trade_count': trade_count
            })
            
            print(f"✅ 最终资金: {final_balance:.2f} USDT")
            print(f"✅ 累计收益: {pnl:+.2f} USDT ({pnl_pct:+.2f}%)")
            print(f"✅ 交易次数: {trade_count}")
            
        except Exception as e:
            print(f"❌ 测试失败: {e}")
            results.append({
                'config': i,
                'take_profit': tp,
                'stop_loss': sl,
                'max_position': max_pos,
                'threshold_long': thresh_long,
                'threshold_short': thresh_short,
                'add_threshold': add_thresh,
                'min_adjust': min_adj,
                'final_balance': 0,
                'pnl': 0,
                'pnl_pct': 0,
                'max_drawdown': 0,
                'trade_count': 0,
                'error': str(e)
            })
        
        # 恢复原始配置
        config.TAKE_PROFIT = original_tp
        config.STOP_LOSS = original_sl
        config.POSITION_MAX = original_max_pos
        config.THRESHOLD_LONG = original_thresh_long
        config.THRESHOLD_SHORT = original_thresh_short
        config.ADD_THRESHOLD = original_add_thresh
        config.MIN_ADJUST_AMOUNT = original_min_adj
    
    # 保存结果
    results_df = pd.DataFrame(results)
    results_df.to_csv('optimization_results.csv', index=False)
    
    # 找到最优配置
    best_result = results_df.loc[results_df['pnl_pct'].idxmax()]
    
    print(f"\n{'='*60}")
    print("优化完成！")
    print(f"{'='*60}")
    print(f"\n最优配置:")
    print(f"配置编号: {best_result['config']}")
    print(f"止盈: {best_result['take_profit']*100:.1f}%")
    print(f"止损: {best_result['stop_loss']*100:.1f}%")
    print(f"仓位上限: {best_result['max_position']*100:.0f}%")
    print(f"做多阈值: {best_result['threshold_long']}")
    print(f"做空阈值: {best_result['threshold_short']}")
    print(f"调仓阈值: {best_result['add_threshold']}")
    print(f"最小调仓: {best_result['min_adjust']} USDT")
    print(f"最终资金: {best_result['final_balance']:.2f} USDT")
    print(f"累计收益: {best_result['pnl']:+.2f} USDT ({best_result['pnl_pct']:+.2f}%)")
    print(f"交易次数: {int(best_result['trade_count'])}")
    
    print(f"\n所有配置排名（按收益率）:")
    print(results_df[['config', 'pnl_pct', 'pnl', 'trade_count', 'take_profit', 'stop_loss']].sort_values('pnl_pct', ascending=False).to_string(index=False))
    
    return results_df

if __name__ == '__main__':
    optimize_parameters()