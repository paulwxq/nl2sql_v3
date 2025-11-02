create table system.sql_embedding
(
    id    serial primary key,
    type	varchar(64),
    embedding     vector,
    document      varchar,
    cmetadata     jsonb,
    updated_at    timestamp with time zone default now()
);

create table system.dim_value_index
(
    dim_table  text,
    dim_col    text,
    key_col    text,
    key_value  text,
    value_text text,
    value_norm text,
    updated_at timestamp with time zone default now()
);

alter table system.dim_value_index
    owner to postgres;

create index idx_dim_value_index_value_norm_trgm
    on system.dim_value_index using gin (value_norm public.gin_trgm_ops);

create table system.sem_object_vec
(
    object_type    text         not null
        constraint sem_object_vec_object_type_check
            check (object_type = ANY (ARRAY ['table'::text, 'column'::text, 'metric'::text])),
    object_id      text         not null,
    parent_id      text generated always as (
        CASE
            WHEN (object_type = 'column'::text) THEN ((split_part(object_id, '.'::text, 1) || '.'::text) ||
                                                      split_part(object_id, '.'::text, 2))
            WHEN (object_type = 'table'::text) THEN object_id
            ELSE NULL::text
            END) stored,
    text_raw       text         not null,
    lang           text,
    grain_hint     text,
    time_col_hint  text,
    boost          real                     default 1.0,
    attrs          jsonb,
    updated_at     timestamp with time zone default now(),
    embedding      vector(1024) not null,
    table_category varchar(64),
    primary key (object_type, object_id)
);

alter table system.sem_object_vec
    owner to postgres;

create index idx_sem_object_vec_type_parent
    on system.sem_object_vec (object_type, parent_id);

create index idx_sem_object_vec_emb_hnsw
    on system.sem_object_vec using hnsw (embedding public.vector_cosine_ops);

