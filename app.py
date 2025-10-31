"""
Compatibility entrypoint for Render.
- Exposes Django WSGI as `app` for `gunicorn app:app`.
- If executed with `python app.py`, runs Django dev server on $PORT.
"""
import os
import sys
from pathlib import Path

# Ensure Python path so el paquete 'mi_chatfuel' (carpeta externa) sea importable
BASE = Path(__file__).resolve().parent
apps_path = str(BASE / "mi_chatfuel")
if apps_path not in sys.path:
    sys.path.append(apps_path)

# Usamos siempre el módulo plano 'mi_chatfuel.settings' (el archivo real está en la subcarpeta interna)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mi_chatfuel.settings")

# WSGI para gunicorn (módulo plano que reexporta la app)
from mi_chatfuel.wsgi import application as app  # noqa: E402

if __name__ == "__main__":
    import django  # noqa: E402
    django.setup()
    from django.core.management import execute_from_command_line  # noqa: E402
    port = os.environ.get("PORT", "8000")
    execute_from_command_line(["manage.py", "runserver", f"0.0.0.0:{port}"])