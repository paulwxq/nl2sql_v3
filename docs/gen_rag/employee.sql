-- =========================
-- 1. 删除旧表（如果存在）
-- =========================
DROP TABLE IF EXISTS employee;
DROP TABLE IF EXISTS department;

-- =========================
-- 2. 创建部门表（主表），不带外键
-- =========================
CREATE TABLE department (
    dept_id     SERIAL PRIMARY KEY,
    dept_code   VARCHAR(20)  NOT NULL UNIQUE,
    dept_name   VARCHAR(100) NOT NULL,
    location    VARCHAR(100)
);

-- COMMENT ON TABLE department IS '部门表';
-- COMMENT ON COLUMN department.dept_id   IS '部门主键ID';
-- COMMENT ON COLUMN department.dept_code IS '部门编码';
-- COMMENT ON COLUMN department.dept_name IS '部门名称';
-- COMMENT ON COLUMN department.location  IS '部门所在城市';

-- =========================
-- 3. 创建员工表（从表），不带外键
-- =========================
CREATE TABLE employee (
    emp_id      SERIAL PRIMARY KEY,
    emp_no      VARCHAR(20)  NOT NULL UNIQUE,
    emp_name    VARCHAR(100) NOT NULL,
    gender      CHAR(1)      NOT NULL CHECK (gender IN ('M', 'F')),
    hire_date   DATE         NOT NULL,
    salary      NUMERIC(10,2) NOT NULL CHECK (salary > 0),
    dept_id     INTEGER      NOT NULL
);

-- COMMENT ON TABLE employee IS '员工表';
-- COMMENT ON COLUMN employee.emp_id    IS '员工主键ID';
-- COMMENT ON COLUMN employee.emp_no    IS '员工工号';
-- COMMENT ON COLUMN employee.emp_name  IS '员工姓名';
-- COMMENT ON COLUMN employee.gender    IS '性别(M/F)';
-- COMMENT ON COLUMN employee.hire_date IS '入职日期';
-- COMMENT ON COLUMN employee.salary    IS '月薪';
-- COMMENT ON COLUMN employee.dept_id   IS '所属部门ID';

-- =========================
-- 4. 插入部门数据（20条）
--    这里显式给 dept_id 赋值，方便员工表引用
-- =========================
INSERT INTO department (dept_id, dept_code, dept_name, location) VALUES
(1,  'HR',        '人力资源部',        '北京'),
(2,  'FIN',       '财务部',            '北京'),
(3,  'IT',        '信息技术部',        '上海'),
(4,  'OPS',       '运营部',            '上海'),
(5,  'SALES',     '销售一部',          '广州'),
(6,  'SALES2',    '销售二部',          '深圳'),
(7,  'MKT',       '市场部',            '广州'),
(8,  'RD',        '研发一部',          '杭州'),
(9,  'RD2',       '研发二部',          '南京'),
(10, 'QA',        '质量管理部',        '苏州'),
(11, 'CS',        '客户服务部',        '成都'),
(12, 'LOG',       '物流部',            '武汉'),
(13, 'PUR',       '采购部',            '天津'),
(14, 'ADM',       '行政部',            '北京'),
(15, 'LEGAL',     '法务部',            '上海'),
(16, 'PMO',       '项目管理办公室',    '深圳'),
(17, 'DATA',      '数据分析部',        '杭州'),
(18, 'TRAIN',     '培训部',            '广州'),
(19, 'SEC',       '信息安全部',        '上海'),
(20, 'INTL',      '国际业务部',        '香港');

-- 如果你以后要继续用 SERIAL 自增，
-- 建议把序列位置调到 20 之后（可选）
-- SELECT setval(pg_get_serial_sequence('department', 'dept_id'), 20, true);

-- =========================
-- 5. 插入员工数据（20条）
--    dept_id 都引用 1~20，保证外键将来能创建成功
-- =========================
INSERT INTO employee (emp_id, emp_no, emp_name, gender, hire_date, salary, dept_id) VALUES
(1,  'E0001', '张伟',   'M', '2020-03-15', 12000.00, 1),
(2,  'E0002', '李娜',   'F', '2019-07-01', 15000.00, 3),
(3,  'E0003', '王强',   'M', '2021-01-10',  9800.00, 2),
(4,  'E0004', '赵敏',   'F', '2018-11-20', 13500.00, 5),
(5,  'E0005', '刘洋',   'M', '2017-05-03', 16800.00, 8),
(6,  'E0006', '陈晨',   'F', '2022-02-18',  9000.00, 11),
(7,  'E0007', '孙浩',   'M', '2016-09-09', 21000.00, 3),
(8,  'E0008', '周颖',   'F', '2020-12-01', 12500.00, 7),
(9,  'E0009', '吴磊',   'M', '2019-03-25', 14000.00, 4),
(10, 'E0010', '郭鹏',   'M', '2015-08-16', 23000.00, 10),
(11, 'E0011', '何珊',   'F', '2021-06-30', 10800.00, 6),
(12, 'E0012', '杨帆',   'M', '2018-01-12', 15500.00, 9),
(13, 'E0013', '徐静',   'F', '2017-04-28', 16200.00, 14),
(14, 'E0014', '罗斌',   'M', '2016-10-05', 19800.00, 16),
(15, 'E0015', '高蕾',   'F', '2023-03-01',  8800.00, 18),
(16, 'E0016', '董凯',   'M', '2022-07-19', 11200.00, 17),
(17, 'E0017', '冯雪',   'F', '2019-09-23', 14500.00, 15),
(18, 'E0018', '蒋磊',   'M', '2020-05-11', 13200.00, 12),
(19, 'E0019', '韩梅',   'F', '2018-02-02', 15800.00, 19),
(20, 'E0020', '谢军',   'M', '2015-12-20', 24000.00, 20);

-- 同理，如果要继续用 SERIAL 自增，这里也可以调序列（可选）
-- SELECT setval(pg_get_serial_sequence('employee', 'emp_id'), 20, true);

-- =========================
-- 6. 单独创建外键约束（关键部分）
-- =========================
ALTER TABLE employee
    ADD CONSTRAINT fk_employee_department
    FOREIGN KEY (dept_id)
    REFERENCES department(dept_id);
