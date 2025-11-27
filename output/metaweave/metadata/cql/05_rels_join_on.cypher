// 05_rels_join_on.cypher
// 建立 JOIN_ON 关系（MERGE + SET，确保幂等性）

UNWIND [
  {
    "src_full_name": "public.dim_company",
    "dst_full_name": "public.dim_store",
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
    "src_full_name": "public.dim_product_type",
    "dst_full_name": "public.fact_store_sales_day",
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
    "src_full_name": "public.dim_product_type",
    "dst_full_name": "public.fact_store_sales_month",
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
    "src_full_name": "public.dim_region",
    "dst_full_name": "public.dim_store",
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
    "src_full_name": "public.dim_store",
    "dst_full_name": "public.fact_store_sales_day",
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
    "src_full_name": "public.dim_store",
    "dst_full_name": "public.fact_store_sales_month",
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
