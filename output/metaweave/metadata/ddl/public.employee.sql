-- ====================================
-- Table: public.employee
-- Comment: 员工基本信息及雇佣信息表
-- Generated: 2025-12-06 18:07:56
-- ====================================

CREATE TABLE IF NOT EXISTS public.employee (
    emp_id INTEGER(32) NOT NULL DEFAULT nextval('employee_emp_id_seq'::regclass),
    emp_no CHARACTER VARYING(20) NOT NULL,
    emp_name CHARACTER VARYING(100) NOT NULL,
    gender CHARACTER(1) NOT NULL,
    hire_date DATE NOT NULL,
    salary NUMERIC(10,2) NOT NULL,
    dept_id INTEGER(32) NOT NULL,
    CONSTRAINT employee_pkey PRIMARY KEY (emp_id),
    CONSTRAINT employee_emp_no_key UNIQUE (emp_no),
    CONSTRAINT fk_employee_department FOREIGN KEY (dept_id) REFERENCES public.department (dept_id)
);

-- Column Comments
COMMENT ON COLUMN public.employee.emp_id IS '员工唯一标识ID';
COMMENT ON COLUMN public.employee.emp_no IS '员工编号';
COMMENT ON COLUMN public.employee.emp_name IS '员工姓名';
COMMENT ON COLUMN public.employee.gender IS '员工性别（M-男，F-女）';
COMMENT ON COLUMN public.employee.hire_date IS '入职日期';
COMMENT ON COLUMN public.employee.salary IS '员工薪资';
COMMENT ON COLUMN public.employee.dept_id IS '所属部门ID';

-- Table Comment
COMMENT ON TABLE public.employee IS '员工基本信息及雇佣信息表';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.employee",
  "generated_at": "2025-12-06T10:07:56.499113Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "emp_id": "1",
        "emp_no": "E0001",
        "emp_name": "张伟",
        "gender": "M",
        "hire_date": "2020-03-15",
        "salary": "12000.0",
        "dept_id": "1"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "emp_id": "2",
        "emp_no": "E0002",
        "emp_name": "李娜",
        "gender": "F",
        "hire_date": "2019-07-01",
        "salary": "15000.0",
        "dept_id": "3"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "emp_id": "3",
        "emp_no": "E0003",
        "emp_name": "王强",
        "gender": "M",
        "hire_date": "2021-01-10",
        "salary": "9800.0",
        "dept_id": "2"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "emp_id": "4",
        "emp_no": "E0004",
        "emp_name": "赵敏",
        "gender": "F",
        "hire_date": "2018-11-20",
        "salary": "13500.0",
        "dept_id": "5"
      }
    },
    {
      "label": "Record 5",
      "data": {
        "emp_id": "5",
        "emp_no": "E0005",
        "emp_name": "刘洋",
        "gender": "M",
        "hire_date": "2017-05-03",
        "salary": "16800.0",
        "dept_id": "8"
      }
    }
  ]
}
*/