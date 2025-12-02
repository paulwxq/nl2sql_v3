-- ====================================
-- Table: public.dim_product_type
-- Comment: 商品类型维表
-- Generated: 2025-12-02 18:30:11
-- ====================================

CREATE TABLE IF NOT EXISTS public.dim_product_type (
    product_type_id INTEGER(32) NOT NULL,
    product_type_name CHARACTER VARYING(100) NOT NULL
);

-- Column Comments
COMMENT ON COLUMN public.dim_product_type.product_type_id IS '商品类型ID（主键）';
COMMENT ON COLUMN public.dim_product_type.product_type_name IS '商品类型名称，唯一';

-- Table Comment
COMMENT ON TABLE public.dim_product_type IS '商品类型维表';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.dim_product_type",
  "generated_at": "2025-12-02T10:30:11.329797Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "product_type_id": "1",
        "product_type_name": "饮料"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "product_type_id": "2",
        "product_type_name": "零食"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "product_type_id": "3",
        "product_type_name": "烟草"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "product_type_id": "4",
        "product_type_name": "水果"
      }
    },
    {
      "label": "Record 5",
      "data": null,
      "note": "placeholder"
    }
  ]
}
*/