from django.urls import path
from . import views

app_name = 'systemadmin'

urlpatterns = [
    # Home - MUST BE FIRST to catch root path
    path('', views.home, name='home'),
    
    # System Admin Authentication
    path('system/login/', views.system_login_view, name='system_login'),
    path('system/logout/', views.system_logout_view, name='system_logout'),
    
    # System Admin Dashboard
    path('system/dashboard/', views.system_dashboard_view, name='system_dashboard'),
    
    # Tenant Management
    path('system/tenant/create/', views.tenant_create_view, name='tenant_create'),
    path('system/tenant/<int:tenant_id>/detail/', views.tenant_detail_view, name='tenant_detail'),
    path('system/tenant/<int:tenant_id>/edit/', views.tenant_edit_view, name='tenant_edit'),
    path('system/tenant/<int:tenant_id>/toggle/', views.tenant_toggle_status, name='tenant_toggle_status'),
    path('tenant/<int:tenant_id>/delete/', views.tenant_delete_view, name='tenant_delete'),
]