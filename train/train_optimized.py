import pandas as pd
import numpy as np
import joblib
import lightgbm as lgb
from sklearn.model_selection import train_test_split, TimeSeriesSplit
from sklearn.utils import resample
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, precision_score, recall_score, f1_score
from config import config
import os
import xgboost as xgb

from core.ml_feature_engineering import merge_multi_period_features, add_advanced_features
from utils.utils import log_info, BASE_DIR

# 统一拼接绝对路径
lgb_path = os.path.join(BASE_DIR, config.MODEL_PATHS.get("lgb_v1"))
xgb_path = os.path.join(BASE_DIR, config.MODEL_PATHS.get("xgb_v1"))
rf_path = os.path.join(BASE_DIR, config.MODEL_PATHS.get("rf_v1"))
feature_path = os.path.join(BASE_DIR, config.FEATURE_LIST_PATH)

def load_local_data():
    """从本地文件加载历史数据"""
    data_dict = {}
    data_dir = os.path.join(BASE_DIR, 'data')
    
    intervals = {
        '5m': '5m',
        '15m': '15m',
        '1H': '1h'
    }
    
    for key, timeframe in intervals.items():
        filename = f"{config.SYMBOL}_{timeframe}.csv"
        filepath = os.path.join(data_dir, filename)
        
        if os.path.exists(filepath):
            df = pd.read_csv(filepath, index_col=0, parse_dates=True)
            data_dict[key] = df
            log_info(f"✅ 加载 {key} 数据: {len(df)} 根K线")
        else:
            log_error(f"❌ 文件不存在: {filepath}")
            return None
    
    return data_dict

def create_labels(df, future_window=5, threshold=0.002):
    df['future_return'] = df['5m_close'].shift(-future_window) / df['5m_close'] - 1
    df['target'] = np.where(df['future_return'] > threshold, 1,
                     np.where(df['future_return'] < -threshold, 0, np.nan))
    df.dropna(subset=['target'], inplace=True)
    return df

def balance_samples(X, y):
    df = pd.concat([X, y.rename('target')], axis=1)
    long_df = df[df['target'] == 1]
    short_df = df[df['target'] == 0]
    min_count = min(len(long_df), len(short_df))
    
    if min_count == 0:
        log_error("没有足够的样本进行平衡")
        return X, y
    
    long_sample = resample(long_df, n_samples=min_count, replace=False, random_state=42)
    short_sample = resample(short_df, n_samples=min_count, replace=False, random_state=42)
    balanced_df = pd.concat([long_sample, short_sample])
    balanced_df = balanced_df.sample(frac=1, random_state=42)
    return balanced_df.drop('target', axis=1), balanced_df['target']

def evaluate_model(model, model_name, X_test, y_test):
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, average='binary')
    recall = recall_score(y_test, y_pred, average='binary')
    f1 = f1_score(y_test, y_pred, average='binary')
    
    log_info(f"✅ {model_name} 评估结果:")
    log_info(f"   准确率: {acc:.4f}")
    log_info(f"   精确率: {precision:.4f}")
    log_info(f"   召回率: {recall:.4f}")
    log_info(f"   F1分数: {f1:.4f}")
    log_info(f"分类报告:\n{classification_report(y_test, y_pred, digits=4)}")
    
    return {'accuracy': acc, 'precision': precision, 'recall': recall, 'f1': f1}

def train():
    log_info("="*60)
    log_info("开始训练模型（使用优化参数和更多数据）")
    log_info("="*60)
    
    # 加载本地数据
    data_dict = load_local_data()
    if data_dict is None:
        log_error("无法加载数据，退出训练")
        return
    
    # 特征工程
    merged_df = merge_multi_period_features(data_dict)
    merged_df = add_advanced_features(merged_df)
    merged_df = create_labels(merged_df, future_window=5, threshold=0.002)
    
    log_info(f"✅ 数据处理完成: {len(merged_df)} 样本")
    
    # 准备特征
    feature_cols = [col for col in merged_df.columns if col not in ['future_return', 'target']]
    X = merged_df[feature_cols].astype(float)
    y = merged_df['target']
    
    log_info(f"✅ 特征数量: {len(feature_cols)}")
    log_info(f"✅ 样本分布: 做多={sum(y==1)}, 做空={sum(y==0)}")
    
    # 平衡样本
    X_bal, y_bal = balance_samples(X, y)
    log_info(f"✅ 平衡后样本: {len(X_bal)}")
    
    # 时间序列分割
    X_train, X_test, y_train, y_test = train_test_split(X_bal, y_bal, test_size=0.2, shuffle=False)
    
    # 保证是DataFrame
    X_train = pd.DataFrame(X_train, columns=feature_cols)
    X_test = pd.DataFrame(X_test, columns=feature_cols)
    
    log_info(f"✅ 训练集: {len(X_train)}, 测试集: {len(X_test)}")
    
    # ========== 优化后的LightGBM ==========
    log_info("\n训练 LightGBM 模型...")
    lgb_model = lgb.LGBMClassifier(
        n_estimators=1000,          # 增加到1000
        learning_rate=0.01,        # 降低学习率
        max_depth=8,               # 增加深度
        num_leaves=64,             # 增加叶子节点
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.2,            # 增加L1正则化
        reg_lambda=2.0,           # 增加L2正则化
        min_child_samples=10,      # 增加最小子样本
        min_split_gain=0.01,       # 增加分裂增益
        force_col_wise=True,
        random_state=42,
        n_jobs=-1                 # 使用所有CPU核心
    )
    
    lgb_model.fit(X_train, y_train)
    joblib.dump(lgb_model, lgb_path)
    log_info(f"✅ LGB 模型已保存至: {lgb_path}")
    
    # ========== 优化后的XGBoost ==========
    log_info("\n训练 XGBoost 模型...")
    xgb_model = xgb.XGBClassifier(
        n_estimators=1000,         # 增加到1000
        learning_rate=0.01,        # 降低学习率
        max_depth=8,               # 增加深度
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.2,             # 增加L1正则化
        reg_lambda=2.0,            # 增加L2正则化
        min_child_weight=5,        # 增加最小子权重
        gamma=0.1,                 # 增加分裂阈值
        random_state=42,
        n_jobs=-1                  # 使用所有CPU核心
    )
    
    xgb_model.fit(X_train, y_train)
    joblib.dump(xgb_model, xgb_path)
    log_info(f"✅ XGB 模型已保存至: {xgb_path}")
    
    # ========== 优化后的Random Forest ==========
    log_info("\n训练 Random Forest 模型...")
    rf_model = RandomForestClassifier(
        n_estimators=500,           # 增加到500
        max_depth=10,              # 增加深度
        min_samples_split=10,      # 增加最小分裂样本
        min_samples_leaf=5,         # 增加最小叶子样本
        max_features='sqrt',        # 使用sqrt特征数
        random_state=42,
        n_jobs=-1                  # 使用所有CPU核心
    )
    
    rf_model.fit(X_train, y_train)
    joblib.dump(rf_model, rf_path)
    log_info(f"✅ RF 模型已保存至: {rf_path}")
    
    # ========== 评估所有模型 ==========
    log_info("\n" + "="*60)
    log_info("模型评估结果")
    log_info("="*60)
    
    lgb_metrics = evaluate_model(lgb_model, "LightGBM", X_test, y_test)
    xgb_metrics = evaluate_model(xgb_model, "XGBoost", X_test, y_test)
    rf_metrics = evaluate_model(rf_model, "RandomForest", X_test, y_test)
    
    # 保存特征列
    joblib.dump(feature_cols, feature_path)
    log_info(f"✅ 特征列已保存至: {feature_path}")
    
    # 总结
    log_info("\n" + "="*60)
    log_info("训练完成！")
    log_info("="*60)
    log_info("模型性能对比:")
    log_info(f"LightGBM  - 准确率: {lgb_metrics['accuracy']:.4f}, F1: {lgb_metrics['f1']:.4f}")
    log_info(f"XGBoost   - 准确率: {xgb_metrics['accuracy']:.4f}, F1: {xgb_metrics['f1']:.4f}")
    log_info(f"RandomForest - 准确率: {rf_metrics['accuracy']:.4f}, F1: {rf_metrics['f1']:.4f}")
    
    # 找出最佳模型
    best_model = max([
        ('LightGBM', lgb_metrics),
        ('XGBoost', xgb_metrics),
        ('RandomForest', rf_metrics)
    ], key=lambda x: x[1]['f1'])
    
    log_info(f"\n🏆 最佳模型: {best_model[0]} (F1: {best_model[1]['f1']:.4f})")

if __name__ == '__main__':
    train()