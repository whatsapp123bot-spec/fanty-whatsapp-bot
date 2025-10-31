import requests
from django.conf import settings
from .models import MessageLog, AIKey


# ======= OpenRouter AI helpers =======

OPENROUTER_API_URL = 'https://openrouter.ai/api/v1/chat/completions'


def _get_active_ai_key() -> str | None:
    try:
        key = AIKey.objects.filter(is_active=True).order_by('priority', 'last_used_at').first()
        return key.api_key if key else None
    except Exception:
        return None


def ai_chat(messages: list[dict], model: str | None = None, temperature: float = 0.3, max_tokens: int | None = 256) -> dict | None:
    api_key = _get_active_ai_key()
    if not api_key:
        return None
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://opti.chat',
        'X-Title': 'OptiChat',
    }
    payload = {
        'model': model or 'openrouter/auto',
        'messages': messages,
        'temperature': temperature,
    }
    if max_tokens:
        payload['max_tokens'] = max_tokens
    try:
        resp = requests.post(OPENROUTER_API_URL, json=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def ai_select_trigger(user_text: str, candidates: list[dict]) -> str | None:
    """Devuelve el id de trigger a activar entre candidates=[{id, patterns}], o None.
    Utiliza OpenRouter para clasificación simple por similitud semántica.
    """
    if not candidates:
        return None
    sys = {
        'role': 'system',
        'content': (
            'Eres un clasificador. Te doy un texto del usuario y una lista de triggers con ejemplos. '
            'Elige el trigger más adecuado y responde sólo con el ID del trigger o NONE si ninguno aplica.'
        )
    }
    user = {
        'role': 'user',
        'content': (
            f"TEXTO: {user_text}\n" +
            "TRIGGERS:\n" +
            "\n".join([f"- id: {c.get('id')}\n  ejemplos: {c.get('patterns') or ''}" for c in candidates]) +
            "\nResponde solo con el id exacto o NONE."
        )
    }
    data = ai_chat([sys, user], temperature=0.0, max_tokens=8)
    if not data:
        return None
    try:
        text = (data.get('choices') or [{}])[0].get('message', {}).get('content', '')
        text = (text or '').strip()
        if not text:
            return None
        if text.upper().startswith('NONE'):
            return None
        # tomar primera palabra como id
        return text.split()[0]
    except Exception:
        return None


def ai_answer(
    user_text: str,
    brand: str = 'OptiChat',
    persona: dict | None = None,
    temperature: float = 0.4,
    max_tokens: int = 220,
) -> str | None:
    """Devuelve una respuesta breve de IA para dudas generales, con persona/"cerebro" opcional.

    persona: {
      'name': str,
      'about': str,        # presentación del asistente/empresa
      'knowledge': str,    # base de conocimiento (FAQ, productos, políticas)
      'style': str,        # tono deseado
      'system': str,       # instrucciones adicionales
    }
    """
    p = persona or {}
    name = (p.get('name') or '').strip() or 'Asistente'
    about = (p.get('about') or p.get('presentation') or '').strip()
    knowledge = (p.get('knowledge') or p.get('brain') or '').strip()
    style = (p.get('style') or 'cálido, directo, profesional').strip()
    sys_extra = (p.get('system') or '').strip()

    rules = [
        f"Te llamas {name}. Perteneces a {brand}.",
        "No digas que eres un modelo de lenguaje o una IA; preséntate como un asistente del negocio.",
        "Usa la base de conocimiento provista; si falta información, pide un dato concreto y sugiere alternativas.",
        "Responde en 1-3 frases. Enlaza pasos claros cuando sea útil.",
    ]
    if about:
        rules.append(f"Presentación: {about}")
    if knowledge:
        rules.append(f"Base de conocimiento:\n{knowledge}")
    if sys_extra:
        rules.append(sys_extra)

    sys = { 'role': 'system', 'content': "\n".join(rules) }
    user = { 'role': 'user', 'content': user_text }
    data = ai_chat([sys, user], temperature=temperature, max_tokens=max_tokens)
    if not data:
        return None
    try:
        return (data.get('choices') or [{}])[0].get('message', {}).get('content', '').strip() or None
    except Exception:
        return None


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
