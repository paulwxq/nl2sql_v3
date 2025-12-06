"""LLM 异步性能对比测试

对比 LangChain ainvoke 和 DashScope AioGeneration 的性能。
测试 78 个表对的完整场景，真实 API 调用。
"""

import asyncio
import json
import os
import sys
import time
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from http import HTTPStatus

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
import yaml
from langchain_core.messages import HumanMessage
from langchain_community.chat_models.tongyi import ChatTongyi
from dashscope import AioGeneration


# LLM 提示词模板（复用现有模板）
RELATIONSHIP_DISCOVERY_PROMPT = """
你是一个数据库关系分析专家。请分析以下两个表以及表中的采样数据，判断它们之间是否存在关联关系。

## 表 1: {table1_name}
```json
{table1_json}
```

## 表 2: {table2_name}
```json
{table2_json}
```

## 任务
分析这两个表之间可能的关联关系（外键关系）。考虑以下因素：
1. 字段名相同或相似
2. 数据类型兼容
3. 字段注释的语义关联
4. 样例数据的值域匹配
5. 复合键的可能性（多个字段组合）

## 输出格式
返回 JSON 格式。如果存在关联，返回关联信息；如果没有关联，返回空数组。

### 单列关联示例
```json
{{
  "relationships": [
    {{
      "type": "single_column",
      "from_table": {{"schema": "public", "table": "dim_region"}},
      "to_table": {{"schema": "public", "table": "dim_store"}},
      "from_column": "region_id",
      "to_column": "region_id"
    }}
  ]
}}
```

### 多列关联示例（type 为 composite，字段用数组）
```json
{{
  "relationships": [
    {{
      "type": "composite",
      "from_table": {{"schema": "public", "table": "equipment_config"}},
      "to_table": {{"schema": "public", "table": "maintenance_work_order"}},
      "from_columns": ["equipment_id", "config_version"],
      "to_columns": ["equipment_id", "config_version"]
    }}
  ]
}}
```

### 无关联
```json
{{
  "relationships": []
}}
```

请只返回 JSON，不要包含其他内容。
"""


class TestConfig:
    """测试配置"""
    def __init__(self):
        # 加载 .env 文件
        load_dotenv()
        
        # 加载 YAML 配置
        config_path = project_root / "configs/metaweave/metadata_config.yaml"
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 提取 LLM 配置
        llm_config = config.get('llm', {})
        qwen_config = llm_config.get('providers', {}).get('qwen', {})
        
        self.api_key = os.getenv('DASHSCOPE_API_KEY')
        self.model = qwen_config.get('model', 'qwen-plus')
        self.temperature = qwen_config.get('temperature', 0.3)
        self.max_tokens = qwen_config.get('max_tokens', 500)
        self.timeout = qwen_config.get('timeout', 60)
        self.concurrent_limit = 10  # 并发限制
        
        # 验证 API Key
        if not self.api_key:
            raise ValueError("DASHSCOPE_API_KEY not found in .env file")


def load_json_llm_files() -> Dict[str, Dict]:
    """加载 json_llm 目录下的所有表文件"""
    json_llm_dir = project_root / "output/metaweave/metadata/json_llm"
    tables = {}
    
    for json_file in json_llm_dir.glob("*.json"):
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            table_info = data.get("table_info", {})
            schema = table_info.get("schema_name", "public")
            table = table_info.get("table_name", json_file.stem)
            full_name = f"{schema}.{table}"
            tables[full_name] = data
    
    return tables


def generate_table_pairs(tables: Dict[str, Dict]) -> List[Tuple[str, str]]:
    """生成所有表对组合"""
    table_names = list(tables.keys())
    return list(combinations(table_names, 2))


def build_prompt(table1: Dict, table2: Dict) -> str:
    """构建 LLM prompt"""
    table1_info = table1.get("table_info", {})
    table2_info = table2.get("table_info", {})
    
    table1_name = f"{table1_info.get('schema_name', 'public')}.{table1_info.get('table_name', 'unknown')}"
    table2_name = f"{table2_info.get('schema_name', 'public')}.{table2_info.get('table_name', 'unknown')}"
    
    return RELATIONSHIP_DISCOVERY_PROMPT.format(
        table1_name=table1_name,
        table1_json=json.dumps(table1, ensure_ascii=False, indent=2),
        table2_name=table2_name,
        table2_json=json.dumps(table2, ensure_ascii=False, indent=2),
    )


class TestResult:
    """测试结果"""
    def __init__(self, name: str):
        self.name = name
        self.total_time = 0.0
        self.success_count = 0
        self.total_count = 0
        self.failures = []
    
    def add_success(self):
        self.success_count += 1
        self.total_count += 1
    
    def add_failure(self, error: str):
        self.failures.append(error)
        self.total_count += 1
    
    @property
    def success_rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return (self.success_count / self.total_count) * 100
    
    @property
    def avg_time(self) -> float:
        if self.success_count == 0:
            return 0.0
        return self.total_time / self.success_count
    
    def print_summary(self):
        """打印测试结果摘要"""
        print(f"✓ 完成")
        print(f"  - 总耗时: {self.total_time:.2f} 秒")
        print(f"  - 成功调用: {self.success_count} / {self.total_count} ({self.success_rate:.1f}%)")
        print(f"  - 平均耗时: {self.avg_time:.2f} 秒/次")
        print(f"  - 失败: {len(self.failures)}")
        if self.failures:
            print(f"\n失败详情:")
            for i, error in enumerate(self.failures[:5], 1):  # 只显示前5个错误
                print(f"    {i}. {error}")
            if len(self.failures) > 5:
                print(f"    ... 还有 {len(self.failures) - 5} 个错误")


async def test_langchain_async(
    config: TestConfig,
    tables: Dict[str, Dict],
    table_pairs: List[Tuple[str, str]]
) -> TestResult:
    """测试 LangChain ainvoke 方法（完全并发）"""
    result = TestResult("LangChain ainvoke")
    
    # 初始化 ChatTongyi
    llm = ChatTongyi(
        model=config.model,
        dashscope_api_key=config.api_key,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=config.timeout,
    )
    
    # 执行测试
    start_time = time.time()
    
    # 创建所有任务（让它们全部并发）
    tasks = []
    for table1_name, table2_name in table_pairs:
        prompt = build_prompt(tables[table1_name], tables[table2_name])
        messages = [HumanMessage(content=prompt)]
        task = llm.ainvoke(messages)
        tasks.append(task)
    
    # 显示进度并收集结果
    completed = 0
    for coro in asyncio.as_completed(tasks):
        try:
            response = await coro
            result.add_success()
        except Exception as e:
            result.add_failure(f"Exception: {str(e)}")
        
        completed += 1
        if completed % 10 == 0:
            print(f"  进度: {completed}/{len(table_pairs)}", end='\r')
    
    result.total_time = time.time() - start_time
    print(f"  进度: {completed}/{len(table_pairs)}")
    
    return result


async def test_dashscope_async(
    config: TestConfig,
    tables: Dict[str, Dict],
    table_pairs: List[Tuple[str, str]]
) -> TestResult:
    """测试 DashScope AioGeneration 方法（官方推荐方式）"""
    result = TestResult("DashScope AioGeneration")
    
    # 执行测试
    start_time = time.time()
    
    # 创建所有任务（不 await，让它们全部并发）
    tasks = []
    for table1_name, table2_name in table_pairs:
        prompt = build_prompt(tables[table1_name], tables[table2_name])
        task = AioGeneration.call(
            model=config.model,
            prompt=prompt,
            api_key=config.api_key,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.timeout,
        )
        tasks.append((task, table1_name, table2_name))
    
    # 显示进度并收集结果
    completed = 0
    for coro in asyncio.as_completed([t[0] for t in tasks]):
        try:
            response = await coro
            if response.status_code == HTTPStatus.OK:
                result.add_success()
            else:
                result.add_failure(f"API returned error: {response.message}")
        except Exception as e:
            result.add_failure(f"Exception: {str(e)}")
        
        completed += 1
        if completed % 10 == 0:
            print(f"  进度: {completed}/{len(table_pairs)}", end='\r')
    
    result.total_time = time.time() - start_time
    print(f"  进度: {completed}/{len(table_pairs)}")
    
    return result


def compare_results(result1: TestResult, result2: TestResult):
    """对比两个测试结果"""
    print("\n" + "="*80)
    print("对比结果")
    print("="*80)
    
    time_diff = result2.total_time - result1.total_time
    time_diff_pct = (time_diff / result1.total_time) * 100 if result1.total_time > 0 else 0
    
    print("性能差异:")
    if time_diff < 0:
        print(f"  - {result2.name} 比 {result1.name} 快 {abs(time_diff):.2f} 秒 ({abs(time_diff_pct):.1f}%)")
    else:
        print(f"  - {result1.name} 比 {result2.name} 快 {abs(time_diff):.2f} 秒 ({abs(time_diff_pct):.1f}%)")
    
    if result1.success_rate == result2.success_rate:
        print(f"  - 两者成功率相同: {result1.success_rate:.1f}%")
    else:
        print(f"  - {result1.name} 成功率: {result1.success_rate:.1f}%")
        print(f"  - {result2.name} 成功率: {result2.success_rate:.1f}%")
    
    print("\n建议:")
    if abs(time_diff_pct) < 5:
        print("  - 两者性能差异不大（<5%），建议优先考虑兼容性")
        print("  - 推荐使用 LangChain (支持多提供商)")
    elif time_diff < 0:
        print(f"  - {result2.name} 性能更优 ({abs(time_diff_pct):.1f}%)")
        print("  - 如仅使用 Qwen，推荐使用 DashScope 原生 API")
        print("  - 如需保持多提供商兼容性，使用 LangChain")
    else:
        print(f"  - {result1.name} 性能更优 ({abs(time_diff_pct):.1f}%)")
        print("  - 推荐使用 LangChain (性能更好且支持多提供商)")
    
    print("="*80)


async def main():
    """主函数"""
    print("="*80)
    print("LLM 异步性能对比测试")
    print("="*80)
    
    # 加载配置
    try:
        config = TestConfig()
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        return
    
    # 加载表文件
    print("加载配置和数据...")
    tables = load_json_llm_files()
    table_pairs = generate_table_pairs(tables)
    
    print(f"配置信息:")
    print(f"  - 模型: {config.model}")
    print(f"  - 测试表数: {len(tables)} 张")
    print(f"  - 表对组合: {len(table_pairs)} 个")
    print(f"  - 并发数: {config.concurrent_limit}")
    print(f"  - Temperature: {config.temperature}")
    print()
    
    # 测试 1: LangChain ainvoke
    print("-"*80)
    print("测试 1: LangChain ainvoke (兼容多提供商)")
    print("-"*80)
    print("执行中...")
    result1 = await test_langchain_async(config, tables, table_pairs)
    result1.print_summary()
    print()
    
    # 等待一下，避免频繁请求
    print("等待 5 秒后开始第二个测试...")
    await asyncio.sleep(5)
    
    # 测试 2: DashScope AioGeneration
    print("-"*80)
    print("测试 2: DashScope AioGeneration (仅 Qwen)")
    print("-"*80)
    print("执行中...")
    result2 = await test_dashscope_async(config, tables, table_pairs)
    result2.print_summary()
    
    # 对比结果
    compare_results(result1, result2)


if __name__ == "__main__":
    asyncio.run(main())

