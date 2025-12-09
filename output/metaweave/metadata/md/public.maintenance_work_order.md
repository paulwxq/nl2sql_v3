# public.maintenance_work_order（维修工单事实表：粒度为“工单-行/条目”，记录设备故障发生时间、故障码上下文、以及停机与成本等关键指标。）
## 字段列表：
- wo_id (integer(32)) - 工单ID [示例: 20000, 20000]
- wo_line_no (smallint(16)) - 工单行号/条目序号 [示例: 1, 2]
- fault_ts (timestamp without time zone) - 故障发生时间 [示例: 2025-11-01 08:00:00, 2025-11-01 08:30:00]
- equipment_id (integer(32)) - 设备ID（资产编号） [示例: 1001, 1002]
- config_version (character varying(64)) - 设备配置版本/改造批次（与设备配置表形成2列关联） [示例: cfg-1.0, cfg-2.0]
- product_line_code (character varying(32)) - 产线/产品线编码（与故障码字典形成3列关联之一） [示例: LINE_A, LINE_B]
- subsystem_code (character varying(32)) - 子系统编码（与故障码字典形成3列关联之一） [示例: CTRL, ELEC]
- fault_code (character varying(32)) - 故障码（与故障码字典形成3列关联之一） [示例: E101, E102]
- downtime_minutes (integer(32)) - 停机时长（分钟） [示例: 23, 36]
- spare_part_cost (numeric(14,2)) - 备件费用（金额） [示例: 1.37, 2.74]
## 字段补充说明：
- spare_part_cost 使用numeric(14,2)存储，精确到小数点后2位