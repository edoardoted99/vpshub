from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('servers/add/', views.server_add, name='server_add'),
    path('servers/<int:pk>/', views.server_detail, name='server_detail'),
    path('servers/<int:pk>/edit/', views.server_edit, name='server_edit'),
    path('servers/<int:pk>/delete/', views.server_delete, name='server_delete'),
    path('servers/<int:pk>/terminal/', views.ssh_terminal, name='ssh_terminal'),
    path('servers/<int:pk>/ssh/', views.server_ssh_update, name='server_ssh_update'),
    # notes
    path('servers/<int:pk>/notes/add/', views.note_add, name='note_add'),
    path('notes/<int:pk>/delete/', views.note_delete, name='note_delete'),
    path('install/<str:token>', views.install_script, name='install_script'),
    # Agent HTTP API (fallback for networks that block WebSocket)
    path('api/agent/enroll/', views.api_agent_enroll, name='api_agent_enroll'),
    path('api/agent/metrics/', views.api_agent_metrics, name='api_agent_metrics'),
    # domains
    path('domains/add/', views.domain_add_global, name='domain_add_global'),
    path('servers/<int:server_pk>/domains/add/', views.domain_add, name='domain_add'),
    path('servers/<int:server_pk>/domains/recheck/', views.domains_recheck_all, name='domains_recheck_all'),
    path('domains/<int:pk>/delete/', views.domain_delete, name='domain_delete'),
    path('domains/<int:pk>/recheck/', views.domain_recheck, name='domain_recheck'),
    # htmx partials
    path('partials/server-list/', views.server_list_partial, name='server_list_partial'),
    path('partials/server/<int:pk>/metrics/', views.server_metrics_partial, name='server_metrics_partial'),
]
