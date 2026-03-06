from django.contrib.auth.decorators import login_required
from django.db.models import Subquery, OuterRef
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.utils import timezone

from .models import Server, Metric, Domain


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


# --- Domains ---

@login_required
def domain_add(request, server_pk):
    """Add a domain and auto-resolve it."""
    server = get_object_or_404(Server, pk=server_pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip().lower()
        if name:
            domain, created = Domain.objects.get_or_create(name=name)
            domain.resolve()
            # If resolved IP doesn't match this server but user added it here,
            # still show it on this server's page (resolve sets server by IP match)
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
