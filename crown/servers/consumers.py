import asyncio
import json

import asyncssh
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone


class SSHConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer that proxies an SSH connection to a server."""

    async def connect(self):
        self.ssh_conn = None
        self.ssh_process = None

        # Check user is authenticated
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self.close()
            return

        self.server_id = self.scope['url_route']['kwargs']['server_id']
        server_data = await self.get_server_ssh_info(self.server_id)
        if not server_data:
            await self.accept()
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Server not found or SSH not configured',
            }))
            await self.close()
            return

        self.server_data = server_data
        await self.accept()

        # Start SSH connection in background
        asyncio.ensure_future(self.start_ssh())

    async def start_ssh(self):
        try:
            self.ssh_conn = await asyncssh.connect(
                self.server_data['host'],
                port=self.server_data['port'],
                username=self.server_data['user'],
                password=self.server_data['password'],
                known_hosts=None,
            )
            self.ssh_process = await self.ssh_conn.create_process(
                term_type='xterm-256color',
                term_size=(80, 24),
            )
            # Read SSH output and forward to WebSocket
            asyncio.ensure_future(self.read_ssh_output())
        except asyncssh.Error as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'SSH connection failed: {e}',
            }))
            await self.close()
        except OSError as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Connection failed: {e}',
            }))
            await self.close()

    async def read_ssh_output(self):
        try:
            while self.ssh_process and not self.ssh_process.stdout.at_eof():
                data = await self.ssh_process.stdout.read(4096)
                if data:
                    await self.send(text_data=json.dumps({
                        'type': 'output',
                        'data': data,
                    }))
        except (asyncssh.Error, ConnectionError):
            pass
        finally:
            await self.close()

    async def disconnect(self, close_code):
        if self.ssh_process:
            self.ssh_process.close()
        if self.ssh_conn:
            self.ssh_conn.close()

    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get('type')

        if msg_type == 'input' and self.ssh_process:
            self.ssh_process.stdin.write(data.get('data', ''))
        elif msg_type == 'resize' and self.ssh_process:
            cols = data.get('cols', 80)
            rows = data.get('rows', 24)
            self.ssh_process.change_terminal_size(cols, rows)

    @database_sync_to_async
    def get_server_ssh_info(self, server_id):
        from .models import Server
        try:
            server = Server.objects.get(pk=server_id)
            if not server.ssh_user or not server.ip_address:
                return None
            return {
                'host': server.ip_address,
                'port': server.ssh_port,
                'user': server.ssh_user,
                'password': server.ssh_password,
            }
        except Server.DoesNotExist:
            return None


class AgentConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for agent connections."""

    async def connect(self):
        self.server_id = None
        # Capture client IP from the connection
        self.client_ip = None
        headers = dict(self.scope.get('headers', []))
        # Check X-Real-IP / X-Forwarded-For (set by nginx)
        x_real_ip = headers.get(b'x-real-ip', b'').decode()
        x_forwarded = headers.get(b'x-forwarded-for', b'').decode()
        if x_real_ip:
            self.client_ip = x_real_ip
        elif x_forwarded:
            self.client_ip = x_forwarded.split(',')[0].strip()
        else:
            client = self.scope.get('client')
            if client:
                self.client_ip = client[0]
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
        server = await self.enroll_agent(token, self.client_ip)
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
    def enroll_agent(self, token, client_ip=None):
        from .models import Server, Domain
        try:
            server = Server.objects.get(enrollment_token=token)
            server.status = Server.Status.ONLINE
            server.enrolled_at = timezone.now()
            server.last_seen = timezone.now()
            if client_ip:
                server.ip_address = client_ip
            server.save()
            # Match unmatched domains to this server by IP
            if server.ip_address:
                Domain.objects.filter(
                    resolved_ip=server.ip_address, server__isnull=True
                ).update(server=server, status=Domain.Status.MATCHED)
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
