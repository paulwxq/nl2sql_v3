// 04_rels_has_column.cypher
// 建立 HAS_COLUMN 关系（MERGE，确保幂等性）

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
