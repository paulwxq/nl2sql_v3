"""数据处理工具函数"""

import logging
from typing import List, Any, Optional
import pandas as pd

logger = logging.getLogger("metaweave.data_utils")


def calculate_uniqueness(data: pd.DataFrame, columns: List[str]) -> float:
    """计算指定列的唯一度
    
    唯一度 = 不重复值的数量 / 总行数
    
    Args:
        data: 数据 DataFrame
        columns: 要计算的列名列表
        
    Returns:
        唯一度 (0.0 ~ 1.0)
    """
    if data.empty or not columns:
        return 0.0
    
    try:
        # 检查列是否存在
        for col in columns:
            if col not in data.columns:
                logger.warning(f"列不存在: {col}")
                return 0.0
        
        # 计算指定列组合的唯一值数量
        if len(columns) == 1:
            unique_count = data[columns[0]].nunique()
        else:
            unique_count = data[columns].drop_duplicates().shape[0]
        
        total_count = len(data)
        
        if total_count == 0:
            return 0.0
        
        uniqueness = unique_count / total_count
        return round(uniqueness, 4)
    
    except Exception as e:
        logger.error(f"计算唯一度失败: {e}")
        return 0.0


def calculate_null_rate(data: pd.DataFrame, columns: List[str]) -> float:
    """计算指定列的空值率
    
    空值率 = 包含空值的行数 / 总行数
    
    Args:
        data: 数据 DataFrame
        columns: 要计算的列名列表
        
    Returns:
        空值率 (0.0 ~ 1.0)
    """
    if data.empty or not columns:
        return 0.0
    
    try:
        # 检查列是否存在
        for col in columns:
            if col not in data.columns:
                logger.warning(f"列不存在: {col}")
                return 0.0
        
        # 计算包含空值的行数
        null_count = data[columns].isnull().any(axis=1).sum()
        total_count = len(data)
        
        if total_count == 0:
            return 0.0
        
        null_rate = null_count / total_count
        return round(null_rate, 4)
    
    except Exception as e:
        logger.error(f"计算空值率失败: {e}")
        return 0.0


def format_data_type(
    data_type: str,
    char_length: Optional[int] = None,
    numeric_precision: Optional[int] = None,
    numeric_scale: Optional[int] = None
) -> str:
    """格式化数据类型显示
    
    Args:
        data_type: 数据类型
        char_length: 字符最大长度
        numeric_precision: 数值精度
        numeric_scale: 数值小数位数
        
    Returns:
        格式化后的数据类型字符串
    """
    formatted_type = data_type.upper()
    
    # 字符类型
    if data_type in ["character varying", "varchar", "character", "char"] and char_length:
        formatted_type = f"{formatted_type}({char_length})"
    
    # 数值类型
    elif data_type in ["numeric", "decimal"] and numeric_precision:
        if numeric_scale:
            formatted_type = f"{formatted_type}({numeric_precision},{numeric_scale})"
        else:
            formatted_type = f"{formatted_type}({numeric_precision})"
    
    return formatted_type


def truncate_sample(data: pd.DataFrame, max_rows: int = 5) -> pd.DataFrame:
    """截断样本数据到指定行数
    
    Args:
        data: 数据 DataFrame
        max_rows: 最大行数
        
    Returns:
        截断后的 DataFrame
    """
    if len(data) <= max_rows:
        return data
    return data.head(max_rows)


def safe_str(value: Any, max_length: int = 100) -> str:
    """安全转换值为字符串
    
    处理 None、特殊字符、过长字符串等情况。
    
    Args:
        value: 要转换的值
        max_length: 最大长度
        
    Returns:
        字符串表示
    """
    if value is None:
        return ""
    
    try:
        str_value = str(value)
        if len(str_value) > max_length:
            return str_value[:max_length] + "..."
        return str_value
    except Exception:
        return "<unconvertible>"


def dataframe_to_sample_dict(
    df: pd.DataFrame, 
    max_rows: int = 5
) -> List[dict]:
    """将 DataFrame 转换为样本字典列表
    
    Args:
        df: DataFrame
        max_rows: 最大行数
        
    Returns:
        样本字典列表
    """
    if df.empty:
        return []
    
    # 截断数据
    sample_df = truncate_sample(df, max_rows)
    
    # 转换为字典列表，处理特殊值
    try:
        result = []
        for _, row in sample_df.iterrows():
            row_dict = {}
            for col in sample_df.columns:
                value = row[col]
                # 处理 NaN 和 None
                if pd.isna(value):
                    row_dict[col] = None
                else:
                    row_dict[col] = safe_str(value, max_length=200)
            result.append(row_dict)
        return result
    except Exception as e:
        logger.error(f"转换 DataFrame 为字典列表失败: {e}")
        return []


def get_column_statistics(
    df: pd.DataFrame, 
    column: str,
    value_distribution_threshold: int = 10
) -> dict:
    """获取列的统计信息
    
    Args:
        df: DataFrame
        column: 列名
        value_distribution_threshold: 唯一值数量阈值，小于等于此值时统计值分布
        
    Returns:
        统计信息字典
    """
    if df.empty or column not in df.columns:
        return {}
    
    try:
        col_data = df[column]
        stats = {
            "sample_count": int(len(col_data)),
            "unique_count": int(col_data.nunique()),
            "null_count": int(col_data.isnull().sum()),
            "null_rate": float(calculate_null_rate(df, [column])),
            "uniqueness": float(calculate_uniqueness(df, [column])),
        }
        
        # 如果是数值类型，添加数值统计
        if pd.api.types.is_numeric_dtype(col_data):
            stats.update({
                "min": safe_str(col_data.min()),
                "max": safe_str(col_data.max()),
                "mean": safe_str(col_data.mean()),
            })
        
        # 如果唯一值较少，添加值分布
        if stats["unique_count"] <= value_distribution_threshold:
            value_counts = col_data.value_counts().head(10)
            stats["value_distribution"] = {
                safe_str(k): int(v) for k, v in value_counts.items()
            }
        
        return stats
    except Exception as e:
        logger.error(f"获取列统计信息失败 ({column}): {e}")
        return {}


def is_potential_key_column(column_name: str) -> bool:
    """判断列名是否可能是主键列
    
    Args:
        column_name: 列名
        
    Returns:
        是否可能是主键
    """
    column_name_lower = column_name.lower()
    key_patterns = ["id", "code", "key", "no", "number", "pk", "_id"]
    
    for pattern in key_patterns:
        if pattern in column_name_lower:
            return True
    
    return False

