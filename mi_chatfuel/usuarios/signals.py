import os
from django.db.models.signals import post_migrate
from django.contrib.auth import get_user_model
from django.dispatch import receiver


@receiver(post_migrate)
def create_superuser_from_env(sender, **kwargs):
    """
    Crea un superusuario automáticamente si existen las variables de entorno:
      - DJANGO_SUPERUSER_USERNAME
      - DJANGO_SUPERUSER_PASSWORD
      - DJANGO_SUPERUSER_EMAIL (opcional)
  Es idempotente: si el usuario ya existe, actualiza email y contraseña.
    """
    username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
    password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
    email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")

    if not username or not password:
        return

    User = get_user_model()
    user_qs = User.objects.filter(username=username)
    if user_qs.exists():
        user = user_qs.first()
        updated = False
        if password:
            user.set_password(password)
            updated = True
        if email and user.email != email:
            user.email = email
            updated = True
        # Asegurar flags de superusuario/activo
        if not user.is_active or not user.is_staff or not user.is_superuser:
            user.is_active = True
            user.is_staff = True
            user.is_superuser = True
            updated = True
        if updated:
            user.save()
    else:
        User.objects.create_superuser(username=username, email=email, password=password)
