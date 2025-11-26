-- 测试用例 4: ALTER TABLE - ADD CONSTRAINT PRIMARY KEY
CREATE TABLE public.test_pk_alter (
    id   INTEGER,
    name TEXT
);

ALTER TABLE public.test_pk_alter ADD CONSTRAINT test_pk_alter_pkey PRIMARY KEY (id);

/*
 * SAMPLE_RECORDS:
 * {
 *   "records": [
 *     {"id": 1, "name": "Grace"},
 *     {"id": 2, "name": "Henry"}
 *   ]
 * }
 */

