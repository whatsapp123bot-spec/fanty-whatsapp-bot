import json
import os
import mimetypes
from pathlib import Path
import difflib

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
    from .services import send_whatsapp_text, send_whatsapp_image, send_whatsapp_document, send_whatsapp_document_id

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
            try:
                result = send_whatsapp_image(u.bot, wa_id, link, caption=text or None)
            except Exception as e:
                return JsonResponse({'error': f'Error enviando imagen a WhatsApp: {e}'}, status=502)
            return JsonResponse({'ok': True, 'sent': 'image', 'wa': result})
        else:
            # Para documentos, además de Cloudinary subimos a la API de WhatsApp para obtener un media_id (más confiable)
            try:
                # Releer bytes del archivo (tras la carga a Cloudinary, reposicionar puntero)
                try:
                    up_file.seek(0)
                except Exception:
                    pass
                data_bytes = up_file.read()
                media_url = f"https://graph.facebook.com/{settings.WA_GRAPH_VERSION}/{u.bot.phone_number_id}/media"
                headers = { 'Authorization': f'Bearer {u.bot.access_token}' }
                # Incluir content-type explícito (recomendado por Meta) para documentos
                files = { 'file': (up_file.name, data_bytes, ctype or 'application/octet-stream') }
                form = { 'messaging_product': 'whatsapp', 'type': ctype or 'application/octet-stream' }
                media_resp = requests.post(media_url, headers=headers, data=form, files=files, timeout=60)
                media_resp.raise_for_status()
                media_id = media_resp.json().get('id')
            except Exception as e:
                # Si falla el upload a WhatsApp, usar el enlace directo como fallback
                media_id = None
            filename = up_file.name
            try:
                if media_id:
                    result = send_whatsapp_document_id(u.bot, wa_id, media_id=media_id, filename=filename, caption=text or None)
                    return JsonResponse({'ok': True, 'sent': 'document', 'strategy': 'media_id', 'media_id': media_id, 'wa': result})
                else:
                    result = send_whatsapp_document(u.bot, wa_id, link, filename=filename, caption=text or None)
                    return JsonResponse({'ok': True, 'sent': 'document', 'strategy': 'link', 'wa': result})
            except Exception as e:
                return JsonResponse({'error': f'Error enviando documento a WhatsApp: {e}'}, status=502)

    # Si no hay archivo, enviar texto
    try:
        result = send_whatsapp_text(u.bot, wa_id, text)
    except Exception as e:
        return JsonResponse({'error': f'Error enviando texto a WhatsApp: {e}'}, status=502)
    return JsonResponse({'ok': True, 'sent': 'text', 'wa': result})


@login_required
def api_outbox(request):
    """Devuelve últimos mensajes SALIENTES con su estado y respuesta de la API.
    Filtros opcionales:
      - wa: número de WhatsApp del cliente
      - limit: cantidad (por defecto 50)
      - only_errors=1: solo fallidos
    """
    limit = int(request.GET.get('limit') or '50')
    wa = (request.GET.get('wa') or request.GET.get('wa_id') or '').strip()
    only_err = (request.GET.get('only_errors') or request.GET.get('errors')) in ('1','true','yes')
    # Bots del usuario
    bots = Bot.objects.filter(owner=request.user)
    qs = MessageLog.objects.filter(bot__in=bots, direction=MessageLog.OUT).order_by('-created_at')
    if wa:
        qs = qs.filter(wa_to=wa)
    if only_err:
        qs = qs.exclude(status='sent')
    qs = qs[:max(1, min(200, limit))]
    items = []
    for m in qs:
        resp = (m.payload or {}).get('response')
        items.append({
            'id': m.id,
            'created_at': m.created_at.isoformat(),
            'to': m.wa_to,
            'status': m.status,
            'error': m.error,
            'response': resp,
            'type': m.message_type,
        })
    return JsonResponse({'items': items})
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
        'title': f'Editar Bot — {bot.name}',
        'form': form,
        'submit_label': 'Guardar',
    })


@login_required
def bot_validate(request, pk):
    bot = get_object_or_404(Bot, pk=pk, owner=request.user)
    # Validación real contra Graph: GET /{phone_number_id}
    if not (bot.access_token and bot.phone_number_id):
        return JsonResponse({'ok': False, 'error': 'Faltan credenciales'}, status=400)
    url = f"https://graph.facebook.com/{settings.WA_GRAPH_VERSION}/{bot.phone_number_id}"
    try:
        r = requests.get(url, headers={'Authorization': f'Bearer {bot.access_token}'}, timeout=15, params={'fields': 'id,display_phone_number'})
        data = r.json() if r.content else {}
        ok = r.ok and (data.get('id') == bot.phone_number_id or data.get('id'))
        return JsonResponse({'ok': bool(ok), 'response': data, 'status': r.status_code})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=502)


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

        # Helper: aplanar configuración de IA del builder (ai_config) a formato plano (ai)
        def _flatten_ai_cfg(cfg: dict) -> dict:
            result = {}
            try:
                # Base plana si existe
                base_ai = (cfg or {}).get('ai') or {}
                if isinstance(base_ai, dict):
                    result.update(base_ai)
                ai_conf = (cfg or {}).get('ai_config') or {}
                if not isinstance(ai_conf, dict):
                    return result
                prof = (ai_conf.get('assistant_profile') or {}) if isinstance(ai_conf.get('assistant_profile'), dict) else {}
                biz = (ai_conf.get('business_profile') or {}) if isinstance(ai_conf.get('business_profile'), dict) else {}
                # Ventas inteligentes (opcional)
                if prof:
                    if prof.get('sales_playbook') and not result.get('sales_playbook'):
                        result['sales_playbook'] = prof.get('sales_playbook')
                    if isinstance(prof.get('cta_phrases'), list) and not result.get('cta_phrases'):
                        result['cta_phrases'] = ", ".join([str(x).strip() for x in prof.get('cta_phrases') if str(x).strip()])
                    if prof.get('emoji_level') and not result.get('emoji_level'):
                        result['emoji_level'] = prof.get('emoji_level')
                    if isinstance(prof.get('recommendation_examples'), list) and not result.get('recommendation_examples'):
                        result['recommendation_examples'] = "\n".join([str(x).strip() for x in prof.get('recommendation_examples') if str(x).strip()])
                # Policies (listas) → líneas
                not_supported = ai_conf.get('not_supported') or []
                if isinstance(not_supported, list) and not result.get('out_of_scope'):
                    result['out_of_scope'] = "\n".join([str(x).strip() for x in not_supported if str(x).strip()])
                policies = ai_conf.get('policies') or []
                if isinstance(policies, list) and not result.get('response_policies'):
                    result['response_policies'] = "\n".join([str(x).strip() for x in policies if str(x).strip()])
                # Assistant profile
                if prof:
                    if prof.get('assistant_name') and not result.get('assistant_name'):
                        result['assistant_name'] = prof.get('assistant_name')
                    if prof.get('language') and not result.get('language'):
                        result['language'] = prof.get('language')
                    # Descripción/presentación del negocio/asistente
                    if prof.get('store_description') and not (result.get('about') or result.get('presentation')):
                        result['about'] = prof.get('store_description')
                        result['presentation'] = prof.get('store_description')
                    if (prof.get('website_url') or prof.get('website')) and not result.get('website'):
                        result['website'] = prof.get('website_url') or prof.get('website')
                    if (prof.get('phone_number') or prof.get('phone')) and not result.get('phone'):
                        result['phone'] = prof.get('phone_number') or prof.get('phone')
                    if prof.get('email') and not result.get('email'):
                        result['email'] = prof.get('email')
                    roi = prof.get('required_order_info') or []
                    if isinstance(roi, list) and not result.get('order_required'):
                        result['order_required'] = "\n".join([str(x).strip() for x in roi if str(x).strip()])
                # Business profile
                if biz:
                    if biz.get('business_name') and not result.get('trade_name'):
                        result['trade_name'] = biz.get('business_name')
                    if biz.get('legal_name') and not result.get('legal_name'):
                        result['legal_name'] = biz.get('legal_name')
                    if biz.get('ruc') and not result.get('ruc'):
                        result['ruc'] = biz.get('ruc')
                    hours = biz.get('hours') or {}
                    if isinstance(hours, dict):
                        if hours.get('timezone') and not result.get('timezone'):
                            result['timezone'] = hours.get('timezone')
                        if hours.get('weekdays') and not result.get('hours_mon_fri'):
                            result['hours_mon_fri'] = hours.get('weekdays')
                        if hours.get('saturday') and not result.get('hours_sat'):
                            result['hours_sat'] = hours.get('saturday')
                        if hours.get('sunday') and not result.get('hours_sun'):
                            result['hours_sun'] = hours.get('sunday')
                    addr = biz.get('address') or {}
                    if isinstance(addr, dict):
                        if addr.get('address_line') and not result.get('address'):
                            result['address'] = addr.get('address_line')
                        if addr.get('city') and not result.get('city'):
                            result['city'] = addr.get('city')
                        if addr.get('region') and not result.get('region'):
                            result['region'] = addr.get('region')
                        if addr.get('country') and not result.get('country'):
                            result['country'] = addr.get('country')
                        if addr.get('maps_url') and not result.get('maps_url'):
                            result['maps_url'] = addr.get('maps_url')
                        if addr.get('ubigeo') and not result.get('ubigeo'):
                            result['ubigeo'] = addr.get('ubigeo')
                    socials = biz.get('socials') or {}
                    if isinstance(socials, dict):
                        for k_src, k_dst in [
                            ('instagram','instagram'), ('facebook','facebook'), ('tiktok','tiktok'), ('youtube','youtube'),
                            ('x','x'), ('linktree','linktree'), ('whatsapp_link','whatsapp_link'), ('website','catalog_url')
                        ]:
                            if socials.get(k_src) and not result.get(k_dst):
                                result[k_dst] = socials.get(k_src)
                    # Catálogo estructurado y guías
                    if isinstance(biz.get('categories'), list) and not result.get('categories'):
                        result['categories'] = ", ".join([str(x).strip() for x in biz.get('categories') if str(x).strip()])
                    featured = biz.get('featured_products') or []
                    if isinstance(featured, list) and not result.get('featured_products'):
                        # Serializar como líneas "Nombre: URL"
                        lines = []
                        for fp in featured:
                            if isinstance(fp, dict):
                                nm = (fp.get('name') or '').strip()
                                url = (fp.get('url') or '').strip()
                                if nm or url:
                                    lines.append(f"{nm}: {url}".strip(': '))
                        if lines:
                            result['featured_products'] = "\n".join(lines)
                    if biz.get('size_guide_url') and not result.get('size_guide_url'):
                        result['size_guide_url'] = biz.get('size_guide_url')
                    if biz.get('size_notes') and not result.get('size_notes'):
                        result['size_notes'] = biz.get('size_notes')
                    if biz.get('materials') and not result.get('materials'):
                        result['materials'] = biz.get('materials')
                    if biz.get('care_instructions') and not result.get('care_instructions'):
                        result['care_instructions'] = biz.get('care_instructions')
                    payments = biz.get('payments') or {}
                    if isinstance(payments, dict):
                        yp = payments.get('yape') or {}
                        if yp:
                            if yp.get('phone') and not result.get('yape_number'):
                                result['yape_number'] = yp.get('phone')
                            if yp.get('holder') and not result.get('yape_holder'):
                                result['yape_holder'] = yp.get('holder')
                            if yp.get('alias') and not result.get('yape_alias'):
                                result['yape_alias'] = yp.get('alias')
                            if yp.get('qr_url') and not result.get('yape_qr'):
                                result['yape_qr'] = yp.get('qr_url')
                        pl = payments.get('plin') or {}
                        if pl:
                            if pl.get('phone') and not result.get('plin_number'):
                                result['plin_number'] = pl.get('phone')
                            if pl.get('holder') and not result.get('plin_holder'):
                                result['plin_holder'] = pl.get('holder')
                            if pl.get('qr_url') and not result.get('plin_qr'):
                                result['plin_qr'] = pl.get('qr_url')
                        card = payments.get('card') or {}
                        if card:
                            brands = card.get('brands')
                            if brands and not result.get('card_brands'):
                                result['card_brands'] = ", ".join(brands) if isinstance(brands, list) else str(brands)
                            if card.get('provider') and not result.get('card_provider'):
                                result['card_provider'] = card.get('provider')
                            if card.get('link_url') and not result.get('card_paylink'):
                                result['card_paylink'] = card.get('link_url')
                            if (card.get('surcharge') or card.get('notes')) and not result.get('card_fee_notes'):
                                result['card_fee_notes'] = card.get('surcharge') or card.get('notes')
                        tf = payments.get('transfer') or {}
                        if tf:
                            banks = tf.get('banks') or []
                            if isinstance(banks, list) and not result.get('transfer_accounts'):
                                lines = []
                                for bk in banks:
                                    if not isinstance(bk, dict):
                                        continue
                                    parts = [
                                        bk.get('bank') or '',
                                        bk.get('account_number') or '',
                                        bk.get('cci') or '',
                                        bk.get('holder') or '',
                                        bk.get('doc') or '',
                                    ]
                                    if any([p.strip() for p in parts]):
                                        lines.append('; '.join(parts).strip())
                                if lines:
                                    result['transfer_accounts'] = "\n".join(lines)
                            if tf.get('instructions') and not result.get('transfer_instructions'):
                                result['transfer_instructions'] = tf.get('instructions')
                        cod = payments.get('cod') or {}
                        if cod and not result.get('cash_on_delivery_yes'):
                            note = cod.get('notes')
                            if note:
                                result['cash_on_delivery_yes'] = note
                    shipping = biz.get('shipping') or {}
                    if isinstance(shipping, dict):
                        dRates = shipping.get('district_rates') or []
                        if isinstance(dRates, list) and not result.get('districts_costs'):
                            lines = []
                            for dr in dRates:
                                if not isinstance(dr, dict):
                                    continue
                                parts = [dr.get('district') or '', dr.get('price') or '', dr.get('eta') or '']
                                if any([p.strip() for p in parts]):
                                    lines.append('; '.join(parts).strip())
                            if lines:
                                result['districts_costs'] = "\n".join(lines)
                        if shipping.get('delivery_time') and not result.get('typical_delivery_time'):
                            result['typical_delivery_time'] = shipping.get('delivery_time')
                        if shipping.get('free_shipping_threshold') and not result.get('free_shipping_from'):
                            result['free_shipping_from'] = shipping.get('free_shipping_threshold')
                        if shipping.get('pickup_address') and not result.get('pickup_address'):
                            result['pickup_address'] = shipping.get('pickup_address')
                        partners = shipping.get('partners')
                        if partners and not result.get('delivery_partners'):
                            result['delivery_partners'] = ", ".join(partners) if isinstance(partners, list) else str(partners)
                    sales = biz.get('sales') or {}
                    if isinstance(sales, dict):
                        retail = sales.get('retail') or {}
                        if isinstance(retail, dict) and result.get('retail_yes') is None:
                            if 'enabled' in retail:
                                result['retail_yes'] = 'Sí' if retail.get('enabled') else 'No'
                        wholesale = sales.get('wholesale') or {}
                        if isinstance(wholesale, dict):
                            if 'enabled' in wholesale and result.get('wholesale_yes') is None:
                                result['wholesale_yes'] = 'Sí' if wholesale.get('enabled') else 'No'
                            if wholesale.get('min_units') and not result.get('wholesale_min_qty'):
                                result['wholesale_min_qty'] = str(wholesale.get('min_units'))
                            if wholesale.get('price_list_url') and not result.get('wholesale_price_list_url'):
                                result['wholesale_price_list_url'] = wholesale.get('price_list_url')
                            if 'requires_ruc' in wholesale and not result.get('wholesale_requires_ruc'):
                                result['wholesale_requires_ruc'] = 'Sí' if wholesale.get('requires_ruc') else 'No'
                            if wholesale.get('prep_time') and not result.get('prep_time_large_orders'):
                                result['prep_time_large_orders'] = wholesale.get('prep_time')
                            disc = wholesale.get('discounts') or []
                            if isinstance(disc, list) and not result.get('volume_discounts'):
                                lines = []
                                for dct in disc:
                                    if not isinstance(dct, dict):
                                        continue
                                    parts = [
                                        (str(dct.get('from_units')) if dct.get('from_units') is not None else ''),
                                        (str(dct.get('percent')) if dct.get('percent') is not None else ''),
                                    ]
                                    if any([p.strip() for p in parts]):
                                        lines.append('; '.join(parts).strip())
                                if lines:
                                    result['volume_discounts'] = "\n".join(lines)
                    policies = biz.get('policies') or {}
                    if isinstance(policies, dict):
                        if policies.get('returns') and not result.get('returns_policy'):
                            result['returns_policy'] = policies.get('returns')
                        if policies.get('warranty') and not result.get('warranty'):
                            result['warranty'] = policies.get('warranty')
                        if policies.get('terms_url') and not result.get('terms_url'):
                            result['terms_url'] = policies.get('terms_url')
                        if policies.get('privacy_url') and not result.get('privacy_url'):
                            result['privacy_url'] = policies.get('privacy_url')
                        inv = policies.get('invoices') or {}
                        if isinstance(inv, dict):
                            if 'boleta' in inv and not result.get('boleta_yes'):
                                result['boleta_yes'] = 'Sí' if inv.get('boleta') else 'No'
                            if 'factura' in inv and not result.get('factura_yes'):
                                result['factura_yes'] = 'Sí' if inv.get('factura') else 'No'
            except Exception:
                # No romper si viene mal formado
                return result
            return result

        # Helpers envío y IA
        from .services import (
            send_whatsapp_text,
            send_whatsapp_interactive_buttons,
            send_whatsapp_image,
            send_whatsapp_document,
            answer_from_persona,
            ai_select_trigger,
            ai_answer,
        )
        # OpenRouter helpers para clasificación de intención y naturalización
        try:
            from services.ai_service import classify_intent_label, naturalize_from_answer
        except Exception:
            classify_intent_label = None  # type: ignore
            naturalize_from_answer = None  # type: ignore

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
                try:
                    send_whatsapp_interactive_buttons(bot, wa_from, body_text, buttons)
                except Exception:
                    # No romper el webhook si falla el envío (p.ej. token inválido)
                    pass
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
                try:
                    send_whatsapp_interactive_buttons(bot, wa_from, text or ' ', buttons)
                except Exception:
                    pass
            else:
                if text:
                    try:
                        send_whatsapp_text(bot, wa_from, text)
                    except Exception:
                        pass
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
            # Acciones rápidas de bienvenida (Catálogo, Pagos, Envíos)
            if pid.upper() in ('OPEN_CATALOG','OPEN_PAYMENTS','OPEN_SHIPPING'):
                ai_cfg_wc = _flatten_ai_cfg(flow_cfg)
                persona = {
                    'name': (
                        ai_cfg_wc.get('assistant_name')
                        or ai_cfg_wc.get('assistant')
                        or ai_cfg_wc.get('assistantName')
                        or ai_cfg_wc.get('nombre_asistente')
                        or ai_cfg_wc.get('name')
                        or 'Asistente'
                    ),
                    'about': ai_cfg_wc.get('about') or ai_cfg_wc.get('presentation') or '',
                    'language': ai_cfg_wc.get('language') or 'español',
                    'website': ai_cfg_wc.get('website') or ai_cfg_wc.get('website_url') or '',
                    'catalog_url': ai_cfg_wc.get('catalog_url') or '',
                    # Pagos
                    'yape_number': ai_cfg_wc.get('yape_number') or '',
                    'yape_holder': ai_cfg_wc.get('yape_holder') or '',
                    'yape_alias': ai_cfg_wc.get('yape_alias') or '',
                    'yape_qr': ai_cfg_wc.get('yape_qr') or '',
                    'plin_number': ai_cfg_wc.get('plin_number') or '',
                    'plin_holder': ai_cfg_wc.get('plin_holder') or '',
                    'plin_qr': ai_cfg_wc.get('plin_qr') or '',
                    'card_brands': ai_cfg_wc.get('card_brands') or '',
                    'card_provider': ai_cfg_wc.get('card_provider') or '',
                    'card_paylink': ai_cfg_wc.get('card_paylink') or '',
                    'transfer_accounts': ai_cfg_wc.get('transfer_accounts') or '',
                    'transfer_instructions': ai_cfg_wc.get('transfer_instructions') or '',
                    'cash_on_delivery_yes': ai_cfg_wc.get('cash_on_delivery_yes') or '',
                    # Envíos
                    'districts_costs': ai_cfg_wc.get('districts_costs') or '',
                    'typical_delivery_time': ai_cfg_wc.get('typical_delivery_time') or '',
                    'free_shipping_from': ai_cfg_wc.get('free_shipping_from') or '',
                    'delivery_partners': ai_cfg_wc.get('delivery_partners') or '',
                }
                quick_text = None
                if pid.upper() == 'OPEN_CATALOG':
                    quick_text = answer_from_persona('web', persona, brand=((flow_cfg or {}).get('brand') or None))
                elif pid.upper() == 'OPEN_PAYMENTS':
                    quick_text = answer_from_persona('pagos', persona, brand=((flow_cfg or {}).get('brand') or None))
                elif pid.upper() == 'OPEN_SHIPPING':
                    quick_text = answer_from_persona('envios', persona, brand=((flow_cfg or {}).get('brand') or None))
                if quick_text:
                    try:
                        send_whatsapp_text(bot, wa_from, quick_text)
                    except Exception:
                        pass
                return JsonResponse({'status': 'ok'})
            return JsonResponse({'status': 'ok'})

        # Expirar flujo si no hubo respuesta del usuario > 5 min
        if user.flow_node and user.last_in_at and (timezone.now() - user.last_in_at) > timezone.timedelta(minutes=5):
            # Enviar aviso de cierre por inactividad + redes sociales (si están configuradas)
            try:
                ai_cfg_wc = _flatten_ai_cfg(flow_cfg)
                redes = []
                if ai_cfg_wc.get('instagram'):
                    redes.append(f"Instagram: {ai_cfg_wc.get('instagram')}")
                if ai_cfg_wc.get('facebook'):
                    redes.append(f"Facebook: {ai_cfg_wc.get('facebook')}")
                if ai_cfg_wc.get('tiktok'):
                    redes.append(f"TikTok: {ai_cfg_wc.get('tiktok')}")
                if ai_cfg_wc.get('youtube'):
                    redes.append(f"YouTube: {ai_cfg_wc.get('youtube')}")
                if ai_cfg_wc.get('x'):
                    redes.append(f"X: {ai_cfg_wc.get('x')}")
                if ai_cfg_wc.get('linktree'):
                    redes.append(f"Linktree: {ai_cfg_wc.get('linktree')}")
                base_msg = "Cerramos este flujo por inactividad (no hubo respuesta). Puedes escribirnos en cualquier momento."
                if redes:
                    base_msg += "\nSíguenos: " + " | ".join(redes)
                send_whatsapp_text(bot, wa_from, base_msg)
            except Exception:
                # no impedir el cierre si falló el envío
                pass
            user.flow_node = None
            user.save(update_fields=['flow_node'])

        # Texto libre: lógica de triggers + cierre de flujo + IA
        raw_text = (msg.get('text', {}).get('body') or '').strip()
        text_low = raw_text.lower()
        nodes = (flow_cfg or {}).get('nodes') or {}
        enabled = (flow_cfg or {}).get('enabled', True)

        # Marcar si es primer contacto (el envío se hará más abajo para evitar duplicados con triggers)
        try:
            is_first_contact = not MessageLog.objects.filter(
                bot=bot,
                direction=MessageLog.OUT,
                wa_to=wa_from,
            ).exists()
        except Exception:
            is_first_contact = False

        # Comando: Cerrar flujo (si hay flujo activo)
        def _norm_close(s: str) -> bool:
            return s.replace('á','a').replace('é','e').replace('í','i').replace('ó','o').replace('ú','u').strip() == 'cerrar flujo'

        if enabled and nodes:
            if user.flow_node:
                if _norm_close(text_low):
                    # Cerrar el flujo y desactivar modo humano para reactivar IA
                    user.flow_node = None
                    user.human_requested = False
                    user.human_expires_at = None
                    user.save(update_fields=['flow_node', 'human_requested', 'human_expires_at'])
                    try:
                        send_whatsapp_text(bot, wa_from, '✅ Flujo cerrado. Puedes escribir otra cosa cuando quieras.')
                    except Exception:
                        pass
                    return JsonResponse({'status': 'ok'})
                # Mientras hay flujo activo, pedimos elegir opción (no activar IA)
                try:
                    send_whatsapp_text(bot, wa_from, 'Por favor, elige una opción del menú.')
                except Exception:
                    pass
                return JsonResponse({'status': 'ok'})

            # Buscar triggers ACTIVOS (keywords, deeplink, IA)
            def ai_match(user_text: str, patterns: str) -> bool:
                # Heurística simple: similitud con muestras (una por línea) o coincidencia de 2+ palabras clave
                lines = [p.strip().lower() for p in patterns.split('\n') if p.strip()]
                for pat in lines:
                    if difflib.SequenceMatcher(None, user_text, pat).ratio() >= 0.72:
                        return True
                    # token match: al menos 2 tokens compartidos de longitud >=3
                    utoks = [t for t in user_text.split() if len(t) >= 3]
                    ptoks = [t for t in pat.split() if len(t) >= 3]
                    if len(set(utoks) & set(ptoks)) >= 2:
                        return True
                return False

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
                        if any(k and k in text_low for k in kws):
                            return node.get('next') or nid
                    elif ttype == 'deeplink':
                        lines = [p.strip().lower() for p in pats.split('\n') if p.strip()]
                        if text_low in lines:
                            return node.get('next') or nid
                    elif ttype == 'ai':
                        if ai_match(text_low, pats):
                            return node.get('next') or nid
                return None

            target = match_trigger()
            if target:
                send_flow_node(target)
                return JsonResponse({'status': 'ok'})

            # Trigger IA con OpenRouter si existen triggers tipo 'ai'
            ai_triggers = []
            for nid, node in nodes.items():
                if (node.get('type') or '').lower() == 'trigger' and (node.get('trigger_type') or '').lower() == 'ai':
                    ai_triggers.append({'id': node.get('next') or nid, 'patterns': node.get('patterns') or ''})
            if ai_triggers:
                chosen = ai_select_trigger(raw_text, ai_triggers)
                if chosen:
                    send_flow_node(chosen)
                    return JsonResponse({'status': 'ok'})

            # Saludo inicial moved: solo si es primer contacto, no hubo trigger y el usuario saludó
            def _looks_like_greeting(s: str) -> bool:
                t = (s or '').lower().strip()
                t = t.replace('¡','').replace('!','').replace('.','').replace(',','')
                return t in ('hola','buenas','buenos dias','buenas tardes','buenas noches','hola buen dia','hola buenos dias')

            if is_first_contact and not user.human_requested and not user.flow_node and raw_text and _looks_like_greeting(raw_text) and (((flow_cfg or {}).get('ai') or (flow_cfg or {}).get('ai_config'))):
                ai_cfg_wc = _flatten_ai_cfg(flow_cfg)
                _assistant_name = (
                    ai_cfg_wc.get('assistant_name')
                    or ai_cfg_wc.get('assistant')
                    or ai_cfg_wc.get('assistantName')
                    or ai_cfg_wc.get('nombre_asistente')
                    or ai_cfg_wc.get('name')
                    or 'Asistente'
                )
                assistant_name = (_assistant_name or '').strip()
                welcome_message = (
                    ai_cfg_wc.get('welcome_message')
                    or ai_cfg_wc.get('welcome')
                    or ai_cfg_wc.get('greeting')
                    or f"Hola, soy {assistant_name}, tu asistente de ventas. ¿Qué te gustaría ver hoy?"
                )
                # Evitar placeholders antiguos tipo "[Nombre del negocio]"
                wlow = (welcome_message or '').lower()
                if ('[' in welcome_message and ']' in welcome_message and 'nombre del negocio' in wlow):
                    welcome_message = f"Hola, soy {assistant_name}, tu asistente de ventas. ¿Qué te gustaría ver hoy?"
                welcome_message = welcome_message.strip()
                # Intentar enviar botones de bienvenida según datos disponibles
                try:
                    buttons = []
                    has_catalog = bool((ai_cfg_wc.get('catalog_url') or ai_cfg_wc.get('website')))
                    has_payments = bool(
                        ai_cfg_wc.get('yape_number') or ai_cfg_wc.get('plin_number') or ai_cfg_wc.get('card_brands') or ai_cfg_wc.get('transfer_accounts') or ai_cfg_wc.get('cash_on_delivery_yes')
                    )
                    has_shipping = bool(
                        ai_cfg_wc.get('districts_costs') or ai_cfg_wc.get('typical_delivery_time') or ai_cfg_wc.get('free_shipping_from') or ai_cfg_wc.get('delivery_partners')
                    )
                    if has_catalog:
                        buttons.append({'id': 'OPEN_CATALOG', 'title': '📎 Catálogo'})
                    if has_payments:
                        buttons.append({'id': 'OPEN_PAYMENTS', 'title': '💳 Pagos'})
                    if has_shipping:
                        buttons.append({'id': 'OPEN_SHIPPING', 'title': '🚚 Envíos'})
                    if buttons:
                        send_whatsapp_interactive_buttons(bot, wa_from, welcome_message, buttons)
                    else:
                        send_whatsapp_text(bot, wa_from, welcome_message)
                except Exception:
                    pass
                return JsonResponse({'status': 'ok'})

            # Respuesta IA general sólo si NO humano y NO flujo activo
            if not user.human_requested:
                # Construir persona/"cerebro" desde el flujo
                ai_cfg = _flatten_ai_cfg(flow_cfg)
                # Back-compat: soportar posibles claves usadas en el builder
                _assistant_name = (
                    ai_cfg.get('assistant_name')
                    or ai_cfg.get('assistant')
                    or ai_cfg.get('assistantName')
                    or ai_cfg.get('nombre_asistente')
                    or ai_cfg.get('name')
                    or 'Asistente'
                )
                persona = {
                    'name': _assistant_name,
                    'about': ai_cfg.get('about') or ai_cfg.get('presentation') or '',
                    'knowledge': ai_cfg.get('knowledge') or ai_cfg.get('brain') or ai_cfg.get('kb') or '',
                    'style': ai_cfg.get('style') or '',
                    'system': ai_cfg.get('system') or ai_cfg.get('instructions') or '',
                    # Ventas y tono
                    'sales_playbook': ai_cfg.get('sales_playbook') or '',
                    'cta_phrases': ai_cfg.get('cta_phrases') or '',
                    'emoji_level': ai_cfg.get('emoji_level') or '',
                    'recommendation_examples': ai_cfg.get('recommendation_examples') or '',
                    'language': ai_cfg.get('language') or ai_cfg.get('lang') or 'español',
                    # Aceptar también claves del Builder: website_url y phone_number
                    'website': ai_cfg.get('website') or ai_cfg.get('website_url') or ai_cfg.get('site') or ai_cfg.get('url') or '',
                    'phone': ai_cfg.get('phone') or ai_cfg.get('phone_number') or ai_cfg.get('telefono') or '',
                    'email': ai_cfg.get('email') or ai_cfg.get('correo') or '',
                    'order_required': ai_cfg.get('order_required') or ai_cfg.get('required_info') or ai_cfg.get('required_fields') or '',
                    'out_of_scope': ai_cfg.get('out_of_scope') or ai_cfg.get('oos') or ai_cfg.get('temas_fuera') or '',
                    'response_policies': ai_cfg.get('response_policies') or ai_cfg.get('pol_resp') or '',
                    'comm_policies': ai_cfg.get('comm_policies') or ai_cfg.get('pol_comm') or '',
                    # Perfil del negocio
                    'trade_name': ai_cfg.get('trade_name') or ai_cfg.get('nombre_comercial') or '',
                    'legal_name': ai_cfg.get('legal_name') or ai_cfg.get('razon_social') or '',
                    'ruc': ai_cfg.get('ruc') or '',
                    'timezone': ai_cfg.get('timezone') or ai_cfg.get('zona_horaria') or '',
                    'address': ai_cfg.get('address') or ai_cfg.get('direccion') or '',
                    'city': ai_cfg.get('city') or ai_cfg.get('ciudad') or '',
                    'region': ai_cfg.get('region') or ai_cfg.get('departamento') or '',
                    'country': ai_cfg.get('country') or ai_cfg.get('pais') or '',
                    'maps_url': ai_cfg.get('maps_url') or ai_cfg.get('google_maps') or '',
                    'ubigeo': ai_cfg.get('ubigeo') or '',
                    'hours_mon_fri': ai_cfg.get('hours_mon_fri') or ai_cfg.get('horario_lv') or '',
                    'hours_sat': ai_cfg.get('hours_sat') or ai_cfg.get('horario_sab') or '',
                    'hours_sun': ai_cfg.get('hours_sun') or ai_cfg.get('horario_dom') or '',
                    # Redes y enlaces
                    'instagram': ai_cfg.get('instagram') or '',
                    'facebook': ai_cfg.get('facebook') or '',
                    'tiktok': ai_cfg.get('tiktok') or '',
                    'youtube': ai_cfg.get('youtube') or '',
                    'x': ai_cfg.get('x') or ai_cfg.get('twitter') or '',
                    'linktree': ai_cfg.get('linktree') or '',
                    'whatsapp_link': ai_cfg.get('whatsapp_link') or '',
                    'catalog_url': ai_cfg.get('catalog_url') or ai_cfg.get('site_shop') or '',
                    # Catálogo estructurado
                    'categories': ai_cfg.get('categories') or '',
                    'featured_products': ai_cfg.get('featured_products') or '',
                    'size_guide_url': ai_cfg.get('size_guide_url') or '',
                    'size_notes': ai_cfg.get('size_notes') or '',
                    # Modalidad de venta
                    'retail_yes': ai_cfg.get('retail_yes') or '',
                    'wholesale_yes': ai_cfg.get('wholesale_yes') or '',
                    'wholesale_min_qty': ai_cfg.get('wholesale_min_qty') or '',
                    'wholesale_price_list_url': ai_cfg.get('wholesale_price_list_url') or '',
                    'wholesale_requires_ruc': ai_cfg.get('wholesale_requires_ruc') or '',
                    'prep_time_large_orders': ai_cfg.get('prep_time_large_orders') or '',
                    'volume_discounts': ai_cfg.get('volume_discounts') or '',
                    # Pagos
                    'yape_number': ai_cfg.get('yape_number') or '',
                    'yape_holder': ai_cfg.get('yape_holder') or '',
                    'yape_alias': ai_cfg.get('yape_alias') or '',
                    'yape_qr': ai_cfg.get('yape_qr') or '',
                    'plin_number': ai_cfg.get('plin_number') or '',
                    'plin_holder': ai_cfg.get('plin_holder') or '',
                    'plin_qr': ai_cfg.get('plin_qr') or '',
                    'card_brands': ai_cfg.get('card_brands') or '',
                    'card_provider': ai_cfg.get('card_provider') or '',
                    'card_paylink': ai_cfg.get('card_paylink') or '',
                    'card_fee_notes': ai_cfg.get('card_fee_notes') or '',
                    'transfer_accounts': ai_cfg.get('transfer_accounts') or '',
                    'transfer_instructions': ai_cfg.get('transfer_instructions') or '',
                    'cash_on_delivery_yes': ai_cfg.get('cash_on_delivery_yes') or '',
                    # Envíos
                    'districts_costs': ai_cfg.get('districts_costs') or '',
                    'typical_delivery_time': ai_cfg.get('typical_delivery_time') or '',
                    'free_shipping_from': ai_cfg.get('free_shipping_from') or '',
                    'pickup_address': ai_cfg.get('pickup_address') or '',
                    'delivery_partners': ai_cfg.get('delivery_partners') or '',
                    # Políticas y comprobantes
                    'returns_policy': ai_cfg.get('returns_policy') or '',
                    'warranty': ai_cfg.get('warranty') or '',
                    'terms_url': ai_cfg.get('terms_url') or '',
                    'privacy_url': ai_cfg.get('privacy_url') or '',
                    'boleta_yes': ai_cfg.get('boleta_yes') or '',
                    'factura_yes': ai_cfg.get('factura_yes') or '',
                }
                # Primero: IA generativa orientada a ventas (anclada al Cerebro)
                brand = (
                    (flow_cfg or {}).get('brand')
                    or persona.get('trade_name')
                    or persona.get('legal_name')
                    or None
                )
                answer = ai_answer(raw_text, brand=brand, persona=persona)
                if answer:
                    try:
                        send_whatsapp_text(bot, wa_from, answer)
                    except Exception:
                        pass
                    return JsonResponse({'status': 'ok'})
                # Segundo: intento determinista basado en el Cerebro
                quick = answer_from_persona(raw_text, persona, brand=brand)
                if quick:
                    try:
                        send_whatsapp_text(bot, wa_from, quick)
                    except Exception:
                        pass
                    return JsonResponse({'status': 'ok'})
                # Segundo: si no encontró, usar IA SOLO para detectar intención y responder con datos del Cerebro
                # (no inventar información; la respuesta final se arma desde persona)
                if callable(classify_intent_label):
                    allowed_labels = [
                        'ubicacion','telefono','web','redes','horarios','pagos','yape','plin','tarjeta','transferencia','contraentrega',
                        'envios','mayorista','ruc','boleta','factura',
                        # Conversión/venta
                        'compra','producto','productos','recomendacion','catalogo','modelos','precios'
                    ]
                    label = classify_intent_label(raw_text, allowed_labels, language=(persona.get('language') or 'español'))
                    if label:
                        # Mapear algunas etiquetas a prompts canónicos del motor determinista
                        mapped = label
                        if label in ('compra','producto','productos','recomendacion','catalogo','modelos','precios'):
                            mapped = 'comprar'
                        # Reusar motor determinista con prompt canónico
                        quick2 = answer_from_persona(mapped, persona, brand=( (flow_cfg or {}).get('brand') or persona.get('trade_name') or persona.get('legal_name') or None ))
                        if quick2:
                            final_text = quick2
                            if callable(naturalize_from_answer):
                                refined = naturalize_from_answer(raw_text, quick2, assistant_name=persona.get('name'), language=(persona.get('language') or 'español'))
                                if (refined or '').strip():
                                    final_text = refined.strip()
                            try:
                                send_whatsapp_text(bot, wa_from, final_text)
                            except Exception:
                                pass
                            return JsonResponse({'status': 'ok'})
                # Si aún no hubo respuesta, usar IA una vez más (por si se armó mejor con label)
                answer = ai_answer(raw_text, brand=brand, persona=persona)
                if not answer:
                    # Fallback amable sin inventar información
                    name = persona.get('name') or 'Asistente'
                    order_lines = [ln.strip() for ln in (persona.get('order_required') or '').split('\n') if ln.strip()]
                    pedido_hint = ("\nSi deseas hacer un pedido, por favor comparte: " + ", ".join(order_lines[:5])) if order_lines else ''
                    answer = f"Disculpa, no te entendí bien. ¿Podrías reformular o darme un poco más de detalle?{pedido_hint}"
                try:
                    send_whatsapp_text(bot, wa_from, answer)
                except Exception:
                    pass
                return JsonResponse({'status': 'ok'})

        # Fallback: aunque el flujo esté deshabilitado o sin nodos, permitir IA si no está activado el modo humano
        if not user.human_requested and raw_text:
            ai_cfg = _flatten_ai_cfg(flow_cfg)
            _assistant_name = (
                ai_cfg.get('assistant_name')
                or ai_cfg.get('assistant')
                or ai_cfg.get('assistantName')
                or ai_cfg.get('nombre_asistente')
                or ai_cfg.get('name')
                or 'Asistente'
            )
            persona = {
                'name': _assistant_name,
                'about': ai_cfg.get('about') or ai_cfg.get('presentation') or '',
                'knowledge': ai_cfg.get('knowledge') or ai_cfg.get('brain') or ai_cfg.get('kb') or '',
                'style': ai_cfg.get('style') or '',
                'system': ai_cfg.get('system') or ai_cfg.get('instructions') or '',
                'sales_playbook': ai_cfg.get('sales_playbook') or '',
                'cta_phrases': ai_cfg.get('cta_phrases') or '',
                'emoji_level': ai_cfg.get('emoji_level') or '',
                'recommendation_examples': ai_cfg.get('recommendation_examples') or '',
                'language': ai_cfg.get('language') or ai_cfg.get('lang') or 'español',
                'website': ai_cfg.get('website') or ai_cfg.get('website_url') or ai_cfg.get('site') or ai_cfg.get('url') or '',
                'phone': ai_cfg.get('phone') or ai_cfg.get('phone_number') or ai_cfg.get('telefono') or '',
                'email': ai_cfg.get('email') or ai_cfg.get('correo') or '',
                'order_required': ai_cfg.get('order_required') or ai_cfg.get('required_info') or ai_cfg.get('required_fields') or '',
                'out_of_scope': ai_cfg.get('out_of_scope') or ai_cfg.get('oos') or ai_cfg.get('temas_fuera') or '',
                'response_policies': ai_cfg.get('response_policies') or ai_cfg.get('pol_resp') or '',
                'comm_policies': ai_cfg.get('comm_policies') or ai_cfg.get('pol_comm') or '',
                # Perfil del negocio
                'trade_name': ai_cfg.get('trade_name') or ai_cfg.get('nombre_comercial') or '',
                'legal_name': ai_cfg.get('legal_name') or ai_cfg.get('razon_social') or '',
                'ruc': ai_cfg.get('ruc') or '',
                'timezone': ai_cfg.get('timezone') or ai_cfg.get('zona_horaria') or '',
                'address': ai_cfg.get('address') or ai_cfg.get('direccion') or '',
                'city': ai_cfg.get('city') or ai_cfg.get('ciudad') or '',
                'region': ai_cfg.get('region') or ai_cfg.get('departamento') or '',
                'country': ai_cfg.get('country') or ai_cfg.get('pais') or '',
                'maps_url': ai_cfg.get('maps_url') or ai_cfg.get('google_maps') or '',
                'ubigeo': ai_cfg.get('ubigeo') or '',
                'hours_mon_fri': ai_cfg.get('hours_mon_fri') or ai_cfg.get('horario_lv') or '',
                'hours_sat': ai_cfg.get('hours_sat') or ai_cfg.get('horario_sab') or '',
                'hours_sun': ai_cfg.get('hours_sun') or ai_cfg.get('horario_dom') or '',
                # Redes y enlaces
                'instagram': ai_cfg.get('instagram') or '',
                'facebook': ai_cfg.get('facebook') or '',
                'tiktok': ai_cfg.get('tiktok') or '',
                'youtube': ai_cfg.get('youtube') or '',
                'x': ai_cfg.get('x') or ai_cfg.get('twitter') or '',
                'linktree': ai_cfg.get('linktree') or '',
                'whatsapp_link': ai_cfg.get('whatsapp_link') or '',
                'catalog_url': ai_cfg.get('catalog_url') or ai_cfg.get('site_shop') or '',
                'categories': ai_cfg.get('categories') or '',
                'featured_products': ai_cfg.get('featured_products') or '',
                'size_guide_url': ai_cfg.get('size_guide_url') or '',
                'size_notes': ai_cfg.get('size_notes') or '',
                # Modalidad de venta
                'retail_yes': ai_cfg.get('retail_yes') or '',
                'wholesale_yes': ai_cfg.get('wholesale_yes') or '',
                'wholesale_min_qty': ai_cfg.get('wholesale_min_qty') or '',
                'wholesale_price_list_url': ai_cfg.get('wholesale_price_list_url') or '',
                'wholesale_requires_ruc': ai_cfg.get('wholesale_requires_ruc') or '',
                'prep_time_large_orders': ai_cfg.get('prep_time_large_orders') or '',
                'volume_discounts': ai_cfg.get('volume_discounts') or '',
                # Pagos
                'yape_number': ai_cfg.get('yape_number') or '',
                'yape_holder': ai_cfg.get('yape_holder') or '',
                'yape_alias': ai_cfg.get('yape_alias') or '',
                'yape_qr': ai_cfg.get('yape_qr') or '',
                'plin_number': ai_cfg.get('plin_number') or '',
                'plin_holder': ai_cfg.get('plin_holder') or '',
                'plin_qr': ai_cfg.get('plin_qr') or '',
                'card_brands': ai_cfg.get('card_brands') or '',
                'card_provider': ai_cfg.get('card_provider') or '',
                'card_paylink': ai_cfg.get('card_paylink') or '',
                'card_fee_notes': ai_cfg.get('card_fee_notes') or '',
                'transfer_accounts': ai_cfg.get('transfer_accounts') or '',
                'transfer_instructions': ai_cfg.get('transfer_instructions') or '',
                'cash_on_delivery_yes': ai_cfg.get('cash_on_delivery_yes') or '',
                # Envíos
                'districts_costs': ai_cfg.get('districts_costs') or '',
                'typical_delivery_time': ai_cfg.get('typical_delivery_time') or '',
                'free_shipping_from': ai_cfg.get('free_shipping_from') or '',
                'pickup_address': ai_cfg.get('pickup_address') or '',
                'delivery_partners': ai_cfg.get('delivery_partners') or '',
                # Políticas y comprobantes
                'returns_policy': ai_cfg.get('returns_policy') or '',
                'warranty': ai_cfg.get('warranty') or '',
                'terms_url': ai_cfg.get('terms_url') or '',
                'privacy_url': ai_cfg.get('privacy_url') or '',
                'boleta_yes': ai_cfg.get('boleta_yes') or '',
                'factura_yes': ai_cfg.get('factura_yes') or '',
            }

            # IA generativa primero
            brand = (
                (flow_cfg or {}).get('brand')
                or persona.get('trade_name')
                or persona.get('legal_name')
                or None
            )
            answer = ai_answer(raw_text, brand=brand, persona=persona)
            if answer:
                try:
                    send_whatsapp_text(bot, wa_from, answer)
                except Exception:
                    pass
                return JsonResponse({'status': 'ok'})
            # Segundo: intento determinista
            quick = answer_from_persona(raw_text, persona, brand=brand)
            if quick:
                try:
                    send_whatsapp_text(bot, wa_from, quick)
                except Exception:
                    pass
                return JsonResponse({'status': 'ok'})
            if not answer:
                name = persona.get('name') or 'Asistente'
                order_lines = [ln.strip() for ln in (persona.get('order_required') or '').split('\n') if ln.strip()]
                pedido_hint = ("\nSi deseas hacer un pedido, por favor comparte: " + ", ".join(order_lines[:5])) if order_lines else ''
                answer = f"Disculpa, no te entendí bien. ¿Podrías reformular o darme un poco más de detalle?{pedido_hint}"
            try:
                send_whatsapp_text(bot, wa_from, answer)
            except Exception:
                pass
            return JsonResponse({'status': 'ok'})

        # No activar flujo si no hay trigger; no responder
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
            # Heurística para previsualización: similitud básica
            lines = [p.strip().lower() for p in pats.split('\n') if p.strip()]
            for pat in lines:
                if difflib.SequenceMatcher(None, text_low, pat).ratio() >= 0.72:
                    return node.get('next') or nid
                utoks = [t for t in text_low.split() if len(t) >= 3]
                ptoks = [t for t in pat.split() if len(t) >= 3]
                if len(set(utoks) & set(ptoks)) >= 2:
                    return node.get('next') or nid
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
