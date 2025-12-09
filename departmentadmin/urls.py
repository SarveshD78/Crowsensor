from django.urls import path
from . import views

app_name = 'departmentadmin'

urlpatterns = [
    # Dashboard
    path('dashboard/', views.dashboard_view, name='dashboard'),
    
    # Devices List
    path('devices/', views.devices_view, name='devices'),
    
    # Device Sensors (Modal - JSON API)
    path('devices/sensors/<int:device_id>/', views.device_sensors_view, name='device_sensors'),
    
    # Device Graphs (2 URLs required)
    path('devices/<int:device_id>/graphs/', views.device_graphs_page_view, name='device_graphs_page'),  # HTML Page
    path('devices/graphs/<int:device_id>/', views.device_graphs_view, name='device_graphs'),             # JSON API
    
    # Users
    path('users/', views.users_view, name='users'),
    
    # Logout
    path('logout/', views.logout_view, name='logout'),
    # Alerts
    path('alerts/', views.alerts_view, name='alerts'),
    
    # Reports
    path('reports/', views.reports_view, name='reports'),
]