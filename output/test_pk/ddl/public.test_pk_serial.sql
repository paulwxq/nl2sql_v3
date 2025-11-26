-- 测试用例 1: 列级主键 - SERIAL PRIMARY KEY
CREATE TABLE public.test_pk_serial (
    id   SERIAL PRIMARY KEY,
    name TEXT
);

/*
 * SAMPLE_RECORDS:
 * {
 *   "records": [
 *     {"id": 1, "name": "Alice"},
 *     {"id": 2, "name": "Bob"}
 *   ]
 * }
 */

