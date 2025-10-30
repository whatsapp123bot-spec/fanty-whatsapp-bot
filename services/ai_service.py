import os
import requests
from typing import List, Dict, Optional
from datetime import datetime

AI_ENABLED = os.getenv("AI_ENABLED", "0") == "1"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
STORE_URL = os.getenv("STORE_URL", "")

# Intentar leer claves desde la base de datos de Django si está disponible
def _get_db_openrouter_keys() -> List[str]:
    try:
        # Carga perezosa de Django
        from django.conf import settings as _dj_settings  # noqa: F401
        from mi_chatfuel.bots.models import AIKey  # type: ignore
        # Solo activas, orden por prioridad y menos usadas primero
        rows = AIKey.objects.filter(provider='openrouter', is_active=True).order_by('priority', 'last_used_at').all()
        keys = []
        for r in rows:
            k = (r.api_key or '').strip()
            if k:
                keys.append(k)
        return keys
    except Exception:
        return []


def _mark_key_used_success(api_key: str):
    try:
        from mi_chatfuel.bots.models import AIKey  # type: ignore
        it = AIKey.objects.filter(provider='openrouter', api_key=api_key).first()
        if it:
            it.last_used_at = datetime.utcnow()
            if it.failure_count:
                it.failure_count = 0
            it.save(update_fields=['last_used_at', 'failure_count'])
    except Exception:
        pass


def _mark_key_failure(api_key: str):
    try:
        from mi_chatfuel.bots.models import AIKey  # type: ignore
        it = AIKey.objects.filter(provider='openrouter', api_key=api_key).first()
        if it:
            it.failure_count = (it.failure_count or 0) + 1
            it.last_used_at = datetime.utcnow()
            it.save(update_fields=['failure_count', 'last_used_at'])
    except Exception:
        pass


def _get_all_openrouter_keys_with_fallback() -> List[str]:
    keys = _get_db_openrouter_keys()
    env_key = (OPENROUTER_API_KEY or '').strip()
    if env_key:
        # Colocar ENV al final como último recurso
        if env_key not in keys:
            keys.append(env_key)
    return [k for k in keys if k]


def generate_reply(messages: List[Dict[str, str]], instruction: str = "", timeout: int = 12) -> str:
    """Llama a OpenRouter con rotación de claves (DB + ENV), retorna texto o ''."""
    if not AI_ENABLED:
        return ""
    keys = _get_all_openrouter_keys_with_fallback()
    if not keys:
        return ""
    system_prompt = (
        "Eres 'Fanty', una asistente de WhatsApp amable y concisa para una tienda de lencería. "
        "Ayuda en español latino, sugiere y guía hacia tienda y pagos/envío. "
        f"Tienda: {STORE_URL}. " + (instruction or "")
    )
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "temperature": 0.5,
        "max_tokens": 300,
    }
    base_headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv('OPENROUTER_SITE_URL', STORE_URL) or "",
        "X-Title": os.getenv('OPENROUTER_APP_NAME', 'Fanty WhatsApp Bot'),
    }
    for key in keys:
        try:
            headers = {**base_headers, "Authorization": f"Bearer {key}"}
            resp = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=timeout)
            if 200 <= resp.status_code < 300:
                data = resp.json()
                choices = (data or {}).get('choices') or []
                if choices:
                    content = ((choices[0].get('message') or {}).get('content') or '').strip()
                    _mark_key_used_success(key)
                    return content[:1800]
            # Si status sugiere invalidación o límite, probar siguiente
            if resp.status_code in (401, 403, 429, 500, 502, 503, 504):
                _mark_key_failure(key)
                continue
        except Exception:
            _mark_key_failure(key)
            continue
    return ""


def classify_should_trigger(user_text: str, instruction: str = "", timeout: int = 8) -> bool:
    """Clasifica SI/NO si debe iniciar el flujo según la instrucción del operador.
    Retorna True solo si el modelo responde exactamente 'SI' o 'SÍ'.
    """
    if not AI_ENABLED:
        return False
    keys = _get_all_openrouter_keys_with_fallback()
    if not keys:
        return False
    try:
        system_prompt = (
            "Eres un clasificador binario. Tu ÚNICA salida debe ser 'SI' o 'NO'. "
            "Lee la instrucción del operador y el texto del usuario. "
            "Responde 'SI' solo si el texto cumple estrictamente lo pedido. "
            "Si no estás seguro o no coincide, responde 'NO'."
        )
        user_payload = (
            f"Instrucción del operador: {instruction or 'N/A'}\n"
            f"Texto del usuario: {user_text or ''}\n"
            "Responde exactamente 'SI' o 'NO'."
        )
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            "temperature": 0.0,
            "max_tokens": 3,
        }
        base_headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv('OPENROUTER_SITE_URL', STORE_URL) or "",
            "X-Title": os.getenv('OPENROUTER_APP_NAME', 'Fanty WhatsApp Bot'),
        }
        for key in keys:
            try:
                headers = {**base_headers, "Authorization": f"Bearer {key}"}
                resp = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=timeout)
                if 200 <= resp.status_code < 300:
                    data = resp.json() or {}
                    choices = data.get('choices') or []
                    if choices:
                        content = ((choices[0].get('message') or {}).get('content') or '').strip().lower()
                        _mark_key_used_success(key)
                        return content in ('si', 'sí')
                if resp.status_code in (401, 403, 429, 500, 502, 503, 504):
                    _mark_key_failure(key)
                    continue
            except Exception:
                _mark_key_failure(key)
                continue
        return False
    except Exception:
        return False
