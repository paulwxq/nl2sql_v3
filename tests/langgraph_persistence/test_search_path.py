#!/usr/bin/env python3
"""验证 search_path 是否生效"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.langgraph_persistence.postgres import build_db_uri_from_config
import psycopg

uri = build_db_uri_from_config()
print('URI:', uri)

with psycopg.connect(uri) as conn:
    with conn.cursor() as cur:
        cur.execute('SHOW search_path')
        print('search_path:', cur.fetchone()[0])

