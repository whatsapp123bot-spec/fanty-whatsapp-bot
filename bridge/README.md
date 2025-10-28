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

Define la URL del backend Flask (si no usas la predeterminada de Render):

```powershell
# Ejemplo local
$env:FANTY_BASE = 'http://127.0.0.1:5000'

# Ejemplo Render
$env:FANTY_BASE = 'https://fanty-whatsapp-bot.onrender.com'
```

## Ejecutar

```powershell
npm start
```

- Escanea el QR que verás en la consola.
- Escribe "hola" desde otro teléfono hacia tu número real.
- El bot responderá según tu flujo (frases exactas, palabras clave, botones como opciones 1/2/3).

## Notas
- Esto es para pruebas rápidas (no oficial). Para producción robusta usa WhatsApp Cloud API (ya soportado en tu backend con multi-cuenta desde el panel ⚙️).
- La sesión queda guardada en `.wwebjs_auth/` para no escanear cada vez.
