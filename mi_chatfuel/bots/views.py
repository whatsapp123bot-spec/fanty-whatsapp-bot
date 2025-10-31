"""
En esta versión consolidamos las vistas publicadas desde views2.py y saneamos bot_flows.
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse

from .models import Bot

# Reexportar vistas completas desde views2
from .views2 import (  # noqa: F401
    index,
    health,
    panel,
    panel_live_chat,
    api_list_conversations,
    api_get_conversation,
    api_panel_send_message,
    api_panel_human_toggle,
    bot_new as bot_create,
    bot_edit,
    bot_validate,
    flow_list,
    flow_new,
    flow_edit,
    internal_upload,
    flow_builder,
    flow_save,
    verify_webhook,
    whatsapp_webhook,
    chat_preview,
    send_message_preview,
)


@login_required
def bot_flows(request, bot_uuid):
    """Compat: esta vista ya no se usa; redirige a la lista de flujos del bot."""
    bot = get_object_or_404(Bot, uuid=bot_uuid, owner=request.user)
    return HttpResponseRedirect(reverse('flow_list', args=[bot.id]))
