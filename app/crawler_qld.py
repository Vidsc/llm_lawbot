# app/crawler_qld.py
"""
从昆士兰政府 Recognised standards 页面抓取所有 PDF 到 ./data/pdfs/
- 仅抓主页面上出现的 PDF 链接（不深度递归）
- 自动去重（已存在则跳过），支持 -f 强制覆盖
- 友好超时与重试，打印下载进度

用法（在项目根目录）：
  python -m app.crawler_qld
  # 或
  python app/crawler_qld.py
可选：
  python -m app.crawler_qld -f        # 强制覆盖已存在文件
  python -m app.crawler_qld -o mydir   # 指定输出目录
"""

import os
import re
import sys
import time
import argparse
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

MAIN_URL = "https://www.business.qld.gov.au/industries/mining-energy-water/resources/safety-health/mining/legislation-standards/recognised-standards"
DEFAULT_OUTDIR = "./data/pdfs"
HEADERS = {
    "User-Agent": "LawBot-MVP/0.1 (+https://example.com; for academic prototype; contact me if issues)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 简单重试策略
def http_get(url, session: requests.Session, timeout=20, retries=3, backoff=1.8):
    last_ex = None
    for i in range(retries):
        try:
            resp = session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if resp.status_code == 200:
                return resp
            else:
                last_ex = RuntimeError(f"HTTP {resp.status_code}")
        except Exception as e:
            last_ex = e
        time.sleep(backoff ** (i + 1) * 0.3)
    raise last_ex or RuntimeError("Unknown HTTP error")

def sanitize_filename(name: str) -> str:
    # 保留常见字符，替换危险字符
    name = name.strip().replace(" ", "_")
    name = re.sub(r"[\\/:*?\"<>|]+", "-", name)
    name = re.sub(r"_+", "_", name)
    return name

def guess_filename_from_url(url: str) -> str:
    path = urlparse(url).path
    base = os.path.basename(path)
    if base.lower().endswith(".pdf"):
        return base
    return sanitize_filename(base or "download.pdf") + ".pdf"

def detect_rs_number(text: str) -> str:
    m = re.search(r"(RS|rs)\s*0?(\d+)", text or "")
    return f"RS{m.group(2)}" if m else ""

def parse_pdf_links(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if ".pdf" in href.lower():
            url = urljoin(base_url, href)
            text = a.get_text(strip=True) or ""
            links.append((url, text))
    # 去重
    seen = set()
    uniq = []
    for url, text in links:
        if url not in seen:
            uniq.append((url, text))
            seen.add(url)
    return uniq

def ensure_outdir(path: str):
    os.makedirs(path, exist_ok=True)
    return os.path.abspath(path)

def content_length(resp: requests.Response):
    try:
        return int(resp.headers.get("Content-Length", "0"))
    except Exception:
        return 0

def download_pdf(url: str, outdir: str, title_text: str, force: bool, session: requests.Session):
    # 生成文件名：优先 URL 文件名；若能匹配 RS 编号则前缀
    base_name = guess_filename_from_url(url)
    rs = detect_rs_number(title_text) or detect_rs_number(base_name)
    if rs and not base_name.lower().startswith(rs.lower()):
        base_name = f"{rs}_{base_name}"
    filename = sanitize_filename(base_name)
    out_path = os.path.join(outdir, filename)

    # 若存在且不强制覆盖，尝试用 HEAD/GET 校验大小相同则跳过
    if os.path.exists(out_path) and not force:
        try:
            head = session.head(url, headers=HEADERS, timeout=15, allow_redirects=True)
            if head.status_code == 200:
                remote_len = int(head.headers.get("Content-Length", "0"))
                local_len = os.path.getsize(out_path)
                if remote_len > 0 and local_len == remote_len:
                    print(f"[skip] 已存在且大小匹配：{filename}")
                    return filename, "skip"
        except Exception:
            pass
        print(f"[skip] 已存在：{filename}（使用 -f 可覆盖）")
        return filename, "skip"

    # 真正下载
    try:
        with session.get(url, headers=HEADERS, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = content_length(r)
            chunk = 64 * 1024
            done = 0
            with open(out_path, "wb") as f:
                for part in r.iter_content(chunk_size=chunk):
                    if part:
                        f.write(part)
                        done += len(part)
                        # 简易进度
                        if total > 0:
                            pct = int(done * 100 / total)
                            sys.stdout.write(f"\r[down] {filename}  {pct:3d}%")
                            sys.stdout.flush()
                sys.stdout.write("\n")
        return filename, "ok"
    except Exception as e:
        print(f"[fail] {filename}: {e}")
        return filename, "fail"

def main():
    parser = argparse.ArgumentParser(description="Download PDFs from Queensland Recognised standards.")
    parser.add_argument("-o", "--outdir", default=DEFAULT_OUTDIR, help="输出目录（默认 ./data/pdfs）")
    parser.add_argument("-f", "--force", action="store_true", help="强制覆盖已存在文件")
    parser.add_argument("--url", default=MAIN_URL, help="列表页 URL（如需自定义）")
    args = parser.parse_args()

    outdir = ensure_outdir(args.outdir)

    with requests.Session() as sess:
        print(f"[fetch] {args.url}")
        html = http_get(args.url, sess, timeout=25).text
        links = parse_pdf_links(html, args.url)
        print(f"[parse] 发现 PDF 链接：{len(links)} 个")

        ok = fail = skip = 0
        for url, text in links:
            print(f"[get ] {text or '(无标题)'}")
            _, status = download_pdf(url, outdir, text, args.force, sess)
            if status == "ok":
                ok += 1
            elif status == "skip":
                skip += 1
            else:
                fail += 1

        print(f"[done] 成功 {ok}，跳过 {skip}，失败 {fail}。输出目录：{outdir}")

if __name__ == "__main__":
    main()
