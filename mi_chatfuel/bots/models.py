from django.db import models
from django.contrib.auth import get_user_model
import uuid


User = get_user_model()


class Bot(models.Model):
	owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bots')
	name = models.CharField(max_length=100)
	uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
	phone_number_id = models.CharField(max_length=64)
	access_token = models.TextField()
	verify_token = models.CharField(max_length=128)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return f"{self.name} ({self.phone_number_id})"


class Flow(models.Model):
	bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name='flows')
	name = models.CharField(max_length=100)
	definition = models.JSONField(default=dict, blank=True)
	is_active = models.BooleanField(default=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		return f"{self.name} - {self.bot.name}"


class MessageLog(models.Model):
	IN = 'in'
	OUT = 'out'
	DIRECTION_CHOICES = [
		(IN, 'Inbound'),
		(OUT, 'Outbound'),
	]

	bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name='messages')
	direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
	wa_from = models.CharField(max_length=64, blank=True)
	wa_to = models.CharField(max_length=64, blank=True)
	message_type = models.CharField(max_length=32, blank=True)
	payload = models.JSONField(default=dict, blank=True)
	status = models.CharField(max_length=32, blank=True)
	error = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return f"{self.direction} {self.message_type} {self.created_at:%Y-%m-%d %H:%M:%S}"


class WaUser(models.Model):
	"""Estado por usuario de WhatsApp para ejecución de flujo y chat humano."""
	bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name='wa_users')
	wa_id = models.CharField(max_length=64)
	name = models.CharField(max_length=200, blank=True)
	human_requested = models.BooleanField(default=False)
	human_timeout_min = models.IntegerField(default=15)
	human_expires_at = models.DateTimeField(null=True, blank=True)
	last_message_at = models.DateTimeField(null=True, blank=True)
	last_in_at = models.DateTimeField(null=True, blank=True)
	flow_node = models.CharField(max_length=128, null=True, blank=True)

	class Meta:
		unique_together = ('bot', 'wa_id')

	def __str__(self):
		return f"{self.wa_id} ({self.bot.name})"


class AIKey(models.Model):
	"""Claves API de IA con prioridad y estado para failover/rotación.
	Actualmente usadas para OpenRouter; extensible a otros proveedores.
	"""
	PROVIDER_OPENROUTER = 'openrouter'
	PROVIDER_CHOICES = [
		(PROVIDER_OPENROUTER, 'OpenRouter'),
	]

	provider = models.CharField(max_length=40, choices=PROVIDER_CHOICES, default=PROVIDER_OPENROUTER)
	name = models.CharField(max_length=100, blank=True, help_text="Etiqueta para identificar la clave")
	api_key = models.TextField(help_text="Valor del API key (se guarda cifrado si el backend lo soporta)")
	is_active = models.BooleanField(default=True)
	priority = models.IntegerField(default=100, help_text="Menor número = mayor prioridad")
	last_used_at = models.DateTimeField(null=True, blank=True)
	failure_count = models.IntegerField(default=0)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['priority', '-is_active', 'last_used_at']

	def __str__(self):
		label = self.name or (self.api_key[:6] + '…' if self.api_key else 'key')
		return f"{self.get_provider_display()} • {label}"

