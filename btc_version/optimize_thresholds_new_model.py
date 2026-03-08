import os
import sys
import pandas as pd
from config import config
from backtest.backtest import Backtester

def optimize_thresholds_for_new_model():
    """为新模型优化交易阈值"""
    
    # 测试不同的阈值组合
    test_configs = [
        # (做多阈值, 做空阈值)
        
        # 配置1: 当前配置
        (0.5, 0.4),
        
        # 配置2: 更激进
        (0.48, 0.42),
        
        # 配置3: 更激进
        (0.46, 0.44),
        
        # 配置4: 极激进
        (0.45, 0.45),
        
        # 配置5: 略微激进
        (0.49, 0.41),
        
        # 配置6: 中等激进
        (0.47, 0.43),
        
        # 配置7: 保守
        (0.52, 0.48),
        
        # 配置8: 更保守
        (0.55, 0.45),
        
        # 配置9: 非常保守
        (0.58, 0.42),
        
        # 配置10: 极端保守
        (0.6, 0.4),
    ]
    
    results = []
    
    for i, (thresh_long, thresh_short) in enumerate(test_configs, 1):
        print(f"\n{'='*60}")
        print(f"测试配置 {i}/{len(test_configs)}")
        print(f"{'='*60}")
        print(f"做多阈值: {thresh_long}")
        print(f"做空阈值: {thresh_short}")
        
        # 临时修改配置
        original_thresh_long = config.THRESHOLD_LONG
        original_thresh_short = config.THRESHOLD_SHORT
        
        config.THRESHOLD_LONG = thresh_long
        config.THRESHOLD_SHORT = thresh_short
        
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
                'threshold_long': thresh_long,
                'threshold_short': thresh_short,
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
                'threshold_long': thresh_long,
                'threshold_short': thresh_short,
                'final_balance': 0,
                'pnl': 0,
                'pnl_pct': 0,
                'max_drawdown': 0,
                'trade_count': 0,
                'error': str(e)
            })
        
        # 恢复原始配置
        config.THRESHOLD_LONG = original_thresh_long
        config.THRESHOLD_SHORT = original_thresh_short
    
    # 保存结果
    results_df = pd.DataFrame(results)
    results_df.to_csv('threshold_optimization_new_model.csv', index=False)
    
    # 找到最优配置
    best_result = results_df.loc[results_df['pnl_pct'].idxmax()]
    
    print(f"\n{'='*60}")
    print("阈值优化完成！")
    print(f"{'='*60}")
    print(f"\n最优配置:")
    print(f"配置编号: {best_result['config']}")
    print(f"做多阈值: {best_result['threshold_long']}")
    print(f"做空阈值: {best_result['threshold_short']}")
    print(f"最终资金: {best_result['final_balance']:.2f} USDT")
    print(f"累计收益: {best_result['pnl']:+.2f} USDT ({best_result['pnl_pct']:+.2f}%)")
    print(f"交易次数: {int(best_result['trade_count'])}")
    
    print(f"\n所有配置排名（按收益率）:")
    print(results_df[['config', 'pnl_pct', 'pnl', 'trade_count', 'threshold_long', 'threshold_short']].sort_values('pnl_pct', ascending=False).to_string(index=False))
    
    return results_df

if __name__ == '__main__':
    optimize_thresholds_for_new_model()