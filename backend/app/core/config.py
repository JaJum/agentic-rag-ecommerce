"""
应用配置：从项目根目录 .env 加载全部运行参数。
集中管理 LLM（阿里云百炼）、MySQL、服务密钥、本地模型路径等配置。
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 本文件位于 backend/app/core/，项目根目录向上三级
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """全局配置项，字段名与 .env 键名一一对应（不区分大小写）"""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    # ---------- 阿里云百炼（DashScope OpenAI 兼容模式） ----------
    dashscope_api_key: str = ""
    llm_base_url: str = "https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1"
    llm_model: str = "qwen3.8-flash"          # 回答生成模型
    llm_rewrite_model: str = "qwen3.8-flash"  # 查询改写模型（轻任务）
    llm_enable_thinking: bool = False         # 思考模式默认关（实测开启后简单问题产生 350+ reasoning tokens）
    llm_temperature: float = 0.3
    llm_request_timeout: int = 60
    llm_max_retries: int = 3

    # ---------- MySQL ----------
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_db: str = "langchain_rag"

    # ---------- 服务 ----------
    secret_key: str = ""                      # JWT 签名密钥（.env 提供）
    access_token_expire_minutes: int = 24 * 60  # token 有效期 24h
    redis_url: str = ""                       # 可选：配置后自动启用 Redis 缓存

    # ---------- 本地模型（M3 生效） ----------
    embedding_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    device: str = "auto"                      # auto / cuda / cpu

    # ---------- 检索（M4） ----------
    retrieval_k: int = 15                     # 双路各取 top-k（M5 压测调优：20→15，降 GPU 负载）
    rerank_top_n: int = 5                     # 重排后进入 Prompt 的块数
    rerank_threshold: float = 0.05            # 低于此分 → 兜底拒答（实测标定：正样本≥0.15，负样本≤0.00002）

    # ---------- 性能（M5） ----------
    rate_limit_chat_per_min: int = 10         # 每用户问答限流（次/分钟）
    llm_max_concurrency: int = 8              # LLM 并发信号量
    cache_ttl: int = 600                      # 问答缓存 TTL（秒）
    cache_size: int = 256                     # 内存缓存条数上限

    # ---------- Agent（M8：LangGraph 编排） ----------
    agent_enabled: bool = True                # 总开关；false 时行为与改造前完全一致
    agent_max_steps: int = 3                  # 最多工具调用步数
    agent_timeout_s: int = 30                 # 单次问答 Agent 总超时
    agent_tool_timeout_s: int = 8             # 单工具超时
    agent_fast_path: bool = True              # 单跳知识问题跳过 Agent，走原 RAG
    agent_allow_write_tools: bool = False     # 转人工等写操作开关
    agent_router_model: str = ""              # 空则复用 llm_rewrite_model
    agent_temperature: float = 0.1
    agent_tool_mode: str = "auto"             # auto | native | prompt

    # ---------- 可复现性 / Lite 模式 ----------
    retrieval_mode: str = "hybrid"            # hybrid | bm25
    embedding_provider: str = "local"         # local | api | none
    mock_llm: bool = False                    # 无 Key 演示 / CI
    db_url: str = Field("", validation_alias="DATABASE_URL")  # 覆盖连接串（如 SQLite）

    # ---------- 可选追踪（LangSmith） ----------
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "agentic-rag-ecommerce"

    @property
    def database_url(self) -> str:
        """SQLAlchemy 异步连接串：DATABASE_URL 优先，否则 MySQL（aiomysql）"""
        if self.db_url:
            return self.db_url
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}?charset=utf8mb4"
        )

    @property
    def agent_router_model_name(self) -> str:
        """路由/改写使用的轻量模型（未单独配置时复用改写模型）"""
        return self.agent_router_model or self.llm_rewrite_model

    @property
    def thinking_extra_body(self) -> dict:
        """ChatOpenAI 的 extra_body：把 enable_thinking 透传给百炼"""
        return {"enable_thinking": self.llm_enable_thinking}


@lru_cache
def get_settings() -> Settings:
    """全局单例配置（进程内缓存）"""
    return Settings()
