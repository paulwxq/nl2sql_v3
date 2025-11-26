#!/usr/bin/env python3
"""
MetaWeave 元数据生成运行脚本

直接运行元数据生成流程的简单脚本。
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

import argparse
import logging
from src.metaweave.core.metadata.generator import MetadataGenerator


def setup_logging(debug: bool = False):
    """设置日志"""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="MetaWeave 元数据生成工具"
    )
    
    parser.add_argument(
        "--config",
        "-c",
        required=True,
        help="配置文件路径"
    )
    
    parser.add_argument(
        "--schemas",
        "-s",
        help="要处理的 schema 列表（逗号分隔）"
    )
    
    parser.add_argument(
        "--tables",
        "-t",
        help="要处理的表名列表（逗号分隔）"
    )
    
    parser.add_argument(
        "--incremental",
        "-i",
        action="store_true",
        help="增量更新模式"
    )
    
    parser.add_argument(
        "--max-workers",
        "-w",
        type=int,
        default=4,
        help="最大并发数（默认: 4）"
    )
    
    parser.add_argument(
        "--step",
        choices=["ddl", "json", "cql", "md", "all"],
        default="all",
        help="指定要执行的步骤，默认为 all（ddl->json->cql->md）"
    )
    
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        help="启用调试模式"
    )
    
    args = parser.parse_args()
    
    # 设置日志
    setup_logging(args.debug)
    logger = logging.getLogger(__name__)
    
    try:
        # 解析配置文件路径
        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = project_root / config_path
        
        logger.info(f"加载配置: {config_path}")
        
        # 初始化生成器
        generator = MetadataGenerator(config_path)
        
        # 解析 schemas 和 tables
        schema_list = None
        if args.schemas:
            schema_list = [s.strip() for s in args.schemas.split(",")]
            logger.info(f"指定 Schema: {schema_list}")
        
        table_list = None
        if args.tables:
            table_list = [t.strip() for t in args.tables.split(",")]
            logger.info(f"指定表: {table_list}")
        
        # 执行生成
        logger.info("开始生成元数据...")
        result = generator.generate(
            schemas=schema_list,
            tables=table_list,
            incremental=args.incremental,
            max_workers=args.max_workers,
            step=args.step
        )
        
        # 显示结果
        print("\n" + "=" * 60)
        print("生成结果统计")
        print("=" * 60)
        print(f"成功处理: {result.processed_tables} 张表")
        print(f"处理失败: {result.failed_tables} 张表")
        print(f"生成注释: {result.generated_comments} 个")
        print(f"识别逻辑主键: {result.logical_keys_found} 个")
        print(f"输出文件: {len(result.output_files)} 个")
        
        if result.errors:
            print(f"\n错误列表:")
            for error in result.errors[:5]:
                print(f"  - {error}")
            if len(result.errors) > 5:
                print(f"  ... 还有 {len(result.errors) - 5} 个错误")
        
        print("=" * 60)
        
        if result.success:
            print("✅ 元数据生成完成！")
            return 0
        else:
            print("⚠️  元数据生成完成，但存在错误")
            return 1
    
    except Exception as e:
        logger.error(f"元数据生成失败: {e}", exc_info=True)
        print(f"\n❌ 错误: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

