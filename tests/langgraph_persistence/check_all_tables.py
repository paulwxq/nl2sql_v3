#!/usr/bin/env python3
"""检查所有 langgraph 表结构"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg
from src.services.config_loader import get_config

config = get_config()
db = config['database']
conn_str = f"host={db['host']} port={db['port']} dbname={db['database']} user={db['user']} password={db['password']}"

tables = ['checkpoints', 'checkpoint_blobs', 'checkpoint_writes', 'store']

with psycopg.connect(conn_str) as conn:
    with conn.cursor() as cur:
        for table in tables:
            print(f"\n{'='*60}")
            print(f"表: langgraph.{table}")
            print('='*60)
            cur.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_schema = 'langgraph' AND table_name = %s
                ORDER BY ordinal_position
            """, (table,))
            for row in cur.fetchall():
                nullable = "NULL" if row[2] == "YES" else "NOT NULL"
                print(f"  {row[0]:<30} {row[1]:<25} {nullable}")

