from django.contrib import admin
from .models import Bot, Flow, MessageLog, AIKey


@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
	list_display = ("name", "owner", "phone_number_id", "is_active", "created_at")
	search_fields = ("name", "phone_number_id", "owner__username")
	list_filter = ("is_active",)


@admin.register(Flow)
class FlowAdmin(admin.ModelAdmin):
	list_display = ("name", "bot", "is_active", "updated_at")
	search_fields = ("name", "bot__name")
	list_filter = ("is_active",)


@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
	list_display = ("bot", "direction", "message_type", "wa_from", "wa_to", "status", "created_at")
	search_fields = ("wa_from", "wa_to", "message_type", "status")
	list_filter = ("direction", "message_type")


@admin.register(AIKey)
class AIKeyAdmin(admin.ModelAdmin):
	list_display = ("provider", "name", "is_active", "priority", "failure_count", "last_used_at", "updated_at")
	list_filter = ("provider", "is_active")
	search_fields = ("name", "api_key")
	readonly_fields = ("last_used_at", "failure_count", "created_at", "updated_at")
