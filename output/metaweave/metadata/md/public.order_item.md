# public.order_item（订单商品明细，记录每个订单中的商品及数量信息）
## 字段列表：
- item_id (integer(32)) - 订单商品唯一标识ID [示例: 1, 2]
- order_id (integer(32)) - 订单编号 [示例: 5001, 5001]
- order_date (date) - 订单创建日期 [示例: 2024-01-01, 2024-01-01]
- product (character varying(100)) - 商品名称 [示例: 苹果, 香蕉]
- quantity (integer(32)) - 商品数量 [示例: 3, 2]
## 字段补充说明：
- 主键约束 order_item_pkey: item_id
- order_date, order_id 关联 public.order_header.order_date, order_id