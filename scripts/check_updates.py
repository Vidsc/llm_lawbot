# scripts/check_updates.py
"""
定时更新脚本（Windows 任务计划可调用）
- 检测 Recognised standards 页面上的 PDF 新增/变更
- 仅对新增/变更文件下载并重嵌入（不会重复嵌入未变化文件）
- 维护 data/manifest.json 记录每个 URL 的 etag/last_modified/size/sha256/本地文件名

用法（项目根目录）：
  python -m scripts.check_updates
可选：
  python -m scripts.check_updates --force   # 忽略标头直接校验并强制下载+重嵌入
"""

import os
import json
import time
import hashlib
import argparse
from typing import Dict, Tuple
from urllib.parse import urlparse, urljoin

import requests

# 复用你的页面&解析逻辑
from app.crawler_qld import (
    MAIN_URL,
    HEADERS,
    ensure_outdir,
    parse_pdf_links,
    guess_filename_from_url,
    sanitize_filename,
    detect_rs_number,
)

# 复用你的切块&入库逻辑
from app.ingest import make_docs_for_store
from app.vectorstore import add_documents

PDF_DIR = "./data/pdfs"
MANIFEST = "./data/manifest.json"

TIMEOUT = 25

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def load_manifest() -> Dict:
    if os.path.exists(MANIFEST):
        try:
            with open(MANIFEST, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"source_url": MAIN_URL, "checked_at": "", "items": {}}  # items: url -> record

def save_manifest(m: Dict):
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    m["checked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)

def head_meta(sess: requests.Session, url: str) -> Tuple[str, str, int]:
    """
    返回 (etag, last_modified, content_length)
    任一字段缺失则为空/0
    """
    try:
        r = sess.head(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            # 有些站点对 HEAD 不友好，退化到 GET，再只读 headers
            r = sess.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True, allow_redirects=True)
        etag = r.headers.get("ETag", "").strip('"').strip()
        lm = r.headers.get("Last-Modified", "").strip()
        try:
            clen = int(r.headers.get("Content-Length", "0"))
        except Exception:
            clen = 0
        return etag, lm, clen
    except Exception:
        return "", "", 0

def decide_change(old: Dict, new_etag: str, new_lm: str, new_len: int, force: bool) -> bool:
    """
    粗判是否变化：
      - force=True 直接认为需要下载
      - etag 或 last-modified 变化
      - size 变化
    进一步用 sha256 双检在下载后进行
    """
    if force or not old:
        return True
    if new_etag and new_etag != old.get("etag", ""):
        return True
    if new_lm and new_lm != old.get("last_modified", ""):
        return True
    if new_len and new_len != int(old.get("content_length", 0)):
        return True
    return False

def build_local_name(url: str, link_text: str) -> str:
    base = guess_filename_from_url(url)
    rs = detect_rs_number(link_text) or detect_rs_number(base)
    if rs and not base.lower().startswith(rs.lower()):
        base = f"{rs}_{base}"
    return sanitize_filename(base)

def download(sess: requests.Session, url: str, out_path: str) -> bool:
    try:
        with sess.get(url, headers=HEADERS, stream=True, timeout=120) as r:
            r.raise_for_status()
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                for part in r.iter_content(1024 * 64):
                    if part:
                        f.write(part)
        return True
    except Exception as e:
        print(f"[download] fail {url}: {e}")
        return False

def reembed_pdf(local_path: str):
    """仅对单个 PDF 做切块并写入向量库"""
    docs = make_docs_for_store(local_path)
    if docs:
        add_documents(docs)
        print(f"[embed] wrote {len(docs)} chunks from {os.path.basename(local_path)}")
    else:
        print(f"[embed] no text extracted: {os.path.basename(local_path)}")

def main():
    parser = argparse.ArgumentParser(description="Check and update PDFs incrementally.")
    parser.add_argument("--url", default=MAIN_URL)
    parser.add_argument("--outdir", default=PDF_DIR)
    parser.add_argument("--force", action="store_true", help="忽略标头强制下载+重嵌入")
    args = parser.parse_args()

    outdir = ensure_outdir(args.outdir)
    manifest = load_manifest()
    items = manifest.get("items", {})

    with requests.Session() as sess:
        print(f"[fetch] {args.url}")
        html = sess.get(args.url, headers=HEADERS, timeout=TIMEOUT).text
        links = parse_pdf_links(html, args.url)
        print(f"[parse] found {len(links)} pdf links")

        added = updated = skipped = failed = 0

        for url, text in links:
            # 1) HEAD/GET headers
            etag, lm, clen = head_meta(sess, url)
            record_old = items.get(url, {})
            need = decide_change(record_old, etag, lm, clen, args.force)

            # 2) 本地文件名
            filename = build_local_name(url, text)
            local_path = os.path.join(outdir, filename)

            if not need and os.path.exists(local_path):
                skipped += 1
                continue

            print(f"[check] {filename}  (etag={etag or '-'} lm={lm or '-'} len={clen})")

            # 3) 下载
            ok = download(sess, url, local_path)
            if not ok:
                failed += 1
                continue

            # 4) sha256 校验变化
            new_sha = sha256_file(local_path)
            if record_old and not args.force and new_sha == record_old.get("sha256"):
                print(f"[skip ] unchanged by sha256: {filename}")
                skipped += 1
                # 即便未变更，也同步下新 header
                record = {**record_old}
                record.update({
                    "filename": filename,
                    "etag": etag,
                    "last_modified": lm,
                    "content_length": clen,
                    "sha256": new_sha,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
                items[url] = record
                continue

            # 5) 重嵌入
            reembed_pdf(local_path)

            # 6) 更新 manifest
            record = {
                "filename": filename,
                "etag": etag,
                "last_modified": lm,
                "content_length": clen,
                "sha256": new_sha,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            items[url] = record

            if record_old:
                updated += 1
            else:
                added += 1

    manifest["items"] = items
    save_manifest(manifest)
    print(f"[done] added={added} updated={updated} skipped={skipped} failed={failed}")
    print(f"[manifest] {os.path.abspath(MANIFEST)}")

if __name__ == "__main__":
    main()
