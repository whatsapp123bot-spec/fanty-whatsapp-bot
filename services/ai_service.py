import os
import requests
from typing import List, Dict

AI_ENABLED = os.getenv("AI_ENABLED", "0") == "1"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
STORE_URL = os.getenv("STORE_URL", "")


def generate_reply(messages: List[Dict[str, str]], instruction: str = "", timeout: int = 12) -> str:
    """Llama a OpenRouter para generar una respuesta, retorna texto o cadena vacía."""
    if not (AI_ENABLED and OPENROUTER_API_KEY):
        return ""
    try:
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
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv('OPENROUTER_SITE_URL', STORE_URL) or "",
            "X-Title": os.getenv('OPENROUTER_APP_NAME', 'Fanty WhatsApp Bot'),
        }
        resp = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=timeout)
        if 200 <= resp.status_code < 300:
            data = resp.json()
            choices = (data or {}).get('choices') or []
            if choices:
                content = ((choices[0].get('message') or {}).get('content') or '').strip()
                return content[:1800]
        return ""
    except Exception:
        return ""
