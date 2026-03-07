import re

with open("frontend/app.py", "r", encoding="utf-8") as f:
    content = f.read()

helper_func = """
# ========== 辅助渲染函数 ==========

def render_sql_detail(detail: dict, prefix_key: str):
    \"\"\"渲染 SQL 和表格详情，并附加下载按钮\"\"\"
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
            
            # 添加显式的下载按钮
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 下载表格数据 (CSV)",
                data=csv,
                file_name="query_result.csv",
                mime="text/csv",
                key=f"dl_{prefix_key}_single"
            )
    else:
        # 多子查询模式
        sub_queries = detail.get("sub_queries", [])
        results = detail.get("execution_results", [])
        result_map = {
            r.get("sub_query_id"): r for r in results
        }
        for i, sq in enumerate(sub_queries):
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
                
                # 添加显式的下载按钮
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"📥 下载结果 (CSV)",
                    data=csv,
                    file_name=f"query_result_{sq_id}.csv",
                    mime="text/csv",
                    key=f"dl_{prefix_key}_multi_{i}"
                )
            elif sq.get("error"):
                st.warning(sq["error"])

# ========== 主区域 ==========
"""

content = content.replace("# ========== 主区域 ==========", helper_func)

# Replace the history loop body
old_hist_loop = """# 渲染消息历史
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
                            st.warning(sq["error"])"""

new_hist_loop = """# 渲染消息历史
for idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        # 当前轮消息有技术详情
        detail = msg.get("detail")
        if detail and msg["role"] == "assistant":
            with st.expander("查看执行的 SQL 与明细数据"):
                render_sql_detail(detail, f"hist_{idx}")"""

content = content.replace(old_hist_loop, new_hist_loop)

# Replace the new chat block body
old_new_chat = """                # 技术详情折叠面板
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
                                st.warning(sq["error"])"""

new_new_chat = """                # 技术详情折叠面板
                with st.expander("查看执行的 SQL 与明细数据"):
                    # 使用当前会话的总消息数作为唯一标识后缀
                    render_sql_detail(detail, f"new_{len(st.session_state.messages)}")"""

content = content.replace(old_new_chat, new_new_chat)

with open("frontend/app.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Patched app.py successfully!")
