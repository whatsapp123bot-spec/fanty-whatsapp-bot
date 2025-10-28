# Fanty Bridge — WhatsApp Web.js ↔ Flujo del Panel

Este puente te permite probar tu flujo actual usando tu número real de WhatsApp (no oficial). Escaneas un QR como WhatsApp Web, y el bot responde según tu `flow.json` del editor visual.

## Requisitos
- Node.js 18+
- Backend Flask corriendo local o en Render (usa el endpoint `/send_message`).

## Instalación

```powershell
# En Windows PowerShell, dentro de la carpeta bridge/
npm install
```

## Configuración

El puente llama a tu backend Flask en la URL que definas:

Opción A) Variables de entorno en PowerShell (temporal para esa sesión)
```powershell
# Local
$env:FANTY_BASE = 'http://127.0.0.1:5000'

# Render (reemplaza por tu URL real)
$env:FANTY_BASE = 'https://tu-app-en-render.onrender.com'
```

Opción B) Archivo .env (persistente)
```powershell
Copy-Item .env.example .env
# Edita .env y pon tu FANTY_BASE
```

## Ejecutar

```powershell
npm start
```

- Escanea el QR que verás en la consola.
- Escribe "hola" desde otro teléfono hacia tu número real.
- El bot responderá según tu flujo (frases exactas, palabras clave, botones como opciones 1/2/3).

La consola mostrará la URL objetivo, por ejemplo:
```
🌐 Backend Flask: https://tu-app-en-render.onrender.com
```

## Notas
- Esto es para pruebas rápidas (no oficial). Para producción robusta usa WhatsApp Cloud API (ya soportado en tu backend con multi-cuenta desde el panel ⚙️).
- La sesión queda guardada en `.wwebjs_auth/` para no escanear cada vez.
