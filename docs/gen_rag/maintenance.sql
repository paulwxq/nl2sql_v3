-- 1) 维修工单事实表（最小粒度：工单行/故障条目）
create table maintenance_work_order (
  wo_id             integer,
  wo_line_no        smallint,
  fault_ts          timestamp,
  equipment_id      integer,
  config_version    varchar(64),
  product_line_code varchar(32),
  subsystem_code    varchar(32),
  fault_code        varchar(32),
  downtime_minutes  integer,
  spare_part_cost   numeric(14,2)
);

comment on table maintenance_work_order is '维修工单事实表：粒度为“工单-行/条目”，记录设备故障发生时间、故障码上下文、以及停机与成本等关键指标。';
comment on column maintenance_work_order.wo_id is '工单ID';
comment on column maintenance_work_order.wo_line_no is '工单行号/条目序号';
comment on column maintenance_work_order.fault_ts is '故障发生时间';
comment on column maintenance_work_order.equipment_id is '设备ID（资产编号）';
comment on column maintenance_work_order.config_version is '设备配置版本/改造批次（与设备配置表形成2列关联）';
comment on column maintenance_work_order.product_line_code is '产线/产品线编码（与故障码字典形成3列关联之一）';
comment on column maintenance_work_order.subsystem_code is '子系统编码（与故障码字典形成3列关联之一）';
comment on column maintenance_work_order.fault_code is '故障码（与故障码字典形成3列关联之一）';
comment on column maintenance_work_order.downtime_minutes is '停机时长（分钟）';
comment on column maintenance_work_order.spare_part_cost is '备件费用（金额）';


-- 2) 设备配置维度表（2列关联：equipment_id + config_version）
create table equipment_config (
  equipment_id      integer,
  config_version    varchar(64),
  controller_model  varchar(64),
  firmware_version  varchar(64)
);

comment on table equipment_config is '设备配置维度表：描述设备在某个配置版本下的关键配置属性，用于按“设备ID + 配置版本”关联到工单事实。';
comment on column equipment_config.equipment_id is '设备ID（资产编号）';
comment on column equipment_config.config_version is '配置版本/改造批次（可为语义化版本或批次号）';
comment on column equipment_config.controller_model is '控制器型号';
comment on column equipment_config.firmware_version is '固件版本号（语义化版本等）';


-- 3) 故障码字典维度表（3列关联：product_line_code + subsystem_code + fault_code）
create table fault_catalog (
  product_line_code   varchar(32),
  subsystem_code      varchar(32),
  fault_code          varchar(32),
  fault_name          varchar(128),
  recommended_action  text
);

comment on table fault_catalog is '故障码字典维度表：按“产线/产品线 + 子系统 + 故障码”定义故障含义与处理建议，避免同码异义。';
comment on column fault_catalog.product_line_code is '产线/产品线编码';
comment on column fault_catalog.subsystem_code is '子系统编码';
comment on column fault_catalog.fault_code is '故障码';
comment on column fault_catalog.fault_name is '故障名称（标准名）';
comment on column fault_catalog.recommended_action is '建议处理措施/排查步骤（长文本）';


-- =========================
-- 维表数据：equipment_config（12条）
-- =========================
insert into equipment_config (equipment_id, config_version, controller_model, firmware_version) values
  (1001, 'cfg-1.0', 'PLC-X1', 'fw-1.2.3'),
  (1001, 'cfg-2.0', 'PLC-X2', 'fw-2.0.1'),
  (1002, 'cfg-1.0', 'PLC-X1', 'fw-1.2.4'),
  (1002, 'cfg-2.0', 'PLC-X2', 'fw-2.0.1'),
  (1003, 'cfg-1.0', 'PLC-Y1', 'fw-1.1.9'),
  (1003, 'cfg-2.0', 'PLC-Y2', 'fw-2.1.0'),
  (1004, 'cfg-1.0', 'PLC-Y1', 'fw-1.1.8'),
  (1004, 'cfg-2.0', 'PLC-Y2', 'fw-2.1.0'),
  (1005, 'cfg-1.0', 'PLC-Z1', 'fw-1.0.5'),
  (1005, 'cfg-2.0', 'PLC-Z2', 'fw-2.0.0'),
  (1006, 'cfg-1.0', 'PLC-Z1', 'fw-1.0.6'),
  (1006, 'cfg-2.0', 'PLC-Z2', 'fw-2.0.0');


-- =========================
-- 维表数据：fault_catalog（18条）
-- 关键：同一个 fault_code 在不同 product_line/subsystem 下可“同码异义”
-- =========================
insert into fault_catalog (product_line_code, subsystem_code, fault_code, fault_name, recommended_action) values
  ('LINE_A', 'ELEC', 'E101', '电源欠压', '检查电源输入与UPS；测量24V/48V输出；确认接地与端子紧固。'),
  ('LINE_A', 'ELEC', 'E102', '电源过压', '检查稳压模块；排查浪涌；必要时更换电源模块。'),
  ('LINE_A', 'CTRL', 'C401', 'PLC 通讯超时', '检查以太网/现场总线；核对IP/站号；观察交换机端口与丢包。'),
  ('LINE_A', 'SENS', 'S301', '温度传感器开路', '检查传感器线缆与接头；更换传感器；确认量程与标定。'),
  ('LINE_A', 'HYD',  'H201', '液压压力不足', '检查油位与油温；排查泄漏；检查泵与溢流阀设定。'),
  ('LINE_A', 'HYD',  'H202', '液压油温过高', '检查冷却回路与风扇；确认油液粘度；清理散热器。'),

  ('LINE_B', 'ELEC', 'E101', '急停回路断开', '检查急停按钮与安全继电器；复位安全回路；排查门禁联锁。'),
  ('LINE_B', 'ELEC', 'E103', '变频器故障', '查看变频器告警码；检查散热与负载；必要时降载或更换变频器。'),
  ('LINE_B', 'CTRL', 'C402', 'I/O 模块丢失', '检查机架供电与背板；重新插拔模块；核对组态与硬件型号。'),
  ('LINE_B', 'SENS', 'S302', '振动传感器超限', '检查安装固定；确认阈值设置；排查轴承/对中问题。'),
  ('LINE_B', 'HYD',  'H201', '液压过滤器堵塞', '检查压差开关；更换滤芯；核对油液清洁度与维护周期。'),
  ('LINE_B', 'HYD',  'H203', '阀卡滞', '检查阀芯污染；清洗阀体；确认电磁阀线圈与供电。'),

  ('LINE_C', 'ELEC', 'E104', '接触器粘连', '断电检查触点；测量线圈；必要时更换接触器并检查浪涌。'),
  ('LINE_C', 'CTRL', 'C401', '控制器心跳丢失', '检查控制器供电与日志；升级固件；检查EMI与屏蔽接地。'),
  ('LINE_C', 'CTRL', 'C403', '程序版本不匹配', '核对程序包与版本；重新下装；保留回滚版本以便恢复。'),
  ('LINE_C', 'SENS', 'S301', '温度传感器漂移', '复核标定曲线；更换探头；检查安装位置与热耦类型。'),
  ('LINE_C', 'SENS', 'S303', '压力传感器零点偏移', '执行零点校准；检查取压口堵塞；确认传感器量程。'),
  ('LINE_C', 'HYD',  'H202', '油温异常（冷却不足）', '检查冷却水流量；确认阀门开度；清理冷却器与过滤器。');


-- =========================
-- 事实表数据：maintenance_work_order（200条左右，这里生成精确 200 条）
-- 通过维表行号取模，保证：
--   1) equipment_id + config_version 一定能命中 equipment_config
--   2) product_line_code + subsystem_code + fault_code 一定能命中 fault_catalog
-- =========================
with
equip_list as (
  select
    row_number() over (order by equipment_id, config_version) as rn,
    equipment_id,
    config_version
  from equipment_config
),
equip_cnt as (
  select count(*)::int as cnt from equip_list
),
fault_list as (
  select
    row_number() over (order by product_line_code, subsystem_code, fault_code) as rn,
    product_line_code,
    subsystem_code,
    fault_code
  from fault_catalog
),
fault_cnt as (
  select count(*)::int as cnt from fault_list
)
insert into maintenance_work_order (
  wo_id,
  wo_line_no,
  fault_ts,
  equipment_id,
  config_version,
  product_line_code,
  subsystem_code,
  fault_code,
  downtime_minutes,
  spare_part_cost
)
select
  (10000 + ((gs - 1) / 2))::int as wo_id,                        -- 每个工单2行
  (1 + ((gs - 1) % 2))::smallint as wo_line_no,
  (timestamp '2025-11-01 08:00:00' + (gs - 1) * interval '45 minutes') as fault_ts,

  e.equipment_id,
  e.config_version,

  f.product_line_code,
  f.subsystem_code,
  f.fault_code,

  (5 + ((gs * 7) % 240))::int as downtime_minutes,               -- 5~244分钟循环
  round((((gs * 97) % 20000) / 100.0)::numeric, 2)::numeric(14,2) as spare_part_cost
from generate_series(1, 200) gs
join equip_cnt ec on true
join fault_cnt fc on true
join equip_list e on e.rn = 1 + ((gs - 1) % ec.cnt)
join fault_list f on f.rn = 1 + ((gs - 1) % fc.cnt);
