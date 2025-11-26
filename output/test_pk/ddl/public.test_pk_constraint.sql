-- 测试用例 3: 表级约束 - CONSTRAINT ... PRIMARY KEY
CREATE TABLE public.test_pk_constraint (
    id   INTEGER,
    name TEXT,
    CONSTRAINT test_pk_constraint_pkey PRIMARY KEY (id)
);

/*
 * SAMPLE_RECORDS:
 * {
 *   "records": [
 *     {"id": 1, "name": "Eve"},
 *     {"id": 2, "name": "Frank"}
 *   ]
 * }
 */

