"""检查 LangGraph 版本和 checkpointer config_specs"""

import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from langgraph.checkpoint.postgres import PostgresSaver
from src.services.langgraph_persistence.postgres import build_db_uri_from_config
import pkg_resources


def check_versions():
    """检查相关包的版本"""
    print("=" * 80)
    print("版本信息检查")
    print("=" * 80)
    
    try:
        lg_version = pkg_resources.get_distribution("langgraph").version
        print(f"\nlanggraph 版本: {lg_version}")
    except Exception as e:
        print(f"无法获取 langgraph 版本: {e}")
    
    try:
        lgcp_version = pkg_resources.get_distribution("langgraph-checkpoint-postgres").version
        print(f"langgraph-checkpoint-postgres 版本: {lgcp_version}")
    except Exception as e:
        print(f"无法获取 langgraph-checkpoint-postgres 版本: {e}")
    
    print("\n" + "=" * 80)
    print("PostgresSaver config_specs 检查")
    print("=" * 80)
    
    db_uri = build_db_uri_from_config()
    
    with PostgresSaver.from_conn_string(db_uri) as saver:
        print(f"\nPostgresSaver 类型: {type(saver)}")
        print(f"config_specs: {saver.config_specs}")
        
        if hasattr(saver, 'config_specs') and saver.config_specs:
            print("\nconfig_specs 详情:")
            for spec in saver.config_specs:
                print(f"  - {spec}")
                if hasattr(spec, '__dict__'):
                    for k, v in spec.__dict__.items():
                        print(f"      {k}: {v}")
        else:
            print("\n⚠️ config_specs 为空！")
            print("这可能意味着 PostgresSaver 不声明需要哪些 configurable 参数")
            print("LangGraph 可能不会自动传递 checkpoint_ns")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    check_versions()

