#!/usr/bin/env python3
"""测试无 checkpointer 时传入 configurable 是否报错"""
from langgraph.graph import StateGraph

def node(state):
    return state

# 创建一个简单的图（无 checkpointer）
graph = StateGraph(dict)
graph.add_node('a', node)
graph.set_entry_point('a')
graph.set_finish_point('a')
app = graph.compile()  # 无 checkpointer

# 尝试传入 configurable
config = {'configurable': {'thread_id': 'test', 'checkpoint_ns': 'test_ns'}}
try:
    result = app.invoke({'data': 1}, config=config)
    print('Success:', result)
except Exception as e:
    print('Error:', type(e).__name__, str(e)[:300])

