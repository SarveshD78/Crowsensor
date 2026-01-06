# departmentadmin/urls.py

from django.urls import path
from . import views

app_name = 'departmentadmin'

urlpatterns = [
    
    
    # Dashboard & Auth
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('logout/', views.logout_view, name='logout'),
    
    # Users
    path('users/', views.users_view, name='users'),
    
    # Devices
    path('devices/', views.devices_view, name='devices'),
    path('devices/<int:device_id>/sensors/', views.device_sensors_view, name='device_sensors'),
    
    # ✨ NEW: Smart Visualization Router (ONE URL for both types)
    path('devices/<int:device_id>/visualization/', views.device_visualization_view, name='device_visualization'),
    path('devices/<int:device_id>/assign/', views.assign_device_view, name='assign_device'),

    
    # Device Graphs (Industrial - Existing URLs, keep them)
    path('devices/<int:device_id>/graphs/', views.device_graphs_page_view, name='device_graphs_page'),
    path('devices/graphs/<int:device_id>/', views.device_graphs_view, name='device_graphs'),
    
    # ✨ NEW: Asset Map View (called by visualization router)
    path('devices/<int:device_id>/asset-map/', views.device_asset_map_view, name='device_asset_map'),
       path('devices/<int:device_id>/asset-map-data/', views.device_asset_map_data_view, name='device_asset_map_data'), 
    
    # Alerts & Reports
    path('alerts/', views.alerts_view, name='alerts'),
    path('reports/', views.reports_view, name='reports'),

    path('switch-department/', views.switch_department, name='switch_department'),
]