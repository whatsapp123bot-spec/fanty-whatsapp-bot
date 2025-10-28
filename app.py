import os
import requests
import json
from flask import Flask, request, render_template, jsonify, redirect, url_for, flash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret')

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CATALOG_DIR = os.path.join(BASE_DIR, 'static', 'catalogos')
os.makedirs(CATALOG_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {'.pdf'}

# Variables de entorno para WhatsApp Cloud API
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "fantasia123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# URLs de negocio (configurables por entorno, con valores por defecto actuales)
STORE_URL = os.getenv("STORE_URL", "https://lenceria-fantasia-intima.onrender.com/")
WHATSAPP_ADVISOR_URL = os.getenv("WHATSAPP_ADVISOR_URL", "https://wa.me/51932187068")
FB_URL = os.getenv("FB_URL", "https://web.facebook.com/fantasiaintimaa/")
IG_URL = os.getenv("IG_URL", "https://www.instagram.com/fantasia_intima_lenceria")
TIKTOK_URL = os.getenv("TIKTOK_URL", "https://www.tiktok.com/@fantasa.ntima")

@app.route('/')
def home():
    # Pantalla principal: Vista previa o Agregar catálogos
    return render_template('index.html')


@app.route('/chat')
def chat():
    # Simulador tipo WhatsApp
    return render_template('chat.html')

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    """Endpoint para verificación de Meta y recepción de mensajes de WhatsApp Cloud API."""
    if request.method == 'GET':
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        if token == VERIFY_TOKEN and challenge is not None:
            return challenge
        return 'Token incorrecto', 403

    # POST (cuando llega un mensaje)
    data = request.get_json(silent=True) or {}
    print("📩 DATA RECIBIDA:", data)
    try:
        if 'entry' in data:
            for entry in data.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    messages = value.get('messages')
                    if messages:
                        message = messages[0]
                        print("💬 MENSAJE DETECTADO:", message)
                        from_wa = message.get('from')
                        msg_type = message.get('type')
                        text = ''
                        if msg_type == 'text':
                            text = message.get('text', {}).get('body', '')
                        elif msg_type == 'interactive':
                            interactive = message.get('interactive', {})
                            # Puede ser button_reply o list_reply
                            if interactive.get('type') == 'button_reply':
                                text = interactive.get('button_reply', {}).get('title', '')
                            elif interactive.get('type') == 'list_reply':
                                text = interactive.get('list_reply', {}).get('title', '')
                        else:
                            print(f"ℹ️ Tipo de mensaje no manejado: {msg_type}")
                        print(f"📱 DE: {from_wa} | TIPO: {msg_type} | TEXTO: {text}")
                        if from_wa:
                            # Lógica: si saluda, enviar botones de bienvenida; si pulsa botones, manejar IDs; si no, eco.
                            if msg_type == 'text':
                                low = (text or '').strip().lower()
                                greetings = ("hola", "holi", "buenas", "buenos días", "buenas tardes", "buenas noches")
                                if any(g in low for g in greetings):
                                    send_whatsapp_buttons_welcome(from_wa)
                                else:
                                    reply_text = (
                                        f"👋 Hola, soy Fanty. Recibí tu mensaje: {text}" if text else
                                        "👋 Hola, soy Fanty. Recibí tu mensaje."
                                    )
                                    send_whatsapp_text(from_wa, reply_text)
                            elif msg_type == 'interactive':
                                interactive = message.get('interactive', {})
                                itype = interactive.get('type')
                                reply_id = None
                                if itype == 'button_reply':
                                    reply_id = interactive.get('button_reply', {}).get('id')
                                elif itype == 'list_reply':
                                    reply_id = interactive.get('list_reply', {}).get('id')
                                print("🔘 INTERACTIVE ID:", reply_id)
                                if reply_id in ('VER_CATALOGO', 'VOLVER_CATALOGO'):
                                    # Mostrar las 3 categorías disponibles del catálogo
                                    send_whatsapp_buttons_categories(from_wa)
                                elif reply_id == 'HABLAR_ASESOR':
                                    send_whatsapp_buttons_advisor(from_wa)
                                elif reply_id == 'MAS_OPCIONES':
                                    send_whatsapp_more_options(from_wa)
                                elif reply_id == 'VER_PAGOS':
                                    send_whatsapp_buttons_payments(from_wa)
                                elif reply_id == 'VER_ENVIO':
                                    send_whatsapp_buttons_shipping(from_wa)
                                elif reply_id == 'MENU_PRINCIPAL':
                                    send_whatsapp_buttons_welcome(from_wa)
                                elif reply_id in ('CATALOGO_DISFRAZ', 'CATALOGO_LENCERIA', 'CATALOGO_MALLAS'):
                                    # Enviar PDF como documento si existe; fallback a link por texto
                                    fname = {
                                        'CATALOGO_DISFRAZ': 'disfraz.pdf',
                                        'CATALOGO_LENCERIA': 'lenceria.pdf',
                                        'CATALOGO_MALLAS': 'mallas.pdf',
                                    }.get(reply_id)
                                    fpath = os.path.join(CATALOG_DIR, fname)
                                    if os.path.exists(fpath):
                                        # Construir URL absoluta al estático
                                        base = request.url_root.rstrip('/')
                                        rel = url_for('static', filename=f'catalogos/{fname}')
                                        link = base + rel
                                        label = 'Catálogo'
                                        if reply_id == 'CATALOGO_DISFRAZ':
                                            label = '🔥 Catálogo Disfraz Sexy'
                                        elif reply_id == 'CATALOGO_LENCERIA':
                                            label = '👙 Catálogo Lencería'
                                        elif reply_id == 'CATALOGO_MALLAS':
                                            label = '🧦 Catálogo Mallas'
                                        r = send_whatsapp_document(from_wa, link, fname, caption=label)
                                        if not r or r.get('status', 500) >= 400:
                                            # Fallback a link por texto
                                            send_whatsapp_text(from_wa, f"{label}: {link}")
                                        # Después de enviar el catálogo, ofrecer siguientes pasos guiados
                                        send_whatsapp_post_catalog_options(from_wa)
                                    else:
                                        send_whatsapp_text(from_wa, '⚠️ Aún no hay catálogo cargado para esa categoría.')
                                elif reply_id == 'POSTCATALOGO_COMPRAR':
                                    # Preguntar ubicación para definir métodos de envío
                                    send_whatsapp_buttons_location(from_wa)
                                elif reply_id == 'POSTCATALOGO_IR_TIENDA':
                                    send_whatsapp_store_link(from_wa)
                                elif reply_id == 'UBIC_LIMA':
                                    send_whatsapp_buttons_shipping_lima(from_wa)
                                elif reply_id == 'UBIC_PROVINCIAS':
                                    send_whatsapp_buttons_shipping_provincias(from_wa)
                                elif reply_id == 'ENVIO_LIMA_TREN':
                                    send_whatsapp_buttons_lima_train(from_wa)
                                elif reply_id == 'ENVIO_LIMA_DELIVERY':
                                    send_whatsapp_buttons_lima_delivery(from_wa)
                                elif reply_id == 'PROV_PROVIDE_DATA':
                                    send_whatsapp_text(from_wa, (
                                        '✍️ Por favor responde a este chat con: "Región - Provincia - Distrito (si aplica)"\n'
                                        'Así te cotizamos el costo de envío y te ayudamos a completar tu pedido. '
                                        'Si prefieres, también puedes hablar con una asesora con el botón del menú.'
                                    ))
                                else:
                                    send_whatsapp_text(from_wa, f"Recibí tu selección: {text}")
                    else:
                        statuses = value.get('statuses')
                        if statuses:
                            print("📬 EVENTO DE ESTADO:", statuses)
    except Exception as e:
        # No romper el webhook ante payloads inesperados
        import traceback
        print("❌ Error procesando webhook:")
        traceback.print_exc()
    return 'ok', 200


@app.route('/internal/subscribe')
def internal_subscribe():
    """Suscribe el PHONE_NUMBER_ID a la app para recibir webhooks (solo dev).
    Protección simple con VERIFY_TOKEN como clave.
    """
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return 'Forbidden', 403
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return 'Faltan WHATSAPP_TOKEN o PHONE_NUMBER_ID', 500
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/subscribed_apps"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    try:
        resp = requests.post(url, headers=headers, timeout=10)
        return f"subscribe status: {resp.status_code} body: {resp.text}", resp.status_code
    except Exception as e:
        return f"error: {e}", 500


def send_whatsapp_text(to: str, body: str):
    """Envía un mensaje de texto usando WhatsApp Cloud API."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print('WHATSAPP_TOKEN o PHONE_NUMBER_ID no configurados; omitiendo envío.')
        return None
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    try:
        print("➡️ Enviando mensaje WA:", payload)
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        print("⬅️ Respuesta WA:", resp.status_code, resp.text)
        if resp.status_code >= 400:
            print('Error enviando mensaje WA:', resp.status_code, resp.text)
        return {
            'status': resp.status_code,
            'body': resp.text
        }
    except Exception as e:
        print('Excepción enviando mensaje WA:', e)
        return {
            'status': 0,
            'body': str(e)
        }


def _post_wa(payload: dict):
    """Helper para enviar payloads arbitrarios a la API de WhatsApp con logs."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print('WHATSAPP_TOKEN o PHONE_NUMBER_ID no configurados; omitiendo envío.')
        return {'status': 0, 'body': 'missing creds'}
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        print("➡️ Enviando WA (generic):", payload)
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        print("⬅️ Respuesta WA (generic):", resp.status_code, resp.text)
        return {'status': resp.status_code, 'body': resp.text}
    except Exception as e:
        print('Excepción enviando WA (generic):', e)
        return {'status': 0, 'body': str(e)}


def send_whatsapp_buttons_welcome(to: str):
    """Envía botones de bienvenida (reply buttons)."""
    body_text = (
        "👋 Hola, soy Fanty, tu asistente virtual 🤖\n"
        "¿Qué deseas hacer hoy?"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "VER_CATALOGO", "title": "📦 Ver catálogo"}},
                    {"type": "reply", "reply": {"id": "HABLAR_ASESOR", "title": "ℹ️ Hablar con asesor"}},
                    {"type": "reply", "reply": {"id": "MAS_OPCIONES", "title": "💬 Más opciones"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_buttons_categories(to: str):
    """Envía botones de categorías de catálogo."""
    body_text = (
        "Tenemos estas categorías disponibles.\n"
        "Elige una para ver el catálogo en PDF:" 
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "CATALOGO_DISFRAZ", "title": "🔥 Disfraz Sexy"}},
                    {"type": "reply", "reply": {"id": "CATALOGO_LENCERIA", "title": "👙 Lencería"}},
                    {"type": "reply", "reply": {"id": "CATALOGO_MALLAS", "title": "🧦 Mallas"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_document(to: str, link: str, filename: str, caption: str | None = None):
    """Envía un PDF como documento usando un link público (Render/static)."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "link": link,
            "filename": filename,
        }
    }
    if caption:
        payload["document"]["caption"] = caption
    return _post_wa(payload)


def send_whatsapp_post_catalog_options(to: str):
    """Opciones guiadas tras enviar un catálogo."""
    body_text = (
        "¿Te gustaría avanzar con tu compra o conocer métodos de pago?\n"
        "También puedes visitar nuestra tienda para ver precios y stock."
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "POSTCATALOGO_COMPRAR", "title": "🛒 Quiero comprar"}},
                    {"type": "reply", "reply": {"id": "VER_PAGOS", "title": "💳 Ver pagos"}},
                    {"type": "reply", "reply": {"id": "POSTCATALOGO_IR_TIENDA", "title": "🛍️ Ir a tienda"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_buttons_location(to: str):
    """Pregunta ubicación para definir métodos de envío."""
    body_text = (
        "Para coordinar el envío, cuéntame dónde te encuentras:" 
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "UBIC_LIMA", "title": "🏙️ Estoy en Lima"}},
                    {"type": "reply", "reply": {"id": "UBIC_PROVINCIAS", "title": "🏞️ Provincias"}},
                    {"type": "reply", "reply": {"id": "MENU_PRINCIPAL", "title": "🔙 Menú principal"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_buttons_shipping_lima(to: str):
    """Opciones y políticas de envío para Lima."""
    body_text = (
        "En Lima ofrecemos:\n\n"
        "• 🚉 Entrega en estación de tren: costo adicional de S/5.\n"
        "• 🏠 Delivery a domicilio: costo según distrito.\n\n"
        "Elige una opción para continuar."
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "ENVIO_LIMA_TREN", "title": "🚉 Estación (S/5)"}},
                    {"type": "reply", "reply": {"id": "ENVIO_LIMA_DELIVERY", "title": "🏠 Delivery domicilio"}},
                    {"type": "reply", "reply": {"id": "VOLVER_CATALOGO", "title": "🔙 Regresar al catálogo"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_buttons_shipping_provincias(to: str):
    """Información y guía para envíos a provincias."""
    body_text = (
        "Enviamos a provincias con Olva Courier (2 a 5 días hábiles).\n"
        "El costo depende de tu región/provincia.\n\n"
        "Indícanos tu región y provincia para cotizar, o habla con una asesora."
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "PROV_PROVIDE_DATA", "title": "✍️ Enviar región/prov."}},
                    {"type": "reply", "reply": {"id": "HABLAR_ASESOR", "title": "ℹ️ Hablar con asesor"}},
                    {"type": "reply", "reply": {"id": "VOLVER_CATALOGO", "title": "🔙 Regresar al catálogo"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_buttons_lima_train(to: str):
    """Confirmación e instrucciones para entrega en estación (Lima)."""
    body_text = (
        "✅ Opción: Entrega en estación de tren.\n"
        "Costo adicional: S/5.\n\n"
        "¿Deseas continuar con tu compra?"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "VER_PAGOS", "title": "💳 Ver métodos de pago"}},
                    {"type": "reply", "reply": {"id": "HABLAR_ASESOR", "title": "🗣️ Hablar con asesor"}},
                    {"type": "reply", "reply": {"id": "MENU_PRINCIPAL", "title": "🔙 Menú principal"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_buttons_lima_delivery(to: str):
    """Instrucciones para delivery a domicilio en Lima."""
    body_text = (
        "🚚 Delivery a domicilio en Lima.\n"
        "El costo depende del distrito.\n\n"
        "Por favor responde con tu distrito para cotizar, o habla con una asesora."
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "HABLAR_ASESOR", "title": "🗣️ Hablar con asesor"}},
                    {"type": "reply", "reply": {"id": "VER_PAGOS", "title": "💳 Ver métodos de pago"}},
                    {"type": "reply", "reply": {"id": "MENU_PRINCIPAL", "title": "🔙 Menú principal"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_store_link(to: str):
    """Muestra enlace a la tienda y navegación básica."""
    body_text = (
        f"🛍️ Visita nuestra tienda: {STORE_URL}\n\n"
        "Ahí puedes ver precios actualizados y stock por producto."
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "VER_PAGOS", "title": "💳 Ver métodos de pago"}},
                    {"type": "reply", "reply": {"id": "VOLVER_CATALOGO", "title": "🔙 Regresar al catálogo"}},
                    {"type": "reply", "reply": {"id": "MENU_PRINCIPAL", "title": "🔙 Menú principal"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_buttons_catalog(to: str):
    """Muestra mensaje de catálogo y botones útiles (pagos/envío/menú)."""
    body_text = (
        "Aquí tienes nuestro catálogo de Lencería Fantasía Íntima 😍\n"
        "Puedes ver todos los modelos disponibles y elegir tus favoritos 💕\n"
        f"👉 Visitar tienda virtual: {STORE_URL}"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "VER_PAGOS", "title": "💳 Ver métodos de pago"}},
                    {"type": "reply", "reply": {"id": "VER_ENVIO", "title": "🚚 Ver métodos de envío"}},
                    {"type": "reply", "reply": {"id": "MENU_PRINCIPAL", "title": "🔙 Menú principal"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_buttons_advisor(to: str):
    """Mensaje con enlace a asesora y botón de regreso al menú."""
    body_text = (
        "Perfecto 💌 Te conectaré con una asesora para ayudarte directamente.\n"
        "Haz clic en el siguiente enlace 👇\n"
        f"Chatear con asesora: {WHATSAPP_ADVISOR_URL}"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "MENU_PRINCIPAL", "title": "🔙 Menú principal"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_more_options(to: str):
    """Mensaje con redes sociales y tienda, y botón de regreso al menú."""
    body_text = (
        "🌸 Aquí tienes más opciones para conocernos y seguirnos:\n\n"
        f"💖 Tienda: {STORE_URL}\n"
        f"📘 Facebook: {FB_URL}\n"
        f"📸 Instagram: {IG_URL}\n"
        f"🎵 TikTok: {TIKTOK_URL}"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "MENU_PRINCIPAL", "title": "🔙 Menú principal"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_buttons_payments(to: str):
    """Mensaje con métodos de pago y navegación."""
    body_text = (
        "💳 Aceptamos los siguientes métodos de pago:\n\n"
        "Yape / Plin / Transferencia bancaria 💜\n\n"
        "También puedes pagar contra entrega (solo en zonas disponibles)."
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "VER_ENVIO", "title": "🚚 Ver métodos de envío"}},
                    {"type": "reply", "reply": {"id": "VOLVER_CATALOGO", "title": "🔙 Regresar al catálogo"}},
                    {"type": "reply", "reply": {"id": "MENU_PRINCIPAL", "title": "🔙 Menú principal"}},
                ]
            }
        }
    }
    return _post_wa(payload)


def send_whatsapp_buttons_shipping(to: str):
    """Mensaje con métodos de envío y navegación."""
    body_text = (
        "🚚 Envíos a todo el Perú 🇵🇪\n\n"
        "Lima: entrega en 1 a 2 días hábiles.\n"
        "Provincias: 2 a 5 días hábiles con Olva Courier."
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "VER_PAGOS", "title": "💳 Ver métodos de pago"}},
                    {"type": "reply", "reply": {"id": "VOLVER_CATALOGO", "title": "🔙 Regresar al catálogo"}},
                    {"type": "reply", "reply": {"id": "MENU_PRINCIPAL", "title": "🔙 Menú principal"}},
                ]
            }
        }
    }
    return _post_wa(payload)


@app.route('/send_message', methods=['POST'])
def send_message():
    """Simula la respuesta del bot para la vista previa del chat."""
    user_message = request.form.get('message', '')
    payload = request.form.get('payload')

    # Si llega un payload de botón, priorizarlo
    if payload:
        if payload == 'CATALOGO_DISFRAZ':
            path = os.path.join(CATALOG_DIR, 'disfraz.pdf')
            if os.path.exists(path):
                link = url_for('static', filename='catalogos/disfraz.pdf')
                return jsonify({
                    'response': '🔥 Catálogo Disfraz Sexy',
                    'response_html': f'🔥 Catálogo Disfraz Sexy<br>👉 <a href="{link}" target="_blank">📄 Abrir catálogo</a>'
                })
            else:
                return jsonify({'response': '⚠️ Aún no hay catálogo de Disfraz Sexy cargado.'})
        if payload == 'CATALOGO_LENCERIA':
            path = os.path.join(CATALOG_DIR, 'lenceria.pdf')
            if os.path.exists(path):
                link = url_for('static', filename='catalogos/lenceria.pdf')
                return jsonify({
                    'response': '👙 Catálogo Lencería',
                    'response_html': f'👙 Catálogo Lencería<br>👉 <a href="{link}" target="_blank">📄 Abrir catálogo</a>'
                })
            else:
                return jsonify({'response': '⚠️ Aún no hay catálogo de Lencería cargado.'})
        if payload == 'CATALOGO_MALLAS':
            path = os.path.join(CATALOG_DIR, 'mallas.pdf')
            if os.path.exists(path):
                link = url_for('static', filename='catalogos/mallas.pdf')
                return jsonify({
                    'response': '🧦 Catálogo Mallas',
                    'response_html': f'🧦 Catálogo Mallas<br>👉 <a href="{link}" target="_blank">📄 Abrir catálogo</a>'
                })
            else:
                return jsonify({'response': '⚠️ Aún no hay catálogo de Mallas cargado.'})
        # Payload desconocido
        return jsonify({'response': '❓ Opción no reconocida.'}), 400

    # Sin payload: procesar texto libre
    text = (user_message or '').strip().lower()
    if not text:
        return jsonify({'response': '⚠️ No recibí ningún mensaje.'}), 400

    greetings = ("hola", "holi", "buenas", "buenos días", "buenas tardes", "buenas noches")
    if any(g in text for g in greetings):
        return jsonify({
            'response': '� Hola, soy Fanty, asistente virtual de Fantasía Íntima. ¿En cuál de nuestros catálogos estás interesad@?',
            'options': [
                { 'title': '🔥 Disfraz Sexy', 'payload': 'CATALOGO_DISFRAZ' },
                { 'title': '👙 Lencería', 'payload': 'CATALOGO_LENCERIA' },
                { 'title': '🧦 Mallas', 'payload': 'CATALOGO_MALLAS' }
            ]
        })

    if 'disfraz' in text:
        return jsonify({'response': '🔥 Catálogo Disfraz Sexy (simulación). PDF: https://ejemplo.com/catalogos/disfraz.pdf'})
    if 'lencer' in text:  # captura lencería/lenceria
        return jsonify({'response': '👙 Catálogo Lencería (simulación). PDF: https://ejemplo.com/catalogos/lenceria.pdf'})
    if 'malla' in text:
        return jsonify({'response': '🧦 Catálogo Mallas (simulación). PDF: https://ejemplo.com/catalogos/mallas.pdf'})

    if "pdf" in text:
        return jsonify({'response': '📄 Te enviaría un PDF (simulación).'})
    if "imagen" in text or "foto" in text:
        return jsonify({'response': '🖼️ Aquí te mostraría una imagen (simulación).'})

    return jsonify({'response': '🤖 No entendí tu mensaje, pero pronto aprenderé más.'})


def _allowed_pdf(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS


@app.route('/admin', methods=['GET', 'POST'])
def admin_upload():
    """Panel para subir catálogos PDF por categoría."""
    saved = {}
    error = None
    if request.method == 'POST':
        try:
            files = {
                'disfraz': request.files.get('disfraz'),
                'lenceria': request.files.get('lenceria'),
                'mallas': request.files.get('mallas'),
            }
            for key, f in files.items():
                if not f or f.filename == '':
                    continue
                if not _allowed_pdf(f.filename):
                    error = f'Archivo inválido para {key}. Solo se permiten PDF.'
                    continue
                filename = key + '.pdf'
                # secure_filename por seguridad, aunque forzamos nombre final
                _ = secure_filename(f.filename)
                dest = os.path.join(CATALOG_DIR, filename)
                f.save(dest)
                saved[key] = filename
            if saved and not error:
                flash('✅ Catálogos guardados correctamente: ' + ', '.join(saved.keys()))
            elif error and not saved:
                flash('⚠️ ' + error)
            else:
                flash('ℹ️ No se subió ningún archivo nuevo.')
            return redirect(url_for('admin_upload'))
        except Exception as e:
            flash('❌ Error al subir archivos: ' + str(e))
            return redirect(url_for('admin_upload'))

    # Estado actual (existencia de archivos)
    exists = {
        'disfraz': os.path.exists(os.path.join(CATALOG_DIR, 'disfraz.pdf')),
        'lenceria': os.path.exists(os.path.join(CATALOG_DIR, 'lenceria.pdf')),
        'mallas': os.path.exists(os.path.join(CATALOG_DIR, 'mallas.pdf')),
    }
    return render_template('upload.html', exists=exists)


@app.route('/internal/health')
def internal_health():
    """Revisa estado básico de la app y credenciales. Protegido con ?key=VERIFY_TOKEN."""
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return jsonify({"status": "forbidden"}), 403
    info = {
        "verify_token_set": bool(VERIFY_TOKEN),
        "whatsapp_token_set": bool(WHATSAPP_TOKEN),
        "phone_number_id": PHONE_NUMBER_ID or None,
    }
    # Intentar consultar suscripciones (si hay token y phone_number_id)
    if WHATSAPP_TOKEN and PHONE_NUMBER_ID:
        try:
            url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/subscribed_apps"
            headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
            r = requests.get(url, headers=headers, timeout=10)
            info["subscribed_apps_status"] = r.status_code
            info["subscribed_apps_body"] = r.text
        except Exception as e:
            info["subscribed_apps_error"] = str(e)
    return jsonify(info)


@app.route('/internal/send_test')
def internal_send_test():
    """Envía un mensaje de prueba a un número (E.164), protegido con ?key=VERIFY_TOKEN&to=+NNNN&text=Hola."""
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return 'Forbidden', 403
    to = request.args.get('to')
    text = request.args.get('text') or 'Prueba desde Fanty'
    if not to:
        return 'Falta parámetro to (E.164, ej. +51987654321)', 400
    # Normalizar número: solo dígitos (WA Cloud suele usar sin '+')
    norm_to = ''.join(ch for ch in to if ch.isdigit())
    result = send_whatsapp_text(norm_to, text)
    return jsonify({
        'phone_number_id': PHONE_NUMBER_ID,
        'to': norm_to,
        'result': result
    }), 200


@app.route('/internal/phone_info')
def internal_phone_info():
    """Obtiene info del PHONE_NUMBER_ID desde Graph (id, display_phone_number y WABA relacionado). Protegido con ?key=VERIFY_TOKEN."""
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return jsonify({"status": "forbidden"}), 403
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return jsonify({"error": "Faltan WHATSAPP_TOKEN o PHONE_NUMBER_ID"}), 500
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}"
    params = {
        "fields": "id,display_phone_number,whatsapp_business_account",
    }
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        return jsonify({
            "status": r.status_code,
            "body": r.json() if r.headers.get('content-type','').startswith('application/json') else r.text
        }), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # En despliegues como Render, el puerto llega por la variable de entorno PORT
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
