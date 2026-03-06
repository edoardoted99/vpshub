import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone


class AgentConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for agent connections."""

    async def connect(self):
        self.server_id = None
        await self.accept()

    async def disconnect(self, close_code):
        if self.server_id:
            await self.mark_server_offline(self.server_id)

    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get('type')

        if msg_type == 'enroll':
            await self.handle_enroll(data)
        elif msg_type == 'heartbeat':
            await self.handle_heartbeat(data)
        elif msg_type == 'metrics':
            await self.handle_metrics(data)

    async def handle_enroll(self, data):
        token = data.get('token', '')
        server = await self.enroll_agent(token)
        if server:
            self.server_id = server.id
            await self.send(text_data=json.dumps({
                'type': 'enrolled',
                'server_id': server.id,
            }))
        else:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid enrollment token',
            }))
            await self.close()

    async def handle_heartbeat(self, data):
        if self.server_id:
            await self.update_last_seen(self.server_id)

    async def handle_metrics(self, data):
        if self.server_id:
            payload = data.get('payload', {})
            await self.save_metrics(self.server_id, payload)
            await self.update_last_seen(self.server_id)

    @database_sync_to_async
    def enroll_agent(self, token):
        from .models import Server
        try:
            server = Server.objects.get(enrollment_token=token)
            server.status = Server.Status.ONLINE
            server.enrolled_at = timezone.now()
            server.last_seen = timezone.now()
            server.save()
            return server
        except Server.DoesNotExist:
            return None

    @database_sync_to_async
    def update_last_seen(self, server_id):
        from .models import Server
        Server.objects.filter(id=server_id).update(
            last_seen=timezone.now(),
            status=Server.Status.ONLINE,
        )

    @database_sync_to_async
    def mark_server_offline(self, server_id):
        from .models import Server
        Server.objects.filter(id=server_id).update(
            status=Server.Status.OFFLINE,
        )

    @database_sync_to_async
    def save_metrics(self, server_id, payload):
        from .models import Metric
        Metric.objects.create(
            server_id=server_id,
            cpu_percent=payload.get('cpu_percent', 0),
            memory_percent=payload.get('memory_percent', 0),
            memory_used_mb=payload.get('memory_used_mb', 0),
            memory_total_mb=payload.get('memory_total_mb', 0),
            disk_percent=payload.get('disk_percent', 0),
            disk_used_gb=payload.get('disk_used_gb', 0),
            disk_total_gb=payload.get('disk_total_gb', 0),
            load_1m=payload.get('load_1m', 0),
            load_5m=payload.get('load_5m', 0),
            load_15m=payload.get('load_15m', 0),
            uptime_seconds=payload.get('uptime_seconds', 0),
        )
