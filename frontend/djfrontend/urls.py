# djfrontend/urls.py
from django.urls import path
from django.views.generic import TemplateView
from djfrontend.views import (
    api_chat,
    api_updates,
    upload_pdf,
    delete_user_pdf,
    api_user_library,
)
from django.views.static import serve as static_serve
from app import config
urlpatterns = [
    path("", TemplateView.as_view(template_name="index.html"), name="home"),
    path("api/chat/", api_chat, name="api_chat"),
    path("api/updates/", api_updates, name="api_updates"),
    path("api/upload/", upload_pdf, name="api_upload"),                     # 上传
    path("api/upload/delete/", delete_user_pdf, name="api_upload_delete"),  # 删除
    path("api/user-library/", api_user_library, name="api_user_library"),   # 列表
    path("updates/", TemplateView.as_view(template_name="updates.html"), name="updates"),
    path(
            "user-files/<path:filename>",
            lambda request, filename: static_serve(
                request, filename, document_root=str(config.USER_PDF_DIR)
            ),
            name="user_file",
        ),
]


