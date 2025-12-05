-- ====================================
-- Table: public.fault_catalog
-- Comment: 故障码字典维度表：按“产线/产品线 + 子系统 + 故障码”定义故障含义与处理建议，避免同码异义。
-- Generated: 2025-12-04 22:17:44
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
  "generated_at": "2025-12-04T14:17:44.487491Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "product_line_code": "LINE_A",
        "subsystem_code": "ELEC",
        "fault_code": "E101",
        "fault_name": "欠压告警（电源侧）",
        "recommended_action": "检查输入电源/UPS；测量直流输出；紧固端子，排除接触不良。"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "product_line_code": "LINE_A",
        "subsystem_code": "CTRL",
        "fault_code": "E101",
        "fault_name": "欠压告警（控制侧）",
        "recommended_action": "检查控制器供电模块与背板供电；查看控制器日志与重启记录。"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "product_line_code": "LINE_A",
        "subsystem_code": "ELEC",
        "fault_code": "E102",
        "fault_name": "过压告警（电源侧）",
        "recommended_action": "检查稳压模块；排查浪涌；必要时更换电源模块。"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "product_line_code": "LINE_A",
        "subsystem_code": "SENS",
        "fault_code": "E102",
        "fault_name": "过压告警（传感器侧）",
        "recommended_action": "检查传感器供电分配；隔离支路逐一排查；必要时更换保护器件。"
      }
    },
    {
      "label": "Record 5",
      "data": {
        "product_line_code": "LINE_A",
        "subsystem_code": "CTRL",
        "fault_code": "C401",
        "fault_name": "通讯超时（控制网络）",
        "recommended_action": "检查以太网/现场总线；核对IP/站号；观察交换机端口错误与丢包。"
      }
    }
  ]
}
*/