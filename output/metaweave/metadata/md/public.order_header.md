# public.order_header（订单信息表，存储订单的基本信息和客户信息）
## 字段列表：
- order_id (integer(32)) - 订单唯一标识ID [示例: 5001, 5002]
- order_date (date) - 订单创建日期 [示例: 2024-01-01, 2024-01-02]
- customer (character varying(100)) - 订单客户姓名 [示例: 张三, 李四]
## 字段补充说明：
- 主键约束 order_header_pkey: order_id, order_date