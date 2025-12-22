#!/usr/bin/env python3
"""检查 store 表结构"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg
from src.services.config_loader import get_config

config = get_config()
db = config['database']
conn_str = f"host={db['host']} port={db['port']} dbname={db['database']} user={db['user']} password={db['password']}"

with psycopg.connect(conn_str) as conn:
    with conn.cursor() as cur:
        print("=== Store 表结构 ===")
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'langgraph' AND table_name = 'store' 
            ORDER BY ordinal_position
        """)
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1]}")
        
        print("\n=== Store 表数据示例 ===")
        cur.execute("SELECT * FROM langgraph.store LIMIT 3")
        cols = [desc[0] for desc in cur.description]
        print(f"  列名: {cols}")
        for row in cur.fetchall():
            print(f"  数据: {row}")

