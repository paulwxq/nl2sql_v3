# public.dim_store（店铺维表）
## 字段列表：
- store_id (integer(32)) - 店铺ID（主键） [示例: 101]
- store_name (character varying(200)) - 店铺名称（同一公司下唯一） [示例: 京东便利天河岗顶店]
- company_id (integer(32)) - 所属公司ID（外键） [示例: 1]
- region_id (integer(32)) - 所属区（县）ID（外键） [示例: 440106]