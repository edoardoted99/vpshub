import json
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.db.models import Subquery, OuterRef
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import Server, Metric, Domain

AGENT_PY = (Path(__file__).resolve().parent.parent.parent / 'agent' / 'agent.py').read_text()


def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'home.html')


@login_required
def dashboard(request):
    latest_metric = Metric.objects.filter(
        server=OuterRef('pk')
    ).order_by('-timestamp')

    servers = Server.objects.annotate(
        latest_cpu=Subquery(latest_metric.values('cpu_percent')[:1]),
        latest_mem=Subquery(latest_metric.values('memory_percent')[:1]),
        latest_disk=Subquery(latest_metric.values('disk_percent')[:1]),
        latest_uptime=Subquery(latest_metric.values('uptime_seconds')[:1]),
    )

    online_count = servers.filter(status=Server.Status.ONLINE).count()
    offline_count = servers.filter(status=Server.Status.OFFLINE).count()
    pending_count = servers.filter(status=Server.Status.PENDING).count()
    context = {
        'servers': servers,
        'total_count': servers.count(),
        'online_count': online_count,
        'offline_count': offline_count,
        'pending_count': pending_count,
    }
    return render(request, 'servers/dashboard.html', context)


@login_required
def server_list_partial(request):
    """htmx partial: returns just the server rows for polling updates."""
    latest_metric = Metric.objects.filter(
        server=OuterRef('pk')
    ).order_by('-timestamp')

    servers = Server.objects.annotate(
        latest_cpu=Subquery(latest_metric.values('cpu_percent')[:1]),
        latest_mem=Subquery(latest_metric.values('memory_percent')[:1]),
        latest_disk=Subquery(latest_metric.values('disk_percent')[:1]),
        latest_uptime=Subquery(latest_metric.values('uptime_seconds')[:1]),
    )
    return render(request, 'servers/partials/server_list.html', {'servers': servers})


@login_required
def server_add(request):
    if request.method == 'POST':
        server = Server.objects.create(
            name=request.POST['name'],
            ip_address=request.POST.get('ip_address') or None,
            tags=request.POST.get('tags', ''),
            notes=request.POST.get('notes', ''),
        )
        if request.headers.get('HX-Request'):
            return render(request, 'servers/partials/enrollment_token.html', {'server': server})
        return redirect('dashboard')
    return render(request, 'servers/server_add.html')


@login_required
def server_detail(request, pk):
    server = get_object_or_404(Server, pk=pk)
    latest_metric = server.metrics.first()
    recent_metrics = server.metrics.all()[:60]
    domains = server.domains.all()
    context = {
        'server': server,
        'metric': latest_metric,
        'recent_metrics': recent_metrics,
        'domains': domains,
    }
    return render(request, 'servers/server_detail.html', context)


@login_required
def server_edit(request, pk):
    server = get_object_or_404(Server, pk=pk)
    if request.method == 'POST':
        server.name = request.POST.get('name', server.name)
        server.tags = request.POST.get('tags', server.tags)
        server.notes = request.POST.get('notes', server.notes)
        server.save()
        if request.headers.get('HX-Request'):
            return render(request, 'servers/partials/server_info.html', {'server': server})
        return redirect('server_detail', pk=pk)
    return render(request, 'servers/server_edit.html', {'server': server})


@login_required
def server_metrics_partial(request, pk):
    """htmx partial: returns updated metrics for a server."""
    server = get_object_or_404(Server, pk=pk)
    latest_metric = server.metrics.first()
    return render(request, 'servers/partials/server_metrics.html', {
        'server': server,
        'metric': latest_metric,
    })


@login_required
def server_delete(request, pk):
    server = get_object_or_404(Server, pk=pk)
    if request.method == 'POST':
        server.delete()
        if request.headers.get('HX-Request'):
            return HttpResponse(status=200, headers={'HX-Redirect': '/'})
        return redirect('dashboard')
    return render(request, 'servers/server_delete.html', {'server': server})


# --- Agent HTTP API (fallback for networks that block WebSocket) ---

@csrf_exempt
def api_agent_enroll(request):
    if request.method != 'POST':
        return JsonResponse({'type': 'error', 'message': 'POST required'}, status=405)
    data = json.loads(request.body)
    token = data.get('token', '')
    client_ip = (
        request.headers.get('X-Real-IP')
        or (request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or None)
        or request.META.get('REMOTE_ADDR')
    )
    try:
        server = Server.objects.get(enrollment_token=token)
    except Server.DoesNotExist:
        return JsonResponse({'type': 'error', 'message': 'Invalid enrollment token'}, status=401)
    server.status = Server.Status.ONLINE
    server.enrolled_at = timezone.now()
    server.last_seen = timezone.now()
    if client_ip:
        server.ip_address = client_ip
    server.save()
    if server.ip_address:
        Domain.objects.filter(
            resolved_ip=server.ip_address, server__isnull=True
        ).update(server=server, status=Domain.Status.MATCHED)
    return JsonResponse({'type': 'enrolled', 'server_id': server.id})


@csrf_exempt
def api_agent_metrics(request):
    if request.method != 'POST':
        return JsonResponse({'type': 'error', 'message': 'POST required'}, status=405)
    data = json.loads(request.body)
    token = data.get('token', '')
    payload = data.get('payload', {})
    try:
        server = Server.objects.get(enrollment_token=token)
    except Server.DoesNotExist:
        return JsonResponse({'type': 'error', 'message': 'Invalid token'}, status=401)
    server.last_seen = timezone.now()
    server.status = Server.Status.ONLINE
    server.save(update_fields=['last_seen', 'status'])
    Metric.objects.create(
        server=server,
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
    return JsonResponse({'type': 'ok'})


# --- Install script ---

def install_script(request, token):
    """Serve a bash install script with the agent embedded. No auth required."""
    from django.conf import settings as django_settings
    server = get_object_or_404(Server, enrollment_token=token)

    crown_url = django_settings.CROWN_URL
    if crown_url:
        # Derive URLs from configured CROWN_URL
        is_secure = crown_url.startswith('https')
        host = crown_url.split('://')[1].rstrip('/')
    else:
        # Fallback: derive from request
        is_secure = request.is_secure() or request.headers.get('X-Forwarded-Proto') == 'https'
        host = request.get_host()

    ws_scheme = 'wss' if is_secure else 'ws'
    http_scheme = 'https' if is_secure else 'http'
    ws_url = f"{ws_scheme}://{host}/ws/agent/"
    http_url = f"{http_scheme}://{host}/api/agent"

    script = f"""#!/bin/bash
set -e

INSTALL_DIR="/opt/servercrown-agent"
WS_URL="{ws_url}"
HTTP_URL="{http_url}"
TOKEN="{token}"

echo "[*] Installing ServerCrown Agent..."

# Install Python3 + pip
if command -v apt-get &>/dev/null; then
    apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-venv > /dev/null 2>&1
elif command -v dnf &>/dev/null; then
    dnf install -y -q python3 python3-pip > /dev/null 2>&1
elif command -v yum &>/dev/null; then
    yum install -y -q python3 python3-pip > /dev/null 2>&1
fi

# Create install dir
mkdir -p "$INSTALL_DIR"

# Create venv and install deps
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet psutil websockets

# Write agent script
cat > "$INSTALL_DIR/agent.py" << 'AGENT_SCRIPT'
{AGENT_PY}
AGENT_SCRIPT

# Create systemd service
cat > /etc/systemd/system/servercrown-agent.service << SVCEOF
[Unit]
Description=ServerCrown Agent
After=network.target

[Service]
Type=simple
Environment=CROWN_SERVER_URL=$WS_URL
# If WebSocket is blocked by your network, switch to HTTP mode:
# Environment=CROWN_SERVER_URL=$HTTP_URL
Environment=CROWN_TOKEN=$TOKEN
Environment=CROWN_INTERVAL=10
Environment=PYTHONUNBUFFERED=1
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable servercrown-agent
systemctl restart servercrown-agent

echo "[*] ServerCrown Agent installed and running!"
echo "[*] Check status: systemctl status servercrown-agent"
"""
    return HttpResponse(script, content_type='text/plain')


# --- Domains ---

@login_required
def domain_add_global(request):
    """Add a domain from anywhere — auto-resolve and match to server by IP."""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip().lower()
        if name:
            domain, created = Domain.objects.get_or_create(name=name)
            domain.resolve()
            if domain.server:
                return redirect('server_detail', pk=domain.server.pk)
    return redirect('dashboard')


@login_required
def domain_add(request, server_pk):
    """Add a domain from a server's detail page."""
    server = get_object_or_404(Server, pk=server_pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip().lower()
        if name:
            domain, created = Domain.objects.get_or_create(name=name)
            domain.resolve()
    domains = server.domains.all()
    all_domains_for_ip = Domain.objects.filter(resolved_ip=server.ip_address) if server.ip_address else Domain.objects.none()
    if request.headers.get('HX-Request'):
        return render(request, 'servers/partials/domain_list.html', {
            'server': server,
            'domains': domains,
            'matched_domains': all_domains_for_ip,
        })
    return redirect('server_detail', pk=server_pk)


@login_required
def domain_delete(request, pk):
    domain = get_object_or_404(Domain, pk=pk)
    server_pk = domain.server_id
    if request.method == 'POST':
        domain.delete()
    if request.headers.get('HX-Request'):
        if server_pk:
            server = get_object_or_404(Server, pk=server_pk)
            domains = server.domains.all()
            all_domains_for_ip = Domain.objects.filter(resolved_ip=server.ip_address) if server.ip_address else Domain.objects.none()
            return render(request, 'servers/partials/domain_list.html', {
                'server': server,
                'domains': domains,
                'matched_domains': all_domains_for_ip,
            })
        return HttpResponse('')
    return redirect('server_detail', pk=server_pk) if server_pk else redirect('dashboard')


@login_required
def domain_recheck(request, pk):
    """Re-resolve a single domain."""
    domain = get_object_or_404(Domain, pk=pk)
    domain.resolve()
    server_pk = domain.server_id
    if request.headers.get('HX-Request') and server_pk:
        server = get_object_or_404(Server, pk=server_pk)
        domains = server.domains.all()
        all_domains_for_ip = Domain.objects.filter(resolved_ip=server.ip_address) if server.ip_address else Domain.objects.none()
        return render(request, 'servers/partials/domain_list.html', {
            'server': server,
            'domains': domains,
            'matched_domains': all_domains_for_ip,
        })
    return redirect('server_detail', pk=server_pk) if server_pk else redirect('dashboard')


@login_required
def domains_recheck_all(request, server_pk):
    """Re-resolve all domains for a server."""
    server = get_object_or_404(Server, pk=server_pk)
    for domain in Domain.objects.filter(resolved_ip=server.ip_address):
        domain.resolve()
    domains = server.domains.all()
    all_domains_for_ip = Domain.objects.filter(resolved_ip=server.ip_address) if server.ip_address else Domain.objects.none()
    if request.headers.get('HX-Request'):
        return render(request, 'servers/partials/domain_list.html', {
            'server': server,
            'domains': domains,
            'matched_domains': all_domains_for_ip,
        })
    return redirect('server_detail', pk=server_pk)
