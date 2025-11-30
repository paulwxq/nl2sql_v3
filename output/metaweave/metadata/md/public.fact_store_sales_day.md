# public.fact_store_sales_day（店铺销售日流水事实表（按天、店铺、商品类型汇总））
## 字段列表：
- store_id (integer(32)) - 店铺ID（外键） [示例: 101, 101]
- date_day (date) - 交易日期（日粒度） [示例: 2025-08-01, 2025-08-01]
- product_type_id (integer(32)) - 商品类型ID（外键） [示例: 1, 2]
- amount (numeric(18,2)) - 销售金额（当日） [示例: 206.0, 211.0]
## 字段补充说明：
- amount 使用numeric(18,2)存储，精确到小数点后2位