const { Client, LocalAuth, Buttons, List } = require('whatsapp-web.js');
const qrcodeTerminal = require('qrcode-terminal');
const QRCode = require('qrcode');
const express = require('express');
const axios = require('axios');
require('dotenv').config();

// Configura la URL del backend Flask que ya tienes corriendo (local o Render)
// Prioridad: env FANTY_BASE, luego Render, luego localhost
const FLASK_BASE = process.env.FANTY_BASE || process.env.FANTY_URL || 'https://fanty-whatsapp-bot.onrender.com';

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: '.wwebjs_auth' }), // guarda sesión QR
  puppeteer: { headless: true }
});

// Guarda últimas opciones por chat (para permitir responder 1/2/3 o por título)
const lastOptionsByChat = new Map();
// Estado del QR/Conexión para exponer por HTTP
let lastQr = null;
let isReady = false;

client.on('qr', (qr) => {
  lastQr = qr;
  isReady = false;
  // Mostrar también en consola
  try { qrcodeTerminal.generate(qr, { small: true }); } catch (_) {}
  console.log('📱 Escanea este código QR con tu WhatsApp (como WhatsApp Web)');
});

client.on('ready', () => {
  isReady = true;
  lastQr = null;
  console.log('✅ Bot conectado con tu WhatsApp');
  console.log('🌐 Backend Flask:', FLASK_BASE);
});
client.on('disconnected', () => {
  isReady = false;
});

function htmlToText(html) {
  if (!html) return '';
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .trim();
}

async function askFlowWithMessage(text) {
  const res = await axios.post(`${FLASK_BASE}/send_message`,
    new URLSearchParams({ message: text }).toString(),
    { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
  );
  return res.data;
}

async function askFlowWithPayload(payload) {
  const res = await axios.post(`${FLASK_BASE}/send_message`,
    new URLSearchParams({ payload }).toString(),
    { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
  );
  return res.data;
}

function pickOptionByUserReply(options, userText) {
  if (!Array.isArray(options) || options.length === 0) return null;
  const txt = (userText || '').trim();
  // Si responde con número (1..n)
  const num = parseInt(txt, 10);
  if (!isNaN(num) && num >= 1 && num <= options.length) {
    return options[num - 1];
  }
  // Si responde con el título exacto (case-insensitive)
  const found = options.find(o => (o.title || '').toLowerCase() === txt.toLowerCase());
  return found || null;
}

function buildInteractiveMessage(options, promptText) {
  if (!Array.isArray(options) || options.length === 0) return null;
  const text = (promptText && promptText.trim()) ? promptText.trim() : 'Elige una opción:';

  // Hasta 3: usar Buttons (botones rápidos)
  if (options.length <= 3) {
    const btns = options.map(o => ({ id: o.payload || o.title, body: o.title?.slice(0, 20) || 'Opción' }));
    return new Buttons(htmlToText(text), btns, undefined, 'Selecciona una opción');
  }

  // 4 o más: usar List
  const rows = options.map(o => ({ title: o.title || 'Opción', rowId: o.payload || o.title }));
  const sections = [{ title: 'Opciones', rows }];
  return new List(htmlToText(text), 'Abrir menú', sections, 'Menú', '');
}

client.on('message', async (msg) => {
  try {
    if (msg.fromMe) return; // evita eco si tú mismo escribes
    const chatId = msg.from;
    const body = (msg.body || '').trim();

    const prev = lastOptionsByChat.get(chatId) || [];
    let data;

    // Respuestas interactivas nativas
    if (msg.type === 'buttons_response' && msg.selectedButtonId) {
      data = await askFlowWithPayload(msg.selectedButtonId);
    } else if (msg.type === 'list_response' && msg.selectedRowId) {
      data = await askFlowWithPayload(msg.selectedRowId);
    } else {
      // Fallback: texto libre o elegir por número/título
      const chosen = pickOptionByUserReply(prev, body);
      if (chosen && chosen.payload) {
        data = await askFlowWithPayload(chosen.payload);
      } else {
        data = await askFlowWithMessage(body);
      }
    }

    // Construir respuesta
    let replyText = '';
    if (data.response_html) replyText = htmlToText(data.response_html);
    else if (data.response) replyText = data.response;
    else replyText = '🤖 (Sin contenido)';

    // Opciones: intentar enviar como botones/lista nativos
    if (Array.isArray(data.options) && data.options.length > 0) {
      const interactive = buildInteractiveMessage(data.options, replyText);
      if (interactive) {
        try {
          await client.sendMessage(chatId, interactive);
        } catch (e) {
          // Fallback a enumeración si no soporta
          const lines = ['','Elige una opción respondiendo con el número o el texto exacto:'];
          data.options.forEach((o, i) => lines.push(`${i + 1}) ${o.title}`));
          await client.sendMessage(chatId, replyText + '\n' + lines.join('\n'));
        }
      } else {
        // Fallback: enumeración
        const lines = ['','Elige una opción respondiendo con el número o el texto exacto:'];
        data.options.forEach((o, i) => lines.push(`${i + 1}) ${o.title}`));
        await client.sendMessage(chatId, replyText + '\n' + lines.join('\n'));
      }
      lastOptionsByChat.set(chatId, data.options);
    } else {
      lastOptionsByChat.delete(chatId);
      await client.sendMessage(chatId, replyText);
    }
  } catch (err) {
    console.error('Error procesando mensaje:', err?.response?.data || err.message);
    try { await client.sendMessage(msg.from, '⚠️ Error temporal procesando tu mensaje.'); } catch(_) {}
  }
});

client.initialize();
// Servidor HTTP para exponer QR y estado (para el panel Flask)
const app = express();
const PORT = parseInt(process.env.BRIDGE_PORT || process.env.PORT || '3001', 10);
app.get('/status', (req, res) => {
  res.json({ connected: isReady, has_qr: !!lastQr });
});
app.get('/qr.png', async (req, res) => {
  try {
    if (!lastQr) {
      res.status(404).send('No QR');
      return;
    }
    const png = await QRCode.toBuffer(lastQr, { type: 'png', margin: 1, scale: 8 });
    res.setHeader('Content-Type', 'image/png');
    res.send(png);
  } catch (e) {
    res.status(500).send(String(e?.message || e));
  }
});
app.listen(PORT, () => {
  console.log(`📡 Bridge HTTP escuchando en http://127.0.0.1:${PORT}`);
});
