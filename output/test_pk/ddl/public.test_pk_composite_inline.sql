-- 测试用例 5: 无名表级主键 - PRIMARY KEY (col1, col2)
CREATE TABLE public.test_pk_composite_inline (
    store_id   INTEGER,
    product_id INTEGER,
    quantity   INTEGER,
    PRIMARY KEY (store_id, product_id)
);

/*
 * SAMPLE_RECORDS:
 * {
 *   "records": [
 *     {"store_id": 1, "product_id": 100, "quantity": 5},
 *     {"store_id": 1, "product_id": 200, "quantity": 3}
 *   ]
 * }
 */

