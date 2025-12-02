-- ====================================
-- Table: public.dim_store
-- Comment: 店铺维表
-- Generated: 2025-12-02 18:30:11
-- ====================================

CREATE TABLE IF NOT EXISTS public.dim_store (
    store_id INTEGER(32) NOT NULL,
    store_name CHARACTER VARYING(200) NOT NULL,
    company_id INTEGER(32) NOT NULL,
    region_id INTEGER(32) NOT NULL
);

-- Column Comments
COMMENT ON COLUMN public.dim_store.store_id IS '店铺ID（主键）';
COMMENT ON COLUMN public.dim_store.store_name IS '店铺名称（同一公司下唯一）';
COMMENT ON COLUMN public.dim_store.company_id IS '所属公司ID（外键）';
COMMENT ON COLUMN public.dim_store.region_id IS '所属区（县）ID（外键）';

-- Table Comment
COMMENT ON TABLE public.dim_store IS '店铺维表';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.dim_store",
  "generated_at": "2025-12-02T10:30:11.316331Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "store_id": "101",
        "store_name": "京东便利天河岗顶店",
        "company_id": "1",
        "region_id": "440106"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "store_id": "103",
        "store_name": "京东便利南京新街口店",
        "company_id": "1",
        "region_id": "320106"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "store_id": "102",
        "store_name": "京东便利深圳南山科技园店",
        "company_id": "1",
        "region_id": "440305"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "store_id": "201",
        "store_name": "喜士多广州越秀店",
        "company_id": "2",
        "region_id": "440104"
      }
    },
    {
      "label": "Record 5",
      "data": {
        "store_id": "202",
        "store_name": "喜士多深圳福田会展店",
        "company_id": "2",
        "region_id": "440304"
      }
    }
  ]
}
*/