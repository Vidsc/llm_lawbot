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

from typing import Any, Optional
from pathlib import Path

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

# Upload Documents
def get_or_create_vectorstore(
    persist_dir: Path,
    embeddings: Any,
    collection_name: Optional[str] = None,
) -> Chroma:
    return get_store()

# 用户专用向量库
_user_vectorstore: Optional[Chroma] = None
# 创建新的Chroma来获取user的pdfs
def get_user_store() -> Chroma:
    global _user_vectorstore
    if _user_vectorstore is None:
        os.makedirs(settings.USER_CHROMA_DIR, exist_ok=True)
        _user_vectorstore = Chroma(
            collection_name=settings.USER_COLLECTION_NAME,
            embedding_function=_embeddings,
            persist_directory=settings.USER_CHROMA_DIR,
        )
    return _user_vectorstore
# 添加文档块
def add_user_documents(docs: List[Dict]) -> None:
    store = get_user_store()
    texts = [d["page_content"] for d in docs]
    metadatas = [d.get("metadata", {}) for d in docs]
    store.add_texts(texts=texts, metadatas=metadatas)

# 相似度检索
def search_user(query: str, k: int = None) -> List[Dict]:
    store = get_user_store()
    k = k or settings.RETRIEVAL_K
    docs = store.similarity_search_with_score(query, k=k)
    results: List[Dict] = []
    for doc, score in docs:
        results.append({
            "page_content": doc.page_content,
            "metadata": doc.metadata,
            "score": score
        })
    return results

def user_index_count() -> int:
    store = get_user_store()
    return store._collection.count()

# 删除用户库
def delete_user_documents_by_filenames(filenames: List[str]) -> int:
    store = get_user_store()
    col = store._collection
    before = col.count()

    # 去重后逐个删除
    for fn in { (fn or "").strip() for fn in filenames }:
        if not fn:
            continue
        try:
            col.delete(where={"filename": fn})
        except Exception:
            pass

    after = col.count()
    return max(before - after, 0)
