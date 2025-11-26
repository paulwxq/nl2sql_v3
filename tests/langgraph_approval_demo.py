"""
LangGraph v1.0.3 多人工审批节点工作流 Demo
演示如何使用 interrupt() 实现命令行交互式审批流程
"""

from typing import TypedDict, List, Dict
from datetime import datetime
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command


# 状态定义
class WorkflowState(TypedDict):
    """工作流状态结构"""
    task: str  # 任务描述
    approval_history: List[Dict]  # 审批历史
    process_results: List[Dict]  # 处理结果
    current_step: int  # 当前步骤
    status: str  # 工作流状态 (pending/approved/rejected/completed)
    final_summary: str  # 最终总结


# Mock LLM 函数
def mock_llm_call(decision: str, step: int, task: str, comment: str = "") -> Dict:
    """
    模拟 LLM 调用，根据审批结果返回预设响应
    """
    if decision == "approve":
        responses = [
            f"已审核任务：{task}，审批通过，开始处理...",
            f"根据审批结果，已完成步骤 {step} 的处理，结果符合预期。",
            f"最终处理完成，所有审批已通过，任务 '{task}' 已成功完成。"
        ]
        return {
            "response": responses[min(step - 1, len(responses) - 1)],
            "confidence": 0.95,
            "status": "success"
        }
    elif decision == "reject":
        return {
            "response": f"审批被拒绝，原因：{comment if comment else '未提供原因'}",
            "confidence": 1.0,
            "status": "rejected"
        }
    else:  # modify
        return {
            "response": f"根据修改建议 '{comment}'，已调整处理方案，重新处理中...",
            "confidence": 0.90,
            "status": "modified"
        }


# 节点函数定义
def start_node(state: WorkflowState) -> WorkflowState:
    """开始节点：初始化工作流状态"""
    return {
        "task": state.get("task", ""),
        "approval_history": [],
        "process_results": [],
        "current_step": 0,
        "status": "pending",
        "final_summary": ""
    }


def approval_1_node(state: WorkflowState) -> WorkflowState:
    """审批节点 1：第一个审批点"""
    # 准备审批信息
    approval_info = {
        "step": 1,
        "task": state["task"],
        "message": f"请审批步骤 1 的任务：{state['task']}"
    }
    
    # 调用 interrupt 暂停执行，返回值是用户输入
    user_input = interrupt(approval_info)
    
    # 如果没有输入，使用默认值
    if not user_input:
        user_input = {}
    
    # 更新审批历史
    updated_history = state.get("approval_history", [])
    updated_history.append({
        "step": 1,
        "decision": user_input.get("decision", "unknown"),
        "comment": user_input.get("comment", ""),
        "timestamp": datetime.now().isoformat()
    })
    
    return {
        "approval_history": updated_history,
        "current_step": 1
    }


def process_1_node(state: WorkflowState) -> WorkflowState:
    """处理节点 1：根据第一个审批结果进行处理"""
    approval = state["approval_history"][0] if state["approval_history"] else {}
    decision = approval.get("decision", "unknown")
    comment = approval.get("comment", "")
    
    # Mock LLM 调用
    result = mock_llm_call(decision, 1, state["task"], comment)
    
    # 更新处理结果
    updated_results = state.get("process_results", [])
    updated_results.append(result)
    
    return {
        "process_results": updated_results,
        "status": "approved" if decision == "approve" else state.get("status", "pending")
    }


def approval_2_node(state: WorkflowState) -> WorkflowState:
    """审批节点 2：第二个审批点"""
    # 准备审批信息，包含第一个处理结果
    process_result = state["process_results"][0] if state["process_results"] else {}
    approval_info = {
        "step": 2,
        "task": state["task"],
        "previous_result": process_result.get("response", ""),
        "message": f"请审批步骤 2，处理结果：{process_result.get('response', '无')}"
    }
    
    # 调用 interrupt 暂停执行，返回值是用户输入
    user_input = interrupt(approval_info)
    
    # 如果没有输入，使用默认值
    if not user_input:
        user_input = {}
    
    # 更新审批历史
    updated_history = state.get("approval_history", [])
    updated_history.append({
        "step": 2,
        "decision": user_input.get("decision", "unknown"),
        "comment": user_input.get("comment", ""),
        "timestamp": datetime.now().isoformat()
    })
    
    return {
        "approval_history": updated_history,
        "current_step": 2
    }


def process_2_node(state: WorkflowState) -> WorkflowState:
    """处理节点 2：根据第二个审批结果进行处理"""
    approval = state["approval_history"][1] if len(state["approval_history"]) > 1 else {}
    decision = approval.get("decision", "unknown")
    comment = approval.get("comment", "")
    
    # Mock LLM 调用
    result = mock_llm_call(decision, 2, state["task"], comment)
    
    # 更新处理结果
    updated_results = state.get("process_results", [])
    updated_results.append(result)
    
    return {
        "process_results": updated_results,
        "status": "approved" if decision == "approve" else state.get("status", "pending")
    }


def approval_3_node(state: WorkflowState) -> WorkflowState:
    """审批节点 3：第三个审批点（最终审批）"""
    # 准备审批信息，包含所有处理结果
    all_results = state.get("process_results", [])
    approval_info = {
        "step": 3,
        "task": state["task"],
        "all_results": [r.get("response", "") for r in all_results],
        "message": f"最终审批步骤 3，所有处理结果：{', '.join([r.get('response', '') for r in all_results])}"
    }
    
    # 调用 interrupt 暂停执行，返回值是用户输入
    user_input = interrupt(approval_info)
    
    # 如果没有输入，使用默认值
    if not user_input:
        user_input = {}
    
    # 更新审批历史
    updated_history = state.get("approval_history", [])
    updated_history.append({
        "step": 3,
        "decision": user_input.get("decision", "unknown"),
        "comment": user_input.get("comment", ""),
        "timestamp": datetime.now().isoformat()
    })
    
    return {
        "approval_history": updated_history,
        "current_step": 3
    }


def end_node(state: WorkflowState) -> WorkflowState:
    """结束节点：汇总所有审批结果，完成工作流"""
    summary_parts = [
        f"任务：{state['task']}",
        f"审批步骤数：{len(state['approval_history'])}",
        "审批历史："
    ]
    
    for approval in state["approval_history"]:
        summary_parts.append(
            f"  步骤 {approval['step']}: {approval['decision']} - {approval.get('comment', '无备注')}"
        )
    
    summary_parts.append("处理结果：")
    for i, result in enumerate(state.get("process_results", []), 1):
        summary_parts.append(f"  结果 {i}: {result.get('response', '无')}")
    
    final_summary = "\n".join(summary_parts)
    
    return {
        "status": "completed",
        "final_summary": final_summary
    }


# 命令行交互函数
def get_user_approval_input(approval_info: Dict) -> Dict:
    """获取用户审批输入"""
    print(f"\n=== 审批节点 {approval_info.get('step', '?')} ===")
    print(f"任务: {approval_info.get('task', '')}")
    
    if "previous_result" in approval_info:
        print(f"处理结果: {approval_info['previous_result']}")
    elif "all_results" in approval_info:
        print("所有处理结果:")
        for i, result in enumerate(approval_info["all_results"], 1):
            print(f"  {i}. {result}")
    
    print(f"\n{approval_info.get('message', '请审批')}")
    
    while True:
        decision = input("请审批 (approve/reject/modify): ").strip().lower()
        if decision in ["approve", "reject", "modify"]:
            break
        print("无效输入，请输入 approve、reject 或 modify")
    
    comment = ""
    if decision == "modify":
        comment = input("请输入修改建议: ").strip()
    elif decision == "reject":
        comment = input("请输入拒绝原因（可选）: ").strip()
    
    return {
        "decision": decision,
        "comment": comment
    }


# 构建工作流图
def build_workflow():
    """构建并编译工作流图"""
    # 创建检查点保存器
    checkpointer = MemorySaver()
    
    # 构建工作流图
    workflow = StateGraph(WorkflowState)
    
    # 添加节点
    workflow.add_node("start", start_node)
    workflow.add_node("approval_1", approval_1_node)
    workflow.add_node("process_1", process_1_node)
    workflow.add_node("approval_2", approval_2_node)
    workflow.add_node("process_2", process_2_node)
    workflow.add_node("approval_3", approval_3_node)
    workflow.add_node("end", end_node)
    
    # 定义边
    workflow.add_edge(START, "start")
    workflow.add_edge("start", "approval_1")
    workflow.add_edge("approval_1", "process_1")
    workflow.add_edge("process_1", "approval_2")
    workflow.add_edge("approval_2", "process_2")
    workflow.add_edge("process_2", "approval_3")
    workflow.add_edge("approval_3", "end")
    workflow.add_edge("end", END)
    
    # 编译工作流，配置 checkpointer 以支持 interrupt
    app = workflow.compile(checkpointer=checkpointer)
    
    return app


# 主程序
def main():
    """主程序入口"""
    print("=" * 50)
    print("LangGraph 多人工审批节点工作流 Demo")
    print("=" * 50)
    
    # 获取初始任务输入
    task = input("\n请输入任务描述: ").strip()
    if not task:
        task = "默认任务"
        print(f"使用默认任务: {task}")
    
    # 构建工作流
    app = build_workflow()
    
    # 初始化状态
    initial_state: WorkflowState = {
        "task": task,
        "approval_history": [],
        "process_results": [],
        "current_step": 0,
        "status": "pending",
        "final_summary": ""
    }
    
    # 配置
    config = {"configurable": {"thread_id": "thread-1"}}
    
    try:
        # 第一次调用，执行到第一个 interrupt
        result = app.invoke(initial_state, config)
        
        # 主循环：处理每个 interrupt
        while "__interrupt__" in result:
            # 获取中断信息
            interrupt_list = result["__interrupt__"]
            if not interrupt_list:
                break
            
            # 获取中断数据
            interrupt_obj = interrupt_list[0]
            interrupt_data = interrupt_obj.value if hasattr(interrupt_obj, 'value') else interrupt_obj.get("value", {})
            
            # 获取用户输入
            user_input = get_user_approval_input(interrupt_data)
            
            # 通过 Command 恢复执行
            result = app.invoke(Command(resume=user_input), config)
        
        # 显示最终结果
        print("\n" + "=" * 50)
        print("工作流完成！")
        print("=" * 50)
        print(result.get("final_summary", "未生成总结"))
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断\n")
    except Exception as e:
        print(f"\n\n❌ 错误: {e}\n")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

