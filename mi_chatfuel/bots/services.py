import requests
from django.conf import settings
from .models import MessageLog


def _wa_url(phone_number_id: str) -> str:
    return f"https://graph.facebook.com/{settings.WA_GRAPH_VERSION}/{phone_number_id}/messages"


def send_whatsapp_text(bot, to_number: str, text: str) -> dict:
    url = _wa_url(bot.phone_number_id)
    headers = {
        'Authorization': f'Bearer {bot.access_token}',
        'Content-Type': 'application/json'
    }
    payload = {
        'messaging_product': 'whatsapp',
        'to': to_number,
        'type': 'text',
        'text': {
            'preview_url': False,
            'body': text
        }
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=15)

    status = 'sent' if resp.ok else 'error'
    try:
        data = resp.json()
    except Exception:
        data = {'text': resp.text}

    MessageLog.objects.create(
        bot=bot,
        direction=MessageLog.OUT,
        wa_from=bot.phone_number_id,
        wa_to=to_number,
        message_type='text',
        payload={'request': payload, 'response': data},
        status=status,
        error='' if resp.ok else str(data)
    )

    resp.raise_for_status()
    return data


def send_whatsapp_interactive_buttons(bot, to_number: str, body_text: str, buttons: list[dict]) -> dict:
    """Envía botones de respuesta rápida (máx 3).
    buttons: [{ 'id': 'FLOW:nodo' o 'MENU_PRINCIPAL', 'title': 'Texto' }]
    """
    url = _wa_url(bot.phone_number_id)
    headers = {
        'Authorization': f'Bearer {bot.access_token}',
        'Content-Type': 'application/json'
    }
    # Normalizar a estructura de WA
    btns = [
        { 'type': 'reply', 'reply': { 'id': b['id'], 'title': b['title'][:20] } }
        for b in buttons[:3]
        if (b.get('id') and b.get('title'))
    ]
    payload = {
        'messaging_product': 'whatsapp',
        'to': to_number,
        'type': 'interactive',
        'interactive': {
            'type': 'button',
            'body': { 'text': body_text },
            'action': { 'buttons': btns }
        }
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    status = 'sent' if resp.ok else 'error'
    try:
        data = resp.json()
    except Exception:
        data = {'text': resp.text}
    MessageLog.objects.create(
        bot=bot,
        direction=MessageLog.OUT,
        wa_from=bot.phone_number_id,
        wa_to=to_number,
        message_type='interactive',
        payload={'request': payload, 'response': data},
        status=status,
        error='' if resp.ok else str(data)
    )
    resp.raise_for_status()
    return data


def send_whatsapp_image(bot, to_number: str, link: str, caption: str | None = None) -> dict:
    url = _wa_url(bot.phone_number_id)
    headers = {
        'Authorization': f'Bearer {bot.access_token}',
        'Content-Type': 'application/json'
    }
    payload = {
        'messaging_product': 'whatsapp',
        'to': to_number,
        'type': 'image',
        'image': { 'link': link, **({'caption': caption} if caption else {}) }
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    status = 'sent' if resp.ok else 'error'
    try:
        data = resp.json()
    except Exception:
        data = {'text': resp.text}
    MessageLog.objects.create(
        bot=bot,
        direction=MessageLog.OUT,
        wa_from=bot.phone_number_id,
        wa_to=to_number,
        message_type='image',
        payload={'request': payload, 'response': data},
        status=status,
        error='' if resp.ok else str(data)
    )
    resp.raise_for_status()
    return data


def send_whatsapp_document(bot, to_number: str, link: str, filename: str, caption: str | None = None) -> dict:
    url = _wa_url(bot.phone_number_id)
    headers = {
        'Authorization': f'Bearer {bot.access_token}',
        'Content-Type': 'application/json'
    }
    doc = { 'link': link, 'filename': filename }
    if caption:
        doc['caption'] = caption
    payload = {
        'messaging_product': 'whatsapp',
        'to': to_number,
        'type': 'document',
        'document': doc
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    status = 'sent' if resp.ok else 'error'
    try:
        data = resp.json()
    except Exception:
        data = {'text': resp.text}
    MessageLog.objects.create(
        bot=bot,
        direction=MessageLog.OUT,
        wa_from=bot.phone_number_id,
        wa_to=to_number,
        message_type='document',
        payload={'request': payload, 'response': data},
        status=status,
        error='' if resp.ok else str(data)
    )
    resp.raise_for_status()
    return data


def send_whatsapp_document_id(bot, to_number: str, media_id: str, filename: str, caption: str | None = None) -> dict:
    """Envía un documento usando un media_id previamente subido a la API de WhatsApp.
    Es útil cuando el proveedor del enlace no expone un Content-Type claro; con media_id garantizamos entrega.
    """
    url = _wa_url(bot.phone_number_id)
    headers = {
        'Authorization': f'Bearer {bot.access_token}',
        'Content-Type': 'application/json'
    }
    doc = { 'id': media_id, 'filename': filename }
    if caption:
        doc['caption'] = caption
    payload = {
        'messaging_product': 'whatsapp',
        'to': to_number,
        'type': 'document',
        'document': doc
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    status = 'sent' if resp.ok else 'error'
    try:
        data = resp.json()
    except Exception:
        data = {'text': resp.text}
    MessageLog.objects.create(
        bot=bot,
        direction=MessageLog.OUT,
        wa_from=bot.phone_number_id,
        wa_to=to_number,
        message_type='document',
        payload={'request': payload, 'response': data},
        status=status,
        error='' if resp.ok else str(data)
    )
    resp.raise_for_status()
    return data
