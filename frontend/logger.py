"""Streamlit 前端独立日志"""

import logging
import os

os.makedirs("logs", exist_ok=True)

streamlit_logger = logging.getLogger("streamlit_frontend")
streamlit_logger.setLevel(logging.INFO)

if not streamlit_logger.handlers:
    fh = logging.FileHandler("logs/streamlit.log", encoding="utf-8")
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    streamlit_logger.addHandler(fh)
