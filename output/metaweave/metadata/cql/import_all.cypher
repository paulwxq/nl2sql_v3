// import_all.cypher
// Neo4j 元数据导入脚本（global 模式，包含所有表和关系）
// 生成时间: 2025-11-30T17:12:16.363542
// 统计: 6 张表, 22 个列, 6 个关系

// =====================================================================
// 1. 创建唯一约束
// =====================================================================

CREATE CONSTRAINT table_id IF NOT EXISTS FOR (t:Table) REQUIRE t.id IS UNIQUE;
CREATE CONSTRAINT table_full_name IF NOT EXISTS FOR (t:Table) REQUIRE t.full_name IS UNIQUE;
CREATE CONSTRAINT column_full_name IF NOT EXISTS FOR (c:Column) REQUIRE c.full_name IS UNIQUE;

// =====================================================================
// 2. 创建 Table 节点
// =====================================================================

UNWIND [
  {
    "full_name": "public.dim_company",
    "schema": "public",
    "name": "dim_company",
    "comment": "公司维表",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [
      [
        "company_id"
      ]
    ],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": []
  },
  {
    "full_name": "public.dim_product_type",
    "schema": "public",
    "name": "dim_product_type",
    "comment": "商品类型维表",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [
      [
        "product_type_id"
      ]
    ],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": []
  },
  {
    "full_name": "public.dim_region",
    "schema": "public",
    "name": "dim_region",
    "comment": "地区维表：省/市/区（含各级名称与ID）",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [
      [
        "region_id"
      ]
    ],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": []
  },
  {
    "full_name": "public.dim_store",
    "schema": "public",
    "name": "dim_store",
    "comment": "店铺维表",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [
      [
        "store_id"
      ]
    ],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": []
  },
  {
    "full_name": "public.fact_store_sales_day",
    "schema": "public",
    "name": "fact_store_sales_day",
    "comment": "店铺销售日流水事实表（按天、店铺、商品类型汇总）",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [
      [
        "store_id",
        "date_day",
        "product_type_id"
      ]
    ],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": []
  },
  {
    "full_name": "public.fact_store_sales_month",
    "schema": "public",
    "name": "fact_store_sales_month",
    "comment": "店铺销售月汇总事实表（按月、店铺、商品类型汇总）",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [
      [
        "store_id",
        "date_month",
        "product_type_id"
      ]
    ],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": []
  }
] AS t
MERGE (n:Table {full_name: t.full_name})
SET n.id       = t.full_name,
    n.schema   = t.schema,
    n.name     = t.name,
    n.comment  = t.comment,
    n.pk       = t.pk,
    n.uk       = t.uk,
    n.fk       = t.fk,
    n.logic_pk = t.logic_pk,
    n.logic_fk = t.logic_fk,
    n.logic_uk = t.logic_uk,
    n.indexes  = t.indexes;

// =====================================================================
// 3. 创建 Column 节点
// =====================================================================

UNWIND [
  {
    "full_name": "public.dim_company.company_id",
    "schema": "public",
    "table": "dim_company",
    "name": "company_id",
    "comment": "公司ID（主键）",
    "data_type": "integer",
    "semantic_role": "identifier",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_company.company_name",
    "schema": "public",
    "table": "dim_company",
    "name": "company_name",
    "comment": "公司名称，唯一",
    "data_type": "character varying",
    "semantic_role": "attribute",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_product_type.product_type_id",
    "schema": "public",
    "table": "dim_product_type",
    "name": "product_type_id",
    "comment": "商品类型ID（主键）",
    "data_type": "integer",
    "semantic_role": "identifier",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_product_type.product_type_name",
    "schema": "public",
    "table": "dim_product_type",
    "name": "product_type_name",
    "comment": "商品类型名称，唯一",
    "data_type": "character varying",
    "semantic_role": "attribute",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_region.region_id",
    "schema": "public",
    "table": "dim_region",
    "name": "region_id",
    "comment": "区（县）ID（主键）",
    "data_type": "integer",
    "semantic_role": "identifier",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_region.region_name",
    "schema": "public",
    "table": "dim_region",
    "name": "region_name",
    "comment": "区（县）名称",
    "data_type": "character varying",
    "semantic_role": "attribute",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_region.city_id",
    "schema": "public",
    "table": "dim_region",
    "name": "city_id",
    "comment": "城市ID",
    "data_type": "integer",
    "semantic_role": "identifier",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.5,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_region.city_name",
    "schema": "public",
    "table": "dim_region",
    "name": "city_name",
    "comment": "城市名称",
    "data_type": "character varying",
    "semantic_role": "attribute",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.5,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_region.province_id",
    "schema": "public",
    "table": "dim_region",
    "name": "province_id",
    "comment": "省份ID",
    "data_type": "integer",
    "semantic_role": "identifier",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.25,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_region.province_name",
    "schema": "public",
    "table": "dim_region",
    "name": "province_name",
    "comment": "省份名称",
    "data_type": "character varying",
    "semantic_role": "attribute",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.25,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_store.store_id",
    "schema": "public",
    "table": "dim_store",
    "name": "store_id",
    "comment": "店铺ID（主键）",
    "data_type": "integer",
    "semantic_role": "identifier",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_store.store_name",
    "schema": "public",
    "table": "dim_store",
    "name": "store_name",
    "comment": "店铺名称（同一公司下唯一）",
    "data_type": "character varying",
    "semantic_role": "attribute",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_store.company_id",
    "schema": "public",
    "table": "dim_store",
    "name": "company_id",
    "comment": "所属公司ID（外键）",
    "data_type": "integer",
    "semantic_role": "identifier",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.3333,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_store.region_id",
    "schema": "public",
    "table": "dim_store",
    "name": "region_id",
    "comment": "所属区（县）ID（外键）",
    "data_type": "integer",
    "semantic_role": "identifier",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.8889,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_day.store_id",
    "schema": "public",
    "table": "fact_store_sales_day",
    "name": "store_id",
    "comment": "店铺ID（外键）",
    "data_type": "integer",
    "semantic_role": "identifier",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.0625,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_day.date_day",
    "schema": "public",
    "table": "fact_store_sales_day",
    "name": "date_day",
    "comment": "交易日期（日粒度）",
    "data_type": "date",
    "semantic_role": "datetime",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": true,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.0278,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_day.product_type_id",
    "schema": "public",
    "table": "fact_store_sales_day",
    "name": "product_type_id",
    "comment": "商品类型ID（外键）",
    "data_type": "integer",
    "semantic_role": "identifier",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.0278,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_day.amount",
    "schema": "public",
    "table": "fact_store_sales_day",
    "name": "amount",
    "comment": "销售金额（当日）",
    "data_type": "numeric",
    "semantic_role": "metric",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": true,
    "pk_position": 0,
    "uniqueness": 0.625,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_month.store_id",
    "schema": "public",
    "table": "fact_store_sales_month",
    "name": "store_id",
    "comment": "店铺ID（外键）",
    "data_type": "integer",
    "semantic_role": "identifier",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.125,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_month.date_month",
    "schema": "public",
    "table": "fact_store_sales_month",
    "name": "date_month",
    "comment": "月份（建议为当月第一天）",
    "data_type": "date",
    "semantic_role": "datetime",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": true,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.0278,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_month.product_type_id",
    "schema": "public",
    "table": "fact_store_sales_month",
    "name": "product_type_id",
    "comment": "商品类型ID（外键）",
    "data_type": "integer",
    "semantic_role": "identifier",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.0556,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_month.amount",
    "schema": "public",
    "table": "fact_store_sales_month",
    "name": "amount",
    "comment": "销售金额（当月累计值）",
    "data_type": "numeric",
    "semantic_role": "metric",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": true,
    "pk_position": 0,
    "uniqueness": 0.75,
    "null_rate": 0.0
  }
] AS c
MERGE (n:Column {full_name: c.full_name})
SET n.schema       = c.schema,
    n.table        = c.table,
    n.name         = c.name,
    n.comment      = c.comment,
    n.data_type    = c.data_type,
    n.semantic_role= c.semantic_role,
    n.is_pk        = c.is_pk,
    n.is_uk        = c.is_uk,
    n.is_fk        = c.is_fk,
    n.is_time      = c.is_time,
    n.is_measure   = c.is_measure,
    n.pk_position  = c.pk_position,
    n.uniqueness   = c.uniqueness,
    n.null_rate    = c.null_rate;

// =====================================================================
// 4. 建立 HAS_COLUMN 关系
// =====================================================================

UNWIND [
  {
    "table_full_name": "public.dim_company",
    "column_full_name": "public.dim_company.company_id"
  },
  {
    "table_full_name": "public.dim_company",
    "column_full_name": "public.dim_company.company_name"
  },
  {
    "table_full_name": "public.dim_product_type",
    "column_full_name": "public.dim_product_type.product_type_id"
  },
  {
    "table_full_name": "public.dim_product_type",
    "column_full_name": "public.dim_product_type.product_type_name"
  },
  {
    "table_full_name": "public.dim_region",
    "column_full_name": "public.dim_region.region_id"
  },
  {
    "table_full_name": "public.dim_region",
    "column_full_name": "public.dim_region.region_name"
  },
  {
    "table_full_name": "public.dim_region",
    "column_full_name": "public.dim_region.city_id"
  },
  {
    "table_full_name": "public.dim_region",
    "column_full_name": "public.dim_region.city_name"
  },
  {
    "table_full_name": "public.dim_region",
    "column_full_name": "public.dim_region.province_id"
  },
  {
    "table_full_name": "public.dim_region",
    "column_full_name": "public.dim_region.province_name"
  },
  {
    "table_full_name": "public.dim_store",
    "column_full_name": "public.dim_store.store_id"
  },
  {
    "table_full_name": "public.dim_store",
    "column_full_name": "public.dim_store.store_name"
  },
  {
    "table_full_name": "public.dim_store",
    "column_full_name": "public.dim_store.company_id"
  },
  {
    "table_full_name": "public.dim_store",
    "column_full_name": "public.dim_store.region_id"
  },
  {
    "table_full_name": "public.fact_store_sales_day",
    "column_full_name": "public.fact_store_sales_day.store_id"
  },
  {
    "table_full_name": "public.fact_store_sales_day",
    "column_full_name": "public.fact_store_sales_day.date_day"
  },
  {
    "table_full_name": "public.fact_store_sales_day",
    "column_full_name": "public.fact_store_sales_day.product_type_id"
  },
  {
    "table_full_name": "public.fact_store_sales_day",
    "column_full_name": "public.fact_store_sales_day.amount"
  },
  {
    "table_full_name": "public.fact_store_sales_month",
    "column_full_name": "public.fact_store_sales_month.store_id"
  },
  {
    "table_full_name": "public.fact_store_sales_month",
    "column_full_name": "public.fact_store_sales_month.date_month"
  },
  {
    "table_full_name": "public.fact_store_sales_month",
    "column_full_name": "public.fact_store_sales_month.product_type_id"
  },
  {
    "table_full_name": "public.fact_store_sales_month",
    "column_full_name": "public.fact_store_sales_month.amount"
  }
] AS hc
MATCH (t:Table {full_name: hc.table_full_name})
MATCH (c:Column {full_name: hc.column_full_name})
MERGE (t)-[:HAS_COLUMN]->(c);

// =====================================================================
// 5. 建立 JOIN_ON 关系
// =====================================================================

UNWIND [
  {
    "src_full_name": "public.dim_store",
    "dst_full_name": "public.dim_company",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.company_id = DST.company_id",
    "source_columns": [
      "company_id"
    ],
    "target_columns": [
      "company_id"
    ]
  },
  {
    "src_full_name": "public.fact_store_sales_day",
    "dst_full_name": "public.dim_product_type",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.product_type_id = DST.product_type_id",
    "source_columns": [
      "product_type_id"
    ],
    "target_columns": [
      "product_type_id"
    ]
  },
  {
    "src_full_name": "public.fact_store_sales_month",
    "dst_full_name": "public.dim_product_type",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.product_type_id = DST.product_type_id",
    "source_columns": [
      "product_type_id"
    ],
    "target_columns": [
      "product_type_id"
    ]
  },
  {
    "src_full_name": "public.dim_store",
    "dst_full_name": "public.dim_region",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.region_id = DST.region_id",
    "source_columns": [
      "region_id"
    ],
    "target_columns": [
      "region_id"
    ]
  },
  {
    "src_full_name": "public.fact_store_sales_day",
    "dst_full_name": "public.dim_store",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.store_id = DST.store_id",
    "source_columns": [
      "store_id"
    ],
    "target_columns": [
      "store_id"
    ]
  },
  {
    "src_full_name": "public.fact_store_sales_month",
    "dst_full_name": "public.dim_store",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.store_id = DST.store_id",
    "source_columns": [
      "store_id"
    ],
    "target_columns": [
      "store_id"
    ]
  }
] AS j
MATCH (src:Table {full_name: j.src_full_name})
MATCH (dst:Table {full_name: j.dst_full_name})
MERGE (src)-[r:JOIN_ON]->(dst)
SET r.cardinality     = j.cardinality,
    r.constraint_name = j.constraint_name,
    r.join_type       = coalesce(j.join_type, 'INNER JOIN'),
    r.on              = j.on,
    r.source_columns  = j.source_columns,
    r.target_columns  = j.target_columns;
