"""Milvus Collection 重命名工具。

用途：将 table_schema_embedding（单数）重命名为 table_schema_embeddings（复数）
作者：系统维护工具
日期：2025-12-18
"""

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv


def resolve_env_vars(config: Any) -> Any:
    """递归解析配置中的环境变量占位符。

    支持格式：${VAR_NAME:default_value} 或 ${VAR_NAME}
    """
    if isinstance(config, dict):
        return {k: resolve_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [resolve_env_vars(item) for item in config]
    elif isinstance(config, str):
        # 匹配 ${VAR_NAME:default} 或 ${VAR_NAME}
        pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'

        def replacer(match):
            var_name = match.group(1)
            default_value = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default_value)

        return re.sub(pattern, replacer, config)
    else:
        return config


def load_config() -> Dict[str, Any]:
    """加载配置文件和环境变量。"""
    # 1. 加载 .env 文件
    project_root = Path(__file__).parent.parent
    env_file = project_root / ".env"

    if not env_file.exists():
        print(f"⚠️  警告: .env 文件不存在: {env_file}")
    else:
        load_dotenv(env_file)
        print(f"✅ 已加载环境变量: {env_file}")

    # 2. 加载 config.yaml
    config_file = project_root / "src" / "configs" / "config.yaml"
    if not config_file.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_file}")

    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # 3. 解析环境变量占位符
    config = resolve_env_vars(config)

    print(f"✅ 已加载配置文件: {config_file}")
    return config


def rename_collection(old_name: str, new_name: str, config: Dict[str, Any]) -> None:
    """重命名 Milvus Collection。

    Args:
        old_name: 原 collection 名称
        new_name: 新 collection 名称
        config: 配置字典
    """
    try:
        from pymilvus import Collection, connections, db, utility
    except ImportError as exc:
        print("❌ 错误: pymilvus 未安装，请先安装：pip install pymilvus")
        sys.exit(1)

    # 获取 Milvus 配置
    vector_db_config = config.get("vector_database", {})
    milvus_config = vector_db_config.get("providers", {}).get("milvus", {})

    if not milvus_config:
        print("❌ 错误: 配置文件中未找到 Milvus 配置")
        sys.exit(1)

    host = milvus_config.get("host", "localhost")
    port = str(milvus_config.get("port", "19530"))
    database = milvus_config.get("database", "nl2sql")
    user = milvus_config.get("user", "")
    password = milvus_config.get("password", "")
    alias = milvus_config.get("alias", "default")
    timeout = milvus_config.get("timeout", 30)

    print(f"\n📋 连接信息:")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   Database: {database}")
    print(f"   User: {user if user else '(无认证)'}")
    print(f"   Alias: {alias}")

    try:
        # 1. 连接 Milvus
        print(f"\n🔗 正在连接 Milvus...")
        connections.connect(
            alias=alias,
            host=host,
            port=port,
            user=user if user else None,
            password=password if password else None,
            timeout=timeout,
        )
        print(f"✅ 连接成功")

        # 2. 切换到指定 database
        print(f"\n📂 切换到 database: {database}")
        existing_databases = db.list_database(using=alias)
        print(f"   可用的 databases: {existing_databases}")

        if database not in existing_databases:
            print(f"❌ 错误: Database '{database}' 不存在")
            sys.exit(1)

        db.using_database(database, using=alias)
        print(f"✅ 已切换到 database: {database}")

        # 3. 列出所有 collections
        collections = utility.list_collections(using=alias)
        print(f"\n📊 当前所有 Collections:")
        for coll in collections:
            print(f"   - {coll}")

        # 4. 检查源 collection 是否存在
        print(f"\n🔍 检查源 collection: {old_name}")
        if old_name not in collections:
            print(f"❌ 错误: 源 collection '{old_name}' 不存在")
            print(f"提示: 可能已经被重命名为 '{new_name}'")
            sys.exit(1)
        print(f"✅ 源 collection 存在")

        # 5. 检查目标 collection 是否已存在
        print(f"\n🔍 检查目标 collection: {new_name}")
        if new_name in collections:
            print(f"⚠️  警告: 目标 collection '{new_name}' 已存在")
            print(f"提示: 重命名操作已完成，无需再次执行")
            sys.exit(0)
        print(f"✅ 目标 collection 不存在，可以继续")

        # 6. 获取源 collection 统计信息
        print(f"\n📈 获取源 collection 统计信息...")
        collection = Collection(old_name, using=alias)
        old_count = collection.num_entities
        print(f"   记录数: {old_count:,}")
        print(f"   索引数: {len(collection.indexes)}")

        # 7. 释放 collection（重命名前必须释放）
        print(f"\n🔓 释放 collection: {old_name}")
        collection.release()
        print(f"✅ Collection 已释放")

        # 8. 执行重命名
        print(f"\n🔄 正在重命名 collection...")
        print(f"   {old_name} → {new_name}")
        utility.rename_collection(old_name, new_name, using=alias)
        print(f"✅ 重命名成功")

        # 9. 验证重命名结果
        print(f"\n✓ 验证重命名结果...")
        collections_after = utility.list_collections(using=alias)

        if new_name not in collections_after:
            print(f"❌ 错误: 新 collection '{new_name}' 未找到")
            sys.exit(1)

        if old_name in collections_after:
            print(f"❌ 错误: 旧 collection '{old_name}' 仍然存在")
            sys.exit(1)

        # 10. 加载并验证数据
        print(f"\n📥 加载新 collection...")
        new_collection = Collection(new_name, using=alias)
        new_collection.load()
        new_count = new_collection.num_entities
        print(f"   记录数: {new_count:,}")

        if new_count != old_count:
            print(f"⚠️  警告: 记录数不一致 (旧: {old_count:,}, 新: {new_count:,})")
        else:
            print(f"✅ 记录数验证通过")

        # 11. 最终报告
        print(f"\n" + "="*60)
        print(f"🎉 重命名操作完成！")
        print(f"="*60)
        print(f"原名称: {old_name}")
        print(f"新名称: {new_name}")
        print(f"记录数: {new_count:,}")
        print(f"="*60)

    except Exception as exc:
        print(f"\n❌ 错误: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # 断开连接
        try:
            connections.disconnect(alias=alias)
            print(f"\n👋 已断开连接")
        except Exception:
            pass


def main():
    """主函数。"""
    print("="*60)
    print("Milvus Collection 重命名工具")
    print("="*60)

    # 定义重命名参数
    old_name = "table_schema_embedding"  # 单数（旧名称）
    new_name = "table_schema_embeddings"  # 复数（新名称）

    print(f"\n目标操作:")
    print(f"  {old_name} → {new_name}")

    # 加载配置
    print(f"\n⚙️  加载配置...")
    config = load_config()

    # 执行重命名
    rename_collection(old_name, new_name, config)


if __name__ == "__main__":
    main()
