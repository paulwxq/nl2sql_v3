-- ====================================
-- Table: public.dim_company
-- Comment: 公司维表
-- Generated: 2025-12-04 22:17:44
-- ====================================

CREATE TABLE IF NOT EXISTS public.dim_company (
    company_id INTEGER(32) NOT NULL,
    company_name CHARACTER VARYING(200) NOT NULL
);

-- Column Comments
COMMENT ON COLUMN public.dim_company.company_id IS '公司ID（主键）';
COMMENT ON COLUMN public.dim_company.company_name IS '公司名称，唯一';

-- Table Comment
COMMENT ON TABLE public.dim_company IS '公司维表';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.dim_company",
  "generated_at": "2025-12-04T14:17:44.300233Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "company_id": "1",
        "company_name": "京东便利"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "company_id": "2",
        "company_name": "喜士多"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "company_id": "3",
        "company_name": "全家"
      }
    },
    {
      "label": "Record 4",
      "data": null,
      "note": "placeholder"
    },
    {
      "label": "Record 5",
      "data": null,
      "note": "placeholder"
    }
  ]
}
*/