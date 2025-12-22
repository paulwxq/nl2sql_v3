"""验证 Milvus 中的 dim_value_embeddings 数据"""

from pymilvus import connections, db, Collection, utility

# 连接配置（从 .env 读取）
import os
from dotenv import load_dotenv

load_dotenv()

MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
MILVUS_DATABASE = os.getenv("MILVUS_DATABASE", "nl2sql")
ALIAS = "verify_connection"

print("=" * 60)
print("🔍 验证 Milvus dim_value_embeddings 数据")
print("=" * 60)
print()

# 1. 连接到 Milvus
print(f"📡 连接到 Milvus: {MILVUS_HOST}:{MILVUS_PORT}")
connections.connect(
    alias=ALIAS,
    host=MILVUS_HOST,
    port=MILVUS_PORT,
)
print("✅ 连接成功")
print()

# 2. 列出所有 database
print("📦 所有 Database:")
databases = db.list_database()
for db_name in databases:
    print(f"  - {db_name}")
print()

# 3. 切换到 nl2sql database
if MILVUS_DATABASE not in databases:
    print(f"❌ Database '{MILVUS_DATABASE}' 不存在！")
    exit(1)

print(f"🔄 切换到 database: {MILVUS_DATABASE}")
db.using_database(MILVUS_DATABASE)
print("✅ 切换成功")
print()

# 4. 列出该 database 下的所有 collection
print(f"📚 Database '{MILVUS_DATABASE}' 中的 Collections:")
collections = utility.list_collections(using=ALIAS)
for coll_name in collections:
    print(f"  - {coll_name}")
print()

# 5. 检查 dim_value_embeddings collection
COLLECTION_NAME = "dim_value_embeddings"
if COLLECTION_NAME not in collections:
    print(f"❌ Collection '{COLLECTION_NAME}' 不存在于 database '{MILVUS_DATABASE}'！")
    exit(1)

print(f"🔍 检查 Collection: {COLLECTION_NAME}")
collection = Collection(COLLECTION_NAME, using=ALIAS)

# 6. 获取统计信息
collection.load()
stats = collection.num_entities
print(f"  - 记录数: {stats}")
print()

# 7. 查询前 10 条数据
print("📄 前 10 条数据：")
results = collection.query(
    expr="id >= 0",
    output_fields=["table_name", "col_name", "col_value"],
    limit=10,
)
for i, record in enumerate(results, 1):
    print(f"  {i}. {record['table_name']}.{record['col_name']}: {record['col_value']}")
print()

# 8. 按表统计
print("📊 按表统计：")
table_stats = {}
all_records = collection.query(
    expr="id >= 0",
    output_fields=["table_name"],
    limit=1000,
)
for record in all_records:
    table_name = record["table_name"]
    table_stats[table_name] = table_stats.get(table_name, 0) + 1

for table, count in sorted(table_stats.items()):
    print(f"  - {table}: {count} 条")
print()

print("=" * 60)
print("✅ 验证完成！")
print("=" * 60)

# 断开连接
connections.disconnect(ALIAS)

