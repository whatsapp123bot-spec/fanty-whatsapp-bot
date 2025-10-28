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

    # POST
    data = request.get_json(silent=True) or {}
    try:
        print('Webhook payload:', json.dumps(data)[:2000])
    except Exception:
        pass
    try:
        if 'entry' in data:
            for entry in data.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    messages = value.get('messages')
                    if messages:
                        message = messages[0]
                        from_wa = message.get('from')
                        text = message.get('text', {}).get('body', '')
                        if from_wa and text:
                            send_whatsapp_text(from_wa, f"👋 Hola, soy Fanty. Recibí tu mensaje: {text}")
    except Exception as e:
        # No romper el webhook ante payloads inesperados
        print('Error procesando webhook:', e)
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


def send_whatsapp_text(to: str, body: str) -> None:
    """Envía un mensaje de texto usando WhatsApp Cloud API."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print('WHATSAPP_TOKEN o PHONE_NUMBER_ID no configurados; omitiendo envío.')
        return
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
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code >= 400:
            print('Error enviando mensaje WA:', resp.status_code, resp.text)
    except Exception as e:
        print('Excepción enviando mensaje WA:', e)


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

if __name__ == '__main__':
    # En despliegues como Render, el puerto llega por la variable de entorno PORT
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
