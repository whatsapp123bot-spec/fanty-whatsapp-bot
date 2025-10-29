import os
import requests
import sqlite3
import time
import json
from flask import Flask, request, render_template, jsonify, redirect, url_for, flash, g
from werkzeug.utils import secure_filename
try:
    import cloudinary
    import cloudinary.uploader
except Exception:
    cloudinary = None
try:
    import psycopg2
    import psycopg2.extras
except Exception:
    psycopg2 = None

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret')

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_UPLOADS = {'.pdf', '.jpg', '.jpeg', '.png'}

# Cloudinary (opcional)
CLOUDINARY_URL = os.getenv('CLOUDINARY_URL')  # formato: cloudinary://api_key:api_secret@cloud_name
CLOUDINARY_STRICT = os.getenv('CLOUDINARY_STRICT', '0') == '1'  # Si 1, exigir Cloudinary (sin fallback local)
if CLOUDINARY_URL and cloudinary:
    try:
        cloudinary.config(cloudinary_url=CLOUDINARY_URL)
        print('☁️ Cloudinary configurado')
    except Exception as e:
        print('⚠️ No se pudo configurar Cloudinary:', e)

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

# Configuración de flujo dinámico (opcional) controlado por JSON
FLOW_ENABLED = os.getenv("FLOW_ENABLED", "0") == "1"  # Obsoleto en webhook: preferimos flag en flow.json
FLOW_JSON_PATH = os.path.join(BASE_DIR, 'flow.json')
FLOW_CONFIG: dict = {}
CONV_DB_PATH = os.path.join(BASE_DIR, 'conversations.db')

# -------- DB helper (SQLite local / Postgres en Render) --------
DATABASE_URL = os.getenv('DATABASE_URL')
DB_IS_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith(('postgres://', 'postgresql://')) and psycopg2)

def _get_conn():
    if DB_IS_POSTGRES:
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(CONV_DB_PATH)

def _adapt_query(query: str):
    if DB_IS_POSTGRES:
        return query.replace('?', '%s')
    return query

def db_execute(query: str, params: tuple = (), fetch: str | None = None):
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor if DB_IS_POSTGRES else None)
    try:
        cur.execute(_adapt_query(query), params or ())
        result = None
        if fetch == 'one':
            result = cur.fetchone()
        elif fetch == 'all':
            result = cur.fetchall()
        conn.commit()
        return result
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

# -------- Multi-cuenta WhatsApp (configurable desde panel) --------
def init_accounts_db():
    try:
        if DB_IS_POSTGRES:
            db_execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id SERIAL PRIMARY KEY,
                    label TEXT,
                    phone_number_id TEXT,
                    whatsapp_token TEXT,
                    verify_token TEXT,
                    is_default INTEGER DEFAULT 0
                )
                """
            )
            try:
                db_execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS account_id INTEGER")
            except Exception:
                pass
        else:
            db_execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT,
                    phone_number_id TEXT,
                    whatsapp_token TEXT,
                    verify_token TEXT,
                    is_default INTEGER DEFAULT 0
                )
                """
            )
            try:
                db_execute("ALTER TABLE users ADD COLUMN account_id INTEGER")
            except Exception:
                pass
    except Exception as e:
        print('⚠️ Error preparando tabla accounts:', e)


def ensure_default_account_from_env():
    """Si no hay cuentas, crea una por defecto usando las variables de entorno actuales."""
    try:
        row = db_execute("SELECT COUNT(1) AS c FROM accounts", (), fetch='one')
        cnt = (row.get('c') if isinstance(row, dict) else (row[0] if row else 0)) if row is not None else 0
        if cnt == 0 and PHONE_NUMBER_ID and WHATSAPP_TOKEN:
            db_execute(
                "INSERT INTO accounts(label, phone_number_id, whatsapp_token, verify_token, is_default) VALUES (?,?,?,?,1)",
                ("Cuenta principal", PHONE_NUMBER_ID, WHATSAPP_TOKEN, VERIFY_TOKEN)
            )
    except Exception as e:
        print('⚠️ No se pudo crear cuenta por defecto desde ENV:', e)


def get_default_account():
    try:
        row = db_execute("SELECT id,label,phone_number_id,whatsapp_token,verify_token,is_default FROM accounts WHERE is_default=1 ORDER BY id LIMIT 1", (), fetch='one')
        if not row:
            return None
        if isinstance(row, dict):
            return row
        return { 'id': row[0], 'label': row[1], 'phone_number_id': row[2], 'whatsapp_token': row[3], 'verify_token': row[4], 'is_default': row[5] }
    except Exception:
        return None


def get_account_by_phone_number_id(pnid: str):
    try:
        row = db_execute("SELECT id,label,phone_number_id,whatsapp_token,verify_token,is_default FROM accounts WHERE phone_number_id=?", (pnid,), fetch='one')
        if not row:
            return None
        if isinstance(row, dict):
            return row
        return { 'id': row[0], 'label': row[1], 'phone_number_id': row[2], 'whatsapp_token': row[3], 'verify_token': row[4], 'is_default': row[5] }
    except Exception:
        return None

def get_account_by_verify_token(vtok: str):
    try:
        row = db_execute("SELECT id,label,phone_number_id,whatsapp_token,verify_token,is_default FROM accounts WHERE verify_token=?", (vtok,), fetch='one')
        if not row:
            return None
        if isinstance(row, dict):
            return row
        return { 'id': row[0], 'label': row[1], 'phone_number_id': row[2], 'whatsapp_token': row[3], 'verify_token': row[4], 'is_default': row[5] }
    except Exception:
        return None


def list_accounts():
    try:
        rows = db_execute("SELECT id,label,phone_number_id,is_default FROM accounts ORDER BY id", (), fetch='all') or []
        out = []
        for r in rows:
            if isinstance(r, dict):
                out.append({ 'id': r['id'], 'label': r['label'], 'phone_number_id': r['phone_number_id'], 'is_default': r['is_default'] })
            else:
                out.append({ 'id': r[0], 'label': r[1], 'phone_number_id': r[2], 'is_default': r[3] })
        return out
    except Exception:
        return []


def upsert_account(label: str, phone_number_id: str, whatsapp_token: str, verify_token: str, is_default: bool=False, account_id: int=None):
    try:
        if is_default:
            db_execute("UPDATE accounts SET is_default=0")
        if account_id:
            db_execute("UPDATE accounts SET label=?, phone_number_id=?, whatsapp_token=?, verify_token=?, is_default=? WHERE id=?",
                       (label, phone_number_id, whatsapp_token, verify_token, 1 if is_default else 0, account_id))
        else:
            db_execute("INSERT INTO accounts(label, phone_number_id, whatsapp_token, verify_token, is_default) VALUES (?,?,?,?,?)",
                       (label, phone_number_id, whatsapp_token, verify_token, 1 if is_default else 0))
        return True
    except Exception as e:
        print('⚠️ upsert_account error:', e); return False


def delete_account(account_id: int):
    try:
        db_execute("DELETE FROM accounts WHERE id=?", (account_id,))
        return True
    except Exception as e:
        print('⚠️ delete_account error:', e); return False


def init_conversations_db():
    try:
        if DB_IS_POSTGRES:
            db_execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    wa_id TEXT PRIMARY KEY,
                    name TEXT,
                    human_requested INTEGER DEFAULT 0,
                    last_message_at INTEGER DEFAULT 0,
                    last_in_at INTEGER DEFAULT 0,
                    human_timeout_min INTEGER DEFAULT 15,
                    human_expires_at INTEGER DEFAULT 0,
                    account_id INTEGER
                )
                """
            )
            db_execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    wa_id TEXT,
                    direction TEXT,
                    mtype TEXT,
                    body TEXT,
                    ts INTEGER
                )
                """
            )
            # Asegurar columnas nuevas
            try:
                db_execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_in_at INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                db_execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS human_timeout_min INTEGER DEFAULT 15")
            except Exception:
                pass
            try:
                db_execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS human_expires_at INTEGER DEFAULT 0")
            except Exception:
                pass
        else:
            db_execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    wa_id TEXT PRIMARY KEY,
                    name TEXT,
                    human_requested INTEGER DEFAULT 0,
                    last_message_at INTEGER DEFAULT 0,
                    last_in_at INTEGER DEFAULT 0,
                    human_timeout_min INTEGER DEFAULT 15,
                    human_expires_at INTEGER DEFAULT 0
                )
                """
            )
            db_execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wa_id TEXT,
                    direction TEXT, -- 'in' | 'out'
                    mtype TEXT,
                    body TEXT,
                    ts INTEGER
                )
                """
            )
            # Asegurar columnas nuevas
            try:
                db_execute("ALTER TABLE users ADD COLUMN last_in_at INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                db_execute("ALTER TABLE users ADD COLUMN human_timeout_min INTEGER DEFAULT 15")
            except Exception:
                pass
            try:
                db_execute("ALTER TABLE users ADD COLUMN human_expires_at INTEGER DEFAULT 0")
            except Exception:
                pass
    except Exception as e:
        print('⚠️ No se pudo inicializar conversations.db:', e)


def _db_execute(query: str, params: tuple = ()):  # simple helper
    db_execute(query, params)


def save_incoming_message(wa_id: str, body: str, mtype: str = 'text', name: str | None = None, ts: int | None = None):
    try:
        ts = ts or int(time.time())
        exists = db_execute("SELECT wa_id FROM users WHERE wa_id=?", (wa_id,), fetch='one')
        if exists:
            if name:
                db_execute("UPDATE users SET name=?, last_message_at=?, last_in_at=? WHERE wa_id=?", (name, ts, ts, wa_id))
            else:
                db_execute("UPDATE users SET last_message_at=?, last_in_at=? WHERE wa_id=?", (ts, ts, wa_id))
        else:
            db_execute("INSERT INTO users (wa_id, name, last_message_at, last_in_at) VALUES (?,?,?,?)", (wa_id, name or '', ts, ts))
        db_execute("INSERT INTO messages (wa_id, direction, mtype, body, ts) VALUES (?,?,?,?,?)", (wa_id, 'in', mtype, body or '', ts))
    except Exception as e:
        print('⚠️ No se pudo guardar mensaje entrante:', e)


def save_outgoing_message(wa_id: str, body: str, mtype: str = 'text', ts: int | None = None):
    try:
        ts = ts or int(time.time())
        _db_execute("INSERT INTO messages (wa_id, direction, mtype, body, ts) VALUES (?,?,?,?,?)", (wa_id, 'out', mtype, body or '', ts))
        _db_execute("UPDATE users SET last_message_at=? WHERE wa_id=?", (ts, wa_id))
    except Exception as e:
        print('⚠️ No se pudo guardar mensaje saliente:', e)


def set_human_requested(wa_id: str, value: bool):
    try:
        _db_execute("UPDATE users SET human_requested=? WHERE wa_id=?", (1 if value else 0, wa_id))
    except Exception as e:
        print('⚠️ No se pudo actualizar human_requested:', e)


def set_human_on(wa_id: str, timeout_min: int):
    try:
        now = int(time.time())
        expires = now + max(1, int(timeout_min or 15)) * 60
        db_execute("UPDATE users SET human_requested=1, human_timeout_min=?, human_expires_at=? WHERE wa_id=?", (int(timeout_min or 15), expires, wa_id))
        exists = db_execute("SELECT wa_id FROM users WHERE wa_id=?", (wa_id,), fetch='one')
        if not exists:
            db_execute("INSERT INTO users (wa_id, human_requested, human_timeout_min, human_expires_at, last_message_at) VALUES (?,?,?,?,?)", (wa_id, 1, int(timeout_min or 15), expires, now))
    except Exception as e:
        print('⚠️ No se pudo activar chat humano:', e)


def set_human_off(wa_id: str):
    try:
        _db_execute("UPDATE users SET human_requested=0, human_expires_at=0 WHERE wa_id=?", (wa_id,))
    except Exception as e:
        print('⚠️ No se pudo desactivar chat humano:', e)


def list_conversations(limit: int = 100, human_only: bool = False):
    try:
        if human_only:
            rows = db_execute("SELECT wa_id, name, human_requested, last_message_at FROM users WHERE human_requested=1 ORDER BY last_message_at DESC LIMIT ?", (limit,), fetch='all') or []
        else:
            rows = db_execute("SELECT wa_id, name, human_requested, last_message_at FROM users ORDER BY last_message_at DESC LIMIT ?", (limit,), fetch='all') or []
        out = []
        for r in rows:
            if isinstance(r, dict):
                out.append({'wa_id': r.get('wa_id'), 'name': r.get('name') or '', 'human_requested': bool(r.get('human_requested') or 0), 'last_message_at': r.get('last_message_at') or 0})
            else:
                out.append({'wa_id': r[0], 'name': r[1] or '', 'human_requested': bool(r[2] or 0), 'last_message_at': r[3] or 0})
        return out
    except Exception as e:
        print('⚠️ No se pudo listar conversaciones:', e)
        return []


def get_conversation(wa_id: str, limit: int = 200):
    try:
        row_user = db_execute("SELECT human_requested, name FROM users WHERE wa_id=?", (wa_id,), fetch='one')
        if isinstance(row_user, dict):
            human_requested = bool(row_user.get('human_requested') or 0)
            name = row_user.get('name') or ''
        else:
            row_user = row_user or (0, '')
            human_requested = bool(row_user[0] or 0)
            name = row_user[1] or ''
        rows = db_execute("SELECT direction, mtype, body, ts FROM messages WHERE wa_id=? ORDER BY ts ASC, id ASC LIMIT ?", (wa_id, limit), fetch='all') or []
        messages = []
        for r in rows:
            if isinstance(r, dict):
                messages.append({'direction': r.get('direction'), 'mtype': r.get('mtype'), 'body': r.get('body'), 'ts': r.get('ts')})
            else:
                messages.append({'direction': r[0], 'mtype': r[1], 'body': r[2], 'ts': r[3]})
        return {'wa_id': wa_id, 'name': name, 'human_requested': human_requested, 'messages': messages}
    except Exception as e:
        print('⚠️ No se pudo obtener conversación:', e)
        return {'wa_id': wa_id, 'name': '', 'human_requested': False, 'messages': []}


def load_flow_config():
    """Carga el archivo flow.json a memoria."""
    global FLOW_CONFIG
    try:
        if os.path.exists(FLOW_JSON_PATH):
            with open(FLOW_JSON_PATH, 'r', encoding='utf-8') as f:
                FLOW_CONFIG = json.load(f)
            print("🔄 Flujo cargado:", list(FLOW_CONFIG.get('nodes', {}).keys()))
        else:
            FLOW_CONFIG = {}
    except Exception as e:
        print("❌ Error cargando flow.json:", e)
        FLOW_CONFIG = {}


def send_flow_node(to: str, node_id: str):
    """Envía un nodo del flujo según su tipo.
    Tipos soportados:
      - action (default): texto + botones (máx 3). Cada botón puede tener next (FLOW:<id>) o id (acción del bot)
      - advisor: envía un texto y un enlace a wa.me/<phone> configurado en el nodo
      - start: igual que action; además puede tener 'keywords' (solo lectura en el builder)
    """
    node = (FLOW_CONFIG or {}).get('nodes', {}).get(node_id)
    if not node:
        return send_whatsapp_text(to, "⚠️ Flujo no disponible en este paso.")
    ntype = (node.get('type') or 'action').lower()
    text = node.get('text') or ''

    if ntype == 'advisor':
        # Preparar mensaje con enlace directo a WhatsApp del asesor y links de redes/web
        raw_phone = (node.get('phone') or '').strip()
        digits = ''.join(ch for ch in raw_phone if ch.isdigit() or ch == '+')
        link = f"https://wa.me/{digits.lstrip('+')}" if digits else WHATSAPP_ADVISOR_URL

        lines = []
        if text:
            lines.append(text)
        else:
            lines.append("Te estamos transfiriendo con una asesora humana. Un momento por favor.")
        links_cfg = node.get('links') or {}
        if isinstance(links_cfg, dict) and any((links_cfg.get('web') or {}).get('enabled') or (links_cfg.get('fb') or {}).get('enabled') or (links_cfg.get('ig') or {}).get('enabled') or (links_cfg.get('tiktok') or {}).get('enabled')):
            lines.append("\nMientras tanto, puedes revisar:")
            def _add_line(label, key):
                item = links_cfg.get(key) or {}
                if item.get('enabled') and (item.get('url') or '').strip():
                    lines.append(f"• {label}: {item.get('url').strip()}")
            _add_line('Web', 'web')
            _add_line('Facebook', 'fb')
            _add_line('Instagram', 'ig')
            _add_line('TikTok', 'tiktok')
        elif node.get('include_links', True):
            lines.append("\nMientras tanto, puedes revisar:")
            if STORE_URL:
                lines.append(f"• Web: {STORE_URL}")
            if FB_URL:
                lines.append(f"• Facebook: {FB_URL}")
            if IG_URL:
                lines.append(f"• Instagram: {IG_URL}")
            if TIKTOK_URL:
                lines.append(f"• TikTok: {TIKTOK_URL}")
        lines.append(f"\nChatear: {link}")
        body_text = "\n".join(lines)
        # Habilitar chat humano para este usuario con timeout configurable
        try:
            timeout_min = int(node.get('timeout_min') or node.get('human_timeout_min') or 15)
            set_human_on(to, timeout_min)
        except Exception:
            pass
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": "MENU_PRINCIPAL", "title": "🔙 Menú principal"}}
                    ]
                }
            }
        }
        return _post_wa(payload)

    # start: si tiene next, redirigir directamente al siguiente nodo
    if ntype == 'start' and node.get('next'):
        return send_flow_node(to, node.get('next'))

    # Si hay adjuntos (assets), enviarlos primero
    for asset in (node.get('assets') or [])[:5]:
        try:
            atype = (asset.get('type') or '').lower()
            url = asset.get('url') or ''
            name = asset.get('name') or 'archivo.pdf'
            if atype == 'image' and url:
                send_whatsapp_image(to, url)
            elif atype in ('file', 'document') and url:
                send_whatsapp_document(to, url, name)
        except Exception:
            pass

    # action / (start sin next): texto + botones
    raw_buttons = (node.get('buttons') or [])[:3]
    buttons = []
    for b in raw_buttons:
        title = b.get('title') or 'Opción'
        target = None
        if b.get('next'):
            target = f"FLOW:{b['next']}"
        elif b.get('id'):
            target = b['id']
        if not target:
            continue
        buttons.append({"type": "reply", "reply": {"id": target, "title": title}})
    if buttons:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {"buttons": buttons}
            }
        }
        return _post_wa(payload)
    else:
        # Sin botones: enviar texto (si hay) y, si el nodo es de acción y tiene next, encadenar al siguiente
        sent = None
        if text:
            sent = send_whatsapp_text(to, text)
        if ntype == 'action' and node.get('next'):
            try:
                return send_flow_node(to, node.get('next'))
            except Exception:
                pass
        return sent


# Cargar flujo al iniciar
load_flow_config()
init_conversations_db()
init_accounts_db()
ensure_default_account_from_env()

@app.route('/')
def home():
    # Pantalla principal
    return render_template('index.html')


@app.route('/live-chat')
def live_chat_page():
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return 'Forbidden', 403
    return render_template('live_chat.html', key=key)


@app.get('/internal/conversations')
def api_list_conversations():
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return jsonify({'error': 'forbidden'}), 403
    human_only = request.args.get('live') == '1'
    data = list_conversations(limit=int(request.args.get('limit', '100')), human_only=human_only)
    return jsonify({'items': data})


@app.get('/internal/conversations/<wa_id>')
def api_get_conversation(wa_id):
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return jsonify({'error': 'forbidden'}), 403
    data = get_conversation(wa_id)
    return jsonify(data)


@app.post('/internal/send')
def api_send_message():
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return jsonify({'error': 'forbidden'}), 403
    wa_id = (request.form.get('wa_id') or request.json.get('wa_id') if request.is_json else request.form.get('wa_id'))
    text = (request.form.get('text') or (request.json.get('text') if request.is_json else None)) or ''
    if not wa_id or not text.strip():
        return jsonify({'error': 'faltan campos'}), 400
    # Verificar permiso de chat humano
    try:
        row = db_execute("SELECT human_requested FROM users WHERE wa_id=?", (wa_id,), fetch='one')
        allowed = bool((row.get('human_requested') if isinstance(row, dict) else (row[0] if row else 0)) or 0)
    except Exception:
        allowed = False
    if not allowed:
        return jsonify({'error': 'usuario no solicitó chat humano'}), 403
    # Enviar y registrar (la cuenta se resuelve por usuario o g.account)
    send_whatsapp_text(wa_id, text)
    save_outgoing_message(wa_id, text, 'text')
    return jsonify({'ok': True})


@app.post('/internal/human/close')
def api_human_close():
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True) or {}
    wa_id = data.get('wa_id') or request.form.get('wa_id')
    if not wa_id:
        return jsonify({'error': 'faltan campos'}), 400
    set_human_off(wa_id)
    return jsonify({'ok': True})


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
        # Aceptar verify_token del ENV o de cualquier cuenta registrada
        if challenge is not None and (
            token == VERIFY_TOKEN or (get_account_by_verify_token(token) is not None)
        ):
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
                    # Determinar cuenta por phone_number_id del webhook
                    pnid = ((value.get('metadata') or {}).get('phone_number_id')
                            or value.get('phone_number_id'))
                    g.account = get_account_by_phone_number_id(pnid) or get_default_account()
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
                            # Lógica basada SOLO en el flujo del panel (flow.json)
                            if msg_type == 'text':
                                low = (text or '').strip().lower()
                                # Guardar entrante
                                try:
                                    name = None
                                    contacts = value.get('contacts') or []
                                    if contacts:
                                        name = (contacts[0].get('profile') or {}).get('name')
                                    save_incoming_message(from_wa, text or '', 'text', name=name)
                                    # Asociar usuario a la cuenta de este webhook
                                    try:
                                        if getattr(g, 'account', None):
                                            db_execute("UPDATE users SET account_id=? WHERE wa_id=?", (g.account.get('id'), from_wa))
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                                # Control de chat humano (pausar flujo)
                                try:
                                    row = db_execute("SELECT human_requested, human_timeout_min, human_expires_at FROM users WHERE wa_id=?", (from_wa,), fetch='one')
                                    if isinstance(row, dict):
                                        human_requested = int(row.get('human_requested') or 0)
                                        timeout_min = int(row.get('human_timeout_min') or 15)
                                        expires = int(row.get('human_expires_at') or 0)
                                    else:
                                        human_requested = int(((row[0] if row else 0) or 0))
                                        timeout_min = int(((row[1] if row else 15) or 15))
                                        expires = int(((row[2] if row else 0) or 0))
                                    if human_requested == 1:
                                        now = int(time.time())
                                        # Frase para cerrar manualmente desde el cliente
                                        close_phrase = 'cerrar chat en vivo'
                                        if close_phrase in low:
                                            set_human_off(from_wa)
                                            send_whatsapp_text(from_wa, '✅ Chat en vivo cerrado. El asistente continuará atendiéndote.')
                                        else:
                                            # Si venció, desactivar para permitir flujo; si no, extender ventana y no responder
                                            if expires and now > expires:
                                                set_human_off(from_wa)
                                            else:
                                                # Extender por actividad del cliente
                                                set_human_on(from_wa, timeout_min)
                                                return 'ok', 200
                                except Exception:
                                    pass
                                greetings = ("hola", "holi", "buenas", "buenos días", "buenas tardes", "buenas noches")
                                flow_nodes = (FLOW_CONFIG or {}).get('nodes') or {}
                                flow_enabled = (FLOW_CONFIG or {}).get('enabled', True)
                                if flow_enabled and flow_nodes:
                                    matched_node = None
                                    try:
                                        # 1) Match exacto (frases exactas) en nodos de inicio
                                        for nid, ndef in flow_nodes.items():
                                            if (ndef.get('type') or 'action').lower() != 'start':
                                                continue
                                            ex_raw = (ndef.get('exact') or '')
                                            if ex_raw:
                                                # Soporta separar por líneas y comas
                                                parts = []
                                                for line in ex_raw.split('\n'):
                                                    parts.extend([p.strip().lower() for p in line.split(',') if p.strip()])
                                                if any(p and p == low for p in parts):
                                                    matched_node = nid
                                                    break
                                        # 2) Si no hubo exacto, probar por palabras clave (contiene)
                                        if not matched_node:
                                            for nid, ndef in flow_nodes.items():
                                                if (ndef.get('type') or 'action').lower() != 'start':
                                                    continue
                                                kws_raw = (ndef.get('keywords') or '')
                                                if not kws_raw:
                                                    continue
                                                kws = [k.strip().lower() for k in kws_raw.split(',') if k.strip()]
                                                if any(k and k in low for k in kws):
                                                    matched_node = nid
                                                    break
                                    except Exception:
                                        matched_node = None
                                    if matched_node:
                                        send_flow_node(from_wa, matched_node)
                                    elif FLOW_CONFIG.get('start_node') and any(g in low for g in greetings):
                                        send_flow_node(from_wa, FLOW_CONFIG.get('start_node'))
                                    # Si no hay match, no respondemos (solo flujo gestionado por panel)
                            elif msg_type == 'interactive':
                                interactive = message.get('interactive', {})
                                itype = interactive.get('type')
                                reply_id = None
                                if itype == 'button_reply':
                                    reply_id = interactive.get('button_reply', {}).get('id')
                                elif itype == 'list_reply':
                                    reply_id = interactive.get('list_reply', {}).get('id')
                                print("🔘 INTERACTIVE ID:", reply_id)
                                # Si hay chat humano activo, ignorar flujo para interactivos también
                                try:
                                    row = db_execute("SELECT human_requested FROM users WHERE wa_id=?", (from_wa,), fetch='one')
                                    val = (row.get('human_requested') if isinstance(row, dict) else (row[0] if row else 0)) or 0
                                    if int(val) == 1:
                                        return 'ok', 200
                                except Exception:
                                    pass
                                # Guardar entrante de tipo interactivo (como texto con el título si existe)
                                try:
                                    title = ''
                                    if itype == 'button_reply':
                                        title = (interactive.get('button_reply') or {}).get('title') or ''
                                    elif itype == 'list_reply':
                                        title = (interactive.get('list_reply') or {}).get('title') or ''
                                    save_incoming_message(from_wa, title or reply_id or '', 'interactive')
                                except Exception:
                                    pass
                                # Ramas del flujo del panel (ids tipo FLOW:<next>)
                                if reply_id and isinstance(reply_id, str) and reply_id.startswith('FLOW:'):
                                    next_id = reply_id.split(':', 1)[1]
                                    send_flow_node(from_wa, next_id)
                                # Para cualquier otro id, no respondemos (todo se gestiona desde el panel)
                                
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
    """Envía un mensaje de texto usando WhatsApp Cloud API (multi-cuenta)."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    return _post_wa(payload)


def _post_wa(payload: dict):
    """Helper para enviar payloads con la cuenta activa de la request, del usuario, o por defecto."""
    # Resolver cuenta: (1) g.account; (2) por destinatario en users; (3) por defecto; (4) ENV
    acc = None
    try:
        if hasattr(g, 'account') and g.account:
            acc = g.account
    except Exception:
        acc = None
    if not acc:
        try:
            to = payload.get('to')
            if to:
                row = db_execute(
                    "SELECT a.id,a.label,a.phone_number_id,a.whatsapp_token,a.verify_token,a.is_default FROM users u JOIN accounts a ON a.id=u.account_id WHERE u.wa_id=?",
                    (to,), fetch='one'
                )
                if row:
                    if isinstance(row, dict):
                        acc = row
                    else:
                        acc = { 'id': row[0], 'label': row[1], 'phone_number_id': row[2], 'whatsapp_token': row[3], 'verify_token': row[4], 'is_default': row[5] }
        except Exception:
            acc = None
    if not acc:
        acc = get_default_account()
    pnid = (acc or {}).get('phone_number_id') or PHONE_NUMBER_ID
    token = (acc or {}).get('whatsapp_token') or WHATSAPP_TOKEN
    if not pnid or not token:
        print('WHATSAPP_TOKEN o PHONE_NUMBER_ID no configurados; omitiendo envío.')
        return {'status': 0, 'body': 'missing creds'}
    url = f"https://graph.facebook.com/v19.0/{pnid}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        print("➡️ Enviando WA (generic):", payload)
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        print("⬅️ Respuesta WA (generic):", resp.status_code, resp.text)
        # Log básico de salientes si es texto o si tiene body
        try:
            to = payload.get('to')
            if payload.get('type') == 'text':
                body = (payload.get('text') or {}).get('body') or ''
                save_outgoing_message(to, body, 'text')
            elif payload.get('type') == 'interactive':
                body = ((payload.get('interactive') or {}).get('body') or {}).get('text') or ''
                if body:
                    save_outgoing_message(to, body, 'interactive')
        except Exception:
            pass
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


def send_whatsapp_image(to: str, link: str, caption: str | None = None):
    """Envía una imagen usando un link público."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {
            "link": link
        }
    }
    if caption:
        payload["image"]["caption"] = caption
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


def _build_preview_response_for_node(node_id: str):
    nodes = (FLOW_CONFIG or {}).get('nodes') or {}
    node = nodes.get(node_id)
    if not node:
        return {'response': '⚠️ Paso no encontrado en el flujo.'}
    ntype = (node.get('type') or 'action').lower()
    # Redirigir automáticamente si es start con next
    if ntype == 'start' and node.get('next'):
        return _build_preview_response_for_node(node.get('next'))

    # Texto + assets (HTML)
    text = (node.get('text') or '').strip()
    parts = []
    if text:
        parts.append(text.replace('\n', '<br>'))
    for asset in (node.get('assets') or [])[:5]:
        atype = (asset.get('type') or '').lower()
        url = asset.get('url') or ''
        name = asset.get('name') or ''
        if not url:
            continue
        if atype == 'image':
            parts.append(f'<div><img src="{url}" alt="imagen" style="max-width:100%" /></div>')
        else:
            label = name or 'archivo'
            parts.append(f'📄 <a href="{url}" target="_blank">{label}</a>')

    options = []
    if ntype == 'advisor':
        raw_phone = (node.get('phone') or '').strip()
        digits = ''.join(ch for ch in raw_phone if ch.isdigit() or ch == '+')
        link = f"https://wa.me/{digits.lstrip('+')}" if digits else WHATSAPP_ADVISOR_URL
        lines = []
        if not text:
            lines.append("Te estamos transfiriendo con una asesora humana. Un momento por favor.")
        links_cfg = node.get('links') or {}
        any_enabled = False
        if isinstance(links_cfg, dict):
            for k in ('web','fb','ig','tiktok'):
                item = links_cfg.get(k) or {}
                if item.get('enabled') and (item.get('url') or '').strip():
                    any_enabled = True; break
        if any_enabled or node.get('include_links', True):
            lines.append("<br>Mientras tanto, puedes revisar:")
            def _add_line(label, key, url_val):
                if url_val:
                    lines.append(f"• {label}: <a href=\"{url_val}\" target=\"_blank\">{url_val}</a>")
            if any_enabled:
                def _url(k):
                    it = links_cfg.get(k) or {}
                    return it.get('url').strip() if (it.get('enabled') and (it.get('url') or '').strip()) else ''
                _add_line('Web','web', _url('web'))
                _add_line('Facebook','fb', _url('fb'))
                _add_line('Instagram','ig', _url('ig'))
                _add_line('TikTok','tiktok', _url('tiktok'))
            else:
                _add_line('Web','web', STORE_URL)
                _add_line('Facebook','fb', FB_URL)
                _add_line('Instagram','ig', IG_URL)
                _add_line('TikTok','tiktok', TIKTOK_URL)
        lines.append(f"<br>Chatear: <a href=\"{link}\" target=\"_blank\">{link}</a>")
        parts.append('<br>'.join(lines))
        start_id = (FLOW_CONFIG or {}).get('start_node')
        if start_id:
            options.append({'title': '🔙 Menú principal', 'payload': f'FLOW:{start_id}'})
        return {'response_html': '<br>'.join(parts) if parts else 'Asesor humano', 'options': options}

    # Botones
    raw_buttons = (node.get('buttons') or [])[:3]
    for b in raw_buttons:
        title = b.get('title') or 'Opción'
        if b.get('next'):
            options.append({'title': title, 'payload': f"FLOW:{b['next']}"})
        elif b.get('id'):
            options.append({'title': title, 'payload': b.get('id')})
    if not options and ntype == 'action' and node.get('next'):
        options.append({'title': '➡️ Siguiente', 'payload': f"FLOW:{node.get('next')}"})

    resp = {}
    if parts:
        resp['response_html'] = '<br>'.join(parts)
    else:
        resp['response'] = text or ' '
    if options:
        resp['options'] = options
    return resp


@app.route('/send_message', methods=['POST'])
def send_message():
    """Vista previa conectada al flow.json (sin usar catálogos antiguos)."""
    user_message = request.form.get('message', '')
    payload = request.form.get('payload')

    if payload:
        if isinstance(payload, str) and payload.startswith('FLOW:'):
            next_id = payload.split(':', 1)[1]
            return jsonify(_build_preview_response_for_node(next_id))
        if payload == 'MENU_PRINCIPAL' and (FLOW_CONFIG or {}).get('start_node'):
            return jsonify(_build_preview_response_for_node(FLOW_CONFIG.get('start_node')))
        return jsonify({'response': 'ℹ️ Esta acción no se simula en vista previa.'})

    low = (user_message or '').strip().lower()
    if not low:
        return jsonify({'response': '⚠️ Escribe un mensaje para empezar.'}), 400

    flow_nodes = (FLOW_CONFIG or {}).get('nodes') or {}
    flow_enabled = (FLOW_CONFIG or {}).get('enabled', True)
    if flow_enabled and flow_nodes:
        try:
            for nid, ndef in flow_nodes.items():
                if (ndef.get('type') or 'action').lower() != 'start':
                    continue
                ex_raw = (ndef.get('exact') or '')
                if ex_raw:
                    parts = []
                    for line in ex_raw.split('\n'):
                        parts.extend([p.strip().lower() for p in line.split(',') if p.strip()])
                    if any(p and p == low for p in parts):
                        return jsonify(_build_preview_response_for_node(nid))
        except Exception:
            pass
        try:
            for nid, ndef in flow_nodes.items():
                if (ndef.get('type') or 'action').lower() != 'start':
                    continue
                kws_raw = (ndef.get('keywords') or '')
                if not kws_raw:
                    continue
                kws = [k.strip().lower() for k in kws_raw.split(',') if k.strip()]
                if any(k and k in low for k in kws):
                    return jsonify(_build_preview_response_for_node(nid))
        except Exception:
            pass
        greetings = ("hola", "holi", "buenas", "buenos días", "buenas tardes", "buenas noches")
        if (FLOW_CONFIG or {}).get('start_node') and any(g in low for g in greetings):
            return jsonify(_build_preview_response_for_node(FLOW_CONFIG.get('start_node')))
    return jsonify({'response': '🤖 No hay un match en el flujo para tu mensaje.'})


def _allowed_upload(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_UPLOADS


## Ruta /admin eliminada: la gestión de assets se hace vía /internal/upload desde el editor visual.


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


@app.route('/internal/upload', methods=['POST'])
def internal_upload():
    """Sube un archivo (pdf/jpg/png) y devuelve su URL pública. Protegido con ?key=VERIFY_TOKEN o form key.
    Retorna: { url, name, ext }
    """
    key = request.args.get('key') or request.form.get('key')
    if key != VERIFY_TOKEN:
        return jsonify({"error": "forbidden"}), 403
    if 'file' not in request.files:
        return jsonify({"error": "missing file"}), 400
    f = request.files['file']
    if not f or f.filename == '':
        return jsonify({"error": "empty filename"}), 400
    _, ext = os.path.splitext(f.filename)
    if not _allowed_upload(f.filename):
        return jsonify({"error": "invalid type"}), 400
    try:
        # Leer bytes una vez para permitir fallback sin perder el stream
        data = f.read()
        if not data:
            return jsonify({"error": "file is empty"}), 400

        # Si está configurado Cloudinary, intentar subir ahí primero
        if CLOUDINARY_URL and cloudinary:
            try:
                resource_type = 'image' if ext.lower() in ('.jpg', '.jpeg', '.png') else 'raw'
                base_name = secure_filename(os.path.basename(f.filename)) or 'file'
                up = cloudinary.uploader.upload(
                    data,
                    resource_type=resource_type,
                    folder=os.getenv('CLOUDINARY_FOLDER', 'fanty/uploads'),
                    use_filename=True,
                    unique_filename=False,
                    filename=base_name
                )
                url = up.get('secure_url') or up.get('url')
                public_id = up.get('public_id')
                name = base_name
                return jsonify({
                    "url": url,
                    "name": name,
                    "ext": ext.lower(),
                    "provider": "cloudinary",
                    "public_id": public_id,
                    "resource_type": resource_type
                }), 200
            except Exception as ce:
                # Log y continuar con fallback local
                try:
                    print('⚠️ Cloudinary upload failed, falling back to local:', ce)
                except Exception:
                    pass
                if CLOUDINARY_STRICT:
                    # En modo estricto, no permitir fallback local
                    return jsonify({"error": "cloudinary_upload_failed", "detail": str(ce)}), 500

        # Fallback: guardar local en static/uploads
        base_name = secure_filename(os.path.basename(f.filename)) or 'file'
        # Asegura extensión .pdf para PDFs, para Content-Type correcto en navegador
        root, current_ext = os.path.splitext(base_name)
        if ext.lower() == '.pdf' and current_ext.lower() != '.pdf':
            base_name = root + '.pdf'
        name = base_name
        dest = os.path.join(UPLOAD_DIR, name)
        # Evitar colisiones añadiendo sufijo
        i = 1
        while os.path.exists(dest):
            name = f"{os.path.splitext(base_name)[0]}_{i}{ext}"
            dest = os.path.join(UPLOAD_DIR, name)
            i += 1
        with open(dest, 'wb') as out:
            out.write(data)
        base_url = request.url_root.rstrip('/')
        rel = url_for('static', filename=f'uploads/{name}')
        url = base_url + rel
        return jsonify({
            "url": url,
            "name": name,
            "ext": ext.lower(),
            "provider": "local"
        }), 200
    except Exception as e:
        # Loguear para diagnóstico y responder 500
        try:
            print('❌ Upload error:', e)
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


def _extract_cloudinary_public_id_from_url(url: str) -> tuple[str|None, str|None]:
    """Devuelve (public_id, resource_type) a partir de una URL de Cloudinary si es posible."""
    try:
        # Ej: https://res.cloudinary.com/<cloud>/<type>/upload/v1729/fanty/uploads/name.ext
        # type puede ser image, raw, video
        from urllib.parse import urlparse
        p = urlparse(url)
        parts = [s for s in p.path.split('/') if s]
        # parts: [<cloud_name?>, <resource_type>, 'upload', 'vXXXX', 'folder', 'name.ext'] o similar
        if 'upload' in parts:
            idx = parts.index('upload')
            if idx >= 1 and idx+1 < len(parts):
                resource_type = parts[idx-1]  # image|raw|video
                tail = parts[idx+1:]
                # omitir prefijo de versión si comienza con vNNN
                if tail and tail[0].startswith('v') and tail[0][1:].isdigit():
                    tail = tail[1:]
                if tail:
                    filename = tail[-1]
                    noext = os.path.splitext(filename)[0]
                    # public_id = (folder/...)/noext
                    public_id = '/'.join(tail[:-1] + [noext]) if len(tail) > 1 else noext
                    return public_id, resource_type
        return None, None
    except Exception:
        return None, None


@app.post('/internal/delete_asset')
def internal_delete_asset():
    """Elimina un asset remoto (Cloudinary) o local (static/uploads). Protegido con ?key=VERIFY_TOKEN o form key.
    Acepta JSON o form con campos:
      - provider: 'cloudinary' | 'local'
      - public_id (opcional para cloudinary)
      - url (opcional, se usará para derivar public_id o nombre local)
      - resource_type: 'image' | 'raw' (opcional)
    """
    key = request.args.get('key') or request.form.get('key')
    if key != VERIFY_TOKEN:
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or request.form
    provider = (data.get('provider') or '').strip().lower()
    url_val = (data.get('url') or '').strip()
    if provider == 'cloudinary' and CLOUDINARY_URL and cloudinary:
        public_id = (data.get('public_id') or '').strip()
        resource_type = (data.get('resource_type') or '').strip() or None
        if not public_id and url_val:
            public_id, inferred_type = _extract_cloudinary_public_id_from_url(url_val)
            if not resource_type:
                resource_type = inferred_type or 'image'
        if not public_id:
            return jsonify({"error": "missing public_id/url"}), 400
        try:
            # cloudinary.uploader.destroy soporta resource_type='image' por defecto; para raw/video se debe indicar
            resp = cloudinary.uploader.destroy(public_id, resource_type=resource_type or 'image')
            return jsonify({"ok": True, "result": resp}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    elif provider == 'local' or not provider:
        # Borrar archivo de static/uploads por nombre tomado desde la URL
        try:
            from urllib.parse import urlparse
            p = urlparse(url_val)
            name = os.path.basename(p.path) if p and p.path else (data.get('name') or '')
            if not name:
                return jsonify({"error": "missing name/url"}), 400
            dest = os.path.join(UPLOAD_DIR, secure_filename(name))
            if os.path.exists(dest):
                os.remove(dest)
            return jsonify({"ok": True}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify({"error": "unknown provider or cloudinary not configured"}), 400


@app.route('/settings', methods=['GET', 'POST'])
def settings_page():
    """Panel para gestionar múltiples cuentas de WhatsApp. Protegido con ?key=VERIFY_TOKEN."""
    key = request.values.get('key')
    if key != VERIFY_TOKEN:
        return 'Forbidden', 403
    msg = None
    # Acciones via GET: make_default / delete
    if request.method == 'GET':
        action = request.args.get('action')
        aid = request.args.get('id')
        if action and aid:
            try:
                aid_int = int(aid)
                if action == 'make_default':
                    upsert_account(label='', phone_number_id='', whatsapp_token='', verify_token='', is_default=True, account_id=aid_int)
                    msg = '✅ Cuenta marcada como predeterminada.'
                elif action == 'delete':
                    delete_account(aid_int)
                    msg = '🗑️ Cuenta eliminada.'
            except Exception:
                msg = '⚠️ Acción inválida.'
    # Crear/actualizar via POST (solo crear simple en esta versión)
    if request.method == 'POST':
        label = (request.form.get('label') or '').strip()
        pnid = (request.form.get('phone_number_id') or '').strip()
        wtok = (request.form.get('whatsapp_token') or '').strip()
        vtok = (request.form.get('verify_token') or '').strip()
        is_def = request.form.get('is_default') == '1'
        if label and pnid and wtok:
            ok = upsert_account(label, pnid, wtok, vtok, is_def)
            msg = '✅ Cuenta guardada.' if ok else '❌ No se pudo guardar la cuenta.'
        else:
            msg = '⚠️ Faltan campos requeridos.'
    return render_template('settings.html', accounts=list_accounts(), key=key, message=msg)


@app.route('/flow', methods=['GET', 'POST'])
@app.route('/flow/', methods=['GET', 'POST'])
def flow_editor():
    """Editor simple del flujo en JSON. Protegido con ?key=VERIFY_TOKEN."""
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return 'Forbidden', 403
    if request.method == 'POST':
        content = request.form.get('content', '')
        try:
            data = json.loads(content)
            with open(FLOW_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            load_flow_config()
            # Respuesta JSON opcional para guardado sin redirección (desde el builder)
            if request.args.get('format') == 'json':
                return jsonify({"ok": True, "message": "✅ Flujo guardado correctamente."}), 200
            flash('✅ Flujo guardado correctamente.')
            return redirect(url_for('flow_editor', key=key))
        except Exception as e:
            if request.args.get('format') == 'json':
                return jsonify({"ok": False, "error": str(e)}), 400
            flash('❌ Error guardando flujo: ' + str(e))
            return render_template('flow.html', content=content)
    else:
        current = ''
        try:
            if os.path.exists(FLOW_JSON_PATH):
                with open(FLOW_JSON_PATH, 'r', encoding='utf-8') as f:
                    current = f.read()
        except Exception:
            current = ''
        return render_template('flow.html', content=current)


@app.route('/internal/reload_flow')
def internal_reload_flow():
    """Recarga flow.json a memoria. Protegido con ?key=VERIFY_TOKEN."""
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return 'Forbidden', 403
    load_flow_config()
    return jsonify({"status": "ok", "nodes": list((FLOW_CONFIG or {}).get('nodes', {}).keys())})


@app.route('/flow/builder')
@app.route('/flow/builder/')
def flow_builder():
    """Editor visual simple del flujo (nodos y conexiones). Protegido con ?key=VERIFY_TOKEN."""
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return 'Forbidden', 403
    current = {"start_node": None, "nodes": {}}
    try:
        if os.path.exists(FLOW_JSON_PATH):
            with open(FLOW_JSON_PATH, 'r', encoding='utf-8') as f:
                current = json.load(f)
    except Exception:
        pass
    # Render con los datos actuales y la key para reusar el guardado en /flow
    return render_template(
        'flow_builder.html',
        flow=current,
        key=key,
        store_url=STORE_URL,
        fb_url=FB_URL,
        ig_url=IG_URL,
        tiktok_url=TIKTOK_URL,
    )


@app.route('/internal/send_test')
def internal_send_test():
    """Envía un mensaje de prueba a un número (E.164).
    Params: ?key=VERIFY_TOKEN&to=+NNNN&text=Hola[&account_id=ID]
    """
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return 'Forbidden', 403
    to = request.args.get('to')
    text = request.args.get('text') or 'Prueba desde Fanty'
    account_id = request.args.get('account_id')
    if not to:
        return 'Falta parámetro to (E.164, ej. +51987654321)', 400
    # Normalizar número: solo dígitos (WA Cloud suele usar sin '+')
    norm_to = ''.join(ch for ch in to if ch.isdigit())
    # Si se indica account_id, establecerla en g.account temporalmente
    if account_id:
        try:
            row = db_execute("SELECT id,label,phone_number_id,whatsapp_token,verify_token,is_default FROM accounts WHERE id=?", (account_id,), fetch='one')
            if row:
                if isinstance(row, dict):
                    g.account = row
                else:
                    g.account = { 'id': row[0], 'label': row[1], 'phone_number_id': row[2], 'whatsapp_token': row[3], 'verify_token': row[4], 'is_default': row[5] }
        except Exception:
            pass
    result = send_whatsapp_text(norm_to, text)
    return jsonify({
        'phone_number_id': (getattr(g, 'account', None) or {}).get('phone_number_id') or PHONE_NUMBER_ID,
        'to': norm_to,
        'result': result
    }), 200


@app.route('/internal/phone_info')
def internal_phone_info():
    """Obtiene info del PHONE_NUMBER_ID desde Graph.
    Params: ?key=VERIFY_TOKEN[&account_id=ID]
    Si no se indica, usa la cuenta por defecto o ENV.
    """
    key = request.args.get('key')
    if key != VERIFY_TOKEN:
        return jsonify({"status": "forbidden"}), 403
    account_id = request.args.get('account_id')
    acc = None
    if account_id:
        try:
            row = db_execute("SELECT id,label,phone_number_id,whatsapp_token,verify_token,is_default FROM accounts WHERE id=?", (account_id,), fetch='one')
            if row:
                if isinstance(row, dict):
                    acc = row
                else:
                    acc = { 'id': row[0], 'label': row[1], 'phone_number_id': row[2], 'whatsapp_token': row[3], 'verify_token': row[4], 'is_default': row[5] }
        except Exception:
            pass
    if not acc:
        acc = get_default_account()
    pnid = (acc or {}).get('phone_number_id') or PHONE_NUMBER_ID
    token = (acc or {}).get('whatsapp_token') or WHATSAPP_TOKEN
    if not pnid or not token:
        return jsonify({"error": "Faltan credenciales de WhatsApp"}), 500
    url = f"https://graph.facebook.com/v19.0/{pnid}"
    params = {
        "fields": "id,display_phone_number,whatsapp_business_account",
    }
    headers = {"Authorization": f"Bearer {token}"}
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
