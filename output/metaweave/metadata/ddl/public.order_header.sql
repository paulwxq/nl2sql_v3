-- ====================================
-- Table: public.order_header
-- Comment: 订单信息表，存储订单的基本信息和客户信息
-- Generated: 2025-12-07 19:11:44
-- ====================================

CREATE TABLE IF NOT EXISTS public.order_header (
    order_id INTEGER(32) NOT NULL,
    order_date DATE NOT NULL,
    customer CHARACTER VARYING(100),
    CONSTRAINT order_header_pkey PRIMARY KEY (order_id, order_date)
);

-- Column Comments
COMMENT ON COLUMN public.order_header.order_id IS '订单唯一标识ID';
COMMENT ON COLUMN public.order_header.order_date IS '订单创建日期';
COMMENT ON COLUMN public.order_header.customer IS '订单客户姓名';

-- Table Comment
COMMENT ON TABLE public.order_header IS '订单信息表，存储订单的基本信息和客户信息';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.order_header",
  "generated_at": "2025-12-07T11:11:44.812776Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "order_id": "5001",
        "order_date": "2024-01-01",
        "customer": "张三"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "order_id": "5002",
        "order_date": "2024-01-02",
        "customer": "李四"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "order_id": "5003",
        "order_date": "2024-01-03",
        "customer": "王五"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "order_id": "5004",
        "order_date": "2024-01-04",
        "customer": "赵六"
      }
    },
    {
      "label": "Record 5",
      "data": {
        "order_id": "5005",
        "order_date": "2024-01-05",
        "customer": "陈七"
      }
    }
  ]
}
*/