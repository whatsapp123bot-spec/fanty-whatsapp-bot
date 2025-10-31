
from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'usuarios'

    def ready(self):
        # Registrar señales (crear/actualizar superusuario desde ENV, etc.)
        try:
            import mi_chatfuel.usuarios.signals  # noqa: F401
        except Exception:
            # No bloquear el arranque si hay errores en señales
            pass
