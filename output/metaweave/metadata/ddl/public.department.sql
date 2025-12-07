-- ====================================
-- Table: public.department
-- Comment: 部门信息表，存储各部门的编号、代码、名称及所在位置
-- Generated: 2025-12-06 18:07:56
-- ====================================

CREATE TABLE IF NOT EXISTS public.department (
    dept_id INTEGER(32) NOT NULL DEFAULT nextval('department_dept_id_seq'::regclass),
    dept_code CHARACTER VARYING(20) NOT NULL,
    dept_name CHARACTER VARYING(100) NOT NULL,
    location CHARACTER VARYING(100),
    CONSTRAINT department_pkey PRIMARY KEY (dept_id),
    CONSTRAINT department_dept_code_key UNIQUE (dept_code)
);

-- Column Comments
COMMENT ON COLUMN public.department.dept_id IS '部门唯一标识ID';
COMMENT ON COLUMN public.department.dept_code IS '部门编码（如HR、FIN）';
COMMENT ON COLUMN public.department.dept_name IS '部门名称（如人力资源部）';
COMMENT ON COLUMN public.department.location IS '部门所在城市（如北京、上海）';

-- Table Comment
COMMENT ON TABLE public.department IS '部门信息表，存储各部门的编号、代码、名称及所在位置';

/* SAMPLE_RECORDS
{
  "version": 1,
  "table": "public.department",
  "generated_at": "2025-12-06T10:07:56.395323Z",
  "records": [
    {
      "label": "Record 1",
      "data": {
        "dept_id": "1",
        "dept_code": "HR",
        "dept_name": "人力资源部",
        "location": "北京"
      }
    },
    {
      "label": "Record 2",
      "data": {
        "dept_id": "2",
        "dept_code": "FIN",
        "dept_name": "财务部",
        "location": "北京"
      }
    },
    {
      "label": "Record 3",
      "data": {
        "dept_id": "3",
        "dept_code": "IT",
        "dept_name": "信息技术部",
        "location": "上海"
      }
    },
    {
      "label": "Record 4",
      "data": {
        "dept_id": "4",
        "dept_code": "OPS",
        "dept_name": "运营部",
        "location": "上海"
      }
    },
    {
      "label": "Record 5",
      "data": {
        "dept_id": "5",
        "dept_code": "SALES",
        "dept_name": "销售一部",
        "location": "广州"
      }
    }
  ]
}
*/