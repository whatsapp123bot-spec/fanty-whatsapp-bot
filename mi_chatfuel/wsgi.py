"""
WSGI puente (plano) para ejecutar el proyecto tanto local como en Render.
Este módulo vive en la carpeta externa 'mi_chatfuel/' y reexporta la app WSGI
apuntando a la configuración real del proyecto en 'mi_chatfuel/mi_chatfuel/'.
"""
import os
from django.core.wsgi import get_wsgi_application

# Asegurar el DJANGO_SETTINGS_MODULE plano
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mi_chatfuel.settings')

# La configuración real está en la subcarpeta interna; definimos el módulo aquí para
# que Django resuelva settings correctamente cuando el paquete externo está en sys.path.
os.environ.setdefault('DJANGO_CONFIGURATION_FALLBACK', 'mi_chatfuel.mi_chatfuel.settings')

# Inicializa la app WSGI
application = get_wsgi_application()
