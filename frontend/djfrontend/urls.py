from django.urls import path
from django.views.generic import TemplateView
from djfrontend.views import api_chat

urlpatterns = [
    path("", TemplateView.as_view(template_name="index.html"), name="home"),
    path("api/chat/", api_chat, name="api_chat"),  # ← 带 /
]
