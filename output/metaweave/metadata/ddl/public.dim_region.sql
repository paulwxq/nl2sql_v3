-- ====================================
-- Table: public.dim_region
-- Comment: 地区维表：省/市/区（含各级名称与ID）
-- Generated: 2025-12-04 22:17:44
-- ====================================

CREATE TABLE IF NOT EXISTS public.dim_region (
    region_id INTEGER(32) NOT NULL,
    region_name CHARACTER VARYING(100) NOT NULL,
    city_id INTEGER(32) NOT NULL,
    city_name CHARACTER VARYING(100) NOT NULL,
    province_id INTEGER(32) NOT NULL,
    province_name CHARACTER VARYING(100) NOT NULL
);

-- Column Comments
COMMENT ON COLUMN public.dim_region.region_id IS '区（县）ID（主键）';
COMMENT ON COLUMN public.dim_region.region_name IS '区（县）名称';
COMMENT ON COLUMN public.dim_region.city_id IS '城市ID';
COMMENT ON COLUMN public.dim_region.city_name IS '城市名称';
COMMENT ON COLUMN public.dim_region.province_id IS '省份ID';
COMMENT ON COLUMN public.dim_region.province_name IS '省份名称';

-- Table Comment
COMMENT ON TABLE public.dim_region IS '地区维表：省/市/区（含各级名称与ID）';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.dim_region",
  "generated_at": "2025-12-04T14:17:44.342076Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "region_id": "440106",
        "region_name": "天河区",
        "city_id": "4401",
        "city_name": "广州市",
        "province_id": "44",
        "province_name": "广东省"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "region_id": "440104",
        "region_name": "越秀区",
        "city_id": "4401",
        "city_name": "广州市",
        "province_id": "44",
        "province_name": "广东省"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "region_id": "440305",
        "region_name": "南山区",
        "city_id": "4403",
        "city_name": "深圳市",
        "province_id": "44",
        "province_name": "广东省"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "region_id": "440304",
        "region_name": "福田区",
        "city_id": "4403",
        "city_name": "深圳市",
        "province_id": "44",
        "province_name": "广东省"
      }
    },
    {
      "label": "Record 5",
      "data": {
        "region_id": "320106",
        "region_name": "鼓楼区",
        "city_id": "3201",
        "city_name": "南京市",
        "province_id": "32",
        "province_name": "江苏省"
      }
    }
  ]
}
*/