import secrets
import socket

from django.db import models
from django.utils import timezone


class Server(models.Model):
    class Status(models.TextChoices):
        ONLINE = 'online', 'Online'
        OFFLINE = 'offline', 'Offline'
        PENDING = 'pending', 'Pending Enrollment'

    name = models.CharField(max_length=100)
    hostname = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    tags = models.CharField(max_length=255, blank=True, help_text='Comma-separated tags')
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    # Agent enrollment
    enrollment_token = models.CharField(max_length=64, unique=True, default=secrets.token_hex)
    api_key_hash = models.CharField(max_length=128, blank=True)
    enrolled_at = models.DateTimeField(null=True, blank=True)

    # Agent info (reported by agent on connect)
    os_info = models.CharField(max_length=255, blank=True)
    agent_version = models.CharField(max_length=32, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def get_tags_list(self):
        if not self.tags:
            return []
        return [t.strip() for t in self.tags.split(',') if t.strip()]

    class Meta:
        ordering = ['name']


class Metric(models.Model):
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='metrics')
    cpu_percent = models.FloatField()
    memory_percent = models.FloatField()
    memory_used_mb = models.FloatField()
    memory_total_mb = models.FloatField()
    disk_percent = models.FloatField()
    disk_used_gb = models.FloatField()
    disk_total_gb = models.FloatField()
    load_1m = models.FloatField(default=0)
    load_5m = models.FloatField(default=0)
    load_15m = models.FloatField(default=0)
    uptime_seconds = models.BigIntegerField(default=0)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['server', '-timestamp']),
        ]


class Domain(models.Model):
    class Status(models.TextChoices):
        MATCHED = 'matched', 'Matched'
        UNMATCHED = 'unmatched', 'Unmatched'
        ERROR = 'error', 'DNS Error'

    name = models.CharField(max_length=255, unique=True)
    resolved_ip = models.GenericIPAddressField(blank=True, null=True)
    server = models.ForeignKey(
        Server, on_delete=models.SET_NULL, null=True, blank=True, related_name='domains'
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ERROR)
    last_checked = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def resolve(self):
        """DNS lookup and auto-match to a server by IP."""
        try:
            results = socket.getaddrinfo(self.name, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            ip = results[0][4][0] if results else None
        except socket.gaierror:
            self.resolved_ip = None
            self.server = None
            self.status = self.Status.ERROR
            self.last_checked = timezone.now()
            self.save()
            return

        self.resolved_ip = ip
        self.last_checked = timezone.now()

        matched_server = Server.objects.filter(ip_address=ip).first()
        if matched_server:
            self.server = matched_server
            self.status = self.Status.MATCHED
        else:
            self.server = None
            self.status = self.Status.UNMATCHED
        self.save()

    class Meta:
        ordering = ['name']
