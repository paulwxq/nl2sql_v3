"""
LangGraph v1.0.x Human-in-the-Loop (HIL) Demo
演示场景：SQL查询审批流程，包含三个HIL审批点
"""
from typing import TypedDict
import uuid
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command


# ========== 1. 状态定义 ==========

class State(TypedDict, total=False):
    """流程状态"""
    question: str       # 输入：用户问题
    sql: str           # 生成的SQL
    email_body: str    # 生成的邮件
    schedule: str      # 建议的执行时间
    result: str        # 最终结果


# ========== 2. 模拟 LLM 调用 ==========

def mock_generate_sql(question: str) -> str:
    """模拟LLM生成SQL"""
    print("🤖 [LLM] 正在生成 SQL...")
    return f"SELECT * FROM orders WHERE status = 'error' ORDER BY created_at DESC LIMIT 10;"


def mock_generate_email(sql: str) -> str:
    """模拟LLM生成通知邮件"""
    print("🤖 [LLM] 正在生成通知邮件...")
    return (
        "各位好，\n\n"
        "为排查问题，系统将执行以下查询：\n\n"
        f"```sql\n{sql}\n```\n\n"
        "如有疑问请及时反馈。\n\n"
        "此致\n数据团队"
    )


def mock_generate_schedule() -> str:
    """模拟LLM建议执行时间"""
    print("🤖 [LLM] 正在分析最佳执行时间...")
    return "建议执行时间：今晚 23:00-23:30（业务低峰时段）"


# ========== 3. 图节点定义 ==========

def node_generate_and_review_sql(state: State) -> State:
    """节点1: 生成SQL并等待人工审核（HIL #1）"""
    print("\n📍 [节点] generate_and_review_sql")
    
    # 生成SQL
    sql = mock_generate_sql(state["question"])
    
    # interrupt() 会暂停执行，返回值来自 Command(resume=...)
    print("⏸️  [HIL #1] 暂停，等待人工审核 SQL...")
    human_response = interrupt({
        "type": "review_sql",
        "sql": sql
    })
    
    print(f"✅ 收到审核结果")
    
    # 检查审核结果
    if not human_response or not human_response.get("approved"):
        return {
            "sql": sql,
            "result": "❌ SQL 未通过审核，流程终止"
        }
    
    return {"sql": sql}


def node_generate_and_review_email(state: State) -> State:
    """节点2: 生成邮件并等待人工审核（HIL #2）"""
    print("\n📍 [节点] generate_and_review_email")
    
    # 如果前面失败，直接返回
    if state.get("result"):
        return state
    
    # 生成邮件
    email_body = mock_generate_email(state["sql"])
    
    # 暂停等待审核
    print("⏸️  [HIL #2] 暂停，等待人工审核邮件...")
    human_response = interrupt({
        "type": "review_email",
        "email_body": email_body
    })
    
    print(f"✅ 收到审核结果")
    
    if not human_response or not human_response.get("approved"):
        return {
            "email_body": email_body,
            "result": "❌ 邮件未通过审核，流程终止"
        }
    
    return {"email_body": email_body}


def node_generate_and_confirm_schedule(state: State) -> State:
    """节点3: 生成执行时间并等待人工确认（HIL #3）"""
    print("\n📍 [节点] generate_and_confirm_schedule")
    
    if state.get("result"):
        return state
    
    # 生成执行时间
    schedule = mock_generate_schedule()
    
    # 暂停等待确认
    print("⏸️  [HIL #3] 暂停，等待人工确认时间...")
    human_response = interrupt({
        "type": "confirm_schedule",
        "schedule": schedule
    })
    
    print(f"✅ 收到确认结果")
    
    if not human_response or not human_response.get("confirmed"):
        return {
            "schedule": schedule,
            "result": "❌ 时间未确认，流程终止"
        }
    
    return {"schedule": schedule}


def node_execute(state: State) -> State:
    """节点4: 执行SQL"""
    print("\n📍 [节点] execute")
    
    if state.get("result"):
        return state
    
    print("⚙️  执行 SQL...")
    print("📧 发送邮件...")
    print("✅ 完成！")
    
    result = (
        "\n✅ 流程执行成功！\n\n"
        f"【SQL】\n{state['sql']}\n\n"
        f"【邮件】\n{state.get('email_body', '')[:80]}...\n\n"
        f"【时间】\n{state['schedule']}"
    )
    
    return {"result": result}


# ========== 4. 构建图 ==========

def build_graph():
    """构建工作流图"""
    builder = StateGraph(State)
    
    # 添加节点
    builder.add_node("sql", node_generate_and_review_sql)
    builder.add_node("email", node_generate_and_review_email)
    builder.add_node("schedule", node_generate_and_confirm_schedule)
    builder.add_node("execute", node_execute)
    
    # 定义流程
    builder.add_edge(START, "sql")
    builder.add_edge("sql", "email")
    builder.add_edge("email", "schedule")
    builder.add_edge("schedule", "execute")
    builder.add_edge("execute", END)
    
    # 编译（必须有 checkpointer）
    memory = MemorySaver()
    return builder.compile(checkpointer=memory)


# ========== 5. 命令行交互 ==========

def run_cli():
    """运行CLI"""
    print("\n" + "=" * 70)
    print("  LangGraph v1.0.x HIL Demo - SQL 查询审批流程")
    print("=" * 70)
    
    app = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    
    # 获取用户问题
    question = input("\n请输入需求（例如：查询最近10个出错订单）：\n> ").strip()
    if not question:
        question = "查询最近10个出错订单"
        print(f"(使用默认：{question})")
    
    print("\n" + "=" * 70)
    print("  开始执行流程")
    print("=" * 70)
    
    try:
        def resume_with(command_payload):
            """封装 resume 调用，避免重复代码。"""
            return app.invoke(Command(resume=command_payload), config)

        # 第一次调用，执行到第一个 interrupt
        result = app.invoke({"question": question}, config)
        
        # 主循环：处理每个 interrupt
        while "__interrupt__" in result:
            # 获取中断信息
            interrupt_list = result["__interrupt__"]
            if not interrupt_list:
                break
            
            # Interrupt 对象有 .value 属性，不是字典
            interrupt_obj = interrupt_list[0]
            interrupt_data = interrupt_obj.value if hasattr(interrupt_obj, 'value') else interrupt_obj["value"]
            interrupt_type = interrupt_data.get("type")
            
            print("\n" + "=" * 70)
            print(f"  ⏸️  HIL 中断: {interrupt_type}")
            print("=" * 70)
            
            # 根据不同类型处理
            if interrupt_type == "review_sql":
                sql = interrupt_data.get("sql", "")
                print(f"\n✨ 生成的 SQL:\n")
                print("-" * 70)
                print(sql)
                print("-" * 70)
                
                ans = input("\n是否批准执行该 SQL？(yes/no): ").strip().lower()
                
                if ans == "yes":
                    result = resume_with({"approved": True})
                else:
                    result = resume_with({"approved": False})
            
            elif interrupt_type == "review_email":
                email_body = interrupt_data.get("email_body", "")
                print(f"\n📧 邮件内容:\n")
                print("-" * 70)
                print(email_body)
                print("-" * 70)
                
                ans = input("\n是否批准该邮件？(yes/no): ").strip().lower()
                
                if ans == "yes":
                    result = app.invoke(Command(resume={"approved": True}), config)
                else:
                    result = app.invoke(Command(resume={"approved": False}), config)
            
            elif interrupt_type == "confirm_schedule":
                schedule = interrupt_data.get("schedule", "")
                print(f"\n🕒 执行时间:\n")
                print("-" * 70)
                print(schedule)
                print("-" * 70)
                
                ans = input("\n是否确认该时间？(yes/no): ").strip().lower()
                
                if ans == "yes":
                    result = resume_with({"confirmed": True})
                else:
                    result = resume_with({"confirmed": False})
            
            else:
                print(f"\n⚠️ 未知中断类型: {interrupt_type}")
                break
        
        # 显示最终结果
        print("\n" + "=" * 70)
        print("  流程结束")
        print("=" * 70)
        
        final_message = result.get("result") or result.get("error")
        if final_message:
            print(f"{final_message}\n")
        else:
            print("流程已终止或未产生结果。\n")
    
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断\n")
    except Exception as e:
        print(f"\n\n❌ 错误: {e}\n")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_cli()
