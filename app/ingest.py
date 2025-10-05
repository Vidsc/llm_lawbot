# app/ingest.py
"""
本地 PDF → 文本切块 → 写入向量库（Chroma）
- 扫描 ./data/pdfs/*.pdf
- pypdf 提取每页文本
- 合并成适中大小的 chunk（带页码范围与文件名等 metadata）
- 调用 vectorstore.add_documents() 入库
"""

import os
import re
from typing import List, Dict, Tuple
from pypdf import PdfReader

from app.config import settings
from app.vectorstore import add_documents


# ====== 可调参数（根据你的 PDF 质量微调） ======
# 每个 chunk 的期望字符数（面向中文/英文混排，简单用字符数控制）
CHUNK_SIZE = 1500
# 相邻 chunk 的重叠字符数，帮助跨页或跨段落的语义连续
CHUNK_OVERLAP = 150

PDF_DIR = "./data/pdfs"


def normalize_text(s: str) -> str:
    """去除多余空白与控制字符"""
    s = s.replace("\x00", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\r?\n\s*\r?\n", "\n\n", s)  # 连续空行压成一个
    s = re.sub(r"\r?\n", "\n", s)
    return s.strip()


def detect_rs_number(filename: str) -> str:
    """从文件名中粗略提取 RS 编号（如果有）"""
    m = re.search(r"(RS|rs)\s*0?(\d+)", filename)
    if m:
        return f"RS{m.group(2)}"
    return ""


def extract_pages(path: str) -> List[Tuple[int, str]]:
    """
    读取 PDF，返回 [(page_index0, text), ...]
    仅做最小错误处理：空页返回 ""。
    """
    pages = []
    reader = PdfReader(path)
    for i, page in enumerate(reader.pages):
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        pages.append((i, normalize_text(txt)))
    return pages


def paragraphs_from_pages(pages: List[Tuple[int, str]]) -> List[Tuple[int, int, str]]:
    """
    将每页文本按段落切分，再携带原始页码。
    返回 [(start_page, end_page, paragraph_text), ...]
    """
    paras = []
    for idx, txt in pages:
        if not txt:
            continue
        # 以空行分段（适配 pypdf 常见换行）
        parts = [p.strip() for p in re.split(r"\n{2,}", txt) if p.strip()]
        for p in parts:
            paras.append((idx, idx, p))
    return paras


def merge_paras_to_chunks(paras: List[Tuple[int, int, str]],
                          chunk_size: int = CHUNK_SIZE,
                          overlap: int = CHUNK_OVERLAP) -> List[Tuple[int, int, str]]:
    """
    将段落合并成接近 chunk_size 的块，保留起止页码。
    简单策略：不断追加段落直到超过阈值，开始新块；相邻块做字符串重叠。
    返回 [(start_page, end_page, chunk_text), ...]
    """
    chunks = []
    buf_text = ""
    buf_start = None
    buf_end = None

    for (p_start, p_end, p_txt) in paras:
        if buf_text == "":
            buf_start, buf_end = p_start, p_end
            buf_text = p_txt
            continue

        # 若追加后超长，则先收束当前块，再新开一块
        if len(buf_text) + 1 + len(p_txt) > chunk_size:
            chunks.append((buf_start, buf_end, buf_text.strip()))
            # 重叠：从末尾截取 overlap 字符作为新块开头
            if overlap > 0 and len(buf_text) > overlap:
                overlap_txt = buf_text[-overlap:]
                buf_text = overlap_txt + "\n" + p_txt
                buf_start = min(buf_end, p_start)
                buf_end = max(buf_end, p_end)
            else:
                buf_text = p_txt
                buf_start, buf_end = p_start, p_end
        else:
            # 继续追加
            buf_text += "\n" + p_txt
            buf_end = max(buf_end, p_end)

    # 收尾
    if buf_text.strip():
        chunks.append((buf_start, buf_end, buf_text.strip()))

    return chunks


def make_docs_for_store(file_path: str) -> List[Dict]:
    """
    将单个 PDF 转换为向量库可写入的文档块列表。
    每个元素结构：
      {
        "page_content": "...",
        "metadata": {
            "filename": "...",
            "source": "file:///abs/path",
            "page_range": "p.X-Y",
            "rs_number": "RSxx"
        }
      }
    """
    filename = os.path.basename(file_path)
    rs = detect_rs_number(filename)

    pages = extract_pages(file_path)
    paras = paragraphs_from_pages(pages)
    chunks = merge_paras_to_chunks(paras)

    docs = []
    for (p_start, p_end, text) in chunks:
        page_range = f"p.{p_start+1}-{p_end+1}" if p_end != p_start else f"p.{p_start+1}"
        docs.append({
            "page_content": text,
            "metadata": {
                "filename": filename,
                "source": f"file://{os.path.abspath(file_path)}",
                "page_range": page_range,
                "rs_number": rs
            }
        })
    return docs


def ingest_directory(pdf_dir: str = PDF_DIR) -> int:
    """
    扫描目录下的所有 PDF，入库。
    返回写入的 chunk 数量。
    """
    if not os.path.isdir(pdf_dir):
        print(f"[ingest] 目录不存在：{pdf_dir}")
        return 0

    total = 0
    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print(f"[ingest] 未在 {pdf_dir} 发现 PDF 文件。")
        return 0

    for name in pdf_files:
        path = os.path.join(pdf_dir, name)
        print(f"[ingest] 处理：{name}")
        try:
            docs = make_docs_for_store(path)
            if docs:
                add_documents(docs)
                total += len(docs)
                print(f"[ingest] 写入 {len(docs)} 块")
            else:
                print("[ingest] 无可用文本，跳过。")
        except Exception as e:
            print(f"[ingest] 失败：{name} -> {e}")

    print(f"[ingest] 完成。共写入 {total} 块到集合 {settings.COLLECTION_NAME}")
    return total


if __name__ == "__main__":
    # 用法（在项目根目录）：
    #   python -m app.ingest
    # 或：
    #   python app/ingest.py
    os.makedirs(PDF_DIR, exist_ok=True)
    ingest_directory(PDF_DIR)
