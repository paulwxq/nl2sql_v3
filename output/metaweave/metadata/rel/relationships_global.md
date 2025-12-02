# 表间关系发现报告

生成时间: 2025-12-02 10:25:07
关系总数: 6

## 统计摘要

- 外键直通: 0
- 推断关系: 6
- 复合键关系: 0
- 单列关系: 6
- 高置信度 (≥0.9): 6
- 中置信度 (0.8-0.9): 0

## 关系详情

### 1. public.dim_company.company_id → public.dim_store.company_id

- **类型**: 单列
- **源列**: `company_id`
- **目标列**: `company_id`
- **关系类型**: inferred
- **置信度**: 0.933 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - uniqueness: 0.333
  - name_similarity: 1.000
  - type_compatibility: 1.000
  - semantic_role_bonus: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 2. public.dim_product_type.product_type_id → public.fact_store_sales_day.product_type_id

- **类型**: 单列
- **源列**: `product_type_id`
- **目标列**: `product_type_id`
- **关系类型**: inferred
- **置信度**: 0.903 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - uniqueness: 0.028
  - name_similarity: 1.000
  - type_compatibility: 1.000
  - semantic_role_bonus: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 3. public.dim_product_type.product_type_id → public.fact_store_sales_month.product_type_id

- **类型**: 单列
- **源列**: `product_type_id`
- **目标列**: `product_type_id`
- **关系类型**: inferred
- **置信度**: 0.906 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - uniqueness: 0.056
  - name_similarity: 1.000
  - type_compatibility: 1.000
  - semantic_role_bonus: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 4. public.dim_region.region_id → public.dim_store.region_id

- **类型**: 单列
- **源列**: `region_id`
- **目标列**: `region_id`
- **关系类型**: inferred
- **置信度**: 0.989 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - uniqueness: 0.889
  - name_similarity: 1.000
  - type_compatibility: 1.000
  - semantic_role_bonus: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 5. public.dim_store.store_id → public.fact_store_sales_day.store_id

- **类型**: 单列
- **源列**: `store_id`
- **目标列**: `store_id`
- **关系类型**: inferred
- **置信度**: 0.906 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - uniqueness: 0.062
  - name_similarity: 1.000
  - type_compatibility: 1.000
  - semantic_role_bonus: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 6. public.dim_store.store_id → public.fact_store_sales_month.store_id

- **类型**: 单列
- **源列**: `store_id`
- **目标列**: `store_id`
- **关系类型**: inferred
- **置信度**: 0.912 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - uniqueness: 0.125
  - name_similarity: 1.000
  - type_compatibility: 1.000
  - semantic_role_bonus: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk
