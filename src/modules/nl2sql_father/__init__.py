"""NL2SQL 父图模块

此模块实现 NL2SQL 系统的父图（编排层），负责：
1. Router：判定问题复杂度（simple/complex）
2. Simple Planner：参数准备（Fast Path）
3. SQL执行：调用数据库执行SQL
4. Summarizer：生成自然语言总结

Phase 1 实现 Fast Path（简单问题处理路径）。
"""

__version__ = "0.1.0"
