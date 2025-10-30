# Mi Chatfuel (Django)

Pequeña plataforma multi-bot para WhatsApp Cloud API, con bots multiusuario, webhook por bot y logs de mensajes.

## Requisitos
- Windows con PowerShell
- Python 3.11+ (probado con 3.13)
- Virtualenv (ya existe en `D:\whatsapp-bot\venv` si sigues este repo)

## Configuración rápida

1. Crear `.env` a partir del ejemplo:

```powershell
Copy-Item .env.example .env
```

Edita `.env` si necesitas cambiar `ALLOWED_HOSTS` o `WA_GRAPH_VERSION`.

2. (Opcional) Instalar dependencias si el entorno está vacío:

```powershell
& D:\whatsapp-bot\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Migraciones:

```powershell
& D:\whatsapp-bot\venv\Scripts\python.exe manage.py migrate
```

4. Crear superusuario (para entrar a `/admin/`):

```powershell
& D:\whatsapp-bot\venv\Scripts\python.exe manage.py createsuperuser
```

5. Ejecutar el servidor de desarrollo:

```powershell
& D:\whatsapp-bot\venv\Scripts\python.exe manage.py runserver
```

Accede a:
- Admin: http://127.0.0.1:8000/admin/
- Webhook (por bot): `GET/POST http://127.0.0.1:8000/webhooks/whatsapp/<uuid>/`

Para usar el webhook, primero crea un Bot en el admin con `phone_number_id`, `access_token` y `verify_token`.

## Estructura relevante
- `bots/models.py`: Bot, Flow (JSON), MessageLog
- `bots/views.py`: Webhook WhatsApp (verificación y recepción básica)
- `bots/services.py`: Envío de texto a WhatsApp (Graph API)
- `mi_chatfuel/settings.py`: Configuración de entorno y apps

## Notas
- `WA_GRAPH_VERSION` por defecto es `v21.0`. Cambia en `.env` si tu app usa otro.
- A futuro: CRUD de Bots/Flows con DRF y builder de flujos.
