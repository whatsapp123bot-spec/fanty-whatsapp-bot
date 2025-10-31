import json
import os
import mimetypes
from pathlib import Path

from django.http import (
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
    HttpResponseRedirect,
)
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, NoReverseMatch
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.utils import timezone
import requests
from django.conf import settings
import mimetypes as _mtypes

from .models import Bot, MessageLog, Flow, WaUser
from .forms import BotForm, FlowForm


def index(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse('bots:panel'))
    return HttpResponse(
        """
        <h1>Mi Chatfuel — Django</h1>
        <p>Servidor en ejecución.</p>
        <ul>
          <li><a href="/admin/">Ir al Admin</a></li>
          <li>Panel: <a href="/panel/">/panel/</a></li>
          <li>Webhook por bot: <code>/webhooks/whatsapp/&lt;uuid&gt;/</code></li>
        </ul>
        <p>Inicia sesión en el admin y vuelve a <a href="/panel/">/panel/</a> para gestionar bots y flujos.</p>
        """,
        content_type="text/html"
    )


def health(request):
    return JsonResponse({"ok": True})


@login_required
def panel(request):
    bots_qs = Bot.objects.filter(owner=request.user).order_by('-created_at')
    bots_info = []
    for b in bots_qs:
        try:
            webhook_url = request.build_absolute_uri(
                reverse('bots:whatsapp_webhook', args=[str(b.uuid)])
            )
        except NoReverseMatch:
            # Fallback si el nombre de URL no está disponible sin namespace
            webhook_url = request.build_absolute_uri(f'/webhooks/whatsapp/{b.uuid}/')
        bots_info.append({
            'id': b.id,
            'name': b.name,
            'pnid': b.phone_number_id,
            'uuid': str(b.uuid),
            'is_active': b.is_active,
            'created_at': b.created_at,
            'edit_url': reverse('bots:bot_edit', args=[b.id]),
            'validate_url': reverse('bots:bot_validate', args=[b.id]),
            'flows_url': reverse('bots:flow_list', args=[b.id]),
            'webhook_url': webhook_url,
        })
    return render(request, 'bots/panel.html', {
        'brand': 'OptiChat',
        'bots': bots_info,
    })


@login_required
def panel_live_chat(request):
    """Página de chat en vivo integrada en el panel."""
    return render(request, 'bots/live_chat.html', {
        'brand': 'OptiChat',
    })


@login_required
def api_list_conversations(request):
    """Lista conversaciones recientes del usuario logueado (todas las de sus bots)."""
    limit = int(request.GET.get('limit', '100'))
    live_param = request.GET.get('live')  # '1' -> solo abiertas, '0' -> solo cerradas, None -> todas
    bots = list(Bot.objects.filter(owner=request.user, is_active=True))
    bot_ids = [b.id for b in bots]
    items = []
    if bot_ids:
        qs = WaUser.objects.filter(bot_id__in=bot_ids)
        if live_param == '1':
            qs = qs.filter(human_requested=True)
        elif live_param == '0':
            qs = qs.filter(human_requested=False)
        qs = qs.order_by('-last_message_at')[:limit]
        for u in qs:
            items.append({
                'wa_id': u.wa_id,
                'name': u.name,
                'human_requested': u.human_requested,
                'bot_id': u.bot_id,
                'bot_name': u.bot.name,
                'last_message_at': u.last_message_at.isoformat() if u.last_message_at else None,
            })
    return JsonResponse({'items': items})


@login_required
def api_get_conversation(request, wa_id: str):
    """Devuelve mensajes de una conversación en orden ascendente."""
    u = WaUser.objects.filter(wa_id=wa_id, bot__owner=request.user).first()
    if not u:
        return JsonResponse({'error': 'No encontrado'}, status=404)
    limit = int(request.GET.get('limit', '200'))
    # Solo la conversación entre este wa_id y el número del bot seleccionado,
    # evitando mezclar mensajes de otros clientes que comparten el mismo phone_number_id.
    msgs = MessageLog.objects.filter(
        bot=u.bot
    ).filter(
        (
            Q(wa_from=wa_id) & Q(wa_to=u.bot.phone_number_id)
        ) | (
            Q(wa_from=u.bot.phone_number_id) & Q(wa_to=wa_id)
        )
    ).order_by('created_at')[:limit]
    out = []
    for m in msgs:
        body_text = None
        options = None
        p = m.payload or {}

        if m.direction == MessageLog.OUT:
            # Mensajes enviados por el bot (nuestro request a Meta)
            if m.message_type == 'text':
                body_text = (p.get('request') or {}).get('text', {}).get('body')
            elif m.message_type == 'interactive':
                ireq = (p.get('request') or {}).get('interactive') or {}
                body_text = (ireq.get('body') or {}).get('text')
                # Mostrar las etiquetas de los botones como opciones
                btns = (((ireq.get('action') or {}).get('buttons')) or [])
                options = [
                    ((b.get('reply') or {}).get('title') or '').strip()
                    for b in btns if (b.get('reply') or {}).get('title')
                ] or None
            elif m.message_type == 'image':
                body_text = '[imagen]'
            elif m.message_type == 'document':
                body_text = '[documento]'
        else:
            # Mensajes entrantes desde Meta (webhook crudo)
            try:
                entry = (p.get('entry') or [{}])[0]
                value = (entry.get('changes') or [{}])[0].get('value') or {}
                mm = (value.get('messages') or [{}])[0]
                mtype = (mm.get('type') or m.message_type or '').lower()
                if mtype == 'text':
                    body_text = (mm.get('text') or {}).get('body')
                elif mtype == 'interactive':
                    inter = mm.get('interactive') or {}
                    if 'button_reply' in inter:
                        body_text = (inter.get('button_reply') or {}).get('title') or (inter.get('button_reply') or {}).get('id')
                    elif 'list_reply' in inter:
                        body_text = (inter.get('list_reply') or {}).get('title') or (inter.get('list_reply') or {}).get('id')
                    else:
                        body_text = '[interacción]'
                elif mtype == 'button':
                    body_text = (mm.get('button') or {}).get('text') or (mm.get('button') or {}).get('payload')
                else:
                    body_text = f'[{mtype or "mensaje"}]'
            except Exception:
                body_text = None

        out.append({
            'direction': m.direction,
            'type': m.message_type,
            'body': body_text,
            'options': options,
            'created_at': m.created_at.isoformat(),
        })
    return JsonResponse({'wa_id': wa_id, 'name': u.name, 'human_requested': u.human_requested, 'messages': out})


@login_required
def api_panel_send_message(request):
    """Envia un mensaje de texto a un wa_id si el chat humano está activo."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    wa_id = request.POST.get('wa_id')
    text = (request.POST.get('text') or '').strip()
    up_file = request.FILES.get('file')
    if not wa_id or (not text and not up_file):
        return JsonResponse({'error': 'Faltan parámetros'}, status=400)
    u = WaUser.objects.filter(wa_id=wa_id, bot__owner=request.user).first()
    if not u:
        return JsonResponse({'error': 'No encontrado'}, status=404)
    if not u.human_requested:
        return JsonResponse({'error': 'Chat humano no activo para este usuario'}, status=403)
    from .services import send_whatsapp_text, send_whatsapp_image, send_whatsapp_document

    # Si viene archivo, primero subir a Cloudinary (recomendado) y luego enviar
    if up_file:
        try:
            import cloudinary
            from cloudinary import uploader
        except Exception:
            return JsonResponse({'error': 'Cargas de archivo requieren CLOUDINARY_URL configurado'}, status=400)

        # Detectar tipo
        ctype = getattr(up_file, 'content_type', None) or _mtypes.guess_type(up_file.name)[0] or ''
        is_image = ctype.startswith('image/')

        # Parámetros para Cloudinary
        folder = os.environ.get('CLOUDINARY_FOLDER', 'opti-chat/uploads')
        max_mb = int(os.environ.get('CLOUDINARY_MAX_MB') or '20')
        up_file.seek(0, os.SEEK_END)
        size_mb = up_file.tell() / (1024*1024)
        up_file.seek(0)
        if size_mb > max_mb:
            return JsonResponse({'error': f'Archivo demasiado grande (> {max_mb} MB)'}, status=400)

        try:
            if is_image:
                res = uploader.upload(up_file, folder=folder, resource_type='image', use_filename=True, unique_filename=True)
            else:
                # documentos (pdf, docx, etc.) van como raw; usar upload_large si pesa más de ~20MB
                if size_mb > 18:
                    res = uploader.upload_large(up_file, folder=folder, resource_type='raw', use_filename=True, unique_filename=True)
                else:
                    res = uploader.upload(up_file, folder=folder, resource_type='raw', use_filename=True, unique_filename=True)
        except Exception as e:
            return JsonResponse({'error': f'Error subiendo archivo: {e}'}, status=400)

        link = res.get('secure_url') or res.get('url')
        if not link:
            return JsonResponse({'error': 'No se obtuvo URL pública del archivo'}, status=500)

        if is_image:
            send_whatsapp_image(u.bot, wa_id, link, caption=text or None)
        else:
            filename = res.get('original_filename') or up_file.name
            send_whatsapp_document(u.bot, wa_id, link, filename=filename, caption=text or None)
        return JsonResponse({'ok': True, 'sent': 'file'})

    # Si no hay archivo, enviar texto
    send_whatsapp_text(u.bot, wa_id, text)
    return JsonResponse({'ok': True, 'sent': 'text'})


@login_required
def api_panel_human_toggle(request):
    """Activa/desactiva chat humano para un wa_id.
    POST: wa_id, on=1|0, timeout_min opcional
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    wa_id = request.POST.get('wa_id')
    on = request.POST.get('on') == '1'
    timeout_min = int(request.POST.get('timeout_min') or '15')
    u = WaUser.objects.filter(wa_id=wa_id, bot__owner=request.user).first()
    if not u:
        return JsonResponse({'error': 'No encontrado'}, status=404)
    if on:
        u.human_requested = True
        u.human_timeout_min = max(1, timeout_min)
        u.human_expires_at = timezone.now() + timezone.timedelta(minutes=u.human_timeout_min)
    else:
        u.human_requested = False
        u.human_expires_at = None
    u.save(update_fields=['human_requested', 'human_timeout_min', 'human_expires_at'])
    return JsonResponse({'ok': True})


@login_required
def bot_new(request):
    if request.method == 'POST':
        form = BotForm(request.POST)
        if form.is_valid():
            bot = form.save(commit=False)
            bot.owner = request.user
            bot.save()
            return HttpResponseRedirect(reverse('bots:panel'))
    else:
        form = BotForm()
    return render(request, 'bots/bot_form.html', {
        'title': 'Nuevo Bot',
        'form': form,
        'submit_label': 'Guardar',
    })


@login_required
def bot_edit(request, pk):
    bot = get_object_or_404(Bot, pk=pk, owner=request.user)
    if request.method == 'POST':
        form = BotForm(request.POST, instance=bot)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse('bots:panel'))
    else:
        form = BotForm(instance=bot)
    return render(request, 'bots/bot_form.html', {
        'title': f'Editar Bot: {bot.name}',
        'form': form,
        'submit_label': 'Guardar',
    })


@login_required
def bot_validate(request, pk):
    bot = get_object_or_404(Bot, pk=pk, owner=request.user)
    url = f"https://graph.facebook.com/{bot.phone_number_id}?fields=display_phone_number,id"
    headers = {'Authorization': f'Bearer {bot.access_token}'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        ok = r.ok
        data = r.json() if 'application/json' in r.headers.get('Content-Type', '') else {'text': r.text}
        return JsonResponse({'ok': ok, 'data': data, 'status_code': r.status_code})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
def flow_list(request, bot_pk):
    bot = get_object_or_404(Bot, pk=bot_pk, owner=request.user)
    flows = bot.flows.order_by('-updated_at')
    return render(request, 'bots/flows.html', {
        'brand': 'OptiChat',
        'bot': bot,
        'flows': flows,
    })


@login_required
def flow_new(request, bot_pk):
    bot = get_object_or_404(Bot, pk=bot_pk, owner=request.user)
    if request.method == 'POST':
        form = FlowForm(request.POST)
        if form.is_valid():
            flow = form.save(commit=False)
            flow.bot = bot
            flow.save()
            return HttpResponseRedirect(reverse('bots:flow_list', args=[bot.id]))
    else:
        form = FlowForm()
    return render(request, 'bots/flow_form.html', {
        'title': f'Nuevo Flujo — {bot.name}',
        'form': form,
        'submit_label': 'Guardar',
        'bot': bot,
    })


@login_required
def flow_edit(request, bot_pk, flow_pk):
    # Redirige al Builder visual directamente
    return HttpResponseRedirect(reverse('bots:flow_builder', args=[bot_pk, flow_pk]))


@csrf_exempt
def internal_upload(request):
    # Validación simple de URL alcanzable (HEAD)
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    # Caso 1: carga de archivo
    f = request.FILES.get('file')
    if f:
        name = f.name
        ext = os.path.splitext(name)[1]
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        # Evitar colisiones
        base, extension = os.path.splitext(name)
        safe_name = base
        i = 1
        while os.path.exists(os.path.join(upload_dir, safe_name + extension)):
            safe_name = f"{base}_{i}"
            i += 1
        final_name = safe_name + extension
        filepath = os.path.join(upload_dir, final_name)
        with open(filepath, 'wb') as out:
            for chunk in f.chunks():
                out.write(chunk)
        url = settings.MEDIA_URL + 'uploads/' + final_name
        return JsonResponse({'ok': True, 'url': url, 'name': final_name, 'ext': ext})

    # Caso 2: validación de URL
    url = request.POST.get('url') or ''
    if url:
        try:
            r = requests.head(url, timeout=8, allow_redirects=True)
            ok = r.status_code < 400
            ctype = r.headers.get('Content-Type', '')
            guessed_ext = mimetypes.guess_extension(ctype.split(';')[0].strip()) if ctype else ''
            return JsonResponse({'ok': ok, 'status_code': r.status_code, 'headers': dict(r.headers), 'ext': guessed_ext or ''})
        except Exception as e:
            return JsonResponse({'ok': False, 'error': str(e)}, status=500)

    return JsonResponse({'ok': False, 'error': 'No se recibió archivo ni url'}, status=400)


@login_required
def flow_builder(request, bot_pk, flow_pk):
    bot = get_object_or_404(Bot, pk=bot_pk, owner=request.user)
    flow = get_object_or_404(Flow, pk=flow_pk, bot=bot)
    flow_def = flow.definition or { 'enabled': True, 'start_node': None, 'nodes': {} }
    if not (flow_def.get('nodes') or {}):
        legacy_path = (Path(settings.BASE_DIR).parent / 'flow.json').resolve()
        if legacy_path.exists():
            try:
                with legacy_path.open('r', encoding='utf-8') as fh:
                    legacy_data = json.load(fh)
                if isinstance(legacy_data, dict) and legacy_data.get('nodes'):
                    flow_def = legacy_data
                    flow.definition = flow_def
                    flow.save(update_fields=['definition'])
            except (OSError, json.JSONDecodeError):
                pass
    ctx = {
        'flow_json': json.dumps(flow_def),
        'flow_key': flow.id,
        'upload_max_mb': 10,
        'bot_id': bot_pk,
    }
    return render(request, 'flow_builder.html', ctx)


@csrf_exempt
def flow_save(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'No autenticado'}, status=401)
    key = request.GET.get('key') or request.POST.get('key')
    if not key:
        return JsonResponse({'error': 'Falta key'}, status=400)
    try:
        flow_id = int(key)
    except ValueError:
        return JsonResponse({'error': 'Key inválida'}, status=400)
    flow = get_object_or_404(Flow, pk=flow_id)
    if flow.bot.owner_id != request.user.id:
        return JsonResponse({'error': 'Sin permiso'}, status=403)
    content = request.POST.get('content')
    if not content:
        return JsonResponse({'error': 'Falta content'}, status=400)
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return JsonResponse({'error': f'JSON inválido: {e}'}, status=400)
    flow.definition = data
    flow.save(update_fields=['definition'])
    return JsonResponse({'ok': True, 'id': flow.id})


def verify_webhook(request, bot):
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')

    if mode == 'subscribe' and token and token == bot.verify_token:
        return HttpResponse(challenge)
    return HttpResponseForbidden('Verification token mismatch')


@csrf_exempt
def whatsapp_webhook(request, bot_uuid):
    bot = get_object_or_404(Bot, uuid=bot_uuid, is_active=True)

    if request.method == 'GET':
        return verify_webhook(request, bot)

    if request.method == 'POST':
        try:
            body = json.loads(request.body.decode('utf-8') or '{}')
        except json.JSONDecodeError:
            body = {}

        entry = (body.get('entry') or [{}])[0]
        changes = entry.get('changes') or []
        value = changes[0].get('value') if changes else {}
        messages = value.get('messages') or []

        if not messages:
            return JsonResponse({'status': 'ok'})

        msg = messages[0]
        wa_from = msg.get('from', '')
        message_type = msg.get('type', '')
        profile = (value.get('contacts') or [{}])[0].get('profile') if value.get('contacts') else {}
        name = (profile or {}).get('name', '')

        # Log in
        # Guardar usando phone_number_id (consistente con envíos) para poder cruzar luego
        meta = value.get('metadata', {}) if isinstance(value, dict) else {}
        wa_to_number = meta.get('phone_number_id') or bot.phone_number_id
        MessageLog.objects.create(
            bot=bot,
            direction=MessageLog.IN,
            wa_from=wa_from,
            wa_to=wa_to_number,
            message_type=message_type,
            payload=body,
            status='received',
        )

        # Upsert WaUser
        user, _ = WaUser.objects.get_or_create(bot=bot, wa_id=wa_from, defaults={'name': name or ''})
        if name and user.name != name:
            user.name = name
        now = timezone.now()
        user.last_message_at = now
        user.last_in_at = now

        # Helper: conseguir flow activo para el bot
        def get_active_flow_def():
            f = bot.flows.filter(is_active=True).order_by('-updated_at').first()
            if f and f.definition:
                return f.definition
            # fallback al flow.json legado
            try:
                legacy_path = (Path(settings.BASE_DIR).parent / 'flow.json').resolve()
                if legacy_path.exists():
                    with legacy_path.open('r', encoding='utf-8') as fh:
                        data = json.load(fh)
                        if isinstance(data, dict):
                            return data
            except Exception:
                pass
            return {'enabled': False, 'nodes': {}, 'start_node': None}

        flow_cfg = get_active_flow_def()

        # Helpers envío
        from .services import (
            send_whatsapp_text,
            send_whatsapp_interactive_buttons,
            send_whatsapp_image,
            send_whatsapp_document,
        )

        def send_flow_node(node_id: str):
            nodes = (flow_cfg or {}).get('nodes') or {}
            node = nodes.get(node_id)
            if not node:
                send_whatsapp_text(bot, wa_from, '⚠️ Flujo no disponible en este paso.')
                return
            ntype = (node.get('type') or 'action').lower()
            text = node.get('text') or ''

            # Guardar estado
            user.flow_node = node_id
            user.save(update_fields=['name', 'last_message_at', 'last_in_at', 'flow_node'])

            if ntype == 'advisor':
                raw_phone = (node.get('phone') or '').strip()
                digits = ''.join(ch for ch in raw_phone if ch.isdigit() or ch == '+')
                lines = []
                if text:
                    lines.append(text)
                else:
                    lines.append('Te estamos transfiriendo con una asesora humana. Un momento por favor.')
                links_cfg = node.get('links') or {}
                if isinstance(links_cfg, dict):
                    for label, key in [('Web','web'),('Facebook','fb'),('Instagram','ig'),('TikTok','tiktok')]:
                        ent = links_cfg.get(key) or {}
                        if ent.get('enabled') and (ent.get('url') or '').strip():
                            lines.append(f"{label}: {ent['url']}")
                if digits:
                    link = f"https://wa.me/{digits.lstrip('+')}"
                    lines.append(f"\nChatear: {link}")
                body_text = "\n".join(lines)
                # Activar chat humano con timeout
                try:
                    tmin = int(node.get('timeout_min') or node.get('human_timeout_min') or 15)
                except Exception:
                    tmin = 15
                user.human_requested = True
                user.human_timeout_min = tmin
                user.human_expires_at = now + timezone.timedelta(minutes=max(1, tmin))
                user.save(update_fields=['human_requested', 'human_timeout_min', 'human_expires_at'])
                buttons = [{ 'id': 'MENU_PRINCIPAL', 'title': '🔙 Menú principal' }]
                send_whatsapp_interactive_buttons(bot, wa_from, body_text, buttons)
                return

            # start/trigger con next → saltar
            if ntype in ('start', 'trigger') and node.get('next'):
                send_flow_node(node.get('next'))
                return

            # Enviar assets primero
            for asset in (node.get('assets') or [])[:5]:
                atype = (asset.get('type') or '').lower()
                url_a = asset.get('url') or ''
                name_a = asset.get('name') or 'archivo.pdf'
                try:
                    if atype == 'image' and url_a:
                        send_whatsapp_image(bot, wa_from, url_a, None)
                    elif atype in ('file', 'document') and url_a:
                        send_whatsapp_document(bot, wa_from, url_a, name_a, None)
                except Exception:
                    pass

            # Botones o texto simple
            raw_buttons = (node.get('buttons') or [])[:3]
            buttons = []
            for b in raw_buttons:
                title = b.get('title') or 'Opción'
                target = None
                if b.get('next'):
                    target = f"FLOW:{b['next']}"
                elif b.get('id'):
                    target = b['id']
                if target:
                    buttons.append({'id': target, 'title': title})
            if buttons:
                send_whatsapp_interactive_buttons(bot, wa_from, text or ' ', buttons)
            else:
                if text:
                    send_whatsapp_text(bot, wa_from, text)
                # Encadenar si action con next
                if (node.get('type') or 'action').lower() == 'action' and node.get('next'):
                    send_flow_node(node.get('next'))
                else:
                    # Terminal: limpiar estado
                    user.flow_node = None
                    user.save(update_fields=['flow_node'])

        # Extraer payload interactivo o texto
        payload_id = None
        if message_type == 'interactive':
            it = msg.get('interactive') or {}
            if 'button_reply' in it:
                payload_id = (it['button_reply'] or {}).get('id')
            elif 'list_reply' in it:
                payload_id = (it['list_reply'] or {}).get('id')
        elif message_type == 'button':
            payload_id = (msg.get('button') or {}).get('payload') or (msg.get('button') or {}).get('text')
        elif message_type == 'text':
            payload_id = None
        else:
            payload_id = None

        # Manejo de payloads
        if payload_id:
            pid = (payload_id or '').strip()
            if pid.upper().startswith('FLOW:'):
                node_id = pid.split(':', 1)[1]
                send_flow_node(node_id)
                return JsonResponse({'status': 'ok'})
            if pid.upper() == 'MENU_PRINCIPAL' and (flow_cfg or {}).get('start_node'):
                send_flow_node(flow_cfg.get('start_node'))
                return JsonResponse({'status': 'ok'})
            return JsonResponse({'status': 'ok'})

        # Texto libre: intentar triggers si no hay flujo activo
        text_low = (msg.get('text', {}).get('body') or '').strip().lower()
        nodes = (flow_cfg or {}).get('nodes') or {}
        enabled = (flow_cfg or {}).get('enabled', True)
        if enabled and nodes:
            if user.flow_node:
                send_whatsapp_text(bot, wa_from, 'Por favor, elige una opción del menú.')
                return JsonResponse({'status': 'ok'})

            def match_trigger():
                for nid, node in nodes.items():
                    if (node.get('type') or '').lower() != 'trigger':
                        continue
                    if 'enabled' in node and not node.get('enabled'):
                        continue
                    ttype = (node.get('trigger_type') or 'keywords').lower()
                    pats = (node.get('patterns') or '').strip()
                    if not pats:
                        continue
                    if ttype == 'keywords':
                        kws = [p.strip().lower() for p in pats.split(',') if p.strip()]
                        if any(k in text_low for k in kws):
                            return node.get('next') or nid
                    elif ttype == 'deeplink':
                        lines = [p.strip().lower() for p in pats.split('\n') if p.strip()]
                        if text_low in lines:
                            return node.get('next') or nid
                    elif ttype == 'ai':
                        continue
                return None

            target = match_trigger()
            if target:
                send_flow_node(target)
                return JsonResponse({'status': 'ok'})
            if flow_cfg.get('start_node'):
                send_flow_node(flow_cfg.get('start_node'))
                return JsonResponse({'status': 'ok'})

        return JsonResponse({'status': 'ok'})

    return HttpResponse(status=405)


# ====== Vista previa del flujo (como Flask) ======

def _load_legacy_flow_config():
    """Carga flow.json (raíz del repo) para la vista previa, sin usar DB."""
    try:
        legacy_path = (Path(settings.BASE_DIR).parent / 'flow.json').resolve()
        if legacy_path.exists():
            with legacy_path.open('r', encoding='utf-8') as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    data.setdefault('enabled', True)
                    data.setdefault('start_node', None)
                    data.setdefault('nodes', {})
                    return data
    except Exception:
        pass
    return { 'enabled': True, 'start_node': None, 'nodes': {} }


def _build_preview_for_node(flow_cfg: dict, node_id: str) -> dict:
    nodes = (flow_cfg or {}).get('nodes') or {}
    node = nodes.get(node_id)
    if not node:
        return {'response': '⚠️ Paso no encontrado en el flujo.'}
    ntype = (node.get('type') or 'action').lower()

    if ntype == 'start' and node.get('next'):
        return _build_preview_for_node(flow_cfg, node.get('next'))
    if ntype == 'trigger' and node.get('next'):
        return _build_preview_for_node(flow_cfg, node.get('next'))

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
            parts.append(f'<img src="{url}" alt="{name}" style="max-width:100%; border-radius:8px;"/>')
        else:
            safe = name or os.path.basename(url)
            parts.append(f'📄 <a href="{url}" target="_blank" rel="noopener">{safe}</a>')

    options = []
    if ntype == 'advisor':
        raw_phone = (node.get('phone') or '').strip()
        digits = ''.join(ch for ch in raw_phone if ch.isdigit() or ch == '+')
        link = f"https://wa.me/{digits.lstrip('+')}" if digits else ''
        lines = []
        if not text:
            lines.append('Te estamos transfiriendo con una asesora humana. Un momento por favor.')
        links_cfg = node.get('links') or {}
        if isinstance(links_cfg, dict):
            for label, key in [('Web','web'),('Facebook','fb'),('Instagram','ig'),('TikTok','tiktok')]:
                ent = links_cfg.get(key) or {}
                if ent.get('enabled') and (ent.get('url') or '').strip():
                    lines.append(f"{label}: <a href=\"{ent['url']}\" target=\"_blank\">{ent['url']}</a>")
        if link:
            lines.append(f"Chatear: <a href=\"{link}\" target=\"_blank\">{link}</a>")
        if lines:
            parts.append('<br>'.join(lines))
        start_id = (flow_cfg or {}).get('start_node')
        if start_id:
            options.append({'title': '🔙 Menú principal', 'payload': f'FLOW:{start_id}'})
        return {'response_html': '<br>'.join(parts) if parts else 'Asesor humano', 'options': options}

    raw_buttons = (node.get('buttons') or [])[:3]
    for b in raw_buttons:
        title = b.get('title') or 'Opción'
        if b.get('next'):
            options.append({'title': title, 'payload': f"FLOW:{b['next']}"})
        elif b.get('id'):
            options.append({'title': title, 'payload': b['id']})

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


def _match_trigger(flow_cfg: dict, text_low: str) -> str | None:
    nodes = (flow_cfg or {}).get('nodes') or {}
    for nid, node in nodes.items():
        if (node.get('type') or '').lower() != 'trigger':
            continue
        if 'enabled' in node and not node.get('enabled'):
            continue
        ttype = (node.get('trigger_type') or 'keywords').lower()
        pats = (node.get('patterns') or '').strip()
        if not pats:
            continue
        if ttype == 'keywords':
            kws = [p.strip().lower() for p in pats.split(',') if p.strip()]
            if any(k in text_low for k in kws):
                return node.get('next') or nid
        elif ttype == 'deeplink':
            lines = [p.strip().lower() for p in pats.split('\n') if p.strip()]
            if text_low in lines:
                return node.get('next') or nid
        elif ttype == 'ai':
            continue
    return None


from django.views.decorators.clickjacking import xframe_options_exempt


@xframe_options_exempt
def chat_preview(request):
    """Simulador de chat embebible en el builder.
    Exento de X-Frame-Options para permitir iframe en el mismo origen.
    """
    return render(request, 'chat.html')


@csrf_exempt
def send_message_preview(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    flow_cfg = _load_legacy_flow_config()
    payload = request.POST.get('payload')
    user_message = request.POST.get('message', '')

    if payload:
        p = payload.strip()
        if p.upper().startswith('FLOW:'):
            node_id = p.split(':', 1)[1]
            return JsonResponse(_build_preview_for_node(flow_cfg, node_id))
        if p.upper() == 'MENU_PRINCIPAL' and flow_cfg.get('start_node'):
            return JsonResponse(_build_preview_for_node(flow_cfg, flow_cfg.get('start_node')))
        return JsonResponse({'response': ' '})

    low = (user_message or '').strip().lower()
    if not low:
        return JsonResponse({'response': ' '})

    nodes = (flow_cfg or {}).get('nodes') or {}
    if (flow_cfg or {}).get('enabled', True) and nodes:
        target = _match_trigger(flow_cfg, low)
        if target:
            return JsonResponse(_build_preview_for_node(flow_cfg, target))
        if flow_cfg.get('start_node'):
            return JsonResponse(_build_preview_for_node(flow_cfg, flow_cfg.get('start_node')))

    return JsonResponse({'response': '🤖 No hay un match en el flujo para tu mensaje.'})
