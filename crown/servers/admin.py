from django.contrib import admin
from .models import Server, Metric, Domain


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = ['name', 'ip_address', 'status', 'last_seen', 'created_at']
    list_filter = ['status']
    search_fields = ['name', 'ip_address', 'hostname']
    readonly_fields = ['enrollment_token', 'enrolled_at', 'last_seen', 'created_at', 'updated_at']


@admin.register(Metric)
class MetricAdmin(admin.ModelAdmin):
    list_display = ['server', 'cpu_percent', 'memory_percent', 'disk_percent', 'timestamp']
    list_filter = ['server']


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ['name', 'resolved_ip', 'server', 'status', 'last_checked']
    list_filter = ['status']
    search_fields = ['name', 'resolved_ip']
