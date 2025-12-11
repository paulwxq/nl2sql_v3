"""dim_value 配置与选项数据模型。"""

from dataclasses import dataclass
from typing import Any, Dict, List, Union


@dataclass
class DimTableConfig:
    """单个维表配置。"""

    schema: str
    table: str
    embedding_col: Union[str, List[str], None]  # 支持单列、多列或空

    @property
    def full_table_name(self) -> str:
        return f"{self.schema}.{self.table}"

    @property
    def embedding_cols_list(self) -> List[str]:
        """返回列名列表（统一处理单列和多列）。

        支持三种格式：
        1. None: 返回空列表
        2. 列表: ["col1", "col2", "col3"]
        3. 字符串: "col1" 或 "col1, col2, col3"（自动拆分逗号）

        Returns:
            List[str]: 列名列表，如果为空则返回空列表
        """
        if self.embedding_col is None:
            return []
        if isinstance(self.embedding_col, list):
            return self.embedding_col

        # 字符串格式：检查是否包含逗号（支持逗号分隔的多列）
        col_str = str(self.embedding_col).strip()
        if "," in col_str:
            # 拆分逗号分隔的列名，并去除每个列名的前后空格
            return [col.strip() for col in col_str.split(",") if col.strip()]
        return [col_str]


@dataclass
class DimTablesConfig:
    """维表配置集合。"""

    tables: Dict[str, DimTableConfig]

    @classmethod
    def from_yaml(cls, yaml_data: Dict[str, Any]) -> "DimTablesConfig":
        tables: Dict[str, DimTableConfig] = {}
        for full_name, config in yaml_data.get("tables", {}).items():
            if "." not in full_name:
                # 跳过非法表名
                continue
            schema, table = full_name.split(".", 1)
            tables[full_name] = DimTableConfig(
                schema=schema,
                table=table,
                embedding_col=config.get("embedding_col"),
            )
        return cls(tables=tables)


@dataclass
class LoaderOptions:
    """加载器选项配置（带默认值）。"""

    batch_size: int = 100
    max_records_per_table: int = 0  # 0 = 不限制
    skip_empty_values: bool = True
    truncate_long_text: bool = True
    max_text_length: int = 1024

    @classmethod
    def from_dict(cls, options: Dict[str, Any]) -> "LoaderOptions":
        """从配置字典创建，未提供的字段使用默认值。"""

        return cls(
            batch_size=options.get("batch_size", cls.batch_size),
            max_records_per_table=options.get("max_records_per_table", cls.max_records_per_table),
            skip_empty_values=options.get("skip_empty_values", cls.skip_empty_values),
            truncate_long_text=options.get("truncate_long_text", cls.truncate_long_text),
            max_text_length=options.get("max_text_length", cls.max_text_length),
        )

