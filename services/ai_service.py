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
        "Eres 'OptiChat', una asistente de WhatsApp amable y concisa para una tienda de lencería. "
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
        "X-Title": os.getenv('OPENROUTER_APP_NAME', 'OptiChat WhatsApp Bot'),
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
            "X-Title": os.getenv('OPENROUTER_APP_NAME', 'OptiChat WhatsApp Bot'),
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


def classify_intent_label(user_text: str, labels: List[str], language: str = "español", timeout: int = 8) -> Optional[str]:
    """Clasifica la intención del usuario en una etiqueta de la lista `labels`.
    - Devuelve exactamente una etiqueta incluida en `labels` o None si no hay confianza.
    - No usa conocimientos externos; sólo clasificación semántica de la frase.
    """
    if not AI_ENABLED:
        return None
    labels = [str(x).strip() for x in (labels or []) if str(x).strip()]
    if not labels:
        return None
    keys = _get_all_openrouter_keys_with_fallback()
    if not keys:
        return None
    allowed = ", ".join(labels)
    try:
        system_prompt = (
            f"Eres un clasificador de intención. Responde en {language}. "
            "Debes responder ÚNICAMENTE con una etiqueta EXACTA de la lista permitida. "
            "Si no estás seguro, responde 'none'.\n"
            f"Etiquetas permitidas: {allowed}"
        )
        user_payload = (
            f"Texto del usuario: {user_text or ''}\n"
            "Responde solo con una etiqueta exacta de la lista, o 'none'."
        )
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            "temperature": 0.0,
            "max_tokens": 6,
        }
        base_headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv('OPENROUTER_SITE_URL', STORE_URL) or "",
            "X-Title": os.getenv('OPENROUTER_APP_NAME', 'OptiChat WhatsApp Bot'),
        }
        for key in keys:
            try:
                headers = {**base_headers, "Authorization": f"Bearer {key}"}
                resp = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=timeout)
                if 200 <= resp.status_code < 300:
                    data = resp.json() or {}
                    choices = data.get('choices') or []
                    if choices:
                        content = ((choices[0].get('message') or {}).get('content') or '').strip()
                        _mark_key_used_success(key)
                        label = content.lower().strip()
                        if label in [l.lower() for l in labels]:
                            # Devuelve etiqueta con el mismo casing de entrada si coincide
                            for l in labels:
                                if l.lower() == label:
                                    return l
                        if label in ('none', 'ninguna'):
                            return None
                if resp.status_code in (401, 403, 429, 500, 502, 503, 504):
                    _mark_key_failure(key)
                    continue
            except Exception:
                _mark_key_failure(key)
                continue
        return None
    except Exception:
        return None


def naturalize_from_answer(user_text: str, base_answer: str, assistant_name: Optional[str] = None, language: str = "español", timeout: int = 8) -> str:
    """Reformula una respuesta determinística en un estilo natural sin agregar información.
    - Debe mantener exactamente los datos (números, URLs, cuentas) del 'base_answer'.
    - Puede ajustar saludo y fluidez, máximo 2-3 frases.
    - Si la IA está deshabilitada o falla, retorna cadena vacía.
    """
    if not AI_ENABLED:
        return ""
    base_answer = (base_answer or '').strip()
    if not base_answer:
        return ""
    keys = _get_all_openrouter_keys_with_fallback()
    if not keys:
        return ""
    try:
        name = (assistant_name or '').strip() or 'Asistente'
        system_prompt = (
            f"Eres {name}, una asistente amable en {language}. "
            "Reescribe la respuesta dada de forma natural y breve (1-2 frases). "
            "NO inventes ni agregues datos que no estén en la respuesta provista. "
            "Mantén números, URLs y nombres exactamente iguales."
        )
        user_payload = (
            f"Pregunta del usuario: {user_text or ''}\n"
            f"Respuesta del sistema (no la alteres en contenido, sólo redacción):\n{base_answer}"
        )
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            "temperature": 0.1,
            "max_tokens": 120,
        }
        base_headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv('OPENROUTER_SITE_URL', STORE_URL) or "",
            "X-Title": os.getenv('OPENROUTER_APP_NAME', 'OptiChat WhatsApp Bot'),
        }
        for key in keys:
            try:
                headers = {**base_headers, "Authorization": f"Bearer {key}"}
                resp = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=timeout)
                if 200 <= resp.status_code < 300:
                    data = resp.json() or {}
                    choices = data.get('choices') or []
                    if choices:
                        content = ((choices[0].get('message') or {}).get('content') or '').strip()
                        _mark_key_used_success(key)
                        return content[:1000]
                if resp.status_code in (401, 403, 429, 500, 502, 503, 504):
                    _mark_key_failure(key)
                    continue
            except Exception:
                _mark_key_failure(key)
                continue
        return ""
    except Exception:
        return ""
