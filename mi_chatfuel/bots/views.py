"""
En esta versión consolidamos las vistas publicadas desde views2.py y saneamos bot_flows.
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

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
    api_outbox,
)


@login_required
def bot_flows(request, bot_uuid):
    """Compat: esta vista ya no se usa; redirige a la lista de flujos del bot."""
    bot = get_object_or_404(Bot, uuid=bot_uuid, owner=request.user)
    return HttpResponseRedirect(reverse('bots:flow_list', args=[bot.id]))


@csrf_exempt
def whatsapp_webhook_legacy(request):
    """Compatibilidad para clientes antiguos que llaman a /webhook sin UUID.
    Selecciona el bot por ?bot_uuid= / ?uuid= / ?bot= o, si existe exactamente
    un bot activo, usa ese.
    """
    bot_uuid = (request.GET.get('bot_uuid') or request.GET.get('uuid') or request.GET.get('bot') or '').strip()
    bot = None
    if bot_uuid:
        bot = Bot.objects.filter(uuid=bot_uuid, is_active=True).first()
    if not bot:
        qs = Bot.objects.filter(is_active=True)
        if qs.count() == 1:
            bot = qs.first()
    if not bot:
        return JsonResponse({
            'error': 'Webhook no configurado',
            'hint': 'Usa /webhooks/whatsapp/<uuid>/ o añade ?bot_uuid=<uuid> a /webhook',
        }, status=404)
    # Delegar a la vista principal reutilizando su lógica
    return whatsapp_webhook(request, str(bot.uuid))
