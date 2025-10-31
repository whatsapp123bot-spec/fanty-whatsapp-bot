
from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'usuarios'
    
    def ready(self):
        # Registra señales para tareas de inicialización (e.g., crear superusuario desde env)
        try:
            import usuarios.signals  # noqa: F401
        except Exception:
            pass
