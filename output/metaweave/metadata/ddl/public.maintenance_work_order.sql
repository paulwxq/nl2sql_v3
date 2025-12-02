-- ====================================
-- Table: public.maintenance_work_order
-- Comment: 维修工单事实表：粒度为“工单-行/条目”，记录设备故障发生时间、故障码上下文、以及停机与成本等关键指标。
-- Generated: 2025-12-02 18:30:11
-- ====================================

CREATE TABLE IF NOT EXISTS public.maintenance_work_order (
    wo_id INTEGER(32),
    wo_line_no SMALLINT(16),
    fault_ts TIMESTAMP WITHOUT TIME ZONE,
    equipment_id INTEGER(32),
    config_version CHARACTER VARYING(64),
    product_line_code CHARACTER VARYING(32),
    subsystem_code CHARACTER VARYING(32),
    fault_code CHARACTER VARYING(32),
    downtime_minutes INTEGER(32),
    spare_part_cost NUMERIC(14,2)
);

-- Column Comments
COMMENT ON COLUMN public.maintenance_work_order.wo_id IS '工单ID';
COMMENT ON COLUMN public.maintenance_work_order.wo_line_no IS '工单行号/条目序号';
COMMENT ON COLUMN public.maintenance_work_order.fault_ts IS '故障发生时间';
COMMENT ON COLUMN public.maintenance_work_order.equipment_id IS '设备ID（资产编号）';
COMMENT ON COLUMN public.maintenance_work_order.config_version IS '设备配置版本/改造批次（与设备配置表形成2列关联）';
COMMENT ON COLUMN public.maintenance_work_order.product_line_code IS '产线/产品线编码（与故障码字典形成3列关联之一）';
COMMENT ON COLUMN public.maintenance_work_order.subsystem_code IS '子系统编码（与故障码字典形成3列关联之一）';
COMMENT ON COLUMN public.maintenance_work_order.fault_code IS '故障码（与故障码字典形成3列关联之一）';
COMMENT ON COLUMN public.maintenance_work_order.downtime_minutes IS '停机时长（分钟）';
COMMENT ON COLUMN public.maintenance_work_order.spare_part_cost IS '备件费用（金额）';

-- Table Comment
COMMENT ON TABLE public.maintenance_work_order IS '维修工单事实表：粒度为“工单-行/条目”，记录设备故障发生时间、故障码上下文、以及停机与成本等关键指标。';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.maintenance_work_order",
  "generated_at": "2025-12-02T10:30:11.618901Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "wo_id": "10000",
        "wo_line_no": "1",
        "fault_ts": "2025-11-01 08:00:00",
        "equipment_id": "1001",
        "config_version": "cfg-1.0",
        "product_line_code": "LINE_A",
        "subsystem_code": "CTRL",
        "fault_code": "C401",
        "downtime_minutes": "12",
        "spare_part_cost": "0.97"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "wo_id": "10000",
        "wo_line_no": "2",
        "fault_ts": "2025-11-01 08:45:00",
        "equipment_id": "1001",
        "config_version": "cfg-2.0",
        "product_line_code": "LINE_A",
        "subsystem_code": "ELEC",
        "fault_code": "E101",
        "downtime_minutes": "19",
        "spare_part_cost": "1.94"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "wo_id": "10001",
        "wo_line_no": "1",
        "fault_ts": "2025-11-01 09:30:00",
        "equipment_id": "1002",
        "config_version": "cfg-1.0",
        "product_line_code": "LINE_A",
        "subsystem_code": "ELEC",
        "fault_code": "E102",
        "downtime_minutes": "26",
        "spare_part_cost": "2.91"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "wo_id": "10001",
        "wo_line_no": "2",
        "fault_ts": "2025-11-01 10:15:00",
        "equipment_id": "1002",
        "config_version": "cfg-2.0",
        "product_line_code": "LINE_A",
        "subsystem_code": "HYD",
        "fault_code": "H201",
        "downtime_minutes": "33",
        "spare_part_cost": "3.88"
      }
    },
    {
      "label": "Record 5",
      "data": {
        "wo_id": "10002",
        "wo_line_no": "1",
        "fault_ts": "2025-11-01 11:00:00",
        "equipment_id": "1003",
        "config_version": "cfg-1.0",
        "product_line_code": "LINE_A",
        "subsystem_code": "HYD",
        "fault_code": "H202",
        "downtime_minutes": "40",
        "spare_part_cost": "4.85"
      }
    }
  ]
}
*/