const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
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

client.on('qr', (qr) => {
  qrcode.generate(qr, { small: true });
  console.log('📱 Escanea este código QR con tu WhatsApp (como WhatsApp Web)');
});

client.on('ready', () => {
  console.log('✅ Bot conectado con tu WhatsApp');
  console.log('🌐 Backend Flask:', FLASK_BASE);
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

client.on('message', async (msg) => {
  try {
    if (msg.fromMe) return; // evita eco si tú mismo escribes
    const chatId = msg.from;
    const body = (msg.body || '').trim();

    const prev = lastOptionsByChat.get(chatId) || [];
    let data;

    const chosen = pickOptionByUserReply(prev, body);
    if (chosen && chosen.payload) {
      data = await askFlowWithPayload(chosen.payload);
    } else {
      data = await askFlowWithMessage(body);
    }

    // Construir respuesta
    let replyText = '';
    if (data.response_html) replyText = htmlToText(data.response_html);
    else if (data.response) replyText = data.response;
    else replyText = '🤖 (Sin contenido)';

    // Opciones
    if (Array.isArray(data.options) && data.options.length > 0) {
      const lines = ['','Elige una opción respondiendo con el número o el texto exacto:'];
      data.options.forEach((o, i) => lines.push(`${i + 1}) ${o.title}`));
      replyText += '\n' + lines.join('\n');
      lastOptionsByChat.set(chatId, data.options);
    } else {
      lastOptionsByChat.delete(chatId);
    }

    await msg.reply(replyText);
  } catch (err) {
    console.error('Error procesando mensaje:', err?.response?.data || err.message);
    try { await msg.reply('⚠️ Error temporal procesando tu mensaje.'); } catch(_) {}
  }
});

client.initialize();
