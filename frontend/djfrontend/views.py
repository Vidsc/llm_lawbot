# djfrontend/views.py
import os, json
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from app.rag import answer as rag_answer

MANIFEST = "./data/manifest.json"

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
