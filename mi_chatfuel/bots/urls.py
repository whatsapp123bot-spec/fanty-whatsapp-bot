from django.urls import path
from . import views2 as views


urlpatterns = [
    path('', views.index, name='home'),
    path('health/', views.health, name='health'),
    path('panel/', views.panel, name='panel'),
    path('panel/bots/new/', views.bot_new, name='bot_new'),
    path('panel/bots/<int:pk>/edit/', views.bot_edit, name='bot_edit'),
    path('panel/bots/<int:pk>/validate/', views.bot_validate, name='bot_validate'),
    path('panel/bots/<int:bot_pk>/flows/', views.flow_list, name='flow_list'),
    path('panel/bots/<int:bot_pk>/flows/new/', views.flow_new, name='flow_new'),
    path('panel/bots/<int:bot_pk>/flows/<int:flow_pk>/edit/', views.flow_edit, name='flow_edit'),
    path('panel/bots/<int:bot_pk>/flows/<int:flow_pk>/builder/', views.flow_builder, name='flow_builder'),
    path('flow', views.flow_save, name='flow_save'),
    path('internal/upload/', views.internal_upload, name='internal_upload'),
    # Preview del builder (como Flask)
    path('chat', views.chat_preview, name='chat_preview'),
    path('send_message', views.send_message_preview, name='send_message_preview'),
    # Live chat en panel
    path('panel/live-chat/', views.panel_live_chat, name='panel_live_chat'),
    path('panel/api/conversations/', views.api_list_conversations, name='api_list_conversations'),
    path('panel/api/conversations/<str:wa_id>/', views.api_get_conversation, name='api_get_conversation'),
    path('panel/api/send/', views.api_panel_send_message, name='api_panel_send_message'),
    path('panel/api/human/', views.api_panel_human_toggle, name='api_panel_human_toggle'),
    path('webhooks/whatsapp/<uuid:bot_uuid>/', views.whatsapp_webhook, name='whatsapp_webhook'),
]
