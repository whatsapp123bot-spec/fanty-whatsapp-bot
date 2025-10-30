"""
Compatibility entrypoint for Render.
- Exposes Django WSGI as `app` for `gunicorn app:app`.
- If executed with `python app.py`, runs Django dev server on $PORT.
"""
import os

# Ensure Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mi_chatfuel.mi_chatfuel.settings")

# WSGI for gunicorn
from mi_chatfuel.mi_chatfuel.wsgi import application as app  # noqa: E402

if __name__ == "__main__":
    import django  # noqa: E402
    django.setup()
    from django.core.management import execute_from_command_line  # noqa: E402
    port = os.environ.get("PORT", "8000")
    execute_from_command_line(["manage.py", "runserver", f"0.0.0.0:{port}"])