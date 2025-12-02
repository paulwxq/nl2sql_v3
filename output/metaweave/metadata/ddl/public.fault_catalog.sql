-- ====================================
-- Table: public.fault_catalog
-- Comment: 故障码字典维度表：按“产线/产品线 + 子系统 + 故障码”定义故障含义与处理建议，避免同码异义。
-- Generated: 2025-12-02 18:30:11
-- ====================================

CREATE TABLE IF NOT EXISTS public.fault_catalog (
    product_line_code CHARACTER VARYING(32),
    subsystem_code CHARACTER VARYING(32),
    fault_code CHARACTER VARYING(32),
    fault_name CHARACTER VARYING(128),
    recommended_action TEXT
);

-- Column Comments
COMMENT ON COLUMN public.fault_catalog.product_line_code IS '产线/产品线编码';
COMMENT ON COLUMN public.fault_catalog.subsystem_code IS '子系统编码';
COMMENT ON COLUMN public.fault_catalog.fault_code IS '故障码';
COMMENT ON COLUMN public.fault_catalog.fault_name IS '故障名称（标准名）';
COMMENT ON COLUMN public.fault_catalog.recommended_action IS '建议处理措施/排查步骤（长文本）';

-- Table Comment
COMMENT ON TABLE public.fault_catalog IS '故障码字典维度表：按“产线/产品线 + 子系统 + 故障码”定义故障含义与处理建议，避免同码异义。';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.fault_catalog",
  "generated_at": "2025-12-02T10:30:11.425193Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "product_line_code": "LINE_A",
        "subsystem_code": "ELEC",
        "fault_code": "E101",
        "fault_name": "电源欠压",
        "recommended_action": "检查电源输入与UPS；测量24V/48V输出；确认接地与端子紧固。"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "product_line_code": "LINE_A",
        "subsystem_code": "ELEC",
        "fault_code": "E102",
        "fault_name": "电源过压",
        "recommended_action": "检查稳压模块；排查浪涌；必要时更换电源模块。"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "product_line_code": "LINE_A",
        "subsystem_code": "CTRL",
        "fault_code": "C401",
        "fault_name": "PLC 通讯超时",
        "recommended_action": "检查以太网/现场总线；核对IP/站号；观察交换机端口与丢包。"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "product_line_code": "LINE_A",
        "subsystem_code": "SENS",
        "fault_code": "S301",
        "fault_name": "温度传感器开路",
        "recommended_action": "检查传感器线缆与接头；更换传感器；确认量程与标定。"
      }
    },
    {
      "label": "Record 5",
      "data": {
        "product_line_code": "LINE_A",
        "subsystem_code": "HYD",
        "fault_code": "H201",
        "fault_name": "液压压力不足",
        "recommended_action": "检查油位与油温；排查泄漏；检查泵与溢流阀设定。"
      }
    }
  ]
}
*/