# public.fault_catalog（故障码字典维度表：按“产线/产品线 + 子系统 + 故障码”定义故障含义与处理建议，避免同码异义。）
## 字段列表：
- product_line_code (character varying(32)) - 产线/产品线编码 [示例: LINE_A, LINE_A]
- subsystem_code (character varying(32)) - 子系统编码 [示例: ELEC, CTRL]
- fault_code (character varying(32)) - 故障码 [示例: E101, E101]
- fault_name (character varying(128)) - 故障名称（标准名） [示例: 欠压告警（电源侧）, 欠压告警（控制侧）]
- recommended_action (text) - 建议处理措施/排查步骤（长文本） [示例: 检查输入电源/UPS；测量直流输出；紧固端子，排除接触不良。, 检查控制器供电模块与背板供电；查看控制器日志与重启记录。]