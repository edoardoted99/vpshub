#!/usr/bin/env python3
"""ServerCrown Agent - collects system metrics and sends them to the server."""

import asyncio
import json
import os
import platform
import signal
import sys
import time
import urllib.request
import urllib.error

import psutil
import websockets


def collect_metrics():
    """Collect system metrics using psutil."""
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    load_1, load_5, load_15 = os.getloadavg()
    uptime = int(time.time() - psutil.boot_time())

    return {
        'cpu_percent': cpu,
        'memory_percent': mem.percent,
        'memory_used_mb': round(mem.used / 1024 / 1024, 1),
        'memory_total_mb': round(mem.total / 1024 / 1024, 1),
        'disk_percent': disk.percent,
        'disk_used_gb': round(disk.used / 1024 / 1024 / 1024, 2),
        'disk_total_gb': round(disk.total / 1024 / 1024 / 1024, 2),
        'load_1m': round(load_1, 2),
        'load_5m': round(load_5, 2),
        'load_15m': round(load_15, 2),
        'uptime_seconds': uptime,
    }


def get_os_info():
    """Return a string describing the OS."""
    return f"{platform.system()} {platform.release()} ({platform.machine()})"


async def run_agent(server_url, token, interval=10):
    """Main agent loop via WebSocket: connect, enroll, send metrics."""
    while True:
        try:
            print(f"[agent] Connecting to {server_url} ...", flush=True)
            async with websockets.connect(server_url) as ws:
                await ws.send(json.dumps({'type': 'enroll', 'token': token}))
                response = json.loads(await ws.recv())
                if response.get('type') == 'error':
                    print(f"[agent] Enrollment failed: {response.get('message')}", flush=True)
                    sys.exit(1)
                server_id = response.get('server_id')
                print(f"[agent] Enrolled as server #{server_id}", flush=True)
                while True:
                    metrics = collect_metrics()
                    await ws.send(json.dumps({'type': 'metrics', 'payload': metrics}))
                    print(f"[agent] Sent metrics: CPU {metrics['cpu_percent']}% | "
                          f"RAM {metrics['memory_percent']}% | "
                          f"Disk {metrics['disk_percent']}%", flush=True)
                    await asyncio.sleep(interval)
        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            print(f"[agent] Connection lost: {e}. Reconnecting in 5s...", flush=True)
            await asyncio.sleep(5)


_ssl_ctx = None

def _get_ssl_ctx():
    global _ssl_ctx
    if _ssl_ctx is None:
        import ssl
        if os.environ.get('CROWN_SSL_VERIFY', '1') == '0':
            _ssl_ctx = ssl.create_default_context()
            _ssl_ctx.check_hostname = False
            _ssl_ctx.verify_mode = ssl.CERT_NONE
        else:
            _ssl_ctx = ssl.create_default_context()
    return _ssl_ctx

def _post_json(url, data):
    """POST JSON data and return parsed response."""
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=30, context=_get_ssl_ctx()) as resp:
        return json.loads(resp.read())


def run_agent_http(server_url, token, interval=10):
    """HTTP polling mode for networks that block WebSocket."""
    base = server_url.rstrip('/')
    enroll_url = f"{base}/enroll/"
    metrics_url = f"{base}/metrics/"

    print(f"[agent] Enrolling via HTTP at {enroll_url} ...", flush=True)
    response = _post_json(enroll_url, {'token': token})
    if response.get('type') == 'error':
        print(f"[agent] Enrollment failed: {response.get('message')}", flush=True)
        sys.exit(1)

    server_id = response.get('server_id')
    print(f"[agent] Enrolled as server #{server_id} (HTTP mode)", flush=True)

    while True:
        try:
            metrics = collect_metrics()
            _post_json(metrics_url, {'token': token, 'payload': metrics})
            print(f"[agent] Sent metrics: CPU {metrics['cpu_percent']}% | "
                  f"RAM {metrics['memory_percent']}% | "
                  f"Disk {metrics['disk_percent']}%", flush=True)
        except (urllib.error.URLError, OSError) as e:
            print(f"[agent] HTTP error: {e}. Retrying in 5s...", flush=True)
            time.sleep(5)
            continue
        time.sleep(interval)


def main():
    server_url = os.environ.get('CROWN_SERVER_URL')
    token = os.environ.get('CROWN_TOKEN')
    interval = int(os.environ.get('CROWN_INTERVAL', '10'))

    if not server_url or not token:
        print("Usage: Set environment variables CROWN_SERVER_URL and CROWN_TOKEN")
        print("  CROWN_SERVER_URL  WebSocket or HTTP URL")
        print("    WebSocket: wss://yourserver/ws/agent/")
        print("    HTTP:      https://yourserver/api/agent")
        print("  CROWN_TOKEN       Enrollment token from the dashboard")
        print("  CROWN_INTERVAL    Metrics interval in seconds (default: 10)")
        sys.exit(1)

    # Auto-detect mode from URL scheme
    if server_url.startswith(('http://', 'https://')):
        run_agent_http(server_url, token, interval)
    else:
        loop = asyncio.new_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, loop.stop)
            except NotImplementedError:
                pass
        try:
            loop.run_until_complete(run_agent(server_url, token, interval))
        finally:
            loop.close()


if __name__ == '__main__':
    main()
