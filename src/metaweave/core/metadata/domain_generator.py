import json
import logging
from pathlib import Path
from typing import Dict, List

import yaml

from src.metaweave.services.llm_service import LLMService

logger = logging.getLogger("metaweave.domain_generator")


class DomainGenerator:
    """Domain 列表生成器"""

    UNCLASSIFIED_DOMAIN = "_未分类_"

    def __init__(
        self,
        config: Dict,
        yaml_path: str,
        md_context: bool = False,
        md_context_dir: str = None,
        md_context_mode: str = "name_comment",
        md_context_limit: int = 50,
    ):
        self.config = config
        self.yaml_path = Path(yaml_path)
        self.llm_service = LLMService(config.get("llm", {}))
        self.db_config = self._load_yaml()
        self.md_context = md_context
        self.md_context_dir = Path(md_context_dir) if md_context_dir else None
        self.md_context_mode = md_context_mode
        self.md_context_limit = max(1, md_context_limit)

    def _load_yaml(self) -> Dict:
        """加载 db_domains.yaml"""
        try:
            with open(self.yaml_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"错误：{self.yaml_path} 文件不存在，请先创建并填写 database.description"
            ) from exc

    def generate_from_description(self) -> List[Dict]:
        """根据 description 生成 domains 列表"""
        description = self.db_config.get("database", {}).get("description", "")
        if not description or not description.strip():
            raise ValueError("错误：database.description 为空，无法生成 domains 列表")

        md_summary = ""
        if self.md_context:
            md_summary = self._build_md_context()
        prompt = self._build_prompt(description, md_summary)
        logger.debug("Domain generation prompt:\n%s", prompt)
        logger.info("正在调用 LLM 生成 domains 列表...")
        response = self.llm_service._call_llm(prompt)

        domains = self._parse_response(response)
        logger.info("成功生成 %s 个 domain", len(domains))
        return domains

    def _build_prompt(self, description: str, md_summary: str) -> str:
        """构建生成 domains 的 Prompt"""
        md_block = ""
        if md_summary:
            md_block = f"\n## 表结构摘要（来自 md 文件，最多 {self.md_context_limit} 个）\n{md_summary}\n"
        return f"""
你是一个数据库业务分析专家。请根据以下数据库描述，生成合理的业务主题分类列表。

## 数据库描述
{description}
{md_block}

## 任务
1. 分析数据库的业务范围
2. 划分合理的业务主题（建议 3-8 个）
3. 每个主题提供名称和描述

## 注意事项
- 不要生成名为 "_未分类_" 的主题（这是系统预置的特殊主题，会自动添加）
- 只生成有明确业务含义的主题

## 输出格式（JSON）
```json
{{
  "domains": [
    {{"name": "主题名称", "description": "主题描述"}},
    ...
  ]
}}
```

请只返回 JSON，不要包含其他内容。
"""

    def _build_md_context(self) -> str:
        """读取 md 目录生成摘要，按模式/数量限制。"""
        if not self.md_context_dir:
            raise ValueError("md_context 启用但未提供 md_context_dir")
        if not self.md_context_dir.exists():
            raise FileNotFoundError(f"md_context 启用，但目录不存在: {self.md_context_dir}")

        md_files = sorted(self.md_context_dir.glob("*.md"))
        if not md_files:
            raise ValueError(f"md_context 启用，但目录为空: {self.md_context_dir}")

        summaries = []
        limit = self.md_context_limit
        max_len_comment = 200
        max_len_full = 2000

        used_files = md_files[:limit]
        for md_file in used_files:
            stem = md_file.stem  # schema.table
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning("读取 md 失败: %s, 错误: %s", md_file, exc)
                continue

            if self.md_context_mode == "name":
                summary = stem
            elif self.md_context_mode == "full":
                text = content.strip()
                if len(text) > max_len_full:
                    text = text[:max_len_full] + "..."
                summary = f"{stem}: {text}"
            else:  # name_comment
                first_line = ""
                for line in content.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("#"):
                        line = line.lstrip("#").strip()
                    first_line = line
                    break
                if not first_line:
                    first_line = "(无描述)"
                if len(first_line) > max_len_comment:
                    first_line = first_line[:max_len_comment] + "..."
                summary = f"{stem}: {first_line}"

            summaries.append(f"- {summary}")

        logger.info("md_context: 已读取 %s 个 md 文件作为摘要（限制 %s）", len(summaries), limit)
        return "\n".join(summaries)

    def _parse_response(self, response: str) -> List[Dict]:
        """解析 LLM 返回的 JSON"""
        try:
            text = response.strip()
            if text.startswith("```"):
                parts = text.split("```")
                if len(parts) >= 2:
                    text = parts[1]
                    if text.startswith("json"):
                        text = text[4:]
                text = text.strip()

            data = json.loads(text)
            domains = data.get("domains", [])

            if not domains:
                logger.error("LLM 返回的 domains 列表为空，原始返回: %s", text)
                raise ValueError("LLM 返回的 domains 列表为空")

            for d in domains:
                if "name" not in d:
                    raise ValueError(f"domain 缺少 name 字段: {d}")

            return domains
        except json.JSONDecodeError as exc:
            logger.error("LLM 返回格式错误，无法解析 JSON: %s", exc)
            logger.error("原始返回: %s", response)
            raise ValueError("错误：LLM 返回格式错误，无法解析为 JSON，请重试") from exc

    def write_to_yaml(self, domains: List[Dict]) -> None:
        """将 domains 写入 yaml 文件（保留 _未分类_）"""
        unclassified = {
            "name": self.UNCLASSIFIED_DOMAIN,
            "description": "无法归入其他业务主题的表",
        }

        filtered_domains = [
            d for d in domains if d.get("name") != self.UNCLASSIFIED_DOMAIN
        ]

        final_domains = [unclassified] + filtered_domains
        self.db_config["domains"] = final_domains

        # 自定义 Dumper：多行字符串使用 | 块标量，保持可读性
        class LiteralDumper(yaml.SafeDumper):
            pass

        def _repr_str(dumper, data):
            style = "|" if "\n" in data else None
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)

        LiteralDumper.add_representer(str, _repr_str)

        with open(self.yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(
                self.db_config,
                f,
                Dumper=LiteralDumper,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

        logger.info(
            "domains 已写入 %s（共 %s 个，含 _未分类_）",
            self.yaml_path,
            len(final_domains),
        )

