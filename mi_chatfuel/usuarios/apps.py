from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mi_chatfuel.usuarios'
    
    def ready(self):
        # Registra señales para tareas de inicialización (e.g., crear superusuario desde env)
        try:
            import mi_chatfuel.usuarios.signals  # noqa: F401
        except Exception:
            # Evitar que errores en import bloqueen el arranque; logs de Django mostrarán detalles
            pass
