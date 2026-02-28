from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from src.services.config_loader import get_config
from src.services.langgraph_persistence.postgres import build_db_uri_from_config

TARGET_THREAD_ID = "guest:20260227T092740986Z"


def mask_uri(uri: str) -> str:
    parts = urlsplit(uri)
    netloc = parts.netloc
    if "@" in netloc:
        auth, host = netloc.rsplit("@", 1)
        if ":" in auth:
            user, _ = auth.split(":", 1)
            netloc = f"{user}:***@{host}"
        else:
            netloc = f"***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def find_table_schema(cur, table_name: str) -> str | None:
    cur.execute(
        """
        SELECT table_schema
        FROM information_schema.tables
        WHERE table_name = %s
        ORDER BY CASE WHEN table_schema='public' THEN 0 ELSE 1 END, table_schema
        LIMIT 1
        """,
        (table_name,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def print_checkpoint_stats(cur, schema_name: str):
    print(f"\n=== checkpoint stats ({schema_name}.checkpoints) ===")

    cur.execute(
        sql.SQL(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'checkpoints'
            ORDER BY ordinal_position
            """
        ),
        (schema_name,),
    )
    cols = [r[0] for r in cur.fetchall()]
    print("columns:", cols)

    cur.execute(sql.SQL("SELECT count(*) FROM {}.checkpoints").format(sql.Identifier(schema_name)))
    total = cur.fetchone()[0]
    print("total_rows:", total)

    cur.execute(
        sql.SQL(
            """
            SELECT checkpoint_ns, count(*)::bigint
            FROM {}.checkpoints
            GROUP BY checkpoint_ns
            ORDER BY count(*) DESC, checkpoint_ns
            LIMIT 20
            """
        ).format(sql.Identifier(schema_name))
    )
    print("by checkpoint_ns:")
    for row in cur.fetchall():
        print("  ", row)

    cur.execute(
        sql.SQL(
            """
            SELECT thread_id, checkpoint_ns, count(*)::bigint
            FROM {}.checkpoints
            WHERE thread_id = %s
            GROUP BY thread_id, checkpoint_ns
            ORDER BY checkpoint_ns
            """
        ).format(sql.Identifier(schema_name)),
        (TARGET_THREAD_ID,),
    )
    rows = cur.fetchall()
    print(f"rows for thread_id={TARGET_THREAD_ID}:")
    if rows:
        for r in rows:
            print("  ", r)
    else:
        print("   (none)")


def print_store_stats(cur, schema_name: str):
    print(f"\n=== store stats ({schema_name}.store) ===")

    cur.execute(sql.SQL("SELECT count(*) FROM {}.store").format(sql.Identifier(schema_name)))
    total = cur.fetchone()[0]
    print("total_rows:", total)

    cur.execute(
        sql.SQL(
            """
            SELECT prefix, key, updated_at
            FROM {}.store
            WHERE prefix = %s
            ORDER BY updated_at DESC
            LIMIT 10
            """
        ).format(sql.Identifier(schema_name)),
        (f"chat_history.{TARGET_THREAD_ID}",),
    )
    rows = cur.fetchall()
    print(f"rows for prefix=chat_history.{TARGET_THREAD_ID}:")
    if rows:
        for r in rows:
            print("  ", r)
    else:
        print("   (none)")


def main() -> int:
    cfg = get_config()
    lp = cfg.get("langgraph_persistence", {})
    db_cfg = lp.get("database", {})

    print("=== Effective Config ===")
    print(json.dumps(
        {
            "langgraph_persistence.enabled": lp.get("enabled"),
            "checkpoint.enabled": lp.get("checkpoint", {}).get("enabled"),
            "store.enabled": lp.get("store", {}).get("enabled"),
            "database.use_global_config": db_cfg.get("use_global_config"),
            "database.schema": db_cfg.get("schema"),
            "database.db_uri_exists": bool(db_cfg.get("db_uri")),
        },
        ensure_ascii=False,
        indent=2,
    ))

    db_uri = build_db_uri_from_config()
    print("resolved_db_uri:", mask_uri(db_uri))

    try:
        with psycopg.connect(db_uri) as conn:
            with conn.cursor() as cur:
                print("\n=== DB Probe ===")
                cur.execute("SHOW search_path;")
                print("search_path:", cur.fetchone()[0])
                cur.execute("SELECT current_database(), current_schema(), current_user;")
                print("current:", cur.fetchone())

                cp_schema = find_table_schema(cur, "checkpoints")
                st_schema = find_table_schema(cur, "store")
                print("detected checkpoints schema:", cp_schema)
                print("detected store schema:", st_schema)

                if cp_schema:
                    print_checkpoint_stats(cur, cp_schema)
                if st_schema:
                    print_store_stats(cur, st_schema)

    except Exception as e:
        print("connect_error:", type(e).__name__, str(e))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
