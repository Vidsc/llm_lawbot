"""
Minimal RAG pipeline (LangChain-only) with per-paragraph inline citations,
strict References building, and citation de-duplication.
"""

import sys
import re
import os
from typing import Dict, List, Tuple

from app.config import settings
from app.vectorstore import search as search_sys, search_user
from app.prompts import (
    SYSTEM_PROMPT,
    GEN_SYSTEM_PROMPT,
    ANSWER_WITH_CONTEXT,
    ANSWER_GENERAL,
    make_context_blocks,
)
from app import config  # 用于判断用户文件路径

# --------- in-process memory ---------
_MEMORY: Dict[str, List[Dict[str, str]]] = {}

def _ensure_session(session_id: str):
    if session_id not in _MEMORY:
        _MEMORY[session_id] = []

def _append_message(session_id: str, role: str, content: str):
    _ensure_session(session_id)
    _MEMORY[session_id].append({"role": role, "content": content})
    keep = max(2 * settings.MAX_HISTORY_TURNS, 10)
    if len(_MEMORY[session_id]) > keep:
        _MEMORY[session_id] = _MEMORY[session_id][-keep:]

def _recent_history_text(session_id: str) -> str:
    _ensure_session(session_id)
    msgs = _MEMORY[session_id][-2 * settings.MAX_HISTORY_TURNS :]
    parts, total = [], 0
    for m in msgs:
        line = f"{m['role']}: {m['content']}".strip()
        if not line:
            continue
        if total + len(line) > settings.MAX_CONTEXT_CHARS:
            break
        parts.append(line)
        total += len(line)
    return "\n".join(parts)

# --------- LLM factory ---------
def _make_llm():
    if settings.LLM_PROVIDER.lower() == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as e:
            raise RuntimeError("Missing langchain-ollama: pip install langchain-ollama") from e
        return ChatOllama(model=settings.OLLAMA_MODEL, temperature=0.2)
    elif settings.LLM_PROVIDER.lower() == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as e:
            raise RuntimeError("Missing langchain-openai: pip install langchain-openai") from e
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not set. Fill .env or switch to Ollama.")
        return ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0.2)
    else:
        raise RuntimeError(f"Unknown LLM_PROVIDER: {settings.LLM_PROVIDER}")

_LLM = None
def _get_llm():
    global _LLM
    if _LLM is None:
        _LLM = _make_llm()
    return _LLM

# --------- distance -> similarity ----------
def _distance_to_similarity(distance: float) -> float:
    # Chroma 的 score 通常是向量距离（越小越相似）。简单映射到 (0,1)： sim = 1/(1+dist)
    return 1.0 / (1.0 + max(distance, 0.0))


def _decide_use_context(results: List[Dict]) -> Tuple[bool, float, Dict]:
    if not results:
        return False, 0.0, {}
    sims = [_distance_to_similarity(r["score"]) for r in results]
    top = max(sims) if sims else 0.0
    mean = sum(sims) / len(sims) if sims else 0.0
    mode = settings.RETRIEVAL_THRESHOLD_MODE.lower()
    chosen = top if mode == "top1" else mean
    use_ctx = chosen >= settings.RETRIEVAL_SCORE_THRESHOLD
    return use_ctx, chosen, results[0]["metadata"] if results else {}


# --------- inline citation helpers ----------
_CIT_PATTERN = re.compile(r"\[(\d+)\]")

def _extract_used_indices(text: str) -> List[int]:
    """Get [n] indices from text in first-appearance order (dedup)."""
    seen, order = set(), []
    for m in _CIT_PATTERN.finditer(text or ""):
        n = int(m.group(1))
        if n not in seen:
            seen.add(n)
            order.append(n)
    return order

def _split_adjacent_citations(body: str) -> str:
    """
    Ensure one citation per paragraph:
    '...[1][2]' => '...[1]\\n\\n[2]'
    """
    return re.sub(r"\](\s*)\[(\d+)\]", r"]\n\n[\2]", body or "")

def _doc_identity(c: Dict) -> Tuple[str, str, str]:
    """Return a hashable identity of a citation item for de-dup: (filename, rs_number, page_range)."""
    return (c.get("filename") or "", c.get("rs_number") or "", c.get("page_range") or "")

def _build_old_to_new_mapping_by_identity(body: str, citations: List[Dict]) -> Tuple[Dict[int, int], List[Dict]]:
    """
    Map old [n] (from CONTEXT) -> new compact indices 1..k based on document identity de-dup.
    - If different old indices refer to the same (filename, rs_number, page_range), they get the SAME new index.
    - New indices assigned in order of FIRST appearance in the BODY.
    Returns: (old_to_new, unique_citations_sorted_by_new_index)
    """
    by_old = {c["index"]: c for c in (citations or [])}
    old_order = _extract_used_indices(body)

    old_to_new: Dict[int, int] = {}
    identity_to_new: Dict[Tuple[str, str, str], int] = {}
    unique_list: List[Dict] = []
    next_new = 1

    for old in old_order:
        c = by_old.get(old)
        if not c:
            continue
        ident = _doc_identity(c)
        if ident in identity_to_new:
            new_idx = identity_to_new[ident]
        else:
            new_idx = next_new
            identity_to_new[ident] = new_idx
            c2 = dict(c)
            c2["index"] = new_idx
            unique_list.append(c2)
            next_new += 1
        old_to_new[old] = new_idx

    # sort unique citations by new index
    unique_list.sort(key=lambda x: x["index"])
    return old_to_new, unique_list

def _renumber_body_with_mapping(body: str, old_to_new: Dict[int, int]) -> str:
    """Rewrite [old] -> [new] in BODY text according to mapping."""
    def repl(m):
        old = int(m.group(1))
        new = old_to_new.get(old, old)
        return f"[{new}]"
    return _CIT_PATTERN.sub(repl, body or "")

def _build_references_block(unique_cites: List[Dict]) -> str:
    """
    参考来源（HTML）：标题 + 有序列表，每项一个可点击链接，形如：
    参考来源：
    [1] <a href="/user-files/xxx.pdf" ...> 或 <a href="/static/xxx.pdf" ...>
    """
    if not unique_cites:
        return ""

    lis = []
    for c in unique_cites:
        rs = f" ({c.get('rs_number')})" if c.get('rs_number') else ""
        pages = f" {c.get('page_range')}" if c.get('page_range') else ""

        # 构造 href
        url = c.get("source_url") or c.get("source") or ""
        href = ""
        if url.startswith("file://"):
            filename_only = os.path.basename(url.replace("file://", ""))
            # 如果该文件在用户目录，则走 /user-files/，否则退回 /static/
            user_path = config.USER_PDF_DIR / filename_only
            if user_path.exists():
                href = f"/user-files/{filename_only}"
            else:
                href = f"/static/{filename_only}"
        elif url:
            href = url  # http(s)

        display = f"{c.get('filename','Unknown')}{rs}{pages}".strip()
        idx = c.get("index", "?")

        if href:
            item = f"[{idx}] <a href=\"{href}\" target=\"_blank\" rel=\"noopener noreferrer\">{display}</a>"
        else:
            item = f"[{idx}] {display}"

        lis.append(f"<li>{item}</li>")

    html = "<div><strong>References：</strong></div>\n<ul>\n" + "\n".join(lis) + "\n</ul>"
    return "\n" + html  # 与正文之间加一个空行


# --------- merge sys & user hits ----------
def _merge_results(sys_hits: List[Dict], user_hits: List[Dict], k: int) -> List[Dict]:
    """
    Merge two hit lists, put user hits first, dedup by (filename, page_range, rs_number),
    then sort by ascending distance score (smaller = more similar).
    """
    def key_fn(r: Dict) -> Tuple[str, str, str]:
        md = r.get("metadata", {}) or {}
        return (
            md.get("filename", "") or "",
            md.get("page_range", "") or "",
            md.get("rs_number", "") or "",
        )

    merged: List[Dict] = []
    seen = set()

    for r in (user_hits + sys_hits):  # user first
        k2 = key_fn(r)
        if k2 in seen:
            continue
        seen.add(k2)
        merged.append(r)

    merged.sort(key=lambda r: r.get("score", 1e9))
    return merged[:k]


# --------- main API ---------
def answer(question: str, session_id: str = "default") -> Dict:
    _append_message(session_id, "user", question)
    history_text = _recent_history_text(session_id)

    # 1) retrieve（合并系统库与用户库）
    sys_hits  = search_sys(question, k=settings.RETRIEVAL_K)
    user_hits = search_user(question, k=settings.RETRIEVAL_K)
    results   = _merge_results(sys_hits, user_hits, settings.RETRIEVAL_K)

    # 2) decide
    use_ctx, chosen_score, _ = _decide_use_context(results)

    # 3) build prompt
    if use_ctx:
        ctx, citations = make_context_blocks(results, max_items=settings.RETRIEVAL_K)
        user_prompt = ANSWER_WITH_CONTEXT.format(
            question=question, history=history_text or "(none)", context=ctx or "(none)"
        )
        system_content = SYSTEM_PROMPT
    else:
        citations = []
        user_prompt = ANSWER_GENERAL.format(question=question)
        system_content = GEN_SYSTEM_PROMPT

    # 4) call LLM
    llm = _get_llm()
    from langchain_core.messages import SystemMessage, HumanMessage
    messages = [SystemMessage(content=system_content), HumanMessage(content=user_prompt)]
    resp = llm.invoke(messages)
    raw_text = resp.content if hasattr(resp, "content") else str(resp)

    # ----- Post-process -----
    # Always ignore any model-written "References"; we rebuild ours.
    parts = re.split(r"\n\s*References\s*\n", raw_text, maxsplit=1, flags=re.IGNORECASE)
    body = parts[0]

    # Split adjacent [n][m] to separate paragraphs (one citation per paragraph)
    body = _split_adjacent_citations(body)

    # Build mapping old->new based on identity de-dup (order by first appearance in BODY)
    old_to_new, unique_cites = _build_old_to_new_mapping_by_identity(body, citations)

    # Renumber BODY citations with the mapping
    body = _renumber_body_with_mapping(body, old_to_new)

    # Build References from unique citations (already 1..k)
    ref_block = _build_references_block(unique_cites)
    text = body.rstrip() + ("\n" + ref_block if ref_block else "")

    # memory
    _append_message(session_id, "assistant", text)

    return {
        "text": text,
        "used_retrieval": bool(use_ctx),
        "citations": unique_cites,  # 去重后的引用列表（索引为 1..k）
        "score": round(chosen_score, 4),
    }

# --------- CLI ---------
def _cli():
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:]).strip()
        res = answer(q, session_id="cli")
        print("\n=== Answer ===\n", res["text"])
        print("\n=== used_retrieval =", res["used_retrieval"], " score =", res["score"])
        if res["citations"]:
            print("\n=== References ===")
            for c in res["citations"]:
                print(f"[{c['index']}] {c['filename']} {c.get('rs_number','')} {c.get('page_range','')}")
        return

    print("Interactive mode (Ctrl+C to exit).")
    sid = "cli"
    while True:
        try:
            q = input("\nYou: ").strip()
            if not q:
                continue
            res = answer(q, session_id=sid)
            print("\nBot:", res["text"])
            print(f"(used_retrieval={res['used_retrieval']}, score={res['score']})")
        except KeyboardInterrupt:
            print("\nBye!")
            break

if __name__ == "__main__":
    _cli()

