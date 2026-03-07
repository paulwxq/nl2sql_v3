import re

with open('frontend/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# We need to refine the CSS for the sidebar buttons.
# Streamlit 1.30+ uses `st-emotion-cache-...` classes.
# The previous CSS was:
css_to_add = """
/* 侧边栏按钮（非主按钮）强制左对齐 */
[data-testid="stSidebar"] button:not([kind="primary"]) {
    text-align: left !important;
}

[data-testid="stSidebar"] button:not([kind="primary"]) > div[data-testid="stMarkdownContainer"] {
    width: 100% !important;
}

[data-testid="stSidebar"] button:not([kind="primary"]) > div[data-testid="stMarkdownContainer"] > p {
    text-align: left !important;
    width: 100% !important;
    margin: 0 !important;
    display: inline-block !important;
}
"""

print("Looking into alternative selectors...")
