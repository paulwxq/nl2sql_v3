-- ====================================
-- Table: public.fact_store_sales_month
-- Comment: 店铺销售月汇总事实表（按月、店铺、商品类型汇总）
-- Generated: 2025-11-28 12:41:11
-- ====================================

CREATE TABLE IF NOT EXISTS public.fact_store_sales_month (
    store_id INTEGER(32) NOT NULL,
    date_month DATE NOT NULL,
    product_type_id INTEGER(32) NOT NULL,
    amount NUMERIC(18,2) NOT NULL DEFAULT 0
);

-- Column Comments
COMMENT ON COLUMN public.fact_store_sales_month.store_id IS '店铺ID（外键）';
COMMENT ON COLUMN public.fact_store_sales_month.date_month IS '月份（建议为当月第一天）';
COMMENT ON COLUMN public.fact_store_sales_month.product_type_id IS '商品类型ID（外键）';
COMMENT ON COLUMN public.fact_store_sales_month.amount IS '销售金额（当月累计值）';

-- Table Comment
COMMENT ON TABLE public.fact_store_sales_month IS '店铺销售月汇总事实表（按月、店铺、商品类型汇总）';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.fact_store_sales_month",
  "generated_at": "2025-11-28T04:41:11.289312Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "store_id": "203",
        "date_month": "2025-09-01",
        "product_type_id": "1",
        "amount": "656.0"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "store_id": "303",
        "date_month": "2025-09-01",
        "product_type_id": "2",
        "amount": "866.0"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "store_id": "102",
        "date_month": "2025-08-01",
        "product_type_id": "4",
        "amount": "464.0"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "store_id": "102",
        "date_month": "2025-08-01",
        "product_type_id": "3",
        "amount": "454.0"
      }
    },
    {
      "label": "Record 5",
      "data": {
        "store_id": "302",
        "date_month": "2025-09-01",
        "product_type_id": "1",
        "amount": "854.0"
      }
    }
  ]
}
*/