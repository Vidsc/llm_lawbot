# app/rag.py
"""
最小 RAG 管道（仅 LangChain）：
- 从 Chroma 检索
- 基于相似度阈值决定：用证据回答 or 通用回答
- 维护极简会话记忆（窗口 N 轮）
- 支持 Ollama 或 OpenAI（按 settings 配置）

用法（项目根目录）：
  python -m app.rag  "你的问题"
或交互模式：
  python -m app.rag
"""

import math
import sys
from typing import Dict, List

from app.config import settings
from app.vectorstore import search
from app.prompts import (
    SYSTEM_PROMPT,
    ANSWER_WITH_CONTEXT,
    ANSWER_GENERAL,
    make_context_blocks,
)

# --------- 极简会话记忆（进程内内存，退出即失） ---------
_MEMORY: Dict[str, List[Dict[str, str]]] = {}  # {session_id: [{"role": "user|assistant", "content": "..."}]}


def _ensure_session(session_id: str):
    if session_id not in _MEMORY:
        _MEMORY[session_id] = []


def _append_message(session_id: str, role: str, content: str):
    _ensure_session(session_id)
    _MEMORY[session_id].append({"role": role, "content": content})
    # 只保留最近 2 * MAX_HISTORY_TURNS 条（user/assistant成对）
    keep = max(2 * settings.MAX_HISTORY_TURNS, 10)
    if len(_MEMORY[session_id]) > keep:
        _MEMORY[session_id] = _MEMORY[session_id][-keep:]


def _recent_history_text(session_id: str) -> str:
    _ensure_session(session_id)
    msgs = _MEMORY[session_id][-2 * settings.MAX_HISTORY_TURNS :]
    parts = []
    total = 0
    for m in msgs:
        line = f"{m['role']}: {m['content']}".strip()
        if not line:
            continue
        if total + len(line) > settings.MAX_CONTEXT_CHARS:
            break
        parts.append(line)
        total += len(line)
    return "\n".join(parts)


# --------- LLM 工厂（按 settings 选择） ---------
def _make_llm():
    """
    返回一个 LangChain ChatModel 实例（非流式）。
    需要你安装对应适配器：
      - Ollama: pip install langchain-ollama
      - OpenAI: pip install langchain-openai
    """
    if settings.LLM_PROVIDER.lower() == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise RuntimeError(
                "缺少 langchain-ollama，请先安装：pip install langchain-ollama"
            )
        return ChatOllama(model=settings.OLLAMA_MODEL, temperature=0.2)
    elif settings.LLM_PROVIDER.lower() == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise RuntimeError(
                "缺少 langchain-openai，请先安装：pip install langchain-openai"
            )
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("未设置 OPENAI_API_KEY。请在 .env 填入或改用 Ollama。")
        return ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0.2)
    else:
        raise RuntimeError(f"未知 LLM_PROVIDER: {settings.LLM_PROVIDER}")


_LLM = None  # 懒加载


def _get_llm():
    global _LLM
    if _LLM is None:
        _LLM = _make_llm()
    return _LLM


# --------- 阈值判定：把 Chroma 的 distance 转换为 similarity ---------
def _distance_to_similarity(distance: float) -> float:
    # Chroma 的 score 通常是向量距离（越小越相似）。简单映射到 (0,1)： sim = 1/(1+dist)
    return 1.0 / (1.0 + max(distance, 0.0))


def _decide_use_context(results: List[Dict]) -> (bool, float, Dict):
    """根据设置的阈值决定是否使用检索上下文"""
    if not results:
        return False, 0.0, {}
    sims = [_distance_to_similarity(r["score"]) for r in results]
    top = max(sims) if sims else 0.0
    mean = sum(sims) / len(sims) if sims else 0.0
    mode = settings.RETRIEVAL_THRESHOLD_MODE.lower()
    chosen = top if mode == "top1" else mean
    use_ctx = chosen >= settings.RETRIEVAL_SCORE_THRESHOLD
    # 为了便于日志/调试，返回首条的 meta 也一并带回
    return use_ctx, chosen, results[0]["metadata"] if results else {}


# --------- 对外主函数 ---------
def answer(question: str, session_id: str = "default") -> Dict:
    """
    输入问题与会话ID，返回：
      {
        "text": "...模型回答...",
        "used_retrieval": True/False,
        "citations": [ {index, filename, rs_number, page_range, source_url}, ... ],
        "score": float  # 命中相似度（便于调阈值）
      }
    """
    _append_message(session_id, "user", question)
    history_text = _recent_history_text(session_id)

    # 1) 检索
    results = search(question, k=settings.RETRIEVAL_K)

    # 2) 判定是否使用上下文
    use_ctx, chosen_score, _ = _decide_use_context(results)

    # 3) 组装 Prompt
    if use_ctx:
        ctx, citations = make_context_blocks(results, max_items=settings.RETRIEVAL_K)
        user_prompt = ANSWER_WITH_CONTEXT.format(
            question=question,
            history=history_text or "（无）",
            context=ctx or "（无）",
        )
    else:
        citations = []
        user_prompt = ANSWER_GENERAL.format(question=question)

    # 4) 调用 LLM
    llm = _get_llm()
    # LangChain 消息格式：system + human
    from langchain_core.messages import SystemMessage, HumanMessage
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]
    resp = llm.invoke(messages)
    text = resp.content if hasattr(resp, "content") else str(resp)

    # 5) 存入记忆
    _append_message(session_id, "assistant", text)

    return {
        "text": text,
        "used_retrieval": bool(use_ctx),
        "citations": citations,
        "score": round(chosen_score, 4),
    }


# --------- CLI 方便你立即测试 ---------
def _cli():
    # 支持：python -m app.rag "你的问题"
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:]).strip()
        res = answer(q, session_id="cli")
        print("\n=== 回答 ===\n", res["text"])
        print("\n=== 使用检索 ===", res["used_retrieval"], "  相似度=", res["score"])
        if res["citations"]:
            print("\n=== 参考来源 ===")
            for c in res["citations"]:
                print(f"[{c['index']}] {c['filename']} {c.get('rs_number') or ''} {c.get('page_range') or ''}")
        return

    # 交互模式
    print("进入交互模式（Ctrl+C 退出）。")
    sid = "cli"
    while True:
        try:
            q = input("\n你：").strip()
            if not q:
                continue
            res = answer(q, session_id=sid)
            print("\n答：", res["text"])
            print("（used_retrieval=", res["used_retrieval"], ", score=", res["score"], ")")
            if res["citations"]:
                print("参考：", " ; ".join(f"[{c['index']}] {c['filename']} {c.get('page_range','')}" for c in res["citations"]))
        except KeyboardInterrupt:
            print("\n再见！")
            break


if __name__ == "__main__":
    _cli()
