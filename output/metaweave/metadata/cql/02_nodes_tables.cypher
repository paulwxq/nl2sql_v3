// 02_nodes_tables.cypher
// 生成 Table 节点（MERGE + SET，确保幂等性）

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
    "logic_fk": [
      [
        "company_id"
      ]
    ],
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
    "logic_fk": [
      [
        "product_type_id"
      ]
    ],
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
    "logic_fk": [
      [
        "region_id"
      ]
    ],
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
    "logic_fk": [
      [
        "store_id"
      ]
    ],
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
  },
  {
    "full_name": "public.table_name",
    "schema": "public",
    "name": "table_name",
    "comment": "表注释",
    "pk": [
      {
        "constraint_name": "pk_name",
        "columns": [
          "column1"
        ]
      }
    ],
    "uk": [
      {
        "constraint_name": "uk_single_column",
        "columns": [
          "column1"
        ]
      },
      {
        "constraint_name": "uk_composite",
        "columns": [
          "column1",
          "column2",
          "column3"
        ]
      }
    ],
    "fk": [
      {
        "constraint_name": "fk_name",
        "source_columns": [
          "local_column"
        ],
        "target_schema": "public",
        "target_table": "referenced_table",
        "target_columns": [
          "referenced_column"
        ]
      }
    ],
    "logic_pk": [
      [
        "column1"
      ]
    ],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [
      {
        "index_name": "idx_single",
        "columns": [
          "column1"
        ],
        "is_unique": false,
        "index_type": "btree"
      },
      {
        "index_name": "idx_composite",
        "columns": [
          "column1",
          "column2"
        ],
        "is_unique": false,
        "index_type": "btree"
      },
      {
        "index_name": "idx_unique_composite",
        "columns": [
          "column2",
          "column3"
        ],
        "is_unique": true,
        "index_type": "btree"
      }
    ]
  },
  {
    "full_name": "public.table_name",
    "schema": "public",
    "name": "table_name",
    "comment": "",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [],
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
