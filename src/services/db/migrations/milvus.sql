-- ==============================================================================
-- NL2SQL v3 数据库迁移脚本 - Milvus Collections
-- ==============================================================================
--
-- 说明：
-- 1. 本文件用于统一维护 Milvus Collection 的 DDL 风格定义。
-- 2. Milvus 不直接执行 SQL，本文件作为结构规范与初始化参考。
-- 3. 实际创建 Collection 时，应使用 pymilvus 的 FieldSchema / CollectionSchema。
--
-- 当前约定：
-- - 向量维度：1024
-- - 向量索引：HNSW
-- - 相似度度量：COSINE
-- - 索引参数：M=16, efConstruction=200
--
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- Collection: table_schema_embeddings
-- 用途：表/字段 schema 向量检索
-- ------------------------------------------------------------------------------
CREATE TABLE table_schema_embeddings (
    object_id VARCHAR(256) PRIMARY KEY,
    object_type VARCHAR(64) NOT NULL,
    db_name VARCHAR(64) NOT NULL,
    table_name VARCHAR(256) NOT NULL,
    object_desc VARCHAR(8192) NOT NULL,
    embedding FLOAT_VECTOR(1024) NOT NULL,
    time_col_hint VARCHAR(512) NOT NULL,
    table_category VARCHAR(64) NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX embedding ON table_schema_embeddings
USING HNSW
WITH (metric_type = 'COSINE', M = 16, efConstruction = 200);

-- 字段约定：
-- - object_id:
--   - 表记录：db.schema.table
--   - 字段记录：db.schema.table.column
-- - db_name: 业务数据库名称
-- - table_name:
--   - 表记录：schema.table
--   - 字段记录：所属表的 schema.table

-- ------------------------------------------------------------------------------
-- Collection: dim_value_embeddings
-- 用途：维度值向量检索
-- ------------------------------------------------------------------------------
CREATE TABLE dim_value_embeddings (
    id BIGINT PRIMARY KEY AUTO_ID,
    db_name VARCHAR(64) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    col_name VARCHAR(128) NOT NULL,
    col_value VARCHAR(1024) NOT NULL,
    embedding FLOAT_VECTOR(1024) NOT NULL,
    update_ts BIGINT NOT NULL
);

CREATE INDEX embedding ON dim_value_embeddings
USING HNSW
WITH (metric_type = 'COSINE', M = 16, efConstruction = 200);

-- 字段约定：
-- - db_name: 从旧数据 table_name 的第一段 db_name 提取
-- - table_name: 统一存储为 schema.table

-- ------------------------------------------------------------------------------
-- Collection: sql_example_embeddings
-- 用途：历史 SQL 示例向量检索
-- ------------------------------------------------------------------------------
CREATE TABLE sql_example_embeddings (
    example_id VARCHAR(256) PRIMARY KEY,
    db_name VARCHAR(64) NOT NULL,
    question_sql VARCHAR(16384) NOT NULL,
    embedding FLOAT_VECTOR(1024) NOT NULL,
    domain VARCHAR(256) NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX embedding ON sql_example_embeddings
USING HNSW
WITH (metric_type = 'COSINE', M = 16, efConstruction = 200);

-- 字段约定：
-- - example_id: db_name:uuid
-- - db_name: 从 example_id 冒号前半段提取
-- - question_sql: JSON 字符串，包含 question / sql
