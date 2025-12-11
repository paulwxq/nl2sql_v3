把表结构加载到milvus，库名：nl2sql，表名：table_schema_embedding

1.下面是这个表在postgresql的定义信息，请把它转成Milvus表的定义，你可以参考
create table table_schema_embedding
(
    object_type    varchar(64)        not null   # column / table ,
    object_id      varchar(256),      # 字段名：public.fact_store_sales_day.amount 或者 表名：public.dim_company
    parent_id    varchar(256),       # 表名：如果是column对象，这个是它的表名，如果table对象，这里也是表名，与object_id相同。
    object_desc     text         not null,   # 表的定义信息，或者字段名的注释。
    embedding      vector(1024) not null,  # 是对object_value的 ebedding 的结果 ，在milvus类型为FLOAT_VECTOR(1024)
    time_col_hint  text,    # 指出表中的日期时间字段，需要从json_llm中获取
    table_category   varchar(64),   # 需要从json_llm获取
    updated_at     timestamp with time zone default now(),  # 在milvus中转为INT64 类型。
);

2.需要读取md目录下的md 和 json.
3.读取md时，需要读取两部分内容：
   a.) 每个表对应的md文件，它的内容包括表的定义信息。整个内容座位一行要写入到milvus表 nl2sql.table_schema_embedding, object_type是table,object_id是带有schema的表名，parent_id仍然是当前表名，object_desc 就是这个表对应的md文件的内容。embedding 就是object_desc使用embedding模型之后的结果。time_col_hint，是这个表中哪些字段是日期时间类型，这个信息可以从这个表对应的json_llm文件中获取。table_category也是从这个表对应的json_llm文件中获取。
   b.) 每个表对应的md文件中的字段的描述，它仅包含每个字段的信息。这个字段的内容也作为一行写入到milvus表 nl2sql.table_schema_embedding, object_type是 column,object_id是带有schema的表名+字段名，比如schema.table.column，parent_id是当前字段所在的表名，object_desc 就是这个字段在md文件的注释的内容。embedding 就是object_desc使用embedding模型之后的结果。column类型的记录 time_col_hint 和 table_category都留空。
4.读取json_llm目录下的json: 对于table类型，读取它的table_category属性（table_profile.table_category）：dim/fact/bridge等。对于 time_col_hint，则遍历json中的字段属性(column_profiles.column_name.data_type)，data_type 是date/time/datetime/timestampe等日期时间型的，识别出来这个字段名称，把它写入到这条记录的 time_col_hint字段中。
