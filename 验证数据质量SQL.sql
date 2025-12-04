-- ====================================
-- 数据质量验证 SQL
-- 目的：验证 Demo 数据库的模拟数据是否导致逻辑主键检测失败
-- ====================================

-- ============================================================
-- 1. fault_catalog 表验证
-- ============================================================

-- 1.1 检查表的总行数
SELECT
    '1.1 fault_catalog 总行数' AS check_item,
    COUNT(*) AS total_rows
FROM public.fault_catalog;

-- 1.2 检查 [product_line_code, subsystem_code, fault_code] 3列组合的唯一性
SELECT
    '1.2 [product_line_code, subsystem_code, fault_code] 组合唯一性' AS check_item,
    COUNT(*) AS total_rows,
    COUNT(DISTINCT (product_line_code, subsystem_code, fault_code)) AS distinct_combinations,
    CASE
        WHEN COUNT(*) = COUNT(DISTINCT (product_line_code, subsystem_code, fault_code))
        THEN '✅ 唯一（可作为主键）'
        ELSE '❌ 不唯一（有重复）'
    END AS is_unique
FROM public.fault_catalog;

-- 1.3 检查是否有重复的 [product_line_code, subsystem_code, fault_code] 组合
SELECT
    '1.3 重复的 [product_line_code, subsystem_code, fault_code] 组合' AS check_item,
    product_line_code,
    subsystem_code,
    fault_code,
    COUNT(*) AS duplicate_count
FROM public.fault_catalog
GROUP BY product_line_code, subsystem_code, fault_code
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC;

-- 1.4 检查各列的唯一值数量
SELECT
    '1.4 各列的唯一值数量' AS check_item,
    COUNT(DISTINCT product_line_code) AS product_line_code_distinct,
    COUNT(DISTINCT subsystem_code) AS subsystem_code_distinct,
    COUNT(DISTINCT fault_code) AS fault_code_distinct,
    COUNT(DISTINCT fault_name) AS fault_name_distinct
FROM public.fault_catalog;

-- 1.5 检查 [product_line_code, fault_name] 2列组合的唯一性（当前逻辑主键）
SELECT
    '1.5 [product_line_code, fault_name] 组合唯一性（当前检测结果）' AS check_item,
    COUNT(*) AS total_rows,
    COUNT(DISTINCT (product_line_code, fault_name)) AS distinct_combinations,
    CASE
        WHEN COUNT(*) = COUNT(DISTINCT (product_line_code, fault_name))
        THEN '✅ 唯一（当前检测为主键）'
        ELSE '❌ 不唯一'
    END AS is_unique
FROM public.fault_catalog;

-- 1.6 验证同一个 fault_code 是否在不同的 subsystem_code 下有不同含义（同码异义）
SELECT
    '1.6 同码异义验证：同一个 fault_code 在不同 subsystem 下的情况' AS check_item,
    fault_code,
    COUNT(DISTINCT subsystem_code) AS subsystem_count,
    STRING_AGG(DISTINCT subsystem_code || ':' || fault_name, '; ' ORDER BY subsystem_code) AS meanings
FROM public.fault_catalog
GROUP BY fault_code
HAVING COUNT(DISTINCT subsystem_code) > 1
ORDER BY fault_code;


-- ============================================================
-- 2. equipment_config 表验证
-- ============================================================

-- 2.1 检查表的总行数
SELECT
    '2.1 equipment_config 总行数' AS check_item,
    COUNT(*) AS total_rows
FROM public.equipment_config;

-- 2.2 检查 [equipment_id, config_version] 2列组合的唯一性
SELECT
    '2.2 [equipment_id, config_version] 组合唯一性' AS check_item,
    COUNT(*) AS total_rows,
    COUNT(DISTINCT (equipment_id, config_version)) AS distinct_combinations,
    CASE
        WHEN COUNT(*) = COUNT(DISTINCT (equipment_id, config_version))
        THEN '✅ 唯一（可作为主键）'
        ELSE '❌ 不唯一（有重复）'
    END AS is_unique
FROM public.equipment_config;

-- 2.3 检查是否有重复的 [equipment_id, config_version] 组合
SELECT
    '2.3 重复的 [equipment_id, config_version] 组合' AS check_item,
    equipment_id,
    config_version,
    COUNT(*) AS duplicate_count
FROM public.equipment_config
GROUP BY equipment_id, config_version
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC;

-- 2.4 检查各列的唯一值数量
SELECT
    '2.4 各列的唯一值数量' AS check_item,
    COUNT(DISTINCT equipment_id) AS equipment_id_distinct,
    COUNT(DISTINCT config_version) AS config_version_distinct,
    COUNT(DISTINCT controller_model) AS controller_model_distinct,
    COUNT(DISTINCT firmware_version) AS firmware_version_distinct
FROM public.equipment_config;

-- 2.5 查看每个 equipment_id 的版本数量
SELECT
    '2.5 每个设备的配置版本数量' AS check_item,
    equipment_id,
    COUNT(*) AS version_count,
    STRING_AGG(config_version, ', ' ORDER BY config_version) AS versions
FROM public.equipment_config
GROUP BY equipment_id
ORDER BY equipment_id;


-- ============================================================
-- 3. maintenance_work_order 表验证
-- ============================================================

-- 3.1 检查表的总行数
SELECT
    '3.1 maintenance_work_order 总行数' AS check_item,
    COUNT(*) AS total_rows
FROM public.maintenance_work_order;

-- 3.2 检查 [wo_id, wo_line_no] 2列组合的唯一性（事实表的粒度）
SELECT
    '3.2 [wo_id, wo_line_no] 组合唯一性（表粒度）' AS check_item,
    COUNT(*) AS total_rows,
    COUNT(DISTINCT (wo_id, wo_line_no)) AS distinct_combinations,
    CASE
        WHEN COUNT(*) = COUNT(DISTINCT (wo_id, wo_line_no))
        THEN '✅ 唯一（事实表粒度正确）'
        ELSE '❌ 不唯一（粒度定义错误）'
    END AS is_unique
FROM public.maintenance_work_order;

-- 3.3 检查 [equipment_id, config_version] 外键组合的唯一性（应该不唯一）
SELECT
    '3.3 [equipment_id, config_version] 组合唯一性（外键）' AS check_item,
    COUNT(*) AS total_rows,
    COUNT(DISTINCT (equipment_id, config_version)) AS distinct_combinations,
    ROUND(COUNT(DISTINCT (equipment_id, config_version))::NUMERIC / COUNT(*), 4) AS uniqueness,
    CASE
        WHEN COUNT(*) = COUNT(DISTINCT (equipment_id, config_version))
        THEN '❌ 唯一（不应该唯一，这是外键）'
        ELSE '✅ 不唯一（正确：一个设备配置对应多个工单）'
    END AS is_correct
FROM public.maintenance_work_order;

-- 3.4 检查 [product_line_code, subsystem_code, fault_code] 外键组合的唯一性（应该不唯一）
SELECT
    '3.4 [product_line_code, subsystem_code, fault_code] 组合唯一性（外键）' AS check_item,
    COUNT(*) AS total_rows,
    COUNT(DISTINCT (product_line_code, subsystem_code, fault_code)) AS distinct_combinations,
    ROUND(COUNT(DISTINCT (product_line_code, subsystem_code, fault_code))::NUMERIC / COUNT(*), 4) AS uniqueness,
    CASE
        WHEN COUNT(*) = COUNT(DISTINCT (product_line_code, subsystem_code, fault_code))
        THEN '❌ 唯一（不应该唯一，这是外键）'
        ELSE '✅ 不唯一（正确：一个故障类型对应多个工单）'
    END AS is_correct
FROM public.maintenance_work_order;

-- 3.5 查看每个 [equipment_id, config_version] 组合对应的工单数量
SELECT
    '3.5 每个 [equipment_id, config_version] 对应的工单数' AS check_item,
    equipment_id,
    config_version,
    COUNT(*) AS wo_count
FROM public.maintenance_work_order
GROUP BY equipment_id, config_version
ORDER BY wo_count DESC, equipment_id, config_version
LIMIT 10;

-- 3.6 查看每个 [product_line_code, subsystem_code, fault_code] 组合对应的工单数量
SELECT
    '3.6 每个 [product_line_code, subsystem_code, fault_code] 对应的工单数' AS check_item,
    product_line_code,
    subsystem_code,
    fault_code,
    COUNT(*) AS wo_count
FROM public.maintenance_work_order
GROUP BY product_line_code, subsystem_code, fault_code
ORDER BY wo_count DESC, product_line_code, subsystem_code, fault_code
LIMIT 10;


-- ============================================================
-- 4. 外键完整性验证（参照完整性）
-- ============================================================

-- 4.1 检查 maintenance_work_order → equipment_config 的参照完整性
SELECT
    '4.1 maintenance_work_order → equipment_config 参照完整性' AS check_item,
    COUNT(*) AS orphan_records,
    CASE
        WHEN COUNT(*) = 0 THEN '✅ 无孤儿记录（参照完整性正确）'
        ELSE '❌ 有孤儿记录（数据不完整）'
    END AS integrity_status
FROM public.maintenance_work_order wo
WHERE NOT EXISTS (
    SELECT 1
    FROM public.equipment_config ec
    WHERE ec.equipment_id = wo.equipment_id
      AND ec.config_version = wo.config_version
);

-- 4.2 如果有孤儿记录，列出前 10 条
SELECT
    '4.2 孤儿记录示例（如果有）' AS check_item,
    wo.wo_id,
    wo.equipment_id,
    wo.config_version
FROM public.maintenance_work_order wo
WHERE NOT EXISTS (
    SELECT 1
    FROM public.equipment_config ec
    WHERE ec.equipment_id = wo.equipment_id
      AND ec.config_version = wo.config_version
)
LIMIT 10;

-- 4.3 检查 maintenance_work_order → fault_catalog 的参照完整性
SELECT
    '4.3 maintenance_work_order → fault_catalog 参照完整性' AS check_item,
    COUNT(*) AS orphan_records,
    CASE
        WHEN COUNT(*) = 0 THEN '✅ 无孤儿记录（参照完整性正确）'
        ELSE '❌ 有孤儿记录（数据不完整）'
    END AS integrity_status
FROM public.maintenance_work_order wo
WHERE NOT EXISTS (
    SELECT 1
    FROM public.fault_catalog fc
    WHERE fc.product_line_code = wo.product_line_code
      AND fc.subsystem_code = wo.subsystem_code
      AND fc.fault_code = wo.fault_code
);

-- 4.4 如果有孤儿记录，列出前 10 条
SELECT
    '4.4 孤儿记录示例（如果有）' AS check_item,
    wo.wo_id,
    wo.product_line_code,
    wo.subsystem_code,
    wo.fault_code
FROM public.maintenance_work_order wo
WHERE NOT EXISTS (
    SELECT 1
    FROM public.fault_catalog fc
    WHERE fc.product_line_code = wo.product_line_code
      AND fc.subsystem_code = wo.subsystem_code
      AND fc.fault_code = wo.fault_code
)
LIMIT 10;


-- ============================================================
-- 5. 反向验证：维度表的主键是否都被事实表引用
-- ============================================================

-- 5.1 equipment_config 中有多少组合未被 maintenance_work_order 引用
SELECT
    '5.1 未被工单引用的设备配置' AS check_item,
    COUNT(*) AS unused_configs
FROM public.equipment_config ec
WHERE NOT EXISTS (
    SELECT 1
    FROM public.maintenance_work_order wo
    WHERE wo.equipment_id = ec.equipment_id
      AND wo.config_version = ec.config_version
);

-- 5.2 fault_catalog 中有多少组合未被 maintenance_work_order 引用
SELECT
    '5.2 未被工单引用的故障码' AS check_item,
    COUNT(*) AS unused_fault_codes
FROM public.fault_catalog fc
WHERE NOT EXISTS (
    SELECT 1
    FROM public.maintenance_work_order wo
    WHERE wo.product_line_code = fc.product_line_code
      AND wo.subsystem_code = fc.subsystem_code
      AND wo.fault_code = fc.fault_code
);


-- ============================================================
-- 6. 数据分布分析（帮助理解为什么逻辑主键检测失败）
-- ============================================================

-- 6.1 maintenance_work_order 各外键列的基数
SELECT
    '6.1 maintenance_work_order 外键列的基数分析' AS check_item,
    COUNT(*) AS total_rows,
    COUNT(DISTINCT equipment_id) AS equipment_id_cardinality,
    COUNT(DISTINCT config_version) AS config_version_cardinality,
    COUNT(DISTINCT product_line_code) AS product_line_code_cardinality,
    COUNT(DISTINCT subsystem_code) AS subsystem_code_cardinality,
    COUNT(DISTINCT fault_code) AS fault_code_cardinality
FROM public.maintenance_work_order;

-- 6.2 计算理论上的组合数与实际行数的比例
SELECT
    '6.2 外键组合的理论基数 vs 实际行数' AS check_item,
    COUNT(*) AS actual_rows,
    COUNT(DISTINCT equipment_id) * COUNT(DISTINCT config_version) AS theoretical_eq_config_combinations,
    ROUND(
        (COUNT(DISTINCT equipment_id) * COUNT(DISTINCT config_version))::NUMERIC / COUNT(*),
        4
    ) AS eq_config_uniqueness,
    COUNT(DISTINCT product_line_code) *
    COUNT(DISTINCT subsystem_code) *
    COUNT(DISTINCT fault_code) AS theoretical_fault_combinations,
    ROUND(
        (COUNT(DISTINCT product_line_code) *
         COUNT(DISTINCT subsystem_code) *
         COUNT(DISTINCT fault_code))::NUMERIC / COUNT(*),
        4
    ) AS fault_uniqueness
FROM public.maintenance_work_order;


-- ============================================================
-- 7. 最终结论性验证
-- ============================================================

-- 7.1 如果维度表添加主键，数据是否会冲突？
SELECT
    '7.1 fault_catalog 如果添加主键 [product_line_code, subsystem_code, fault_code]' AS check_item,
    CASE
        WHEN COUNT(*) = COUNT(DISTINCT (product_line_code, subsystem_code, fault_code))
        THEN '✅ 可以安全添加主键（无冲突）'
        ELSE '❌ 无法添加主键（有重复数据）'
    END AS can_add_pk,
    COUNT(*) - COUNT(DISTINCT (product_line_code, subsystem_code, fault_code)) AS duplicate_rows
FROM public.fault_catalog;

SELECT
    '7.2 equipment_config 如果添加主键 [equipment_id, config_version]' AS check_item,
    CASE
        WHEN COUNT(*) = COUNT(DISTINCT (equipment_id, config_version))
        THEN '✅ 可以安全添加主键（无冲突）'
        ELSE '❌ 无法添加主键（有重复数据）'
    END AS can_add_pk,
    COUNT(*) - COUNT(DISTINCT (equipment_id, config_version)) AS duplicate_rows
FROM public.equipment_config;

SELECT
    '7.3 maintenance_work_order 如果添加主键 [wo_id, wo_line_no]' AS check_item,
    CASE
        WHEN COUNT(*) = COUNT(DISTINCT (wo_id, wo_line_no))
        THEN '✅ 可以安全添加主键（无冲突）'
        ELSE '❌ 无法添加主键（有重复数据）'
    END AS can_add_pk,
    COUNT(*) - COUNT(DISTINCT (wo_id, wo_line_no)) AS duplicate_rows
FROM public.maintenance_work_order;
