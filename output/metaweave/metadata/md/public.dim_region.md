# public.dim_region（地区维表：省/市/区（含各级名称与ID））
## 字段列表：
- region_id (integer(32)) - 区（县）ID（主键） [示例: 440106, 440104]
- region_name (character varying(100)) - 区（县）名称 [示例: 天河区, 越秀区]
- city_id (integer(32)) - 城市ID [示例: 4401, 4401]
- city_name (character varying(100)) - 城市名称 [示例: 广州市, 广州市]
- province_id (integer(32)) - 省份ID [示例: 44, 44]
- province_name (character varying(100)) - 省份名称 [示例: 广东省, 广东省]