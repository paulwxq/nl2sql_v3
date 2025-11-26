"""SQL 查询模板

定义从 PostgreSQL 数据库中提取元数据的 SQL 查询模板。
"""

# 获取表信息
GET_TABLE_INFO_SQL = """
SELECT 
    t.schemaname,
    t.tablename,
    obj_description((t.schemaname || '.' || t.tablename)::regclass, 'pg_class') as table_comment,
    COALESCE(pg_stat_get_live_tuples((t.schemaname || '.' || t.tablename)::regclass), 0) as row_count
FROM pg_tables t
WHERE t.schemaname = %s
ORDER BY t.tablename;
"""

# 获取指定表的信息
GET_SINGLE_TABLE_INFO_SQL = """
SELECT 
    t.schemaname,
    t.tablename,
    obj_description((t.schemaname || '.' || t.tablename)::regclass, 'pg_class') as table_comment,
    COALESCE(pg_stat_get_live_tuples((t.schemaname || '.' || t.tablename)::regclass), 0) as row_count
FROM pg_tables t
WHERE t.schemaname = %s AND t.tablename = %s;
"""

# 获取字段信息
GET_COLUMNS_SQL = """
SELECT 
    c.column_name,
    c.ordinal_position,
    c.data_type,
    c.character_maximum_length,
    c.numeric_precision,
    c.numeric_scale,
    c.is_nullable,
    c.column_default,
    pgd.description as column_comment
FROM information_schema.columns c
LEFT JOIN pg_catalog.pg_statio_all_tables st 
    ON c.table_schema = st.schemaname 
    AND c.table_name = st.relname
LEFT JOIN pg_catalog.pg_description pgd 
    ON pgd.objoid = st.relid 
    AND pgd.objsubid = c.ordinal_position
WHERE c.table_schema = %s AND c.table_name = %s
ORDER BY c.ordinal_position;
"""

# 获取主键
GET_PRIMARY_KEYS_SQL = """
SELECT 
    tc.constraint_name,
    array_agg(kcu.column_name ORDER BY kcu.ordinal_position) as columns
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu 
    ON tc.constraint_name = kcu.constraint_name
    AND tc.table_schema = kcu.table_schema
WHERE tc.constraint_type = 'PRIMARY KEY'
    AND tc.table_schema = %s
    AND tc.table_name = %s
GROUP BY tc.constraint_name;
"""

# 获取外键
GET_FOREIGN_KEYS_SQL = """
SELECT
    tc.constraint_name,
    array_agg(DISTINCT kcu.column_name ORDER BY kcu.column_name) as source_columns,
    ccu.table_schema AS target_schema,
    ccu.table_name AS target_table,
    array_agg(DISTINCT ccu.column_name ORDER BY ccu.column_name) as target_columns,
    rc.delete_rule,
    rc.update_rule
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
    AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
    ON ccu.constraint_name = tc.constraint_name
    AND ccu.table_schema = tc.table_schema
JOIN information_schema.referential_constraints rc
    ON rc.constraint_name = tc.constraint_name
    AND rc.constraint_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
    AND tc.table_schema = %s
    AND tc.table_name = %s
GROUP BY tc.constraint_name, ccu.table_schema, ccu.table_name, 
         rc.delete_rule, rc.update_rule;
"""

# 获取唯一约束
GET_UNIQUE_CONSTRAINTS_SQL = """
SELECT 
    tc.constraint_name,
    array_agg(kcu.column_name ORDER BY kcu.ordinal_position) as columns
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu 
    ON tc.constraint_name = kcu.constraint_name
    AND tc.table_schema = kcu.table_schema
WHERE tc.constraint_type = 'UNIQUE'
    AND tc.table_schema = %s
    AND tc.table_name = %s
GROUP BY tc.constraint_name;
"""

# 获取索引信息（修正版本，处理可能的错误）
GET_INDEXES_SQL = """
SELECT
    i.indexname as index_name,
    am.amname as index_type,
    ix.indisunique as is_unique,
    ix.indisprimary as is_primary,
    pg_get_expr(ix.indpred, ix.indrelid) as condition,
    array_agg(a.attname ORDER BY array_position(ix.indkey::integer[], a.attnum::integer)) as columns
FROM pg_indexes i
JOIN pg_class c ON c.relname = i.tablename AND c.relnamespace = (
    SELECT oid FROM pg_namespace WHERE nspname = i.schemaname
)
JOIN pg_index ix ON ix.indexrelid = (
    SELECT oid FROM pg_class WHERE relname = i.indexname AND relnamespace = (
        SELECT oid FROM pg_namespace WHERE nspname = i.schemaname
    )
)
JOIN pg_class ic ON ic.oid = ix.indexrelid
JOIN pg_am am ON am.oid = ic.relam
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(ix.indkey)
WHERE i.schemaname = %s AND i.tablename = %s
GROUP BY i.indexname, am.amname, ix.indisunique, ix.indisprimary, 
         ix.indpred, ix.indrelid
ORDER BY i.indexname;
"""

# 获取所有 schema
GET_SCHEMAS_SQL = """
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY schema_name;
"""

# 获取指定 schema 下的所有表
GET_TABLES_SQL = """
SELECT tablename
FROM pg_tables
WHERE schemaname = %s
ORDER BY tablename;
"""

# 数据采样 SQL 模板
SAMPLE_DATA_SQL = """
SELECT * FROM {schema}.{table} LIMIT %s;
"""

# 随机采样 SQL 模板（PostgreSQL TABLESAMPLE）
SAMPLE_DATA_RANDOM_SQL = """
SELECT * FROM {schema}.{table} TABLESAMPLE SYSTEM(%s);
"""

# 检查表是否存在
CHECK_TABLE_EXISTS_SQL = """
SELECT EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = %s AND tablename = %s
);
"""

