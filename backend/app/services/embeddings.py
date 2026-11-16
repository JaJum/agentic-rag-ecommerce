"""
BGE-M3 本地 Embedding 单例：
- GPU 自动检测（RTX 4060），显存不足/无卡自动降级 CPU
- 模型经 ModelScope 下载到 backend/data/models（.env 配置本地路径，绕开 HF 网络问题）
- 常驻单例：lifespan 预热，避免首请求冷启动
"""
import os
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

# 模型缓存目录（本文件位于 backend/app/services/，parents[2] = backend/）
_MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models"
_MODELS_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(_MODELS_DIR))
# 国内网络走镜像（若本机已设 HF_ENDPOINT 则尊重原值）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

_model = None  # 常驻单例


def get_embedding_model():
    """获取（或首次加载）Embedding 单例：local=本地模型，api=OpenAI 兼容接口"""
    global _model
    settings = get_settings()
    provider = settings.embedding_provider
    if provider == "none":
        raise RuntimeError(
            "EMBEDDING_PROVIDER=none：Lite 模式不加载 Embedding，请配合 RETRIEVAL_MODE=bm25 使用"
        )
    if _model is None:
        if provider == "api":
            from langchain_openai import OpenAIEmbeddings

            _model = OpenAIEmbeddings(
                model=settings.embedding_api_model,
                api_key=settings.embedding_api_key or settings.resolved_llm_api_key,
                base_url=settings.embedding_api_base or settings.llm_base_url,
                # 关键：非 OpenAI 服务不接受 tiktoken 切好的 token 数组，必须传纯文本
                check_embedding_ctx_length=False,
                chunk_size=16,
                max_retries=settings.llm_max_retries,
                request_timeout=settings.llm_request_timeout,
            )
            log.info("embedding.ready", provider="api", model=settings.embedding_api_model)
            return _model

        from langchain_huggingface import HuggingFaceEmbeddings

        device = resolve_device(settings.device)
        log.info("embedding.loading", model=settings.embedding_model, device=device)
        _model = HuggingFaceEmbeddings(
            model_name=settings.embedding_model,          # langchain-huggingface 1.x 参数名
            cache_folder=str(_MODELS_DIR),                # 模型缓存目录（显式指定）
            model_kwargs={"device": device},
            encode_kwargs={
                "normalize_embeddings": True,  # 余弦相似度需归一化
                "batch_size": 32,              # 批量编码（批量 embedding）
            },
        )
        log.info("embedding.ready", provider="local", model=settings.embedding_model)
    return _model


def embedding_signature() -> str:
    """当前 Embedding 的稳定标识：用于检测「换模型后向量库与查询向量不一致」"""
    settings = get_settings()
    if settings.embedding_provider == "none":
        return "none"
    if settings.embedding_provider == "api":
        return f"api:{settings.embedding_api_model}"
    return f"local:{settings.embedding_model}"


def reset_model() -> None:
    """释放单例（切换 provider / 测试用）"""
    global _model
    _model = None


def is_ready() -> bool:
    """模型是否已加载（health 检查用）"""
    return _model is not None


def resolve_device(device: str) -> str:
    """device=auto 时探测 CUDA；指定值直接采用"""
    if device != "auto":
        return device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"
