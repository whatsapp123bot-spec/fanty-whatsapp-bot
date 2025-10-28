# Fanty — Asistente Virtual de Fantasía Íntima (Flask)

Simulador tipo WhatsApp en Python + Flask donde el asistente “Fanty” responde automáticamente y el administrador puede subir catálogos PDF (Disfraz Sexy, Lencería, Mallas). Funciona localmente y puede exponerse con Ngrok.

## Objetivo

- Vista previa estilo WhatsApp en `http://127.0.0.1:5000`.
- Subir PDFs de catálogos desde un mini panel de administración.
- Responder en el chat con botones y, al elegir una opción, mostrar el PDF subido.
- Endpoint `/webhook` listo para futura integración con WhatsApp Cloud API.

## Funciones

- Vista previa del chat:
   - Escribe “hola/holi/buenas” para ver botones: 🔥 Disfraz Sexy, 👙 Lencería, 🧦 Mallas.
   - Al hacer clic, el bot envía el enlace al PDF correspondiente (si existe).
- Agregar catálogos:
   - Panel para subir PDFs por categoría: se guardan en `static/catalogos/` con nombres fijos.

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
│  ├─ index.html      # Panel principal: Vista previa y Agregar catálogos
│  ├─ chat.html       # Simulación tipo WhatsApp
│  └─ upload.html     # Subida de PDFs
├─ static/
│  └─ catalogos/
│     ├─ disfraz.pdf
│     ├─ lenceria.pdf
│     └─ mallas.pdf
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

- Panel → botones: “Vista previa del chat” y “Agregar catálogos”.
- En “Agregar catálogos”, sube tus PDFs (se guardan como `disfraz.pdf`, `lenceria.pdf`, `mallas.pdf`).
- En “Vista previa del chat”, escribe “hola” y pulsa un botón para ver el PDF.

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
   - Probar el panel (`/`), el chat (`/chat`) y el admin (`/admin`).
   - Configurar el Webhook en WhatsApp Cloud API: `https://<tu-dominio-render>/webhook`.

Notas:
- En local usa `python app.py`. En Render, Gunicorn sirve la app con `app:app`.
- Sube tus PDFs desde `/admin` en producción para que estén disponibles en `static/catalogos/`.
