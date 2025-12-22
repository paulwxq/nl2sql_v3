#!/usr/bin/env python3
"""测试非法 thread_id 时是否记录 warning"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s - %(name)s - %(message)s')

from src.modules.nl2sql_father.state import create_initial_state

print('=== 测试非法 thread_id ===')
state = create_initial_state('测试问题', thread_id='invalid-thread-id')
print(f"actual_thread_id: {state['thread_id']}")
print(f"actual_user_id: {state['user_id']}")

