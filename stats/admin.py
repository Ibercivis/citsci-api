from django.contrib import admin

from stats.models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ('event', 'period_key', 'status', 'created_at', 'sent_at')
    list_filter = ('event', 'status')
    search_fields = ('period_key', 'subject')
    readonly_fields = ('created_at',)
