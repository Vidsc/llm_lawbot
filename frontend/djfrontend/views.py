# djfrontend/views.py
import os, json
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from app.rag import answer as rag_answer

MANIFEST = "./data/manifest.json"

import uuid
from pathlib import Path
from app import config
# from app.ingest import ingest_single_pdf_file
from app.ingest import ingest_single_pdf_to_user_store
from app.vectorstore import delete_user_documents_by_filenames


@csrf_exempt
def api_chat(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        data = {}

    question = (data.get("question") or "").strip()
    session_id = data.get("session_id") or "default"

    if not question:
        return JsonResponse({"error": "question is required"}, status=400)

    try:
        result = rag_answer(question, session_id=session_id)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ✅ 返回 manifest.json 的内容（保持不变）
def api_updates(request: HttpRequest):
    MANIFEST = "./data/manifest.json"
    if os.path.exists(MANIFEST):
        try:
            with open(MANIFEST, "r", encoding="utf-8") as f:
                m = json.load(f)
            # m["items"] 形如：{ url: { filename, etag, last_modified, content_length, sha256, updated_at } }
            return JsonResponse({
                "items": m.get("items", {}),
                "checked_at": m.get("checked_at", "")
            })
        except Exception:
            pass  # 读失败则走目录回退

    # —— 回退：仅列出文件名（无 updated_at）——
    pdf_dir = "./data/pdfs"
    items = {}
    if not os.path.exists(pdf_dir):
        os.makedirs(pdf_dir, exist_ok=True)
    for fname in os.listdir(pdf_dir):
        if fname.lower().endswith(".pdf"):
            items[fname] = {"filename": fname}
    return JsonResponse({"items": items, "checked_at": ""})


# Upload Documents
ALLOWED_EXTS = {".pdf"}

@csrf_exempt
def upload_pdf(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    # accept 'file' (single) or 'files' (multiple)
    files = []
    if "file" in request.FILES:
        files = [request.FILES["file"]]
    elif "files" in request.FILES:
        files = request.FILES.getlist("files")

    if not files:
        return JsonResponse({"error": "No file provided. Use 'file' or 'files'."}, status=400)

    saved, ingested, errors = [], [], []
    os.makedirs(config.USER_PDF_DIR, exist_ok=True)


    for f in files:
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in ALLOWED_EXTS:
            errors.append({"name": f.name, "error": "Only .pdf allowed"})
            continue

        # size guard (falls back to 50MB if MAX_UPLOAD_SIZE is missing)
        if f.size > getattr(config, "MAX_UPLOAD_SIZE", 50 * 1024 * 1024):
            errors.append({"name": f.name, "error": "File too large"})
            continue

        # safe filename
        safe_name = f.name.replace("/", "_").replace("\\", "_")
        new_name = f"{Path(safe_name).stem}-{uuid.uuid4().hex[:8]}{ext}"


        dest = config.USER_PDF_DIR / new_name


        # save file
        try:
            with open(dest, "wb") as out:
                for chunk in f.chunks():
                    out.write(chunk)
        except Exception as e:
            errors.append({"name": f.name, "error": f"save failed: {e}"})
            continue

        saved.append(str(dest.relative_to(config.BASE_DIR)))

        # incremental ingest
        try:
            n = ingest_single_pdf_to_user_store(str(dest)) # 到user的库
            ingested.append({"file": new_name, "chunks": n})
        except Exception as e:
            errors.append({"name": new_name, "error": str(e)})

    return JsonResponse(
        {"saved": saved, "ingested": ingested, "errors": errors},
        status=200 if saved else 400,
    )

# 删除用户 PDF + 同步删除向量 + 更新 manifest
def _manifest_remove_entry_by_filename(filename: str) -> None:
    if not os.path.exists(MANIFEST):
        return
    try:
        with open(MANIFEST, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        items = data.get("items") or {}
        to_del = [k for k in items.keys() if k.endswith("/" + filename)]
        for k in to_del:
            items.pop(k, None)
        for k in list(items.keys()):
            v = items.get(k) or {}
            if v.get("filename") == filename:
                items.pop(k, None)
        data["items"] = items
        with open(MANIFEST, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


@csrf_exempt
def delete_user_pdf(request: HttpRequest):
    if request.method != "DELETE":
        return JsonResponse({"error": "DELETE only"}, status=405)

    filename = (request.GET.get("filename") or "").strip()
    if not filename:
        # 兼容部分客户端传 JSON body
        try:
            data = json.loads(request.body.decode("utf-8") or "{}")
            filename = (data.get("filename") or "").strip()
        except Exception:
            filename = ""

    if not filename:
        return JsonResponse({"error": "filename is required"}, status=400)

    # 仅允许删除 user_pdfs 下的文件名
    if "/" in filename or "\\" in filename:
        return JsonResponse({"error": "invalid filename"}, status=400)

    # 删除原文件
    file_removed = False
    path = config.USER_PDF_DIR / filename
    if path.exists():
        try:
            os.remove(path)
            file_removed = True
        except Exception as e:
            return JsonResponse({"error": f"failed to remove file: {e}"}, status=500)

    # 删除用户向量库中的 chunks
    try:
        vectors_deleted = delete_user_documents_by_filenames([filename])
    except Exception as e:
        return JsonResponse({"error": f"failed to delete vectors: {e}"}, status=500)

    # 移除 manifest 项（如果有）
    _manifest_remove_entry_by_filename(filename)

    return JsonResponse({
        "filename": filename,
        "file_removed": file_removed,
        "vectors_deleted": int(vectors_deleted),
    }, status=200)

# 列出 data/user_pdfs 下的 PDF 文件
def api_user_library(request: HttpRequest):
    base = config.USER_PDF_DIR
    os.makedirs(base, exist_ok=True)

    items = []
    for name in sorted(os.listdir(base)):
        if not name.lower().endswith(".pdf"):
            continue
        p = base / name
        try:
            st = p.stat()
            items.append({
                "filename": name,
                "path": str(p.relative_to(config.BASE_DIR)),
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            })
        except FileNotFoundError:
            continue

    return JsonResponse({"items": items})

