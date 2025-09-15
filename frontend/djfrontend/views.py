import json
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from app.rag import answer as rag_answer

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
        print("[api_chat] incoming:", question)  # 观察后端是否进入这里
        result = rag_answer(question, session_id=session_id)
        print("[api_chat] done, used_retrieval=", result.get("used_retrieval"))
        return JsonResponse(result)
    except Exception as e:
        # 所有异常都走 JSON，避免 Django 返回 HTML debug 页
        return JsonResponse({"error": str(e)}, status=500)
