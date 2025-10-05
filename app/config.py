# app/config.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv

# 读取 .env（没有也不报错）
load_dotenv()

@dataclass
class Settings:
    # —— 基础 —— #
    APP_ENV: str = os.getenv("APP_ENV", "dev")  # dev / prod

    # —— 向量库（MVP 用 Chroma 本地目录）—— #
    CHROMA_DIR: str = os.getenv("CHROMA_DIR", "./data/chroma")
    COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "law_rs")

    # —— 嵌入模型（SentenceTransformers）—— #
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    EMBEDDING_DEVICE: str = os.getenv("EMBEDDING_DEVICE", "cpu")  # cpu / cuda

    # —— 检索参数 —— #
    RETRIEVAL_K: int = int(os.getenv("RETRIEVAL_K", "4"))
    # 命中判定阈值：当 top-k 的最高/平均相似度低于该阈值时，走通用模型回答
    # 0.25~0.35 常见，数值越高越“保守”（更容易走通用模型）
    RETRIEVAL_SCORE_THRESHOLD: float = float(os.getenv("RETRIEVAL_SCORE_THRESHOLD", "0.28"))
    # 采用 top-1 还是均值进行阈值判定：top1 | mean
    RETRIEVAL_THRESHOLD_MODE: str = os.getenv("RETRIEVAL_THRESHOLD_MODE", "top1")

    # —— LLM 选择 —— #
    # provider: ollama | openai（先默认 ollama；后续你要换 openai 只在这里改）
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    # OpenAI 相关（如切换）
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # —— 其他 —— #
    MAX_HISTORY_TURNS: int = int(os.getenv("MAX_HISTORY_TURNS", "6"))  # 简单窗口
    MAX_CONTEXT_CHARS: int = int(os.getenv("MAX_CONTEXT_CHARS", "6000"))  # 防止上下文过长

settings = Settings()
