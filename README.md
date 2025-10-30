# Fanty — WhatsApp Bot (Django)

Backend en Django con panel para bots, editor visual de flujos (Builder), chat en vivo y “Cerebro de IA”. Todo lo necesario para operar por WhatsApp Cloud API.

Importante: Se removió el código antiguo de Flask para evitar confusiones. Usa exclusivamente el proyecto Django en `mi_chatfuel/`.

## Características

- Panel de bots con validación encapsulada en modal y estilos modernos.
- Editor visual (“Builder”) con zoom/pan, grid, líneas entre nodos, adjuntos, “Ajustar a pantalla” y “Cerebro de IA”.
- “Cerebro de IA”: define perfil del asistente y perfil del negocio (redes, pagos Yape/Plin/Tarjeta/Transferencia, envíos, políticas, mayorista/menor) guardado en `flow.ai_config`.
- Chat en vivo integrado al panel con selección y badges de no leídos.
- Carga de archivos desde el Builder (imágenes/PDFs) con límite configurable.
- Soporte de múltiples API keys de IA con failover (Admin → AI Keys).

## Requisitos

- Python 3.11+ (probado con 3.13)
- Pip/venv

## Instalación y ejecución (Windows PowerShell)

```powershell
# 1) Crear y activar entorno
python -m venv venv
.\venv\
Scripts\Activate.ps1

# 2) Instalar dependencias de Django
python -m pip install -U pip
python -m pip install -r .\mi_chatfuel\requirements.txt

# 3) Migrar base de datos
python .\mi_chatfuel\manage.py migrate

# 4) (Opcional) Crear superusuario para /admin
python .\mi_chatfuel\manage.py createsuperuser

# 5) Ejecutar servidor de desarrollo
python .\mi_chatfuel\manage.py runserver
```

Accesos típicos:
- Panel: `/panel/`
- Admin: `/admin/` (gestiona Bots, Flows, AI Keys)
- Flujos por bot: `/panel/bots/<bot_id>/flows/`
- Builder: `/panel/bots/<bot_id>/flows/<flow_id>/builder/`
- Webhook de WhatsApp: `/webhooks/whatsapp/<bot_uuid>/`

## Configuración de IA con failover

Variables de entorno mínimas:
- `AI_ENABLED=1` para habilitar IA.
- `OPENROUTER_MODEL` (ej. `openrouter/auto`).

Claves:
- Sube varias claves en `/admin/` → “AI Keys” (provider: OpenRouter). El sistema rota automáticamente con prioridad y marca fallos.
- Si defines `OPENROUTER_API_KEY` en entorno, se usa como último fallback.

## Configuración de WhatsApp Cloud API

En `/admin/` → Bots:
- Phone Number ID
- Access Token
- Verify Token

Webhook de verificación: `/webhooks/whatsapp/<bot_uuid>/`

## Estructura relevante

```
whatsapp-bot/
├─ mi_chatfuel/
│  ├─ manage.py
│  ├─ mi_chatfuel/
│  │  ├─ settings.py
│  │  └─ urls.py
│  ├─ bots/
│  │  ├─ models.py        # Bot, Flow, MessageLog, AIKey
│  │  ├─ views.py         # Panel, live chat, builder, webhook
│  │  └─ admin.py         # Admin de Bot/Flow/MessageLog/AIKey
│  └─ templates/
│     ├─ flow_builder.html
│     └─ bots/
│        ├─ panel.html
│        ├─ live_chat.html
│        └─ flow_form.html
└─ services/
   └─ ai_service.py       # Rotación de API keys para IA (OpenRouter)
```

## Notas

- El antiguo `app.py` (Flask) y sus templates fueron removidos.
- Usa `mi_chatfuel/requirements.txt`. Si existe otro `requirements.txt` en raíz, ignóralo.
- Para archivos subidos desde el Builder, se guardan según `MEDIA_ROOT`/`MEDIA_URL` (configura en settings si lo deseas).
## Despliegue en Render (Django)

Con el archivo `render.yaml` incluido, Render detecta el blueprint automáticamente.

Qué hace:
- Instala dependencias de `mi_chatfuel/requirements.txt`.
- Ejecuta migraciones: `python mi_chatfuel/manage.py migrate`.
- Inicia Gunicorn con `mi_chatfuel.wsgi:application`.

Variables de entorno recomendadas en Render:
- `DJANGO_ALLOWED_HOSTS=*.onrender.com,localhost,127.0.0.1`
- `DATABASE_URL` (Postgres de Render si usas DB persistente)
- `CLOUDINARY_URL` (si activas cargas a Cloudinary)
- `CLOUDINARY_STRICT=1` y `CLOUDINARY_MAX_MB=10` (opcional)
- `VERIFY_TOKEN`, `WHATSAPP_TOKEN`, `PHONE_NUMBER_ID`
- `AI_ENABLED=1`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL=openrouter/auto` (si usas IA)

Flujo de publicación:

```powershell
git add -A
git commit -m "deploy: Django on Render (gunicorn)"
git push
```

Render hará el build y arrancará el servicio web automáticamente.

## Archivos y medios: Cloudinary (opcional)

Si defines `CLOUDINARY_URL` en tu entorno (formato `cloudinary://api_key:api_secret@cloud_name`),
las cargas desde el editor visual se subirán a Cloudinary y devolverán una URL pública segura.

Variables útiles:
- `CLOUDINARY_URL` (obligatoria para activar)
- `CLOUDINARY_FOLDER` (opcional, ej. `fanty/uploads`)
- `CLOUDINARY_STRICT` (1 para exigir Cloudinary y no permitir fallback local; recomendado en producción)
- `CLOUDINARY_MAX_MB` (tamaño máximo permitido; por defecto 10 en Render)

En Render, agrega estas variables en el panel de Environment.

Notas:
- Los PDFs se suben como `resource_type=raw`. En el panel de Cloudinary, búscalos en la sección “Raw” (no “Images”), dentro de la carpeta definida.
- Para archivos grandes (> ~20 MB) se usa carga segmentada (upload_large) automáticamente. Si el tamaño supera `CLOUDINARY_MAX_MB`, la API devolverá error `file_too_large`.

## Base de datos

- Local: usa SQLite (`conversations.db`). No requiere configuración.
- Producción (Render): si defines `DATABASE_URL` apuntando a PostgreSQL, la app lo detecta automáticamente y usa psycopg2.
   - Las tablas necesarias (`users`, `messages`, `accounts`) se crean al iniciar si no existen.
   - Ventajas: persistencia estable (Render reinicia el contenedor), consultas multi-cuenta y chat en vivo duradero.

Variables:
- `DATABASE_URL`: p.ej. `postgres://user:pass@host:5432/dbname`

En `render.yaml` ya está declarado `DATABASE_URL` como variable. Cópiala desde tu instancia de Render PostgreSQL (External Database > External Connection) y pégala en el servicio web.

## Exponer a Internet (opcional)

Con Ngrok:
```powershell
ngrok http 5000
```
Configura tu Webhook en WhatsApp Cloud API con `https://<tu-ngrok>/webhook`.

## Próximos pasos

- Integrar WhatsApp Cloud API (verificación de token, recepción/envío real).
- Guardar mensajes y clics en Firebase o base de datos.
- Enviar multimedia real (imágenes, PDFs, videos cortos) desde la API.

## Troubleshooting (Windows PowerShell)

- Si no puedes activar el entorno por políticas de ejecución:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
- Comprobar versión de Python:
```powershell
python --version
```

## Notas finales

- Usa `mi_chatfuel/requirements.txt` siempre. El antiguo `requirements.txt` de Flask fue eliminado.
- El servidor antiguo `app.py` y los templates en la carpeta raíz también fueron eliminados.
- Para pruebas locales, `python mi_chatfuel/manage.py runserver`.
