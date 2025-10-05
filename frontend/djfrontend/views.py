# djfrontend/views.py
import os, json
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from app.rag import answer as rag_answer

MANIFEST = "./data/manifest.json"

import uuid
from pathlib import Path
from app import config
from app.ingest import ingest_single_pdf_file

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


# ✅ 新增接口：返回 manifest.json 的内容
def api_updates(request: HttpRequest):
    if not os.path.exists(MANIFEST):
        return JsonResponse({"items": {}, "checked_at": ""})
    with open(MANIFEST, "r", encoding="utf-8") as f:
        m = json.load(f)
    return JsonResponse(m)

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
        dest = config.PDF_DIR / new_name

        # save to data/pdfs
        with open(dest, "wb") as out:
            for chunk in f.chunks():
                out.write(chunk)

        saved.append(str(dest.relative_to(config.BASE_DIR)))

        # incremental ingest
        try:
            n = ingest_single_pdf_file(str(dest))
            ingested.append({"file": new_name, "chunks": n})
        except Exception as e:
            errors.append({"name": new_name, "error": str(e)})

    return JsonResponse(
        {"saved": saved, "ingested": ingested, "errors": errors},
        status=200 if saved else 400,
    )
