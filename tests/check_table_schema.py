"""检查 LangGraph 表结构"""

import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

import psycopg
from src.services.langgraph_persistence.postgres import build_db_uri_from_config


def check_table_schema():
    """检查表结构"""
    db_uri = build_db_uri_from_config()
    
    with psycopg.connect(db_uri) as conn:
        with conn.cursor() as cur:
            # 检查 checkpoints 表结构
            print("checkpoints 表结构:")
            cur.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'langgraph' AND table_name = 'checkpoints'
                ORDER BY ordinal_position
            """)
            for row in cur.fetchall():
                print(f"  {row[0]:<30} {row[1]:<20} nullable={row[2]}")
            
            print("\ncheckpoint_writes 表结构:")
            cur.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'langgraph' AND table_name = 'checkpoint_writes'
                ORDER BY ordinal_position
            """)
            for row in cur.fetchall():
                print(f"  {row[0]:<30} {row[1]:<20} nullable={row[2]}")
            
            print("\ncheckpoint_blobs 表结构:")
            cur.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'langgraph' AND table_name = 'checkpoint_blobs'
                ORDER BY ordinal_position
            """)
            for row in cur.fetchall():
                print(f"  {row[0]:<30} {row[1]:<20} nullable={row[2]}")


if __name__ == "__main__":
    check_table_schema()

