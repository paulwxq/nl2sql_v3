#需求：把指定的维度表数据的加载到向量数据库

1.在metadata_config.yaml中增加embedding database的配置，包括embedding database的ip/端口号/database的名字等。当前开发时，仅开发加载到Milvus的代码，将来需要支持pgvector.
注意，当前metadata_config.yaml中的embedding是embedding llm的配置。

2.需要自动+手工创建一个用于加载维度数据的yaml文件dim_tables.yaml，yaml文件中需要包含的加载的列表：
先自动创建一个，从json_llm找出来维表类型的数据，把dim表名按照格式写入到yaml文件中,然后手工指定需要embedding_col字段。
-schema_name.table_name:
 -embedding_col: column_name

3.维度数据加载代码，读取三个yaml文件：
 - 加载作业的配置 loader_cofnig.yaml，
 - 维表的列表dim_tables.yaml，
 - 原来的配置的metadata_config.yaml文件，它定义了embedding模型和embedding database的配置信息。
 获取足够的配置信息后，代码向数据库中写入数据，把 schema.table_name,column_name,column_value,embedding(向量后的column_value) 存储到 dim_value_embeddings. 在加载过程中，代码调用 embedding模型，对column_value进行向量化，然后把向量化的数据写入到 embedding字段。
 
这个功能可能的执行代码：
python -m src.metaweave.cli.main load --type dim_value --clean --config configs/metaweave/loader_config.yaml

4.当前的表结构的定义的代码示例：

```python
from pymilvus import (
    connections, db,
    FieldSchema, CollectionSchema, Collection,
    DataType
)

# 1. 连接 Milvus
connections.connect(host="localhost", port="19530")


# 2. 创建 Database（等价于 PostgreSQL schema）
db_name = "nl2sql"
if db_name not in db.list_database():
    db.create_database(db_name)

db.using_database(db_name)


# 3. 定义字段 Schema
fields = [
    FieldSchema(
        name="id",
        dtype=DataType.INT64,
        is_primary=True,
        auto_id=True
    ),
    FieldSchema(
        name="table_name",  # 格式 schema_name.table_name
        dtype=DataType.VARCHAR,
        max_length=128
    ),
    FieldSchema(
        name="col_name",
        dtype=DataType.VARCHAR,
        max_length=128
    ),
    FieldSchema(
        name="col_value",
        dtype=DataType.VARCHAR,
        max_length=1024
    ),
    FieldSchema(
        name="embedding",
        dtype=DataType.FLOAT_VECTOR,
        dim=1024     # 阿里云 text-embedding-v3 模型
    ),
    FieldSchema(
        name="update_ts",
        dtype=DataType.INT64,
    )
]

schema = CollectionSchema(
    fields=fields,
    description="Embedding index for dimension value text fields"
)


# 4. 创建 Collection
collection_name = "dim_value_embeddings"
if collection_name not in db.list_collections():
    coll = Collection(
        name=collection_name,
        schema=schema,
        shards_num=2
    )
else:
    coll = Collection(collection_name)


# 5. 创建向量索引（HNSW + COSINE）
index_params = {
    "index_type": "HNSW",
    "metric_type": "COSINE",
    "params": {
        "M": 16,
        "efConstruction": 200
    }
}

coll.create_index(
    field_name="embedding",
    index_params=index_params
)

print("Milvus collection dim_value_index created successfully.")
```