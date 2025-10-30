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
## Instalación (Windows PowerShell)

```powershell
# 1) Crear y activar entorno
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2) Instalar dependencias
python -m pip install -U pip
python -m pip install -r requirements.txt

# 3) Ejecutar el servidor
python app.py
```

Abre en el navegador: http://127.0.0.1:5000

- Desde el panel abre el Editor visual (🔧) con tu clave (`VERIFY_TOKEN`).
- En el editor visual usa “👀 Vista previa” para abrir `/chat` y probar el flujo (escribe “hola/holi”).

### (Opcional) Probar con tu WhatsApp real (no oficial)

En `bridge/` hay un puente con WhatsApp Web.js para pruebas rápidas usando tu número:

```powershell
cd bridge
npm install
$env:FANTY_BASE = 'https://fanty-whatsapp-bot.onrender.com'  # o tu Flask local
npm start
```

Escanea el QR y prueba escribiendo "hola" desde otro teléfono. El bot responde con tu flujo actual.

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

## Despliegue en Render (HTTPS público)

1) Asegura estos archivos en el repo:
   - `requirements.txt` (contiene: flask, requests, gunicorn)
   - `runtime.txt` (por ejemplo: `python-3.11.5`)
   - `render.yaml` (opcional, blueprint de Render)
   - Carpetas `templates/` y `static/catalogos/`

2) Sube el proyecto a GitHub (ejemplo):
```powershell
git init
git add .
git commit -m "Primer commit del bot Fanty"
git branch -M main
git remote add origin https://github.com/tu_usuario/fanty-whatsapp-bot.git
git push -u origin main
```

3) En Render:
   - Crea un nuevo Web Service desde tu repo
   - Runtime: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - (Si usas `render.yaml`, Render lo detectará y rellenará esto automáticamente.)

4) Una vez desplegado, Render te dará una URL pública HTTPS. Úsala para:
   - Probar el panel (`/`), el chat (`/chat`) y el editor visual (`/flow/builder?key=...`).
   - Configurar el Webhook en WhatsApp Cloud API: `https://<tu-dominio-render>/webhook`.

Notas:
- En local usa `python app.py`. En Render, Gunicorn sirve la app con `app:app`.
- La gestión de assets se realiza desde el editor visual y la API `/internal/upload`; ya no existe `/admin` ni `static/catalogos/`.
- Si configuras `CLOUDINARY_URL`, el builder sube a Cloudinary y elimina al borrar/replace mediante `/internal/delete_asset`.
- Con `DATABASE_URL`, los chats y cuentas persisten en Postgres (recomendado para Render). En local, SQLite sigue funcionando.
