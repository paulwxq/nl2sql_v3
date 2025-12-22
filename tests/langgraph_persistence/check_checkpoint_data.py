#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
import psycopg
from src.services.config_loader import get_config

config = get_config()
db = config['database']
conn_str = f"host={db['host']} port={db['port']} dbname={db['database']} user={db['user']} password={db['password']}"

with psycopg.connect(conn_str) as conn:
    with conn.cursor() as cur:
        cur.execute('SELECT thread_id, checkpoint_ns, checkpoint_id, metadata FROM langgraph.checkpoints LIMIT 1')
        row = cur.fetchone()
        if row:
            print('thread_id:', row[0])
            print('checkpoint_ns:', row[1])
            print('checkpoint_id:', row[2])
            print('metadata:', row[3])
        else:
            print('No data')

