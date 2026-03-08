import os
import sys
import pandas as pd
import numpy as np
from core import ml_feature_engineering, okx_api
from config import config

# 测试不同开仓标准的回测结果
def test_different_thresholds():
    thresholds = [
        (0.84, 0.74),  # 原始标准
        (0.80, 0.70),  # 轻微降低
        (0.75, 0.65),  # 中等降低
        (0.70, 0.60),  # 大幅降低
        (0.65, 0.55),  # 非常低
    ]
    
    for long_thresh, short_thresh in thresholds:
        print(f"\n{'='*60}")
        print(f"测试阈值: 做多={long_thresh:.2f}, 做空={short_thresh:.2f}")
        print('='*60)
        
        # 临时修改配置
        config.THRESHOLD_LONG = long_thresh
        config.THRESHOLD_SHORT = short_thresh
        
        # 运行回测
        import backtest.backtest
        backtester = backtest.backtest.Backtester('5m', 2016)
        backtester.run_backtest()

if __name__ == '__main__':
    test_different_thresholds()