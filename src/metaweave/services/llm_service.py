"""LLM 服务

封装 LLM 调用，支持 qwen-plus (DashScope) 和 deepseek。
"""

import logging
from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger("metaweave.llm")


class LLMService:
    """LLM 服务
    
    使用 LangChain 封装 LLM 调用，支持多种 LLM 提供商。
    """
    
    def __init__(self, config: Dict[str, Any]):
        """初始化 LLM 服务
        
        Args:
            config: LLM 配置字典
                - active: 当前激活的提供商名称
                - providers: 各提供商配置字典
                - batch_size: 批量大小
                - retry_times: 重试次数
        """
        # 1. 读取激活的 LLM 配置名称
        self.provider_type = config.get("active", "qwen")
        
        # 2. 获取对应的配置段
        providers = config.get("providers", {})
        if self.provider_type not in providers:
            raise ValueError(
                f"找不到 LLM 配置: '{self.provider_type}'\n"
                f"可用配置: {list(providers.keys())}\n"
                f"请检查 metadata_config.yaml 中的 llm.active 和 llm.providers 配置"
            )
        
        provider_config = providers[self.provider_type]
        
        # 3. 提取通用参数
        self.model = provider_config.get("model")
        self.api_key = provider_config.get("api_key")
        self.api_base = provider_config.get("api_base")
        self.temperature = provider_config.get("temperature", 0.3)
        self.max_tokens = provider_config.get("max_tokens", 500)
        self.timeout = provider_config.get("timeout", 30)
        
        # 早期校验：API Key 必须存在
        if not self.api_key:
            raise ValueError(
                f"LLM API Key 未配置: {self.provider_type}\n"
                f"请在 .env 文件中设置相应的 API Key 环境变量"
            )
        
        # 早期校验：model 必须存在
        if not self.model:
            raise ValueError(
                f"LLM 模型未配置: {self.provider_type}\n"
                f"请在 metadata_config.yaml 中设置 llm.providers.{self.provider_type}.model"
            )
        
        # 4. 提取特定参数
        self.extra_params = provider_config.get("extra_params", {})
        
        # 5. 提取批量配置
        self.batch_size = config.get("batch_size", 10)
        self.retry_times = config.get("retry_times", 3)
        
        # 6. 初始化 LLM 客户端
        self.llm: BaseChatModel = self._init_llm()
        
        logger.info(f"LLM 服务已初始化: {self.provider_type} ({self.model})")
    
    def _init_llm(self) -> BaseChatModel:
        """初始化 LLM 客户端（根据 provider_type 判断）"""
        if self.provider_type == "qwen":
            return self._init_qwen()
        elif self.provider_type == "deepseek":
            return self._init_deepseek()
        else:
            raise ValueError(
                f"不支持的 LLM 提供商: '{self.provider_type}'\n"
                f"当前支持: qwen, deepseek"
            )
    
    def _init_qwen(self) -> BaseChatModel:
        """初始化通义千问"""
        try:
            from langchain_community.chat_models.tongyi import ChatTongyi
            
            # 基础参数
            init_params = {
                "model": self.model,
                "dashscope_api_key": self.api_key,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "timeout": self.timeout,
                "max_retries": self.retry_times,
            }
            
            # 可选：api_base
            if self.api_base:
                init_params["dashscope_api_base"] = self.api_base
            
            # 处理 extra_params（区分顶层参数和 extra_body 参数）
            extra_body_params = {}  # 需要放入 extra_body 的参数
            top_level_params = {}   # 顶层参数
            
            # 定义需要放入 extra_body 的参数列表
            extra_body_keys = {"enable_thinking"}
            
            # 定义参数名映射（处理参数名不一致的情况）
            param_rename_map = {"stream": "streaming"}  # stream -> streaming
            
            for key, value in self.extra_params.items():
                if value is not None:  # 只过滤 None，允许 False 透传
                    # 重命名参数（如果需要）
                    actual_key = param_rename_map.get(key, key)
                    
                    if key in extra_body_keys:
                        extra_body_params[actual_key] = value
                        logger.debug(f"Qwen extra_body 参数: {actual_key}={value}")
                    else:
                        top_level_params[actual_key] = value
                        if actual_key != key:
                            logger.debug(f"Qwen 参数重命名: {key} -> {actual_key}={value}")
                        else:
                            logger.debug(f"Qwen 顶层参数: {actual_key}={value}")
            
            # 添加顶层参数
            init_params.update(top_level_params)
            
            # 添加 extra_body 参数（仅在有值时）
            if extra_body_params:
                init_params["extra_body"] = extra_body_params
            
            logger.info(f"初始化 Qwen LLM: {self.model}")
            logger.debug(f"Qwen 初始化参数: {list(init_params.keys())}")
            if extra_body_params:
                logger.debug(f"Qwen extra_body: {extra_body_params}")
            
            return ChatTongyi(**init_params)
        except ImportError as e:
            logger.error(f"导入 ChatTongyi 失败: {e}")
            raise
        except Exception as e:
            logger.error(f"初始化通义千问失败: {e}")
            raise
    
    def _init_deepseek(self) -> BaseChatModel:
        """初始化 DeepSeek"""
        try:
            from langchain_openai import ChatOpenAI
            
            # 基础参数
            init_params = {
                "model": self.model,
                "openai_api_key": self.api_key,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "timeout": self.timeout,
                "max_retries": self.retry_times,
            }
            
            # 可选：api_base（默认值）
            api_base = self.api_base or "https://api.deepseek.com/v1"
            init_params["openai_api_base"] = api_base
            
            # 添加特定参数（过滤 None 值）
            for key, value in self.extra_params.items():
                if value is not None:
                    init_params[key] = value
                    logger.debug(f"DeepSeek 额外参数: {key}={value}")
            
            logger.info(f"初始化 DeepSeek LLM: {self.model}")
            logger.debug(f"DeepSeek 初始化参数: {list(init_params.keys())}")
            
            return ChatOpenAI(**init_params)
        except ImportError as e:
            logger.error(f"导入 ChatOpenAI 失败: {e}")
            raise
        except Exception as e:
            logger.error(f"初始化 DeepSeek 失败: {e}")
            raise
    
    def generate_table_comment(
        self,
        table_name: str,
        columns: List[Dict[str, str]],
        sample_data: Optional[List[Dict]] = None
    ) -> str:
        """生成表注释
        
        Args:
            table_name: 表名
            columns: 字段信息列表 [{"name": "...", "type": "..."}]
            sample_data: 样本数据（可选）
            
        Returns:
            生成的表注释
        """
        prompt = self._build_table_comment_prompt(table_name, columns, sample_data)
        
        try:
            response = self._call_llm(prompt)
            comment = self._clean_response(response)
            logger.info(f"生成表注释成功: {table_name}")
            return comment
        except Exception as e:
            logger.error(f"生成表注释失败 ({table_name}): {e}")
            return ""
    
    def generate_column_comments(
        self,
        table_name: str,
        columns: List[Dict[str, Any]],
        sample_data: Optional[List[Dict]] = None
    ) -> Dict[str, str]:
        """批量生成字段注释
        
        Args:
            table_name: 表名
            columns: 字段信息列表 [{"name": "...", "type": "...", "sample_values": [...]}]
            sample_data: 样本数据（可选）
            
        Returns:
            字段注释字典 {column_name: comment}
        """
        prompt = self._build_column_comments_prompt(table_name, columns, sample_data)
        
        try:
            response = self._call_llm(prompt)
            comments = self._parse_column_comments(response, columns)
            logger.info(f"生成字段注释成功: {table_name}, {len(comments)} 个字段")
            return comments
        except Exception as e:
            logger.error(f"生成字段注释失败 ({table_name}): {e}")
            return {}
    
    def _call_llm(self, prompt: str, system_message: Optional[str] = None) -> str:
        """调用 LLM
        
        Args:
            prompt: 用户提示词
            system_message: 系统消息（可选）
            
        Returns:
            LLM 响应文本
        """
        messages = []
        
        if system_message:
            messages.append(SystemMessage(content=system_message))
        
        messages.append(HumanMessage(content=prompt))
        
        try:
            response = self.llm.invoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"调用 LLM 失败: {e}")
            raise
    
    def _build_table_comment_prompt(
        self,
        table_name: str,
        columns: List[Dict[str, str]],
        sample_data: Optional[List[Dict]] = None
    ) -> str:
        """构建表注释生成的提示词"""
        prompt = f"""请为数据库表生成简洁的中文注释（一句话描述，不超过50字）。

表名: {table_name}

字段信息:
"""
        for col in columns:
            prompt += f"- {col.get('name')}: {col.get('type')}\n"
        
        if sample_data and len(sample_data) > 0:
            prompt += "\n样本数据（前3行）:\n"
            for i, row in enumerate(sample_data[:3], 1):
                prompt += f"{i}. {row}\n"
        
        prompt += """
请根据表名、字段信息和样本数据，分析这张表的业务用途，然后生成一句话的表注释。
要求：
1. 注释应该简洁明了，突出表的核心业务含义
2. 使用中文
3. 不要包含"这张表"、"该表"等多余词汇
4. 直接描述表的用途或存储的数据

示例格式：
用户信息表，存储系统用户的基本信息和登录凭证
订单记录表，记录用户的购买订单及订单状态

请直接输出注释内容，不要有其他解释：
"""
        return prompt
    
    def _build_column_comments_prompt(
        self,
        table_name: str,
        columns: List[Dict[str, Any]],
        sample_data: Optional[List[Dict]] = None
    ) -> str:
        """构建字段注释生成的提示词"""
        prompt = f"""请为数据库表的字段生成简洁的中文注释。

表名: {table_name}

字段信息:
"""
        for col in columns:
            col_name = col.get('name')
            col_type = col.get('type')
            sample_values = col.get('sample_values', [])
            
            prompt += f"\n字段: {col_name}\n"
            prompt += f"类型: {col_type}\n"
            
            if sample_values:
                prompt += f"样本值: {', '.join(map(str, sample_values[:5]))}\n"
        
        prompt += """
请为每个字段生成简洁的中文注释（10-30字）。
要求：
1. 注释应该准确描述字段的含义和用途
2. 使用中文
3. 对于ID类字段，说明是什么的ID
4. 对于状态、类型等枚举字段，如果能从样本值推断，请说明可能的取值含义

输出格式（每行一个字段）：
字段名: 注释内容

示例：
user_id: 用户唯一标识ID
username: 用户登录名
email: 用户邮箱地址
status: 用户状态（1-正常，0-禁用）

请直接输出结果，不要有其他解释：
"""
        return prompt
    
    def _clean_response(self, response: str) -> str:
        """清理 LLM 响应"""
        # 去除首尾空白
        response = response.strip()
        
        # 去除可能的引号
        if response.startswith('"') and response.endswith('"'):
            response = response[1:-1]
        if response.startswith("'") and response.endswith("'"):
            response = response[1:-1]
        
        # 去除多余的句号
        if response.endswith('。'):
            response = response[:-1]
        
        return response
    
    def _parse_column_comments(
        self,
        response: str,
        columns: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """解析字段注释响应"""
        comments = {}
        
        # 按行分割响应
        lines = response.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or ':' not in line:
                continue
            
            # 解析 "字段名: 注释" 格式
            parts = line.split(':', 1)
            if len(parts) == 2:
                col_name = parts[0].strip()
                comment = parts[1].strip()
                
                # 清理注释
                comment = self._clean_response(comment)
                
                # 验证字段名是否在列表中
                if any(col.get('name') == col_name for col in columns):
                    comments[col_name] = comment
        
        return comments

