# public.equipment_config（设备配置维度表：描述设备在某个配置版本下的关键配置属性，用于按“设备ID + 配置版本”关联到工单事实。）
## 字段列表：
- equipment_id (integer(32)) - 设备ID（资产编号） [示例: 1001, 1001]
- config_version (character varying(64)) - 配置版本/改造批次（可为语义化版本或批次号） [示例: cfg-1.0, cfg-2.0]
- controller_model (character varying(64)) - 控制器型号 [示例: PLC-X1, PLC-X2]
- firmware_version (character varying(64)) - 固件版本号（语义化版本等） [示例: fw-1.2.3, fw-2.0.1]