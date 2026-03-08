import os
import sys
import json
import subprocess
from datetime import datetime
import itertools
import pandas as pd

class ParameterOptimizer:
    def __init__(self):
        self.results = []
        self.base_config = {
            'TAKE_PROFIT': 0.03,
            'STOP_LOSS': 0.015,
            'THRESHOLD_LONG': 0.5,
            'THRESHOLD_SHORT': 0.4,
            'MIN_HOLD_BARS': 8,
        }
    
    def update_env(self, params):
        """更新.env文件中的参数"""
        env_path = '/home/ubuntu/github/quant_sol_project/.env'
        with open(env_path, 'r') as f:
            lines = f.readlines()
        
        updated_lines = []
        for line in lines:
            updated = False
            for key, value in params.items():
                if line.startswith(f'{key}='):
                    updated_lines.append(f'{key}={value}\n')
                    updated = True
                    break
            if not updated:
                updated_lines.append(line)
        
        with open(env_path, 'w') as f:
            f.writelines(updated_lines)
    
    def run_backtest(self):
        """运行回测并解析结果"""
        try:
            result = subprocess.run(
                ['PYTHONPATH=.', '/home/ubuntu/github/quant_sol_project/.venv/bin/python', 
                 'backtest/backtest.py'],
                cwd='/home/ubuntu/github/quant_sol_project',
                capture_output=True,
                text=True,
                timeout=60
            )
            
            output = result.stdout
            
            # 解析回测结果
            metrics = {}
            for line in output.split('\n'):
                if '最终资金:' in line:
                    metrics['final_balance'] = float(line.split(':')[1].strip().split()[0])
                elif '累计收益:' in line:
                    metrics['total_pnl'] = float(line.split(':')[1].strip().split()[0])
                elif '最大回撤:' in line:
                    metrics['max_drawdown'] = float(line.split(':')[1].strip().replace('%', ''))
                elif '胜率:' in line:
                    metrics['win_rate'] = float(line.split(':')[1].strip().replace('%', ''))
                elif '盈利次数:' in line:
                    metrics['wins'] = int(line.split(':')[1].strip())
                elif '亏损次数:' in line:
                    metrics['losses'] = int(line.split(':')[1].strip())
                elif '盈亏比:' in line:
                    metrics['profit_factor'] = float(line.split(':')[1].strip())
                elif '已平仓交易:' in line:
                    metrics['closed_trades'] = int(line.split(':')[1].strip())
            
            return metrics
        except Exception as e:
            print(f"回测失败: {e}")
            return None
    
    def optimize_take_profit_stop_loss(self):
        """优化止盈止损参数"""
        print("\n" + "="*60)
        print("优化止盈止损参数")
        print("="*60)
        
        # 测试不同的止盈止损组合
        tp_values = [0.02, 0.025, 0.03, 0.035, 0.04]
        sl_values = [0.01, 0.012, 0.015, 0.018, 0.02]
        
        for tp, sl in itertools.product(tp_values, sl_values):
            params = {
                'TAKE_PROFIT': tp,
                'STOP_LOSS': sl,
            }
            
            print(f"\n测试: 止盈={tp*100:.1f}%, 止损={sl*100:.1f}%")
            
            # 更新配置
            self.update_env(params)
            
            # 运行回测
            metrics = self.run_backtest()
            
            if metrics:
                metrics.update(params)
                self.results.append(metrics)
                
                # 打印结果
                print(f"  胜率: {metrics.get('win_rate', 0):.1f}% | "
                      f"盈亏比: {metrics.get('profit_factor', 0):.2f} | "
                      f"收益: {metrics.get('total_pnl', 0):+.2f} | "
                      f"回撤: {metrics.get('max_drawdown', 0):.2f}%")
    
    def optimize_thresholds(self):
        """优化策略阈值参数"""
        print("\n" + "="*60)
        print("优化策略阈值参数")
        print("="*60)
        
        # 测试不同的阈值组合
        long_thresholds = [0.45, 0.48, 0.5, 0.52, 0.55]
        short_thresholds = [0.35, 0.38, 0.4, 0.42, 0.45]
        
        for long_th, short_th in itertools.product(long_thresholds, short_thresholds):
            params = {
                'THRESHOLD_LONG': long_th,
                'THRESHOLD_SHORT': short_th,
            }
            
            print(f"\n测试: 做多阈值={long_th:.2f}, 做空阈值={short_th:.2f}")
            
            # 更新配置
            self.update_env(params)
            
            # 运行回测
            metrics = self.run_backtest()
            
            if metrics:
                metrics.update(params)
                self.results.append(metrics)
                
                # 打印结果
                print(f"  胜率: {metrics.get('win_rate', 0):.1f}% | "
                      f"盈亏比: {metrics.get('profit_factor', 0):.2f} | "
                      f"收益: {metrics.get('total_pnl', 0):+.2f} | "
                      f"交易次数: {metrics.get('closed_trades', 0)}")
    
    def optimize_min_hold_bars(self):
        """优化最小持仓期"""
        print("\n" + "="*60)
        print("优化最小持仓期")
        print("="*60)
        
        # 测试不同的最小持仓期
        hold_bars_values = [0, 4, 6, 8, 10, 12]
        
        for hold_bars in hold_bars_values:
            params = {
                'MIN_HOLD_BARS': hold_bars,
            }
            
            print(f"\n测试: 最小持仓期={hold_bars}")
            
            # 更新配置
            self.update_env(params)
            
            # 运行回测
            metrics = self.run_backtest()
            
            if metrics:
                metrics.update(params)
                self.results.append(metrics)
                
                # 打印结果
                print(f"  胜率: {metrics.get('win_rate', 0):.1f}% | "
                      f"盈亏比: {metrics.get('profit_factor', 0):.2f} | "
                      f"收益: {metrics.get('total_pnl', 0):+.2f} | "
                      f"交易次数: {metrics.get('closed_trades', 0)}")
    
    def find_best_config(self):
        """找到最优配置"""
        if not self.results:
            print("没有回测结果")
            return None
        
        df = pd.DataFrame(self.results)
        
        # 计算综合得分
        # 得分 = 胜率 * 0.4 + 盈亏比 * 0.3 + (1-回撤) * 0.3
        df['score'] = (
            df['win_rate'] * 0.4 + 
            df['profit_factor'] * 0.3 + 
            (1 - df['max_drawdown']/100) * 0.3
        )
        
        # 找到得分最高的配置
        best = df.loc[df['score'].idxmax()]
        
        print("\n" + "="*60)
        print("最优配置")
        print("="*60)
        print(f"综合得分: {best['score']:.3f}")
        print(f"胜率: {best['win_rate']:.1f}%")
        print(f"盈亏比: {best['profit_factor']:.2f}")
        print(f"累计收益: {best['total_pnl']:+.2f}")
        print(f"最大回撤: {best['max_drawdown']:.2f}%")
        print(f"已平仓交易: {best['closed_trades']}")
        print("\n最优参数:")
        for key in ['TAKE_PROFIT', 'STOP_LOSS', 'THRESHOLD_LONG', 'THRESHOLD_SHORT', 'MIN_HOLD_BARS']:
            if key in best:
                print(f"  {key}: {best[key]}")
        
        # 保存结果
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_file = f"/home/ubuntu/github/quant_sol_project/logs/optimization_results_{timestamp}.csv"
        df.to_csv(result_file, index=False)
        print(f"\n结果已保存到: {result_file}")
        
        return best
    
    def run_full_optimization(self):
        """运行完整优化流程"""
        print("\n" + "="*60)
        print("开始参数优化")
        print("="*60)
        
        # 1. 优化止盈止损
        self.optimize_take_profit_stop_loss()
        
        # 2. 优化策略阈值
        self.optimize_thresholds()
        
        # 3. 优化最小持仓期
        self.optimize_min_hold_bars()
        
        # 4. 找到最优配置
        best_config = self.find_best_config()
        
        return best_config

if __name__ == '__main__':
    optimizer = ParameterOptimizer()
    best_config = optimizer.run_full_optimization()
    
    if best_config:
        print("\n" + "="*60)
        print("优化完成！")
        print("="*60)
        print("建议使用最优参数配置系统。")