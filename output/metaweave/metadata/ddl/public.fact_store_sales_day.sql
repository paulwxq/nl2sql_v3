-- ====================================
-- Table: public.fact_store_sales_day
-- Comment: 店铺销售日流水事实表（按天、店铺、商品类型汇总）
-- Generated: 2025-12-04 22:17:44
-- ====================================

CREATE TABLE IF NOT EXISTS public.fact_store_sales_day (
    store_id INTEGER(32) NOT NULL,
    date_day DATE NOT NULL,
    product_type_id INTEGER(32) NOT NULL,
    amount NUMERIC(18,2) NOT NULL DEFAULT 0
);

-- Column Comments
COMMENT ON COLUMN public.fact_store_sales_day.store_id IS '店铺ID（外键）';
COMMENT ON COLUMN public.fact_store_sales_day.date_day IS '交易日期（日粒度）';
COMMENT ON COLUMN public.fact_store_sales_day.product_type_id IS '商品类型ID（外键）';
COMMENT ON COLUMN public.fact_store_sales_day.amount IS '销售金额（当日）';

-- Table Comment
COMMENT ON TABLE public.fact_store_sales_day IS '店铺销售日流水事实表（按天、店铺、商品类型汇总）';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.fact_store_sales_day",
  "generated_at": "2025-12-04T14:17:44.505918Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "store_id": "101",
        "date_day": "2025-08-01",
        "product_type_id": "1",
        "amount": "206.0"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "store_id": "101",
        "date_day": "2025-08-01",
        "product_type_id": "2",
        "amount": "211.0"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "store_id": "101",
        "date_day": "2025-08-01",
        "product_type_id": "3",
        "amount": "216.0"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "store_id": "101",
        "date_day": "2025-08-01",
        "product_type_id": "4",
        "amount": "221.0"
      }
    },
    {
      "label": "Record 5",
      "data": {
        "store_id": "101",
        "date_day": "2025-08-15",
        "product_type_id": "1",
        "amount": "226.0"
      }
    }
  ]
}
*/