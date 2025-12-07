-- ====================================
-- Table: public.order_item
-- Comment: 订单商品明细，记录每个订单中的商品及数量信息
-- Generated: 2025-12-06 18:07:56
-- ====================================

CREATE TABLE IF NOT EXISTS public.order_item (
    item_id INTEGER(32) NOT NULL DEFAULT nextval('order_item_item_id_seq'::regclass),
    order_id INTEGER(32) NOT NULL,
    order_date DATE NOT NULL,
    product CHARACTER VARYING(100),
    quantity INTEGER(32) NOT NULL,
    CONSTRAINT order_item_pkey PRIMARY KEY (item_id),
    CONSTRAINT fk_order_item_header FOREIGN KEY (order_date, order_id) REFERENCES public.order_header (order_date, order_id)
);

-- Column Comments
COMMENT ON COLUMN public.order_item.item_id IS '订单商品唯一标识ID';
COMMENT ON COLUMN public.order_item.order_id IS '订单编号';
COMMENT ON COLUMN public.order_item.order_date IS '订单创建日期';
COMMENT ON COLUMN public.order_item.product IS '商品名称';
COMMENT ON COLUMN public.order_item.quantity IS '商品数量';

-- Table Comment
COMMENT ON TABLE public.order_item IS '订单商品明细，记录每个订单中的商品及数量信息';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.order_item",
  "generated_at": "2025-12-06T10:07:56.682540Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "item_id": "1",
        "order_id": "5001",
        "order_date": "2024-01-01",
        "product": "苹果",
        "quantity": "3"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "item_id": "2",
        "order_id": "5001",
        "order_date": "2024-01-01",
        "product": "香蕉",
        "quantity": "2"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "item_id": "3",
        "order_id": "5002",
        "order_date": "2024-01-02",
        "product": "牛奶",
        "quantity": "1"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "item_id": "4",
        "order_id": "5002",
        "order_date": "2024-01-02",
        "product": "面包",
        "quantity": "5"
      }
    },
    {
      "label": "Record 5",
      "data": {
        "item_id": "5",
        "order_id": "5003",
        "order_date": "2024-01-03",
        "product": "鸡蛋",
        "quantity": "12"
      }
    }
  ]
}
*/