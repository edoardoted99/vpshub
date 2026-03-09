#!/usr/bin/env bash
set -e

INSTALL_DIR="$HOME/.local/servercrown-agent"
TOKEN="51b5b458994a548561c62bb5dc3687d8e303ed295c01d0a7cdd8773e4736f8f8"

echo "[*] Installing ServerCrown Agent..."
echo "[*] Install dir: $INSTALL_DIR"

mkdir -p "$INSTALL_DIR"

python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet psutil websockets

cat > "$INSTALL_DIR/agent.py" <<'AGENT_SCRIPT'
#!/usr/bin/env python3
import asyncio, json, os, platform, signal, sys, time
import urllib.request, urllib.error
import psutil
try:
    import websockets
except ImportError:
    websockets = None

def collect_metrics():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    load_1, load_5, load_15 = os.getloadavg()
    uptime = int(time.time() - psutil.boot_time())
    return {
        'cpu_percent': cpu, 'memory_percent': mem.percent,
        'memory_used_mb': round(mem.used/1024/1024,1), 'memory_total_mb': round(mem.total/1024/1024,1),
        'disk_percent': disk.percent,
        'disk_used_gb': round(disk.used/1024/1024/1024,2), 'disk_total_gb': round(disk.total/1024/1024/1024,2),
        'load_1m': round(load_1,2), 'load_5m': round(load_5,2), 'load_15m': round(load_15,2),
        'uptime_seconds': uptime,
    }

def _post_json(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

def run_agent_http(server_url, token, interval=10):
    base = server_url.rstrip('/')
    enroll_url = f"{base}/enroll/"
    metrics_url = f"{base}/metrics/"
    print(f"[agent] Enrolling via HTTP at {enroll_url} ...", flush=True)
    response = _post_json(enroll_url, {'token': token})
    if response.get('type') == 'error':
        print(f"[agent] Enrollment failed: {response.get('message')}", flush=True)
        sys.exit(1)
    print(f"[agent] Enrolled as server #{response.get('server_id')} (HTTP mode)", flush=True)
    while True:
        try:
            metrics = collect_metrics()
            _post_json(metrics_url, {'token': token, 'payload': metrics})
            print(f"[agent] Sent: CPU {metrics['cpu_percent']}% | RAM {metrics['memory_percent']}% | Disk {metrics['disk_percent']}%", flush=True)
        except (urllib.error.URLError, OSError) as e:
            print(f"[agent] HTTP error: {e}. Retrying in 5s...", flush=True)
            time.sleep(5)
            continue
        time.sleep(interval)

async def run_agent_ws(server_url, token, interval=10):
    while True:
        try:
            print(f"[agent] Connecting to {server_url} ...", flush=True)
            async with websockets.connect(server_url) as ws:
                await ws.send(json.dumps({'type':'enroll','token':token}))
                response = json.loads(await ws.recv())
                if response.get('type') == 'error':
                    print(f"[agent] Enrollment failed: {response.get('message')}", flush=True)
                    sys.exit(1)
                print(f"[agent] Enrolled as server #{response.get('server_id')}", flush=True)
                while True:
                    metrics = collect_metrics()
                    await ws.send(json.dumps({'type':'metrics','payload':metrics}))
                    print(f"[agent] Sent: CPU {metrics['cpu_percent']}% | RAM {metrics['memory_percent']}% | Disk {metrics['disk_percent']}%", flush=True)
                    await asyncio.sleep(interval)
        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            print(f"[agent] Connection lost: {e}. Reconnecting in 5s...", flush=True)
            await asyncio.sleep(5)

def main():
    server_url = os.environ.get('CROWN_SERVER_URL')
    token = os.environ.get('CROWN_TOKEN')
    interval = int(os.environ.get('CROWN_INTERVAL', '10'))
    if not server_url or not token:
        print("Set CROWN_SERVER_URL and CROWN_TOKEN"); sys.exit(1)
    if server_url.startswith(('http://','https://')):
        run_agent_http(server_url, token, interval)
    else:
        loop = asyncio.new_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try: loop.add_signal_handler(sig, loop.stop)
            except NotImplementedError: pass
        try: loop.run_until_complete(run_agent_ws(server_url, token, interval))
        finally: loop.close()

if __name__ == '__main__':
    main()
AGENT_SCRIPT

cat > "$INSTALL_DIR/run.sh" <<RUNEOF
#!/usr/bin/env bash
set -euo pipefail
export CROWN_SERVER_URL="https://servercrown.org/api/agent"
export CROWN_TOKEN="$TOKEN"
export CROWN_INTERVAL="10"
exec "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/agent.py"
RUNEOF

chmod +x "$INSTALL_DIR/run.sh"

echo "[*] Installed."
echo "[*] Starting agent..."
exec "$INSTALL_DIR/run.sh"
