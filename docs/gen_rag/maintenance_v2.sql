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


-- 重新生成三张表的数据（不改表结构）
-- 目标：
-- A) equipment_config -> maintenance_work_order 必须用 2 列： (equipment_id, config_version)
-- B) fault_catalog -> maintenance_work_order 必须用 3 列： (product_line_code, subsystem_code, fault_code)
--    且刻意制造 (product_line_code, fault_code) 在维表中“不唯一”，从而两列 join 会产生一对多放大

truncate table maintenance_work_order;
truncate table equipment_config;
truncate table fault_catalog;

-- =========================
-- 1) 维表：equipment_config（20条：10台设备 * 2个配置版本）
-- =========================
insert into equipment_config (equipment_id, config_version, controller_model, firmware_version) values
  (1001, 'cfg-1.0', 'PLC-X1', 'fw-1.2.3'),
  (1001, 'cfg-2.0', 'PLC-X2', 'fw-2.0.1'),
  (1002, 'cfg-1.0', 'PLC-X1', 'fw-1.2.4'),
  (1002, 'cfg-2.0', 'PLC-X2', 'fw-2.0.2'),
  (1003, 'cfg-1.0', 'PLC-Y1', 'fw-1.1.9'),
  (1003, 'cfg-2.0', 'PLC-Y2', 'fw-2.1.0'),
  (1004, 'cfg-1.0', 'PLC-Y1', 'fw-1.1.8'),
  (1004, 'cfg-2.0', 'PLC-Y2', 'fw-2.1.1'),
  (1005, 'cfg-1.0', 'PLC-Z1', 'fw-1.0.5'),
  (1005, 'cfg-2.0', 'PLC-Z2', 'fw-2.0.0'),
  (1006, 'cfg-1.0', 'PLC-Z1', 'fw-1.0.6'),
  (1006, 'cfg-2.0', 'PLC-Z2', 'fw-2.0.0'),
  (1007, 'cfg-1.0', 'PLC-A1', 'fw-1.3.0'),
  (1007, 'cfg-2.0', 'PLC-A2', 'fw-2.2.0'),
  (1008, 'cfg-1.0', 'PLC-A1', 'fw-1.3.1'),
  (1008, 'cfg-2.0', 'PLC-A2', 'fw-2.2.1'),
  (1009, 'cfg-1.0', 'PLC-B1', 'fw-1.4.0'),
  (1009, 'cfg-2.0', 'PLC-B2', 'fw-2.3.0'),
  (1010, 'cfg-1.0', 'PLC-B1', 'fw-1.4.1'),
  (1010, 'cfg-2.0', 'PLC-B2', 'fw-2.3.1');


-- =========================
-- 2) 维表：fault_catalog（24条）
-- 重点：在同一个 product_line_code 内，同一个 fault_code 故意对应两个 subsystem_code
-- 例如：LINE_A + E101 同时出现在 ELEC 与 CTRL
-- 这样 (product_line_code, fault_code) 不唯一，必须加 subsystem_code 才能唯一关联
-- =========================
insert into fault_catalog (product_line_code, subsystem_code, fault_code, fault_name, recommended_action) values
  -- LINE_A：4个故障码 * 2个子系统
  ('LINE_A', 'ELEC', 'E101', '欠压告警（电源侧）', '检查输入电源/UPS；测量直流输出；紧固端子，排除接触不良。'),
  ('LINE_A', 'CTRL', 'E101', '欠压告警（控制侧）', '检查控制器供电模块与背板供电；查看控制器日志与重启记录。'),

  ('LINE_A', 'ELEC', 'E102', '过压告警（电源侧）', '检查稳压模块；排查浪涌；必要时更换电源模块。'),
  ('LINE_A', 'SENS', 'E102', '过压告警（传感器侧）', '检查传感器供电分配；隔离支路逐一排查；必要时更换保护器件。'),

  ('LINE_A', 'CTRL', 'C401', '通讯超时（控制网络）', '检查以太网/现场总线；核对IP/站号；观察交换机端口错误与丢包。'),
  ('LINE_A', 'ELEC', 'C401', '通讯干扰（电磁侧）', '检查屏蔽接地；排查强电干扰源；优化走线与隔离。'),

  ('LINE_A', 'HYD',  'H201', '压力不足（液压侧）', '检查油位与泄漏；确认泵与溢流阀设定；检查过滤器压差。'),
  ('LINE_A', 'SENS', 'H201', '压力采样异常（传感器侧）', '检查压力传感器与取压口；确认管路堵塞；进行零点/量程校准。'),

  -- LINE_B
  ('LINE_B', 'ELEC', 'E101', '欠压告警（电源侧）', '检查输入与电源模块；排查接触不良；确认接地。'),
  ('LINE_B', 'CTRL', 'E101', '欠压告警（控制侧）', '检查控制器供电；确认背板电压；必要时更换控制电源。'),

  ('LINE_B', 'ELEC', 'E102', '过压告警（电源侧）', '检查稳压/浪涌抑制；确认供电质量；必要时更换模块。'),
  ('LINE_B', 'SENS', 'E102', '过压告警（传感器侧）', '检查供电分配与保护；隔离短路支路；更换损坏传感器。'),

  ('LINE_B', 'CTRL', 'C401', '通讯超时（控制网络）', '检查网络链路；核对地址配置；排查端口错包与丢包。'),
  ('LINE_B', 'ELEC', 'C401', '通讯干扰（电磁侧）', '检查屏蔽与接地；评估变频器干扰；加装滤波/隔离。'),

  ('LINE_B', 'HYD',  'H201', '压力不足（液压侧）', '检查油路泄漏；更换滤芯；核对阀组设定。'),
  ('LINE_B', 'SENS', 'H201', '压力采样异常（传感器侧）', '检查传感器接线；清理取压口；进行校准与比对。'),

  -- LINE_C
  ('LINE_C', 'ELEC', 'E101', '欠压告警（电源侧）', '检查供电与端子；确认电源输出稳定性。'),
  ('LINE_C', 'CTRL', 'E101', '欠压告警（控制侧）', '检查控制器与背板供电；查看事件日志与重启。'),

  ('LINE_C', 'ELEC', 'E102', '过压告警（电源侧）', '检查稳压模块；排查浪涌；确认供电质量。'),
  ('LINE_C', 'SENS', 'E102', '过压告警（传感器侧）', '检查供电分配；隔离支路；更换损坏保护器件。'),

  ('LINE_C', 'CTRL', 'C401', '通讯超时（控制网络）', '检查总线/网络；核对配置；关注丢包与延迟。'),
  ('LINE_C', 'ELEC', 'C401', '通讯干扰（电磁侧）', '检查屏蔽接地与走线；排查干扰源；加装滤波。'),

  ('LINE_C', 'HYD',  'H201', '压力不足（液压侧）', '检查油位、泄漏与泵；核对阀组设定；检查过滤器。'),
  ('LINE_C', 'SENS', 'H201', '压力采样异常（传感器侧）', '检查传感器；清理取压口；执行零点/量程校准。');


-- =========================
-- 3) 事实表：maintenance_work_order（精确 200 条）
-- 生成规则：
-- - equipment_id 在 1001~1010 循环
-- - config_version 在 cfg-1.0 / cfg-2.0 交替（保证 2列能命中 equipment_config）
-- - product_line_code 在 LINE_A/B/C 循环
-- - fault_code 在 E101/E102/C401/H201 循环
-- - subsystem_code 由 fault_code 决定在两个子系统间切换（保证 3列能命中 fault_catalog）
--   且因为维表中 (product_line_code, fault_code) 不唯一，所以两列 join 会一对多
-- =========================
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
  (20000 + ((gs - 1) / 2))::int                               as wo_id,          -- 每个工单2行 => 100个工单
  (1 + ((gs - 1) % 2))::smallint                              as wo_line_no,
  (timestamp '2025-11-01 08:00:00' + (gs - 1) * interval '30 minutes') as fault_ts,

  (1001 + ((gs - 1) % 10))::int                               as equipment_id,
  (case when (gs % 2) = 0 then 'cfg-2.0' else 'cfg-1.0' end)::varchar(64) as config_version,

  (case ((gs - 1) % 3)
     when 0 then 'LINE_A'
     when 1 then 'LINE_B'
     else        'LINE_C'
   end)::varchar(32)                                          as product_line_code,

  (case ((gs - 1) % 4)
     when 0 then (case when (gs % 2)=0 then 'ELEC' else 'CTRL' end)  -- E101: ELEC/CTRL
     when 1 then (case when (gs % 2)=0 then 'ELEC' else 'SENS' end)  -- E102: ELEC/SENS
     when 2 then (case when (gs % 2)=0 then 'CTRL' else 'ELEC' end)  -- C401: CTRL/ELEC
     else        (case when (gs % 2)=0 then 'HYD'  else 'SENS' end)  -- H201: HYD/SENS
   end)::varchar(32)                                          as subsystem_code,

  (case ((gs - 1) % 4)
     when 0 then 'E101'
     when 1 then 'E102'
     when 2 then 'C401'
     else        'H201'
   end)::varchar(32)                                          as fault_code,

  (10 + ((gs * 13) % 240))::int                               as downtime_minutes,
  round((((gs * 137) % 50000) / 100.0)::numeric, 2)::numeric(14,2) as spare_part_cost
from generate_series(1, 200) gs;


-- =========================
-- （可选）你可以用这两段 SQL 验证“必须三列”的事实：
-- 1) 证明维表两列不唯一（会返回多行）
-- select product_line_code, fault_code, count(*) cnt
-- from fault_catalog
-- group by product_line_code, fault_code
-- having count(*) > 1;
--
-- 2) 证明如果只用两列 join，会放大行数（结果会 > 200）
-- select count(*)
-- from maintenance_work_order c
-- join fault_catalog b
--   on b.product_line_code = c.product_line_code
--  and b.fault_code = c.fault_code;
--
-- 3) 三列 join 则应为 200（不放大）
-- select count(*)
-- from maintenance_work_order c
-- join fault_catalog b
--   on b.product_line_code = c.product_line_code
--  and b.fault_code = c.fault_code
--  and b.subsystem_code = c.subsystem_code;
