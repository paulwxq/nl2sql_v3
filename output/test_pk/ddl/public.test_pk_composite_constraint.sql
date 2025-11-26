-- 测试用例 6: 联合主键 - CONSTRAINT ... PRIMARY KEY (col1, col2)
CREATE TABLE public.test_pk_composite_constraint (
    store_id   INTEGER,
    product_id INTEGER,
    quantity   INTEGER,
    CONSTRAINT test_pk_composite_pkey PRIMARY KEY (store_id, product_id)
);

/*
 * SAMPLE_RECORDS:
 * {
 *   "records": [
 *     {"store_id": 2, "product_id": 300, "quantity": 7},
 *     {"store_id": 2, "product_id": 400, "quantity": 2}
 *   ]
 * }
 */

