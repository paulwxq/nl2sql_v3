#!/usr/bin/env python3
"""
NL2SQL 命令行对话工具

用法:
    python scripts/nl2sql_cli.py "请对比一下9月份京东便利和全家这两个公司的销售金额"
    
    或交互模式:
    python scripts/nl2sql_cli.py
"""

import sys
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.modules.sql_generation.subgraph.create_subgraph import (
    run_sql_generation_subgraph,
)
from src.utils.logger import setup_logging_from_yaml

# 加载 YAML 日志配置（统一输出到 logs/sql_subgraph.log + 控制台）
setup_logging_from_yaml(str(project_root / "src" / "configs" / "logging.yaml"))

# CLI 使用 nl2sql 命名空间的子 logger，日志会聚合到 sql_subgraph.log
logger = logging.getLogger("nl2sql.cli")


def generate_query_id() -> str:
    """生成查询ID"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = str(uuid.uuid4())[:8]
    return f"q_{timestamp}_{short_uuid}"


def format_input(question: str, query_id: str = None) -> dict:
    """
    将自然语言问题包装成子图输入格式
    
    Args:
        question: 用户输入的自然语言问题
        query_id: 查询ID（可选）
        
    Returns:
        子图输入字典
    """
    if query_id is None:
        query_id = generate_query_id()
    
    input_data = {
        "query": question,
        "query_id": query_id,
        "dependencies_results": {},
        "user_query": question,
    }
    
    logger.info(f"[{query_id}] 输入问题: {question}")
    
    return input_data


def print_result(output: dict, query_id: str):
    """
    打印执行结果
    
    Args:
        output: 子图输出结果
        query_id: 查询ID
    """
    # 检查是否成功
    if output.get("validated_sql"):
        sql = output["validated_sql"]
        
        print("✅ 好的，我为您生成了SQL语句：\n")
        print("-" * 80)
        print(sql)
        print("-" * 80)
        
        # 输出统计信息
        iteration_count = output.get("iteration_count", 0)
        execution_time = output.get("execution_time", 0)
        print(f"\n📊 生成信息：迭代{iteration_count}次，耗时{execution_time:.2f}秒")
        
        # 输出警告（如果有）
        validation_history = output.get("validation_history", [])
        if validation_history:
            last_validation = validation_history[-1].get("result", {})
            warnings = last_validation.get("warnings", [])
            if warnings:
                print(f"\n⚠️  温馨提示：")
                for warning in warnings:
                    print(f"  • {warning}")
        
        print(f"\n💡 查询ID: {query_id}")
        
        logger.info(f"[{query_id}] SQL生成成功，耗时 {execution_time:.2f}秒")
        logger.info(f"[{query_id}] 生成的SQL:\n{sql}")
        
    else:
        # 失败
        error = output.get("error", "未知错误")
        error_type = output.get("error_type", "unknown")
        
        print("❌ 抱歉，SQL生成失败了。\n")
        print(f"错误原因: {error}")
        
        # 输出验证历史（如果有）
        validation_history = output.get("validation_history", [])
        if validation_history and len(validation_history) > 0:
            print(f"\n我尝试了 {len(validation_history)} 次：")
            for i, history_entry in enumerate(validation_history, 1):
                result = history_entry.get("result", {})
                if not result.get("valid"):
                    errors = result.get("errors", [])
                    if errors:
                        print(f"  第{i}次: {errors[0]}")
        
        print(f"\n💡 查询ID: {query_id} (可查看日志了解详情)")
        
        logger.error(f"[{query_id}] SQL生成失败: {error}")
    
    print()


def run_single_query(question: str, show_thinking: bool = False):
    """
    运行单个查询
    
    Args:
        question: 用户问题
        show_thinking: 是否显示"正在思考"提示
    """
    # 1. 包装输入
    query_id = generate_query_id()
    input_data = format_input(question, query_id)
    
    logger.info(f"[{query_id}] 开始执行NL2SQL转换")
    logger.debug(f"[{query_id}] 输入数据: {input_data}")
    
    # 2. 调用子图
    if not show_thinking:
        # 单次查询模式显示详细进度
        print(f"\n🔄 正在生成SQL...")
    
    start_time = time.time()
    
    try:
        output = run_sql_generation_subgraph(
            query=input_data["query"],
            query_id=input_data["query_id"],
            user_query=input_data["user_query"],
            dependencies_results=input_data["dependencies_results"],
        )
        
        elapsed_time = time.time() - start_time
        logger.info(f"[{query_id}] 子图执行完成，总耗时 {elapsed_time:.2f}秒")
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"[{query_id}] 子图执行异常: {e}", exc_info=True)
        
        output = {
            "validated_sql": None,
            "error": f"执行异常: {str(e)}",
            "error_type": "execution_error",
            "execution_time": elapsed_time,
        }
    
    # 3. 打印结果
    print_result(output, query_id)


def interactive_mode():
    """交互对话模式：持续对话，像ChatGPT一样"""
    print("\n" + "="*80)
    print("🤖 NL2SQL 对话助手")
    print("="*80)
    print("\n欢迎使用！我可以帮您把自然语言问题转换为SQL语句。")
    print("\n💡 提示：")
    print("  - 直接输入问题，按回车键提交")
    print("  - 输入 'clear' 清屏")
    print("  - 输入 'exit' 或 'quit' 退出")
    print("  - 按 Ctrl+C 也可以退出\n")
    print("-"*80 + "\n")
    
    logger.info("进入对话模式")
    
    conversation_count = 0
    
    while True:
        try:
            # 获取用户输入
            question = input("👤 您: ").strip()
            
            # 清屏命令
            if question.lower() in ["clear", "cls", "清屏"]:
                import os
                os.system('cls' if os.name == 'nt' else 'clear')
                print("🤖 NL2SQL 对话助手")
                print("-"*80 + "\n")
                continue
            
            # 退出命令
            if question.lower() in ["exit", "quit", "q", "bye", "退出", "再见"]:
                print("\n👋 再见！感谢使用~")
                logger.info(f"退出对话模式，共对话 {conversation_count} 轮")
                break
            
            # 空输入
            if not question:
                print("💭 您还没有输入问题哦~\n")
                continue
            
            conversation_count += 1
            
            # 显示思考提示
            print(f"\n🤖 助手: 让我想想...\n")
            
            # 执行查询
            run_single_query(question)
            
            # 询问是否继续
            print("💬 您可以继续提问，或输入 'exit' 退出\n")
            
        except KeyboardInterrupt:
            print("\n\n👋 再见！感谢使用~")
            logger.info(f"用户中断，退出对话模式，共对话 {conversation_count} 轮")
            break
        except Exception as e:
            logger.error(f"对话模式异常: {e}", exc_info=True)
            print(f"\n❌ 抱歉，出现了一些问题: {e}")
            print("💬 您可以继续提问，或输入 'exit' 退出\n")


def main():
    """主函数"""
    logger.info("="*80)
    logger.info("NL2SQL CLI 启动")
    logger.info("="*80)
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        # 单次查询模式（带参数时使用）
        question = " ".join(sys.argv[1:])
        logger.info("单次查询模式")
        
        print("\n" + "="*80)
        print("🤖 NL2SQL 单次查询")
        print("="*80)
        
        run_single_query(question, show_thinking=False)
        
        print("="*80 + "\n")
    else:
        # 默认：交互对话模式
        interactive_mode()


if __name__ == "__main__":
    main()

