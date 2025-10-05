# app/vectorstore.py
"""
极简向量库封装（基于 Chroma + SentenceTransformers）
- 创建或加载一个 Chroma Collection
- 提供 add_documents() 和 search() 接口
"""

import os
from typing import List, Dict
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings


from app.config import settings


# 初始化 embedding 模型
_embeddings = HuggingFaceEmbeddings(
    model_name=settings.EMBEDDING_MODEL,
    model_kwargs={"device": settings.EMBEDDING_DEVICE},
)

# 懒加载存储实例（单例）
_vectorstore = None


def get_store() -> Chroma:
    """获取或创建一个全局的 Chroma 向量库实例"""
    global _vectorstore
    if _vectorstore is None:
        os.makedirs(settings.CHROMA_DIR, exist_ok=True)
        _vectorstore = Chroma(
            collection_name=settings.COLLECTION_NAME,
            embedding_function=_embeddings,
            persist_directory=settings.CHROMA_DIR,
        )
    return _vectorstore


def add_documents(docs: List[Dict]):
    """
    向向量库添加文档块
    docs: 列表，每个元素形如
      {
        "page_content": "...文本...",
        "metadata": {"filename": "RS22.pdf", "page_range": "p.10-12"}
      }
    """
    store = get_store()
    texts = [d["page_content"] for d in docs]
    metadatas = [d.get("metadata", {}) for d in docs]
    store.add_texts(texts=texts, metadatas=metadatas)



def search(query: str, k: int = None):
    """
    相似度检索
    返回结果格式：List[dict]，每个 dict 含 page_content, metadata, score
    """
    store = get_store()
    k = k or settings.RETRIEVAL_K
    docs = store.similarity_search_with_score(query, k=k)
    results = []
    for doc, score in docs:
        results.append({
            "page_content": doc.page_content,
            "metadata": doc.metadata,
            "score": score
        })
    return results
