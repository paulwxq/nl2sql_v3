# public.employee（员工基本信息及雇佣信息表）
## 字段列表：
- emp_id (integer(32)) - 员工唯一标识ID [示例: 1, 2]
- emp_no (character varying(20)) - 员工编号 [示例: E0001, E0002]
- emp_name (character varying(100)) - 员工姓名 [示例: 张伟, 李娜]
- gender (character(1)) - 员工性别（M-男，F-女） [示例: M, F]
- hire_date (date) - 入职日期 [示例: 2020-03-15, 2019-07-01]
- salary (numeric(10,2)) - 员工薪资 [示例: 12000.0, 15000.0]
- dept_id (integer(32)) - 所属部门ID [示例: 1, 3]
## 字段补充说明：
- 主键约束 employee_pkey: emp_id
- dept_id 关联 public.department.dept_id
- 唯一约束 employee_emp_no_key: emp_no
- salary 使用numeric(10,2)存储，精确到小数点后2位