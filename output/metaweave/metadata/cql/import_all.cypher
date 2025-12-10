// import_all.cypher
// Neo4j 元数据导入脚本（global 模式，包含所有表和关系）
// 生成时间: 2025-12-09T22:58:16.259512
// 统计: 13 张表, 60 个列, 11 个关系

// =====================================================================
// 1. 创建唯一约束
// =====================================================================

CREATE CONSTRAINT table_id IF NOT EXISTS FOR (t:Table) REQUIRE t.id IS UNIQUE;
CREATE CONSTRAINT table_full_name IF NOT EXISTS FOR (t:Table) REQUIRE t.full_name IS UNIQUE;
CREATE CONSTRAINT column_full_name IF NOT EXISTS FOR (c:Column) REQUIRE c.full_name IS UNIQUE;

// =====================================================================
// 2. 创建 Table 节点
// =====================================================================

UNWIND [
  {
    "full_name": "public.department",
    "schema": "public",
    "name": "department",
    "comment": "部门信息维度表，用于描述组织架构中的各个部门及其基本信息。",
    "pk": [
      "dept_id"
    ],
    "uk": [
      [
        "dept_code"
      ]
    ],
    "fk": [],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [
      [
        "dept_code"
      ]
    ],
    "table_domains": [],
    "table_category": "dim"
  },
  {
    "full_name": "public.dim_company",
    "schema": "public",
    "name": "dim_company",
    "comment": "公司维表",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [],
    "table_domains": [],
    "table_category": "dim"
  },
  {
    "full_name": "public.dim_product_type",
    "schema": "public",
    "name": "dim_product_type",
    "comment": "商品类型维表",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [],
    "table_domains": [],
    "table_category": "dim"
  },
  {
    "full_name": "public.dim_region",
    "schema": "public",
    "name": "dim_region",
    "comment": "地区维表：省/市/区（含各级名称与ID）",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [],
    "table_domains": [],
    "table_category": "dim"
  },
  {
    "full_name": "public.dim_store",
    "schema": "public",
    "name": "dim_store",
    "comment": "店铺维表",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [],
    "table_domains": [],
    "table_category": "dim"
  },
  {
    "full_name": "public.employee",
    "schema": "public",
    "name": "employee",
    "comment": "员工信息维度表，记录企业员工的基本信息和所属部门",
    "pk": [
      "emp_id"
    ],
    "uk": [
      [
        "emp_no"
      ]
    ],
    "fk": [
      [
        "dept_id"
      ]
    ],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [
      [
        "emp_no"
      ]
    ],
    "table_domains": [],
    "table_category": "dim"
  },
  {
    "full_name": "public.equipment_config",
    "schema": "public",
    "name": "equipment_config",
    "comment": "设备配置维度表：描述设备在某个配置版本下的关键配置属性，用于按“设备ID + 配置版本”关联到工单事实。",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [],
    "table_domains": [],
    "table_category": "dim"
  },
  {
    "full_name": "public.fact_store_sales_day",
    "schema": "public",
    "name": "fact_store_sales_day",
    "comment": "店铺销售日流水事实表（按天、店铺、商品类型汇总）",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [],
    "table_domains": [],
    "table_category": "fact"
  },
  {
    "full_name": "public.fact_store_sales_month",
    "schema": "public",
    "name": "fact_store_sales_month",
    "comment": "店铺销售月汇总事实表（按月、店铺、商品类型汇总）",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [],
    "table_domains": [],
    "table_category": "fact"
  },
  {
    "full_name": "public.fault_catalog",
    "schema": "public",
    "name": "fault_catalog",
    "comment": "故障码字典维度表：按“产线/产品线 + 子系统 + 故障码”定义故障含义与处理建议，避免同码异义。",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [],
    "table_domains": [],
    "table_category": "dim"
  },
  {
    "full_name": "public.maintenance_work_order",
    "schema": "public",
    "name": "maintenance_work_order",
    "comment": "维修工单事实表：粒度为“工单-行/条目”，记录设备故障发生时间、故障码上下文、以及停机与成本等关键指标。",
    "pk": [],
    "uk": [],
    "fk": [],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [],
    "table_domains": [],
    "table_category": "fact"
  },
  {
    "full_name": "public.order_header",
    "schema": "public",
    "name": "order_header",
    "comment": "记录订单的头部信息，包含订单编号、下单日期及客户名称等关键业务信息。",
    "pk": [
      "order_id",
      "order_date"
    ],
    "uk": [],
    "fk": [],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [],
    "table_domains": [],
    "table_category": "fact"
  },
  {
    "full_name": "public.order_item",
    "schema": "public",
    "name": "order_item",
    "comment": "记录订单明细的事务性事实表，包含每个订单项的产品和数量信息",
    "pk": [
      "item_id"
    ],
    "uk": [],
    "fk": [
      [
        "order_date",
        "order_id"
      ]
    ],
    "logic_pk": [],
    "logic_fk": [],
    "logic_uk": [],
    "indexes": [],
    "table_domains": [],
    "table_category": "fact"
  }
] AS t
MERGE (n:Table {full_name: t.full_name})
SET n.id       = t.full_name,
    n.schema   = t.schema,
    n.name     = t.name,
    n.comment  = t.comment,
    n.pk       = t.pk,
    n.uk       = t.uk,
    n.fk       = t.fk,
    n.logic_pk = t.logic_pk,
    n.logic_fk = t.logic_fk,
    n.logic_uk = t.logic_uk,
    n.indexes  = t.indexes,
    n.table_domains = CASE
        WHEN t.table_domains IS NOT NULL AND size(t.table_domains) > 0
            THEN t.table_domains
        ELSE coalesce(n.table_domains, [])
    END,
    n.table_category = CASE
        WHEN t.table_category IS NOT NULL
            THEN t.table_category
        ELSE n.table_category
    END;

// =====================================================================
// 3. 创建 Column 节点
// =====================================================================

UNWIND [
  {
    "full_name": "public.department.dept_id",
    "schema": "public",
    "table": "department",
    "name": "dept_id",
    "comment": "部门唯一标识ID，主键，用于唯一区分每个部门",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": true,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 1,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.department.dept_code",
    "schema": "public",
    "table": "department",
    "name": "dept_code",
    "comment": "部门编码，唯一标识部门的简写代码，用于系统内引用",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": true,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.department.dept_name",
    "schema": "public",
    "table": "department",
    "name": "dept_name",
    "comment": "部门名称，中文全称，表示部门的业务职能或组织名称",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.department.location",
    "schema": "public",
    "table": "department",
    "name": "location",
    "comment": "所在城市，表示该部门主要办公地点",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.55,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_company.company_id",
    "schema": "public",
    "table": "dim_company",
    "name": "company_id",
    "comment": "公司ID（主键）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_company.company_name",
    "schema": "public",
    "table": "dim_company",
    "name": "company_name",
    "comment": "公司名称，唯一",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_product_type.product_type_id",
    "schema": "public",
    "table": "dim_product_type",
    "name": "product_type_id",
    "comment": "商品类型ID（主键）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_product_type.product_type_name",
    "schema": "public",
    "table": "dim_product_type",
    "name": "product_type_name",
    "comment": "商品类型名称，唯一",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_region.region_id",
    "schema": "public",
    "table": "dim_region",
    "name": "region_id",
    "comment": "区（县）ID（主键）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_region.region_name",
    "schema": "public",
    "table": "dim_region",
    "name": "region_name",
    "comment": "区（县）名称",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_region.city_id",
    "schema": "public",
    "table": "dim_region",
    "name": "city_id",
    "comment": "城市ID",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.5,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_region.city_name",
    "schema": "public",
    "table": "dim_region",
    "name": "city_name",
    "comment": "城市名称",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.5,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_region.province_id",
    "schema": "public",
    "table": "dim_region",
    "name": "province_id",
    "comment": "省份ID",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.25,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_region.province_name",
    "schema": "public",
    "table": "dim_region",
    "name": "province_name",
    "comment": "省份名称",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.25,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_store.store_id",
    "schema": "public",
    "table": "dim_store",
    "name": "store_id",
    "comment": "店铺ID（主键）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_store.store_name",
    "schema": "public",
    "table": "dim_store",
    "name": "store_name",
    "comment": "店铺名称（同一公司下唯一）",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_store.company_id",
    "schema": "public",
    "table": "dim_store",
    "name": "company_id",
    "comment": "所属公司ID（外键）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.3333,
    "null_rate": 0.0
  },
  {
    "full_name": "public.dim_store.region_id",
    "schema": "public",
    "table": "dim_store",
    "name": "region_id",
    "comment": "所属区（县）ID（外键）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.8889,
    "null_rate": 0.0
  },
  {
    "full_name": "public.employee.emp_id",
    "schema": "public",
    "table": "employee",
    "name": "emp_id",
    "comment": "员工唯一标识ID，主键",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": true,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 1,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.employee.emp_no",
    "schema": "public",
    "table": "employee",
    "name": "emp_no",
    "comment": "员工工号，系统内唯一编码",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": true,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.employee.emp_name",
    "schema": "public",
    "table": "employee",
    "name": "emp_name",
    "comment": "员工姓名",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.employee.gender",
    "schema": "public",
    "table": "employee",
    "name": "gender",
    "comment": "性别，M表示男性，F表示女性",
    "data_type": "character",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.1,
    "null_rate": 0.0
  },
  {
    "full_name": "public.employee.hire_date",
    "schema": "public",
    "table": "employee",
    "name": "hire_date",
    "comment": "入职日期",
    "data_type": "date",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.employee.salary",
    "schema": "public",
    "table": "employee",
    "name": "salary",
    "comment": "月薪金额，单位为人民币元",
    "data_type": "numeric",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.employee.dept_id",
    "schema": "public",
    "table": "employee",
    "name": "dept_id",
    "comment": "所属部门ID，外键关联部门表",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": true,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.95,
    "null_rate": 0.0
  },
  {
    "full_name": "public.equipment_config.equipment_id",
    "schema": "public",
    "table": "equipment_config",
    "name": "equipment_id",
    "comment": "设备ID（资产编号）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.5,
    "null_rate": 0.0
  },
  {
    "full_name": "public.equipment_config.config_version",
    "schema": "public",
    "table": "equipment_config",
    "name": "config_version",
    "comment": "配置版本/改造批次（可为语义化版本或批次号）",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.1,
    "null_rate": 0.0
  },
  {
    "full_name": "public.equipment_config.controller_model",
    "schema": "public",
    "table": "equipment_config",
    "name": "controller_model",
    "comment": "控制器型号",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.5,
    "null_rate": 0.0
  },
  {
    "full_name": "public.equipment_config.firmware_version",
    "schema": "public",
    "table": "equipment_config",
    "name": "firmware_version",
    "comment": "固件版本号（语义化版本等）",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.95,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_day.store_id",
    "schema": "public",
    "table": "fact_store_sales_day",
    "name": "store_id",
    "comment": "店铺ID（外键）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.0625,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_day.date_day",
    "schema": "public",
    "table": "fact_store_sales_day",
    "name": "date_day",
    "comment": "交易日期（日粒度）",
    "data_type": "date",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.0278,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_day.product_type_id",
    "schema": "public",
    "table": "fact_store_sales_day",
    "name": "product_type_id",
    "comment": "商品类型ID（外键）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.0278,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_day.amount",
    "schema": "public",
    "table": "fact_store_sales_day",
    "name": "amount",
    "comment": "销售金额（当日）",
    "data_type": "numeric",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.625,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_month.store_id",
    "schema": "public",
    "table": "fact_store_sales_month",
    "name": "store_id",
    "comment": "店铺ID（外键）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.125,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_month.date_month",
    "schema": "public",
    "table": "fact_store_sales_month",
    "name": "date_month",
    "comment": "月份（建议为当月第一天）",
    "data_type": "date",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.0278,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_month.product_type_id",
    "schema": "public",
    "table": "fact_store_sales_month",
    "name": "product_type_id",
    "comment": "商品类型ID（外键）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.0556,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fact_store_sales_month.amount",
    "schema": "public",
    "table": "fact_store_sales_month",
    "name": "amount",
    "comment": "销售金额（当月累计值）",
    "data_type": "numeric",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.75,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fault_catalog.product_line_code",
    "schema": "public",
    "table": "fault_catalog",
    "name": "product_line_code",
    "comment": "产线/产品线编码",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.125,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fault_catalog.subsystem_code",
    "schema": "public",
    "table": "fault_catalog",
    "name": "subsystem_code",
    "comment": "子系统编码",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.1667,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fault_catalog.fault_code",
    "schema": "public",
    "table": "fault_catalog",
    "name": "fault_code",
    "comment": "故障码",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.1667,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fault_catalog.fault_name",
    "schema": "public",
    "table": "fault_catalog",
    "name": "fault_name",
    "comment": "故障名称（标准名）",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.3333,
    "null_rate": 0.0
  },
  {
    "full_name": "public.fault_catalog.recommended_action",
    "schema": "public",
    "table": "fault_catalog",
    "name": "recommended_action",
    "comment": "建议处理措施/排查步骤（长文本）",
    "data_type": "text",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.maintenance_work_order.wo_id",
    "schema": "public",
    "table": "maintenance_work_order",
    "name": "wo_id",
    "comment": "工单ID",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.5,
    "null_rate": 0.0
  },
  {
    "full_name": "public.maintenance_work_order.wo_line_no",
    "schema": "public",
    "table": "maintenance_work_order",
    "name": "wo_line_no",
    "comment": "工单行号/条目序号",
    "data_type": "smallint",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.01,
    "null_rate": 0.0
  },
  {
    "full_name": "public.maintenance_work_order.fault_ts",
    "schema": "public",
    "table": "maintenance_work_order",
    "name": "fault_ts",
    "comment": "故障发生时间",
    "data_type": "timestamp without time zone",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.maintenance_work_order.equipment_id",
    "schema": "public",
    "table": "maintenance_work_order",
    "name": "equipment_id",
    "comment": "设备ID（资产编号）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.05,
    "null_rate": 0.0
  },
  {
    "full_name": "public.maintenance_work_order.config_version",
    "schema": "public",
    "table": "maintenance_work_order",
    "name": "config_version",
    "comment": "设备配置版本/改造批次（与设备配置表形成2列关联）",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.01,
    "null_rate": 0.0
  },
  {
    "full_name": "public.maintenance_work_order.product_line_code",
    "schema": "public",
    "table": "maintenance_work_order",
    "name": "product_line_code",
    "comment": "产线/产品线编码（与故障码字典形成3列关联之一）",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.015,
    "null_rate": 0.0
  },
  {
    "full_name": "public.maintenance_work_order.subsystem_code",
    "schema": "public",
    "table": "maintenance_work_order",
    "name": "subsystem_code",
    "comment": "子系统编码（与故障码字典形成3列关联之一）",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.015,
    "null_rate": 0.0
  },
  {
    "full_name": "public.maintenance_work_order.fault_code",
    "schema": "public",
    "table": "maintenance_work_order",
    "name": "fault_code",
    "comment": "故障码（与故障码字典形成3列关联之一）",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.02,
    "null_rate": 0.0
  },
  {
    "full_name": "public.maintenance_work_order.downtime_minutes",
    "schema": "public",
    "table": "maintenance_work_order",
    "name": "downtime_minutes",
    "comment": "停机时长（分钟）",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.maintenance_work_order.spare_part_cost",
    "schema": "public",
    "table": "maintenance_work_order",
    "name": "spare_part_cost",
    "comment": "备件费用（金额）",
    "data_type": "numeric",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.order_header.order_id",
    "schema": "public",
    "table": "order_header",
    "name": "order_id",
    "comment": "订单唯一标识编号，用于区分每一笔订单",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": true,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 1,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.order_header.order_date",
    "schema": "public",
    "table": "order_header",
    "name": "order_date",
    "comment": "订单创建的日期，表示客户提交订单的时间",
    "data_type": "date",
    "semantic_role": "",
    "is_pk": true,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 2,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.order_header.customer",
    "schema": "public",
    "table": "order_header",
    "name": "customer",
    "comment": "下单客户的姓名",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.order_item.item_id",
    "schema": "public",
    "table": "order_item",
    "name": "item_id",
    "comment": "订单项唯一标识符",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": true,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 1,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.order_item.order_id",
    "schema": "public",
    "table": "order_item",
    "name": "order_id",
    "comment": "关联的订单编号",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": true,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.5,
    "null_rate": 0.0
  },
  {
    "full_name": "public.order_item.order_date",
    "schema": "public",
    "table": "order_item",
    "name": "order_date",
    "comment": "订单日期，与订单编号共同标识所属订单",
    "data_type": "date",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": true,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.5,
    "null_rate": 0.0
  },
  {
    "full_name": "public.order_item.product",
    "schema": "public",
    "table": "order_item",
    "name": "product",
    "comment": "商品名称",
    "data_type": "character varying",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 1.0,
    "null_rate": 0.0
  },
  {
    "full_name": "public.order_item.quantity",
    "schema": "public",
    "table": "order_item",
    "name": "quantity",
    "comment": "商品数量",
    "data_type": "integer",
    "semantic_role": "",
    "is_pk": false,
    "is_uk": false,
    "is_fk": false,
    "is_time": false,
    "is_measure": false,
    "pk_position": 0,
    "uniqueness": 0.4,
    "null_rate": 0.0
  }
] AS c
MERGE (n:Column {full_name: c.full_name})
SET n.schema       = c.schema,
    n.table        = c.table,
    n.name         = c.name,
    n.comment      = c.comment,
    n.data_type    = c.data_type,
    n.semantic_role= c.semantic_role,
    n.is_pk        = c.is_pk,
    n.is_uk        = c.is_uk,
    n.is_fk        = c.is_fk,
    n.is_time      = c.is_time,
    n.is_measure   = c.is_measure,
    n.pk_position  = c.pk_position,
    n.uniqueness   = c.uniqueness,
    n.null_rate    = c.null_rate;

// =====================================================================
// 4. 建立 HAS_COLUMN 关系
// =====================================================================

UNWIND [
  {
    "table_full_name": "public.department",
    "column_full_name": "public.department.dept_id"
  },
  {
    "table_full_name": "public.department",
    "column_full_name": "public.department.dept_code"
  },
  {
    "table_full_name": "public.department",
    "column_full_name": "public.department.dept_name"
  },
  {
    "table_full_name": "public.department",
    "column_full_name": "public.department.location"
  },
  {
    "table_full_name": "public.dim_company",
    "column_full_name": "public.dim_company.company_id"
  },
  {
    "table_full_name": "public.dim_company",
    "column_full_name": "public.dim_company.company_name"
  },
  {
    "table_full_name": "public.dim_product_type",
    "column_full_name": "public.dim_product_type.product_type_id"
  },
  {
    "table_full_name": "public.dim_product_type",
    "column_full_name": "public.dim_product_type.product_type_name"
  },
  {
    "table_full_name": "public.dim_region",
    "column_full_name": "public.dim_region.region_id"
  },
  {
    "table_full_name": "public.dim_region",
    "column_full_name": "public.dim_region.region_name"
  },
  {
    "table_full_name": "public.dim_region",
    "column_full_name": "public.dim_region.city_id"
  },
  {
    "table_full_name": "public.dim_region",
    "column_full_name": "public.dim_region.city_name"
  },
  {
    "table_full_name": "public.dim_region",
    "column_full_name": "public.dim_region.province_id"
  },
  {
    "table_full_name": "public.dim_region",
    "column_full_name": "public.dim_region.province_name"
  },
  {
    "table_full_name": "public.dim_store",
    "column_full_name": "public.dim_store.store_id"
  },
  {
    "table_full_name": "public.dim_store",
    "column_full_name": "public.dim_store.store_name"
  },
  {
    "table_full_name": "public.dim_store",
    "column_full_name": "public.dim_store.company_id"
  },
  {
    "table_full_name": "public.dim_store",
    "column_full_name": "public.dim_store.region_id"
  },
  {
    "table_full_name": "public.employee",
    "column_full_name": "public.employee.emp_id"
  },
  {
    "table_full_name": "public.employee",
    "column_full_name": "public.employee.emp_no"
  },
  {
    "table_full_name": "public.employee",
    "column_full_name": "public.employee.emp_name"
  },
  {
    "table_full_name": "public.employee",
    "column_full_name": "public.employee.gender"
  },
  {
    "table_full_name": "public.employee",
    "column_full_name": "public.employee.hire_date"
  },
  {
    "table_full_name": "public.employee",
    "column_full_name": "public.employee.salary"
  },
  {
    "table_full_name": "public.employee",
    "column_full_name": "public.employee.dept_id"
  },
  {
    "table_full_name": "public.equipment_config",
    "column_full_name": "public.equipment_config.equipment_id"
  },
  {
    "table_full_name": "public.equipment_config",
    "column_full_name": "public.equipment_config.config_version"
  },
  {
    "table_full_name": "public.equipment_config",
    "column_full_name": "public.equipment_config.controller_model"
  },
  {
    "table_full_name": "public.equipment_config",
    "column_full_name": "public.equipment_config.firmware_version"
  },
  {
    "table_full_name": "public.fact_store_sales_day",
    "column_full_name": "public.fact_store_sales_day.store_id"
  },
  {
    "table_full_name": "public.fact_store_sales_day",
    "column_full_name": "public.fact_store_sales_day.date_day"
  },
  {
    "table_full_name": "public.fact_store_sales_day",
    "column_full_name": "public.fact_store_sales_day.product_type_id"
  },
  {
    "table_full_name": "public.fact_store_sales_day",
    "column_full_name": "public.fact_store_sales_day.amount"
  },
  {
    "table_full_name": "public.fact_store_sales_month",
    "column_full_name": "public.fact_store_sales_month.store_id"
  },
  {
    "table_full_name": "public.fact_store_sales_month",
    "column_full_name": "public.fact_store_sales_month.date_month"
  },
  {
    "table_full_name": "public.fact_store_sales_month",
    "column_full_name": "public.fact_store_sales_month.product_type_id"
  },
  {
    "table_full_name": "public.fact_store_sales_month",
    "column_full_name": "public.fact_store_sales_month.amount"
  },
  {
    "table_full_name": "public.fault_catalog",
    "column_full_name": "public.fault_catalog.product_line_code"
  },
  {
    "table_full_name": "public.fault_catalog",
    "column_full_name": "public.fault_catalog.subsystem_code"
  },
  {
    "table_full_name": "public.fault_catalog",
    "column_full_name": "public.fault_catalog.fault_code"
  },
  {
    "table_full_name": "public.fault_catalog",
    "column_full_name": "public.fault_catalog.fault_name"
  },
  {
    "table_full_name": "public.fault_catalog",
    "column_full_name": "public.fault_catalog.recommended_action"
  },
  {
    "table_full_name": "public.maintenance_work_order",
    "column_full_name": "public.maintenance_work_order.wo_id"
  },
  {
    "table_full_name": "public.maintenance_work_order",
    "column_full_name": "public.maintenance_work_order.wo_line_no"
  },
  {
    "table_full_name": "public.maintenance_work_order",
    "column_full_name": "public.maintenance_work_order.fault_ts"
  },
  {
    "table_full_name": "public.maintenance_work_order",
    "column_full_name": "public.maintenance_work_order.equipment_id"
  },
  {
    "table_full_name": "public.maintenance_work_order",
    "column_full_name": "public.maintenance_work_order.config_version"
  },
  {
    "table_full_name": "public.maintenance_work_order",
    "column_full_name": "public.maintenance_work_order.product_line_code"
  },
  {
    "table_full_name": "public.maintenance_work_order",
    "column_full_name": "public.maintenance_work_order.subsystem_code"
  },
  {
    "table_full_name": "public.maintenance_work_order",
    "column_full_name": "public.maintenance_work_order.fault_code"
  },
  {
    "table_full_name": "public.maintenance_work_order",
    "column_full_name": "public.maintenance_work_order.downtime_minutes"
  },
  {
    "table_full_name": "public.maintenance_work_order",
    "column_full_name": "public.maintenance_work_order.spare_part_cost"
  },
  {
    "table_full_name": "public.order_header",
    "column_full_name": "public.order_header.order_id"
  },
  {
    "table_full_name": "public.order_header",
    "column_full_name": "public.order_header.order_date"
  },
  {
    "table_full_name": "public.order_header",
    "column_full_name": "public.order_header.customer"
  },
  {
    "table_full_name": "public.order_item",
    "column_full_name": "public.order_item.item_id"
  },
  {
    "table_full_name": "public.order_item",
    "column_full_name": "public.order_item.order_id"
  },
  {
    "table_full_name": "public.order_item",
    "column_full_name": "public.order_item.order_date"
  },
  {
    "table_full_name": "public.order_item",
    "column_full_name": "public.order_item.product"
  },
  {
    "table_full_name": "public.order_item",
    "column_full_name": "public.order_item.quantity"
  }
] AS hc
MATCH (t:Table {full_name: hc.table_full_name})
MATCH (c:Column {full_name: hc.column_full_name})
MERGE (t)-[:HAS_COLUMN]->(c);

// =====================================================================
// 5. 建立 JOIN_ON 关系
// =====================================================================

UNWIND [
  {
    "src_full_name": "public.department",
    "dst_full_name": "public.employee",
    "cardinality": "1:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.dept_id = DST.dept_id",
    "source_columns": [
      "dept_id"
    ],
    "target_columns": [
      "dept_id"
    ]
  },
  {
    "src_full_name": "public.order_item",
    "dst_full_name": "public.order_header",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.order_date = DST.order_date AND SRC.order_id = DST.order_id",
    "source_columns": [
      "order_date",
      "order_id"
    ],
    "target_columns": [
      "order_date",
      "order_id"
    ]
  },
  {
    "src_full_name": "public.dim_store",
    "dst_full_name": "public.dim_company",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.company_id = DST.company_id",
    "source_columns": [
      "company_id"
    ],
    "target_columns": [
      "company_id"
    ]
  },
  {
    "src_full_name": "public.fact_store_sales_day",
    "dst_full_name": "public.dim_product_type",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.product_type_id = DST.product_type_id",
    "source_columns": [
      "product_type_id"
    ],
    "target_columns": [
      "product_type_id"
    ]
  },
  {
    "src_full_name": "public.fact_store_sales_month",
    "dst_full_name": "public.dim_product_type",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.product_type_id = DST.product_type_id",
    "source_columns": [
      "product_type_id"
    ],
    "target_columns": [
      "product_type_id"
    ]
  },
  {
    "src_full_name": "public.dim_region",
    "dst_full_name": "public.dim_store",
    "cardinality": "M:N",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.region_id = DST.region_id",
    "source_columns": [
      "region_id"
    ],
    "target_columns": [
      "region_id"
    ]
  },
  {
    "src_full_name": "public.fact_store_sales_day",
    "dst_full_name": "public.dim_store",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.store_id = DST.store_id",
    "source_columns": [
      "store_id"
    ],
    "target_columns": [
      "store_id"
    ]
  },
  {
    "src_full_name": "public.fact_store_sales_month",
    "dst_full_name": "public.dim_store",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.store_id = DST.store_id",
    "source_columns": [
      "store_id"
    ],
    "target_columns": [
      "store_id"
    ]
  },
  {
    "src_full_name": "public.maintenance_work_order",
    "dst_full_name": "public.equipment_config",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.equipment_id = DST.equipment_id AND SRC.config_version = DST.config_version",
    "source_columns": [
      "equipment_id",
      "config_version"
    ],
    "target_columns": [
      "equipment_id",
      "config_version"
    ]
  },
  {
    "src_full_name": "public.fact_store_sales_day",
    "dst_full_name": "public.fact_store_sales_month",
    "cardinality": "M:N",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.store_id = DST.store_id AND SRC.product_type_id = DST.product_type_id",
    "source_columns": [
      "store_id",
      "product_type_id"
    ],
    "target_columns": [
      "store_id",
      "product_type_id"
    ]
  },
  {
    "src_full_name": "public.maintenance_work_order",
    "dst_full_name": "public.fault_catalog",
    "cardinality": "N:1",
    "constraint_name": null,
    "join_type": "INNER JOIN",
    "on": "SRC.product_line_code = DST.product_line_code AND SRC.subsystem_code = DST.subsystem_code AND SRC.fault_code = DST.fault_code",
    "source_columns": [
      "product_line_code",
      "subsystem_code",
      "fault_code"
    ],
    "target_columns": [
      "product_line_code",
      "subsystem_code",
      "fault_code"
    ]
  }
] AS j
MATCH (src:Table {full_name: j.src_full_name})
MATCH (dst:Table {full_name: j.dst_full_name})
MERGE (src)-[r:JOIN_ON]->(dst)
SET r.cardinality     = j.cardinality,
    r.constraint_name = j.constraint_name,
    r.join_type       = coalesce(j.join_type, 'INNER JOIN'),
    r.on              = j.on,
    r.source_columns  = j.source_columns,
    r.target_columns  = j.target_columns;
