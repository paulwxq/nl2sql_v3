"""NL2SQL Streamlit 前端主入口"""

from dotenv import load_dotenv

load_dotenv()

import traceback

import pandas as pd
import requests
import streamlit as st

from api_client import NL2SQLApiClient

# ========== 页面配置 ==========

st.set_page_config(
    page_title="NL2SQL",
    page_icon="🔍",
    layout="wide",
)

# ========== 自定义深色主题 CSS ==========

st.markdown(
    """
<style>
/* ---- 全局主题与变量 ---- */
:root {
    --bg-primary: #0F111A;
    --bg-secondary: #161B22;
    --bg-card: #1E2230;
    --accent: #6366F1;
    --accent-dim: rgba(99, 102, 241, 0.15);
    --accent-border: rgba(99, 102, 241, 0.3);
    --text-primary: #F8FAFC;
    --text-secondary: #94A3B8;
    --border: rgba(255, 255, 255, 0.08);
    --radius: 12px;
}

/* 强制使用新的主背景色 */
.stApp {
    background-color: var(--bg-primary) !important;
}

/* 隐藏默认 Streamlit 页头 / 页脚 */
header[data-testid="stHeader"] {
    background: transparent !important;
}
footer { visibility: hidden; }
#MainMenu { visibility: hidden; }

/* ---- 侧边栏 ---- */
section[data-testid="stSidebar"] {
    background-color: var(--bg-secondary) !important;
    background-image: none !important;
    border-right: 1px solid var(--border) !important;
}

section[data-testid="stSidebar"] .stTitle {
    color: var(--text-primary) !important;
    font-weight: 800;
    letter-spacing: 0.5px;
    font-size: 1.5rem;
}

/* 侧边栏：新建对话主按钮 */
section[data-testid="stSidebar"] button[kind="primary"] {
    background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%) !important;
    border: none !important;
    border-radius: var(--radius) !important;
    color: #ffffff !important;
    font-weight: 600;
    transition: all 0.3s ease;
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2) !important;
}
section[data-testid="stSidebar"] button[kind="primary"]:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 16px rgba(99, 102, 241, 0.35) !important;
    filter: brightness(1.1);
}

/* 侧边栏：历史会话按钮（彻底还原为原生效果后再微微美化） */
/* 我们不强制覆盖 Streamlit 内部的层级，只调整边框和背景，保留它自带的对齐和点击涟漪 */
section[data-testid="stSidebar"] .stButton button:not([kind="primary"]) {
    background-color: transparent !important;
    border: 1px solid transparent !important;
    border-radius: var(--radius) !important;
    color: var(--text-secondary) !important;
    font-weight: 500 !important;
    transition: all 0.2s ease;
}
section[data-testid="stSidebar"] .stButton button:not([kind="primary"]):hover {
    background-color: rgba(255, 255, 255, 0.05) !important;
    border-color: rgba(255, 255, 255, 0.1) !important;
    color: var(--text-primary) !important;
}

/* 文本输入框 (Sidebar 用户名) */
input[type="text"] {
    background: var(--bg-primary) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text-primary) !important;
    padding: 0.5rem !important;
}
input[type="text"]:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 2px var(--accent-dim) !important;
}

/* ---- 聊天气泡 ---- */
div[data-testid="stChatMessage"] {
    border-radius: var(--radius) !important;
    padding: 1.2rem 1.5rem !important;
    margin-bottom: 1rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}

/* 用户消息 */
div[data-testid="stChatMessage"]:has(.stChatIconUser) {
    background: var(--accent-dim) !important;
    border: 1px solid var(--accent-border) !important;
}

/* 助手消息 */
div[data-testid="stChatMessage"]:has(.stChatIconAssistant) {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
}

/* ---- 底部输入框 ---- */
div[data-testid="stChatInput"] textarea {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 16px !important;
    color: var(--text-primary) !important;
    padding: 1rem !important;
    caret-color: var(--accent);
}
div[data-testid="stChatInput"] textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 2px var(--accent-dim) !important;
}

/* ---- 代码块 ---- */
pre {
    background: #090A0F !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
}

/* ---- Expander (折叠面板) ---- */
details[data-testid="stExpander"] {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    overflow: hidden;
}
details[data-testid="stExpander"] summary {
    color: var(--text-primary) !important;
    font-weight: 500;
    padding: 0.8rem 1rem !important;
}
details[data-testid="stExpander"] summary:hover {
    background: rgba(255, 255, 255, 0.02) !important;
    color: var(--accent) !important;
}

/* ---- 数据表格 ---- */
div[data-testid="stDataFrame"] {
    border-radius: 8px !important;
    border: 1px solid var(--border) !important;
    overflow: hidden;
}

/* ---- 分隔线 ---- */
hr {
    border-color: var(--border) !important;
}

/* ---- 布局控制（保持右侧60%居中） ---- */
div[data-testid="stMainBlockContainer"] {
    max-width: 60% !important;
    min-width: 60% !important;
    margin-left: auto !important;
    margin-right: auto !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
}

div[data-testid="stBottom"] > div {
    max-width: 60% !important;
    min-width: 60% !important;
    margin-left: auto !important;
    margin-right: auto !important;
}

/* ---- 滚动条美化 ---- */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: rgba(255, 255, 255, 0.2);
}

/* ---- Spinner (加载动画) ---- */
div[data-testid="stSpinner"] > div {
    border-top-color: var(--accent) !important;
}

/* ---- Caption (灰字) ---- */
.stCaption {
    color: var(--text-secondary) !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# ========== 初始化 ==========

client = NL2SQLApiClient()

if "user_id" not in st.session_state:
    st.session_state.user_id = "guest"
if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# ========== 侧边栏 ==========

with st.sidebar:
    st.title("NL2SQL")

    # 用户身份
    new_user_id = st.text_input("当前用户", value=st.session_state.user_id)
    if new_user_id != st.session_state.user_id:
        st.session_state.user_id = new_user_id
        st.session_state.thread_id = None
        st.session_state.messages = []
        print(f"切换用户: {new_user_id}")
        st.rerun()

    # 新建对话
    if st.button("+ 新建对话", type="primary", width="stretch"):
        st.session_state.thread_id = None
        st.session_state.messages = []
        print("新建对话")
        st.rerun()

    st.divider()

    # 历史会话列表
    st.subheader("历史会话")
    try:
        sessions = client.list_sessions(
            user_id=st.session_state.user_id
        )
        if sessions:
            for session in sessions:
                tid = session.get("thread_id", "")
                label = session.get("first_question", tid)
                if label and len(label) > 30:
                    label = label[:30] + "..."
                if st.button(
                    label or tid,
                    key=f"session_{tid}",
                    width="stretch",
                ):
                    if tid != st.session_state.thread_id:
                        st.session_state.thread_id = tid
                        # 加载历史对话
                        try:
                            turns = client.get_turns(thread_id=tid)
                            messages = []
                            for turn in turns:
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": turn.get("question", ""),
                                    }
                                )
                                messages.append(
                                    {
                                        "role": "assistant",
                                        "content": turn.get("answer", ""),
                                    }
                                )
                            st.session_state.messages = messages
                            print(
                                f"加载历史会话: {tid}, {len(turns)} 轮"
                            )
                        except Exception as e:
                            print(f"加载历史对话失败: {e}")
                            traceback.print_exc()
                            st.error(f"加载历史对话失败: {e}")
                        st.rerun()
        else:
            st.caption("暂无历史会话")
    except requests.RequestException:
        st.warning("无法连接后端服务")
    except Exception as e:
        print(f"获取会话列表失败: {e}")
        traceback.print_exc()
        st.warning(f"获取会话列表失败: {e}")

# ========== 主区域 ==========

# 顶部状态
if st.session_state.thread_id:
    st.caption(f"会话: {st.session_state.thread_id}")

# 渲染消息历史
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        # 当前轮消息有技术详情
        detail = msg.get("detail")
        if detail and msg["role"] == "assistant":
            with st.expander("查看执行的 SQL 与明细数据"):
                # 错误提示
                if detail.get("error"):
                    st.warning(f"错误: {detail['error']}")

                sql = detail.get("sql")
                if sql is not None:
                    # 单子查询模式
                    st.code(sql, language="sql")
                    results = detail.get("execution_results", [])
                    if results and results[0].get("success"):
                        r = results[0]
                        df = pd.DataFrame(
                            r.get("rows", []), columns=r.get("columns", [])
                        )
                        st.dataframe(df, width="stretch")
                else:
                    # 多子查询模式
                    sub_queries = detail.get("sub_queries", [])
                    results = detail.get("execution_results", [])
                    result_map = {
                        r.get("sub_query_id"): r for r in results
                    }
                    for sq in sub_queries:
                        sq_id = sq.get("sub_query_id", "")
                        sq_query = sq.get("query", "")
                        sq_sql = sq.get("validated_sql")
                        st.markdown(f"**{sq_query}**")
                        if sq_sql:
                            st.code(sq_sql, language="sql")
                        r = result_map.get(sq_id)
                        if r and r.get("success"):
                            df = pd.DataFrame(
                                r.get("rows", []),
                                columns=r.get("columns", []),
                            )
                            st.dataframe(df, width="stretch")
                        elif sq.get("error"):
                            st.warning(sq["error"])

# ========== 输入区 ==========

if prompt := st.chat_input("请输入您的数据查询需求..."):
    # 显示用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 调用后端
    with st.chat_message("assistant"):
        with st.spinner("正在分析您的问题..."):
            try:
                data = client.submit_query(
                    query=prompt,
                    user_id=st.session_state.user_id,
                    thread_id=st.session_state.thread_id,
                )

                # 回写 thread_id
                if data.get("thread_id"):
                    st.session_state.thread_id = data["thread_id"]

                summary = data.get("summary", "")
                st.markdown(summary)

                # 构建 detail
                detail = {
                    "sql": data.get("sql"),
                    "sub_queries": data.get("sub_queries", []),
                    "execution_results": data.get("execution_results", []),
                    "error": data.get("error"),
                }

                # 技术详情折叠面板
                with st.expander("查看执行的 SQL 与明细数据"):
                    if detail.get("error"):
                        st.warning(f"错误: {detail['error']}")

                    sql = detail.get("sql")
                    if sql is not None:
                        st.code(sql, language="sql")
                        results = detail.get("execution_results", [])
                        if results and results[0].get("success"):
                            r = results[0]
                            df = pd.DataFrame(
                                r.get("rows", []),
                                columns=r.get("columns", []),
                            )
                            st.dataframe(df, width="stretch")
                    else:
                        sub_queries = detail.get("sub_queries", [])
                        results = detail.get("execution_results", [])
                        result_map = {
                            r.get("sub_query_id"): r for r in results
                        }
                        for sq in sub_queries:
                            sq_id = sq.get("sub_query_id", "")
                            sq_query = sq.get("query", "")
                            sq_sql = sq.get("validated_sql")
                            st.markdown(f"**{sq_query}**")
                            if sq_sql:
                                st.code(sq_sql, language="sql")
                            r = result_map.get(sq_id)
                            if r and r.get("success"):
                                df = pd.DataFrame(
                                    r.get("rows", []),
                                    columns=r.get("columns", []),
                                )
                                st.dataframe(df, width="stretch")
                            elif sq.get("error"):
                                st.warning(sq["error"])

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": summary,
                        "detail": detail,
                    }
                )

                print(
                    f"查询完成: query_id={data.get('query_id')}, "
                    f"complexity={data.get('complexity')}"
                )

            except requests.RequestException:
                error_msg = "后端服务未启动，请检查 FastAPI 是否运行中。"
                st.error(error_msg)
                st.session_state.messages.append(
                    {"role": "assistant", "content": error_msg}
                )
                print("后端服务不可用")
            except Exception as e:
                error_msg = f"请求失败: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append(
                    {"role": "assistant", "content": error_msg}
                )
                print(f"查询异常: {e}")
                traceback.print_exc()
