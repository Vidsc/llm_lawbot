# djfrontend/urls.py
from django.urls import path
from django.views.generic import TemplateView
from djfrontend.views import api_chat, api_updates

urlpatterns = [
    path("", TemplateView.as_view(template_name="index.html"), name="home"),
    path("api/chat/", api_chat, name="api_chat"),
    path("api/updates/", api_updates, name="api_updates"),
    path("updates/", TemplateView.as_view(template_name="updates.html"), name="updates"),  # 新增页面
]
