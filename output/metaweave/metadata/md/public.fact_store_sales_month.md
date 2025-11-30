# public.fact_store_sales_month（店铺销售月汇总事实表（按月、店铺、商品类型汇总））
## 字段列表：
- store_id (integer(32)) - 店铺ID（外键） [示例: 203, 303]
- date_month (date) - 月份（建议为当月第一天） [示例: 2025-09-01, 2025-09-01]
- product_type_id (integer(32)) - 商品类型ID（外键） [示例: 1, 2]
- amount (numeric(18,2)) - 销售金额（当月累计值） [示例: 656.0, 866.0]
## 字段补充说明：
- amount 使用numeric(18,2)存储，精确到小数点后2位