"""
Prompt templates for LawBot (dual personas + per-paragraph inline citations).
"""

# Persona when retrieval is used (legal)
SYSTEM_PROMPT = """You are LawBot, a cautious legal assistant focusing on Queensland mining safety Recognised Standards.
Always prioritize the provided CONTEXT and cite sources as [n] using the numbering given in the CONTEXT.
Be concise and structured. Do not fabricate facts or citations. Your response is informational, not legal advice.
"""

# Persona when retrieval is NOT used (general)
GEN_SYSTEM_PROMPT = """You are a helpful, knowledgeable assistant.
When no domain-specific context is provided, you MUST still follow the given answer template.
Be accurate, concise, and do not invent citations.
If the topic touches law/safety, add a short disclaimer that this is not legal advice.
"""

# With retrieval: paragraph-level single citation
ANSWER_WITH_CONTEXT = """Answer the user's question strictly based on the provided CONTEXT.

[Question]
{question}

[Conversation history]
{history}

[CONTEXT]
{context}

Write your answer as multiple short paragraphs.

CITATION RULES (BODY):
- Each paragraph MUST end with exactly ONE citation index in square brackets, e.g., [1].
- Do NOT attach multiple indices to a single paragraph. If multiple sources support the content, split it
  into multiple paragraphs, each ending with its own [index].
- Only use indices that exist in the CONTEXT header. Do not fabricate indices.

After the body, output a section titled exactly:

References

Then, for each citation you used in the body, create a SEPARATE paragraph that
starts with its actual index in square brackets (e.g., “[1] …”, “[2] …”), followed by the filename
(and RS number/page/section if available). Optionally add one short sentence describing what this source supports.
"""

# Without retrieval: keep the same visual structure (body + references)
ANSWER_GENERAL = """[Question]
{question}

Write a concise, accurate answer (one or a few short paragraphs). Do NOT add fabricated citations.

References

Provide a SEPARATE paragraph stating that no context documents were used and this answer is based on general knowledge.
"""

def make_context_blocks(docs, max_items=4):
    """
    Assemble retrieved chunks into a concise CONTEXT string for ANSWER_WITH_CONTEXT.
    Each item is prefixed with [n] so the model can cite them.
    docs: Iterable[dict] with keys:
        page_content, metadata:{source, filename, rs_number, page_range}
    Returns: (context_str, citations_list)
    """
    blocks = []
    citations = []
    for i, d in enumerate(docs[:max_items], start=1):
        content = (d.get("page_content") or "").strip()
        meta = d.get("metadata") or {}
        filename = meta.get("filename") or meta.get("title") or "Unknown"
        rs = meta.get("rs_number") or ""
        pages = meta.get("page_range") or ""
        source = meta.get("source") or meta.get("source_url") or ""

        tag = f"[{i}] {filename}{' (' + rs + ')' if rs else ''}{' ' + pages if pages else ''}"
        blocks.append(f"{tag}\n{content}\n")

        citations.append({
            "index": i,
            "filename": filename,
            "rs_number": rs,
            "page_range": pages,
            "source_url": source
        })
    ctx = "\n".join(blocks).strip()
    return ctx, citations
