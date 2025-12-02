-- ====================================
-- Table: public.equipment_config
-- Comment: 设备配置维度表：描述设备在某个配置版本下的关键配置属性，用于按“设备ID + 配置版本”关联到工单事实。
-- Generated: 2025-12-02 18:30:11
-- ====================================

CREATE TABLE IF NOT EXISTS public.equipment_config (
    equipment_id INTEGER(32),
    config_version CHARACTER VARYING(64),
    controller_model CHARACTER VARYING(64),
    firmware_version CHARACTER VARYING(64)
);

-- Column Comments
COMMENT ON COLUMN public.equipment_config.equipment_id IS '设备ID（资产编号）';
COMMENT ON COLUMN public.equipment_config.config_version IS '配置版本/改造批次（可为语义化版本或批次号）';
COMMENT ON COLUMN public.equipment_config.controller_model IS '控制器型号';
COMMENT ON COLUMN public.equipment_config.firmware_version IS '固件版本号（语义化版本等）';

-- Table Comment
COMMENT ON TABLE public.equipment_config IS '设备配置维度表：描述设备在某个配置版本下的关键配置属性，用于按“设备ID + 配置版本”关联到工单事实。';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.equipment_config",
  "generated_at": "2025-12-02T10:30:11.447376Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "equipment_id": "1001",
        "config_version": "cfg-1.0",
        "controller_model": "PLC-X1",
        "firmware_version": "fw-1.2.3"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "equipment_id": "1001",
        "config_version": "cfg-2.0",
        "controller_model": "PLC-X2",
        "firmware_version": "fw-2.0.1"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "equipment_id": "1002",
        "config_version": "cfg-1.0",
        "controller_model": "PLC-X1",
        "firmware_version": "fw-1.2.4"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "equipment_id": "1002",
        "config_version": "cfg-2.0",
        "controller_model": "PLC-X2",
        "firmware_version": "fw-2.0.1"
      }
    },
    {
      "label": "Record 5",
      "data": {
        "equipment_id": "1003",
        "config_version": "cfg-1.0",
        "controller_model": "PLC-Y1",
        "firmware_version": "fw-1.1.9"
      }
    }
  ]
}
*/