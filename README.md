# Fanty — Asistente Virtual de Fantasía Íntima (Flask)

Simulador tipo WhatsApp en Python + Flask donde el asistente “Fanty” responde automáticamente y el administrador puede subir catálogos PDF (Disfraz Sexy, Lencería, Mallas). Funciona localmente y puede exponerse con Ngrok.

## Objetivo

- Editor visual de flujo con vista previa integrada (abre `/chat` desde el propio builder).
- Subir y gestionar assets desde el editor visual (imágenes, PDFs, etc.).
- Responder en el chat con botones o encadenar nodos (conector de salida) y enviar archivos.
- Endpoint `/webhook` listo para la integración con WhatsApp Cloud API.

## Funciones

- Builder visual con flechas y zoom (Ctrl + rueda), guardado asíncrono y “Vista previa” para probar el flujo.
- Inicio por palabras clave o por frases exactas (para links), y nodo de asesor con pausa de flujo y enlaces sociales.
- Chat en vivo para responder manualmente cuando el cliente pida hablar con humano.
- Envío de multimedia (imágenes/PDFs) desde los nodos de acción.

## Tecnologías

- Python 3.x
- Flask (servidor y API)
- HTML + CSS + JavaScript (UI simulada)
- Ngrok o LocalTunnel (opcional)

## Estructura

```
whatsapp-bot/
├─ app.py
├─ templates/
│  ├─ index.html      # Panel principal con accesos al editor y chat en vivo
│  ├─ chat.html       # Simulación tipo WhatsApp (vista previa)
│  ├─ live_chat.html  # Panel de chat en vivo
│  └─ flow_builder.html # Editor visual del flujo
├─ static/
│  └─ uploads/        # Cargados vía /internal/upload desde el builder
├─ requirements.txt
├─ .gitignore
└─ venv/                # (local)
```

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

En Render, agrega estas variables en el panel de Environment.

Nota: Los PDFs se suben como `resource_type=raw` en Cloudinary. En la consola de Cloudinary, revisa la pestaña/tabla “Raw” o filtra por tipo “Raw” para verlos dentro de la carpeta configurada.

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
