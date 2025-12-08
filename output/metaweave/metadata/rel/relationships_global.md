# 表间关系发现报告

生成时间: 2025-12-07 19:12:48
关系总数: 28

## 统计摘要

- 外键直通: 2
- 推断关系: 26
- 复合键关系: 5
- 单列关系: 23
- 高置信度 (≥0.9): 17
- 中置信度 (0.8-0.9): 6

## 关系详情

### 1. public.employee.dept_id → public.department.dept_id

- **类型**: 单列
- **源列**: `dept_id`
- **目标列**: `dept_id`
- **关系类型**: foreign_key

### 2. public.order_item.[order_date, order_id] → public.order_header.[order_date, order_id]

- **类型**: 复合键
- **源列**: `order_date, order_id`
- **目标列**: `order_date, order_id`
- **关系类型**: foreign_key

### 3. public.fact_store_sales_day.[store_id, date_day, product_type_id] → public.fact_store_sales_month.[store_id, date_month, product_type_id]

- **类型**: 复合键
- **源列**: `store_id, date_day, product_type_id`
- **目标列**: `store_id, date_month, product_type_id`
- **关系类型**: inferred
- **置信度**: 0.665 (低)
- **评分明细**:
  - inclusion_rate: 0.500
  - jaccard_index: 0.500
  - name_similarity: 0.948
  - type_compatibility: 1.000
- **推断方法**: composite_logical

### 4. public.fact_store_sales_month.[store_id, date_month, product_type_id] → public.fact_store_sales_day.[store_id, date_day, product_type_id]

- **类型**: 复合键
- **源列**: `store_id, date_month, product_type_id`
- **目标列**: `store_id, date_day, product_type_id`
- **关系类型**: inferred
- **置信度**: 0.940 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 0.500
  - name_similarity: 0.948
  - type_compatibility: 1.000
- **推断方法**: composite_logical

### 5. public.fault_catalog.[product_line_code, subsystem_code, fault_code] → public.maintenance_work_order.[product_line_code, subsystem_code, fault_code]

- **类型**: 复合键
- **源列**: `product_line_code, subsystem_code, fault_code`
- **目标列**: `product_line_code, subsystem_code, fault_code`
- **关系类型**: inferred
- **置信度**: 0.675 (低)
- **评分明细**:
  - inclusion_rate: 0.500
  - jaccard_index: 0.500
  - name_similarity: 1.000
  - type_compatibility: 1.000
- **推断方法**: composite_logical

### 6. public.order_header.[order_id, order_date] → public.order_item.[order_id, order_date]

- **类型**: 复合键
- **源列**: `order_id, order_date`
- **目标列**: `order_id, order_date`
- **关系类型**: inferred
- **置信度**: 1.000 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 1.000
  - type_compatibility: 1.000
- **推断方法**: composite_physical

### 7. public.order_header.order_id → public.order_item.order_id

- **类型**: 单列
- **源列**: `order_id`
- **目标列**: `order_id`
- **关系类型**: inferred
- **置信度**: 1.000 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 1.000
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint

### 8. public.department.dept_id → public.employee.emp_id

- **类型**: 单列
- **源列**: `dept_id`
- **目标列**: `emp_id`
- **关系类型**: inferred
- **置信度**: 0.938 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 0.690
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint

### 9. public.department.dept_id → public.employee.dept_id

- **类型**: 单列
- **源列**: `dept_id`
- **目标列**: `dept_id`
- **关系类型**: inferred
- **置信度**: 0.968 (高)
- **评分明细**:
  - inclusion_rate: 0.950
  - jaccard_index: 0.950
  - name_similarity: 1.000
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint

### 10. public.department.dept_id → public.order_item.item_id

- **类型**: 单列
- **源列**: `dept_id`
- **目标列**: `item_id`
- **关系类型**: inferred
- **置信度**: 0.954 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 0.771
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint

### 11. public.dim_company.company_id → public.department.dept_id

- **类型**: 单列
- **源列**: `company_id`
- **目标列**: `dept_id`
- **关系类型**: inferred
- **置信度**: 0.860 (中)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 0.150
  - name_similarity: 0.726
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 12. public.dim_company.company_id → public.dim_product_type.product_type_id

- **类型**: 单列
- **源列**: `company_id`
- **目标列**: `product_type_id`
- **关系类型**: inferred
- **置信度**: 0.928 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 0.750
  - name_similarity: 0.767
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 13. public.dim_company.company_id → public.dim_store.company_id

- **类型**: 单列
- **源列**: `company_id`
- **目标列**: `company_id`
- **关系类型**: inferred
- **置信度**: 1.000 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 1.000
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 14. public.dim_company.company_id → public.employee.emp_id

- **类型**: 单列
- **源列**: `company_id`
- **目标列**: `emp_id`
- **关系类型**: inferred
- **置信度**: 0.858 (中)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 0.150
  - name_similarity: 0.713
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 15. public.dim_company.company_id → public.order_item.item_id

- **类型**: 单列
- **源列**: `company_id`
- **目标列**: `item_id`
- **关系类型**: inferred
- **置信度**: 0.870 (中)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 0.150
  - name_similarity: 0.774
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 16. public.dim_product_type.product_type_id → public.department.dept_id

- **类型**: 单列
- **源列**: `product_type_id`
- **目标列**: `dept_id`
- **关系类型**: inferred
- **置信度**: 0.854 (中)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 0.200
  - name_similarity: 0.668
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 17. public.dim_product_type.product_type_id → public.dim_company.company_id

- **类型**: 单列
- **源列**: `product_type_id`
- **目标列**: `company_id`
- **关系类型**: inferred
- **置信度**: 0.791 (低)
- **评分明细**:
  - inclusion_rate: 0.750
  - jaccard_index: 0.750
  - name_similarity: 0.767
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 18. public.dim_product_type.product_type_id → public.employee.emp_id

- **类型**: 单列
- **源列**: `product_type_id`
- **目标列**: `emp_id`
- **关系类型**: inferred
- **置信度**: 0.852 (中)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 0.200
  - name_similarity: 0.659
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 19. public.dim_product_type.product_type_id → public.fact_store_sales_day.product_type_id

- **类型**: 单列
- **源列**: `product_type_id`
- **目标列**: `product_type_id`
- **关系类型**: inferred
- **置信度**: 1.000 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 1.000
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 20. public.dim_product_type.product_type_id → public.fact_store_sales_month.product_type_id

- **类型**: 单列
- **源列**: `product_type_id`
- **目标列**: `product_type_id`
- **关系类型**: inferred
- **置信度**: 1.000 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 1.000
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 21. public.dim_product_type.product_type_id → public.order_item.item_id

- **类型**: 单列
- **源列**: `product_type_id`
- **目标列**: `item_id`
- **关系类型**: inferred
- **置信度**: 0.880 (中)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 0.200
  - name_similarity: 0.799
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 22. public.dim_region.region_id → public.dim_store.region_id

- **类型**: 单列
- **源列**: `region_id`
- **目标列**: `region_id`
- **关系类型**: inferred
- **置信度**: 1.000 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 1.000
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 23. public.dim_store.store_id → public.fact_store_sales_day.store_id

- **类型**: 单列
- **源列**: `store_id`
- **目标列**: `store_id`
- **关系类型**: inferred
- **置信度**: 1.000 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 1.000
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 24. public.dim_store.store_id → public.fact_store_sales_month.store_id

- **类型**: 单列
- **源列**: `store_id`
- **目标列**: `store_id`
- **关系类型**: inferred
- **置信度**: 1.000 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 1.000
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint_and_logical_pk

### 25. public.employee.emp_id → public.department.dept_id

- **类型**: 单列
- **源列**: `emp_id`
- **目标列**: `dept_id`
- **关系类型**: inferred
- **置信度**: 0.938 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 0.690
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint

### 26. public.employee.emp_id → public.order_item.item_id

- **类型**: 单列
- **源列**: `emp_id`
- **目标列**: `item_id`
- **关系类型**: inferred
- **置信度**: 0.951 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 0.753
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint

### 27. public.order_item.item_id → public.department.dept_id

- **类型**: 单列
- **源列**: `item_id`
- **目标列**: `dept_id`
- **关系类型**: inferred
- **置信度**: 0.954 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 0.771
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint

### 28. public.order_item.item_id → public.employee.emp_id

- **类型**: 单列
- **源列**: `item_id`
- **目标列**: `emp_id`
- **关系类型**: inferred
- **置信度**: 0.951 (高)
- **评分明细**:
  - inclusion_rate: 1.000
  - jaccard_index: 1.000
  - name_similarity: 0.753
  - type_compatibility: 1.000
- **推断方法**: single_defined_constraint
