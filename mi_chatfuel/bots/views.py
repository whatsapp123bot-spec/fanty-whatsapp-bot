import json
from pathlib import Path

from django.http import (
	HttpResponse,
	HttpResponseForbidden,
	JsonResponse,
	HttpResponseRedirect,
)
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.contrib.auth.decorators import login_required
import requests
from .models import Bot, MessageLog, Flow, WaUser
	# Esta vista ya no se usa: redirigimos al Builder visual directamente
	return HttpResponseRedirect(reverse('flow_builder', args=[bot_pk, flow_pk]))
		  <li><a href="/admin/">Ir al Admin</a></li>
		  <li>Panel: <a href="/panel/">/panel/</a></li>
		  <li>Webhook por bot: <code>/webhooks/whatsapp/&lt;uuid&gt;/</code></li>
		</ul>
	flows = bot.flows.order_by('-updated_at')
	return render(request, 'bots/flows.html', {
		'brand': 'OptiChat',
		'bot': bot,
		'flows': flows,
	})
	for b in bots_qs:
		webhook_url = request.build_absolute_uri(
			reverse('whatsapp_webhook', args=[str(b.uuid)])
		)
		bots_info.append({
			'id': b.id,
			'name': b.name,
			'pnid': b.phone_number_id,
			'uuid': str(b.uuid),
			'is_active': b.is_active,
			'created_at': b.created_at,
			'edit_url': reverse('bot_edit', args=[b.id]),
			'validate_url': reverse('bot_validate', args=[b.id]),
			'flows_url': reverse('flow_list', args=[b.id]),
			'webhook_url': webhook_url,
		})
	return render(request, 'bots/panel.html', {
		'brand': 'OptiChat',
		'bots': bots_info,
	})


@login_required
def panel_live_chat(request):
	"""Página de chat en vivo integrada en el panel."""
	# Mostramos una lista de conversaciones recientes y la vista de mensajes.
	return render(request, 'bots/live_chat.html', {
		'brand': 'OptiChat',
	})


@login_required
def api_list_conversations(request):
	"""Lista conversaciones recientes del usuario logueado (todas las de sus bots)."""
	limit = int(request.GET.get('limit', '100'))
	human_only = request.GET.get('live') == '1'
	# Traer por bots del usuario
	bots = list(Bot.objects.filter(owner=request.user, is_active=True))
	bot_ids = [b.id for b in bots]
	items = []
	if bot_ids:
		qs = WaUser.objects.filter(bot_id__in=bot_ids)
		if human_only:
			qs = qs.filter(human_requested=True)
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
	# Buscar el WaUser en bots del usuario
	u = WaUser.objects.filter(wa_id=wa_id, bot__owner=request.user).first()
	if not u:
		return JsonResponse({'error': 'No encontrado'}, status=404)
	# Traer últimos N mensajes
	limit = int(request.GET.get('limit', '200'))
	msgs = MessageLog.objects.filter(bot=u.bot, wa_from__in=[wa_id, u.bot.phone_number_id], wa_to__in=[wa_id, u.bot.phone_number_id])\
		.order_by('created_at')[:limit]
	out = []
	for m in msgs:
		out.append({
			'direction': m.direction,
			'type': m.message_type,
			'body': (m.payload or {}).get('request', {}).get('text', {}).get('body') if m.direction == MessageLog.OUT and m.message_type == 'text' else (
				(m.payload or {}).get('request', {}).get('interactive', {}).get('body', {}).get('text') if m.direction == MessageLog.OUT and m.message_type == 'interactive' else (
					(m.payload or {}).get('response', {}).get('messages', [{}])[0].get('text', {}).get('body') if m.direction == MessageLog.IN else None
				)
			),
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
	if not wa_id or not text:
		return JsonResponse({'error': 'Faltan parámetros'}, status=400)
	u = WaUser.objects.filter(wa_id=wa_id, bot__owner=request.user).first()
	if not u:
		return JsonResponse({'error': 'No encontrado'}, status=404)
	if not u.human_requested:
		return JsonResponse({'error': 'Chat humano no activo para este usuario'}, status=403)
	from .services import send_whatsapp_text
	send_whatsapp_text(u.bot, wa_id, text)
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
			return HttpResponseRedirect(reverse('panel'))
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
			return HttpResponseRedirect(reverse('panel'))
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
	# Validación simple contra Graph: obtener datos del PNID
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
	items = ''.join([
		f'<li>{f.name} '
		f'[<a href="/panel/bots/{bot.id}/flows/{f.id}/edit/">Editar</a>] '
		f'[<a href="/panel/bots/{bot.id}/flows/{f.id}/builder/" target="_blank">Builder</a>]'
		f'</li>' for f in flows
	])
	return HttpResponse(
		f'<h1>Flujos de {bot.name}</h1>'
		f'<p><a href="/panel/bots/{bot.id}/flows/new/">+ Nuevo Flujo</a></p>'
		f'<ul>{items}</ul>'
		f'<p><a href="/panel/">Volver</a></p>',
		content_type='text/html'
	)


@login_required
def flow_new(request, bot_pk):
	bot = get_object_or_404(Bot, pk=bot_pk, owner=request.user)
	if request.method == 'POST':
		form = FlowForm(request.POST)
		if form.is_valid():
			flow = form.save(commit=False)
			flow.bot = bot
			flow.save()
			return HttpResponseRedirect(reverse('flow_list', args=[bot.id]))
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
	bot = get_object_or_404(Bot, pk=bot_pk, owner=request.user)
	flow = get_object_or_404(Flow, pk=flow_pk, bot=bot)
	if request.method == 'POST':
		form = FlowForm(request.POST, instance=flow)
		if form.is_valid():
			form.save()
			return HttpResponseRedirect(reverse('flow_list', args=[bot.id]))
	else:
		form = FlowForm(instance=flow)
	return render(request, 'bots/flow_form.html', {
		'title': f'Editar Flujo — {bot.name}: {flow.name}',
		'form': form,
		'submit_label': 'Guardar',
		'bot': bot,
	})


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
	}
	from django.shortcuts import render
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
		return JsonResponse({'error': f'JSON inválido: {e}'} , status=400)
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
		MessageLog.objects.create(
			bot=bot,
			direction=MessageLog.IN,
			wa_from=wa_from,
			wa_to=value.get('metadata', {}).get('display_phone_number', ''),
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
			# formato legacy
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
			# Otros IDs especiales de negocio pueden mapearse aquí si los necesitas
			return JsonResponse({'status': 'ok'})

		# Texto libre: intentar triggers si no hay flujo activo
		text_low = (msg.get('text', {}).get('body') or '').strip().lower()
		nodes = (flow_cfg or {}).get('nodes') or {}
		enabled = (flow_cfg or {}).get('enabled', True)
		if enabled and nodes:
			# Si ya hay flujo, opcionalmente ignorar texto libre (como bloqueo)
			if user.flow_node:
				# Enviar recordatorio de menú
				send_whatsapp_text(bot, wa_from, 'Por favor, elige una opción del menú.')
				return JsonResponse({'status': 'ok'})

			# Triggers: keywords/deeplink
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
						# pendiente: IA
						continue
				return None

			target = match_trigger()
			if target:
				send_flow_node(target)
				return JsonResponse({'status': 'ok'})
			if flow_cfg.get('start_node'):
				send_flow_node(flow_cfg.get('start_node'))
				return JsonResponse({'status': 'ok'})

		# Si no hay flujo o no matcheó
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

	# Redirecciones automáticas
	if ntype == 'start' and node.get('next'):
		return _build_preview_for_node(flow_cfg, node.get('next'))
	if ntype == 'trigger' and node.get('next'):
		return _build_preview_for_node(flow_cfg, node.get('next'))

	# Texto + assets en HTML
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

	# Botones
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
	"""Devuelve el node_id a arrancar si un trigger matchea; si no, None."""
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
			# En preview ignoramos IA real
			continue
	return None


def chat_preview(request):
	# Simulador tipo WhatsApp
	return render(request, 'chat.html')


@csrf_exempt
def send_message_preview(request):
	"""Vista previa conectada al flow.json (similar a Flask)."""
	if request.method != 'POST':
		return JsonResponse({'error': 'Método no permitido'}, status=405)

	flow_cfg = _load_legacy_flow_config()
	payload = request.POST.get('payload')
	user_message = request.POST.get('message', '')

	# Navegación por payload
	if payload:
		p = payload.strip()
		if p.upper().startswith('FLOW:'):
			node_id = p.split(':', 1)[1]
			return JsonResponse(_build_preview_for_node(flow_cfg, node_id))
		# IDs especiales → volver al inicio si existe
		if p.upper() == 'MENU_PRINCIPAL' and flow_cfg.get('start_node'):
			return JsonResponse(_build_preview_for_node(flow_cfg, flow_cfg.get('start_node')))
		return JsonResponse({'response': ' '})

	low = (user_message or '').strip().lower()
	if not low:
		return JsonResponse({'response': ' '})

	nodes = (flow_cfg or {}).get('nodes') or {}
	if (flow_cfg or {}).get('enabled', True) and nodes:
		# Intentar triggers primero
		target = _match_trigger(flow_cfg, low)
		if target:
			return JsonResponse(_build_preview_for_node(flow_cfg, target))
		# Si no hay triggers, arrancar en start_node si existe
		if flow_cfg.get('start_node'):
			return JsonResponse(_build_preview_for_node(flow_cfg, flow_cfg.get('start_node')))

	return JsonResponse({'response': '🤖 No hay un match en el flujo para tu mensaje.'})
