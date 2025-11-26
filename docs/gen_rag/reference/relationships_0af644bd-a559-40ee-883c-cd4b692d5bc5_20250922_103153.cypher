// DB2Graph - 自动生成的 Cypher 语句
// run_id: 0af644bd-a559-40ee-883c-cd4b692d5bc5
// 作业启动时间: 2025-09-22T10:31:06.635003
// 模型类型: lightweight
// ================================================

// 创建唯一约束
CREATE CONSTRAINT table_name_unique IF NOT EXISTS
FOR (t:Table) REQUIRE t.name IS UNIQUE;

// 创建表节点

MERGE (t:Table {name: 'customers'})
SET t.schema = 'public',
    t.full_name = 'public.customers',
    t.column_count = 4,
    t.primary_keys = ['customer_id'],
    t.row_count = 10,
    t.has_primary_key = true,
    t.foreign_key_count = 0,
    t.unique_key_count = 1,
    t.updated_at = datetime();

MERGE (t:Table {name: 'order_items'})
SET t.schema = 'public',
    t.full_name = 'public.order_items',
    t.column_count = 6,
    t.primary_keys = ['order_item_id'],
    t.row_count = 65,
    t.has_primary_key = true,
    t.foreign_key_count = 4,
    t.unique_key_count = 0,
    t.updated_at = datetime();

MERGE (t:Table {name: 'orders'})
SET t.schema = 'public',
    t.full_name = 'public.orders',
    t.column_count = 5,
    t.primary_keys = ['order_id'],
    t.row_count = 24,
    t.has_primary_key = true,
    t.foreign_key_count = 2,
    t.unique_key_count = 0,
    t.updated_at = datetime();

MERGE (t:Table {name: 'price_lists'})
SET t.schema = 'public',
    t.full_name = 'public.price_lists',
    t.column_count = 3,
    t.primary_keys = ['price_list_id'],
    t.row_count = 3,
    t.has_primary_key = true,
    t.foreign_key_count = 0,
    t.unique_key_count = 0,
    t.updated_at = datetime();

MERGE (t:Table {name: 'product_prices'})
SET t.schema = 'public',
    t.full_name = 'public.product_prices',
    t.column_count = 3,
    t.primary_keys = ['product_id', 'price_list_id'],
    t.row_count = 36,
    t.has_primary_key = true,
    t.foreign_key_count = 2,
    t.unique_key_count = 0,
    t.updated_at = datetime();

MERGE (t:Table {name: 'products'})
SET t.schema = 'public',
    t.full_name = 'public.products',
    t.column_count = 3,
    t.primary_keys = ['product_id'],
    t.row_count = 12,
    t.has_primary_key = true,
    t.foreign_key_count = 0,
    t.unique_key_count = 1,
    t.updated_at = datetime();

MERGE (t:Table {name: 'warehouses'})
SET t.schema = 'public',
    t.full_name = 'public.warehouses',
    t.column_count = 4,
    t.primary_keys = ['warehouse_id'],
    t.row_count = 4,
    t.has_primary_key = true,
    t.foreign_key_count = 0,
    t.unique_key_count = 1,
    t.updated_at = datetime();

// 创建关系

// 关系: orders -> customers
MATCH (from:Table {name: 'orders'})
MATCH (to:Table {name: 'customers'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['customer_id'],
    r.to_fields = ['customer_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 1.0,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 1.0,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'customer_id = customer_id';

// 关系: order_items -> orders
MATCH (from:Table {name: 'order_items'})
MATCH (to:Table {name: 'orders'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['order_id'],
    r.to_fields = ['order_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 1.0,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 1.0,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'order_id = order_id';

// 关系: order_items -> price_lists
MATCH (from:Table {name: 'order_items'})
MATCH (to:Table {name: 'price_lists'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['price_list_id'],
    r.to_fields = ['price_list_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 1.0,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 1.0,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'price_list_id = price_list_id';

// 关系: order_items -> product_prices
MATCH (from:Table {name: 'order_items'})
MATCH (to:Table {name: 'product_prices'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['unit_price'],
    r.to_fields = ['unit_price'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 1.0,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 1.0,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'unit_price = unit_price';

// 关系: order_items -> product_prices
MATCH (from:Table {name: 'order_items'})
MATCH (to:Table {name: 'product_prices'})
MERGE (from)-[r:COMPOSITE_JOIN]->(to)
SET r.from_fields = ['product_id', 'price_list_id'],
    r.to_fields = ['product_id', 'price_list_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'composite',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 1.0,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 1.0,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.from_source = 'foreign_key',
    r.to_source = 'primary_key',
    r.column_pairs = '[{"from_column": "product_id", "to_column": "product_id", "name_similarity": 1.0, "name_source": "deterministic", "type_compatibility": 1.0}, {"from_column": "price_list_id", "to_column": "price_list_id", "name_similarity": 1.0, "name_source": "deterministic", "type_compatibility": 1.0}]',
    r.label = 'product_id = product_id AND price_list_id = price_list_id';

// 关系: order_items -> products
MATCH (from:Table {name: 'order_items'})
MATCH (to:Table {name: 'products'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['product_id'],
    r.to_fields = ['product_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 1.0,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 1.0,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'product_id = product_id';

// 关系: orders -> warehouses
MATCH (from:Table {name: 'orders'})
MATCH (to:Table {name: 'warehouses'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['warehouse_code'],
    r.to_fields = ['warehouse_code'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 1.0,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 1.0,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'warehouse_code = warehouse_code';

// 关系: orders -> warehouses
MATCH (from:Table {name: 'orders'})
MATCH (to:Table {name: 'warehouses'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['region_code'],
    r.to_fields = ['region_code'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 1.0,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 1.0,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'region_code = region_code';

// 关系: orders -> warehouses
MATCH (from:Table {name: 'orders'})
MATCH (to:Table {name: 'warehouses'})
MERGE (from)-[r:COMPOSITE_JOIN]->(to)
SET r.from_fields = ['warehouse_code', 'region_code'],
    r.to_fields = ['warehouse_code', 'region_code'],
    r.join_type = 'LEFT',
    r.relationship_type = 'composite',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 1.0,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 1.0,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.from_source = 'foreign_key',
    r.to_source = 'unique_key',
    r.column_pairs = '[{"from_column": "warehouse_code", "to_column": "warehouse_code", "name_similarity": 1.0, "name_source": "deterministic", "type_compatibility": 1.0}, {"from_column": "region_code", "to_column": "region_code", "name_similarity": 1.0, "name_source": "deterministic", "type_compatibility": 1.0}]',
    r.label = 'warehouse_code = warehouse_code AND region_code = region_code';

// 关系: product_prices -> price_lists
MATCH (from:Table {name: 'product_prices'})
MATCH (to:Table {name: 'price_lists'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['price_list_id'],
    r.to_fields = ['price_list_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 1.0,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 1.0,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'price_list_id = price_list_id';

// 关系: product_prices -> products
MATCH (from:Table {name: 'product_prices'})
MATCH (to:Table {name: 'products'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['product_id'],
    r.to_fields = ['product_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 1.0,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 1.0,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'product_id = product_id';

// 关系: product_prices -> order_items
MATCH (from:Table {name: 'product_prices'})
MATCH (to:Table {name: 'order_items'})
MERGE (from)-[r:COMPOSITE_JOIN]->(to)
SET r.from_fields = ['product_id', 'price_list_id'],
    r.to_fields = ['product_id', 'price_list_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'composite',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 0.55,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 0.96,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.from_source = 'primary_key',
    r.to_source = 'foreign_key',
    r.column_pairs = '[{"from_column": "product_id", "to_column": "product_id", "name_similarity": 1.0, "name_source": "deterministic", "type_compatibility": 1.0}, {"from_column": "price_list_id", "to_column": "price_list_id", "name_similarity": 1.0, "name_source": "deterministic", "type_compatibility": 1.0}]',
    r.label = 'product_id = product_id AND price_list_id = price_list_id';

// 关系: customers -> orders
MATCH (from:Table {name: 'customers'})
MATCH (to:Table {name: 'orders'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['customer_id'],
    r.to_fields = ['customer_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 0.42,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 0.94,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'customer_id = customer_id';

// 关系: orders -> order_items
MATCH (from:Table {name: 'orders'})
MATCH (to:Table {name: 'order_items'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['order_id'],
    r.to_fields = ['order_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 0.37,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 0.94,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'order_id = order_id';

// 关系: order_items -> product_prices
MATCH (from:Table {name: 'order_items'})
MATCH (to:Table {name: 'product_prices'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['product_id'],
    r.to_fields = ['product_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 0.33,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 0.93,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'product_id = product_id';

// 关系: products -> product_prices
MATCH (from:Table {name: 'products'})
MATCH (to:Table {name: 'product_prices'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['product_id'],
    r.to_fields = ['product_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 0.33,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 0.93,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'product_id = product_id';

// 关系: product_prices -> order_items
MATCH (from:Table {name: 'product_prices'})
MATCH (to:Table {name: 'order_items'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['product_id'],
    r.to_fields = ['product_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 0.18,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 0.92,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'product_id = product_id';

// 关系: products -> order_items
MATCH (from:Table {name: 'products'})
MATCH (to:Table {name: 'order_items'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['product_id'],
    r.to_fields = ['product_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 0.18,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 0.92,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'product_id = product_id';

// 关系: warehouses -> orders
MATCH (from:Table {name: 'warehouses'})
MATCH (to:Table {name: 'orders'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['warehouse_code'],
    r.to_fields = ['warehouse_code'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 0.17,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 0.92,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'warehouse_code = warehouse_code';

// 关系: warehouses -> orders
MATCH (from:Table {name: 'warehouses'})
MATCH (to:Table {name: 'orders'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['region_code'],
    r.to_fields = ['region_code'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 0.17,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 0.92,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'region_code = region_code';

// 关系: warehouses -> orders
MATCH (from:Table {name: 'warehouses'})
MATCH (to:Table {name: 'orders'})
MERGE (from)-[r:COMPOSITE_JOIN]->(to)
SET r.from_fields = ['warehouse_code', 'region_code'],
    r.to_fields = ['warehouse_code', 'region_code'],
    r.join_type = 'LEFT',
    r.relationship_type = 'composite',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 0.17,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 0.92,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.from_source = 'unique_key',
    r.to_source = 'foreign_key',
    r.column_pairs = '[{"from_column": "warehouse_code", "to_column": "warehouse_code", "name_similarity": 1.0, "name_source": "deterministic", "type_compatibility": 1.0}, {"from_column": "region_code", "to_column": "region_code", "name_similarity": 1.0, "name_source": "deterministic", "type_compatibility": 1.0}]',
    r.label = 'warehouse_code = warehouse_code AND region_code = region_code';

// 关系: order_items -> product_prices
MATCH (from:Table {name: 'order_items'})
MATCH (to:Table {name: 'product_prices'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['price_list_id'],
    r.to_fields = ['price_list_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 0.08,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 0.91,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'price_list_id = price_list_id';

// 关系: price_lists -> product_prices
MATCH (from:Table {name: 'price_lists'})
MATCH (to:Table {name: 'product_prices'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['price_list_id'],
    r.to_fields = ['price_list_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 1.0,
    r.uniqueness_score = 0.08,
    r.name_similarity = 1.0,
    r.type_compatibility = 1.0,
    r.composite_score = 0.91,
    r.confidence_level = 'high',
    r.source = 'auto_detected',
    r.verified = true,
    r.discovered_at = datetime(),
    r.label = 'price_list_id = price_list_id';

// 关系: customers -> orders
MATCH (from:Table {name: 'customers'})
MATCH (to:Table {name: 'orders'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['customer_id'],
    r.to_fields = ['order_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 0.42,
    r.uniqueness_score = 1.0,
    r.name_similarity = 0.75,
    r.type_compatibility = 1.0,
    r.composite_score = 0.87,
    r.confidence_level = 'medium',
    r.source = 'auto_detected',
    r.verified = false,
    r.discovered_at = datetime(),
    r.label = 'customer_id = order_id';

// 关系: order_items -> warehouses
MATCH (from:Table {name: 'order_items'})
MATCH (to:Table {name: 'warehouses'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['price_list_id'],
    r.to_fields = ['warehouse_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 0.75,
    r.uniqueness_score = 1.0,
    r.name_similarity = 0.65,
    r.type_compatibility = 1.0,
    r.composite_score = 0.87,
    r.confidence_level = 'medium',
    r.source = 'auto_detected',
    r.verified = false,
    r.discovered_at = datetime(),
    r.label = 'price_list_id = warehouse_id';

// 关系: price_lists -> warehouses
MATCH (from:Table {name: 'price_lists'})
MATCH (to:Table {name: 'warehouses'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['price_list_id'],
    r.to_fields = ['warehouse_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 0.75,
    r.uniqueness_score = 1.0,
    r.name_similarity = 0.65,
    r.type_compatibility = 1.0,
    r.composite_score = 0.87,
    r.confidence_level = 'medium',
    r.source = 'auto_detected',
    r.verified = false,
    r.discovered_at = datetime(),
    r.label = 'price_list_id = warehouse_id';

// 关系: product_prices -> warehouses
MATCH (from:Table {name: 'product_prices'})
MATCH (to:Table {name: 'warehouses'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['price_list_id'],
    r.to_fields = ['warehouse_id'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = 1.0,
    r.jaccard_index = 0.75,
    r.uniqueness_score = 1.0,
    r.name_similarity = 0.65,
    r.type_compatibility = 1.0,
    r.composite_score = 0.87,
    r.confidence_level = 'medium',
    r.source = 'auto_detected',
    r.verified = false,
    r.discovered_at = datetime(),
    r.label = 'price_list_id = warehouse_id';

// 统计信息
// ================================================
// 总关系数: 27
// 高置信度: 23
// 中置信度: 4
// 低置信度: 0
// 平均包含率: 100.00%
// 平均置信度: 94.81%
// ================================================