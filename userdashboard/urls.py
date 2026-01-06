# userdashboard/urls.py - USER DASHBOARD ROUTES

from django.urls import path
from . import views

app_name = 'userdashboard'

urlpatterns = [
    # Dashboard Home
    path('', views.user_home_view, name='user_home'),
    
    # Devices (assigned to user)
    path('devices/', views.user_devices_view, name='user_devices'),
    
    # Alerts (for assigned devices)
    path('alerts/', views.user_alerts_view, name='user_alerts'),
    
    # Reports (download only)
    path('reports/', views.user_reports_view, name='user_reports'),
    path('reports/<int:report_id>/download/', views.download_report_view, name='download_report'),
    
    # Device Visualization Router (detects device type)
    path(
        'devices/<int:device_id>/view/',
        views.user_device_visualization_view,
        name='user_device_visualization'
    ),
    
    # Industrial Sensor Graphs - Page (renders template)
    path(
        'devices/<int:device_id>/graphs/',
        views.user_device_graphs_page_view,
        name='user_device_graphs'
    ),
    
    # Industrial Sensor Graphs - Data API (returns JSON)
    path(
        'devices/<int:device_id>/graphs/data/',
        views.user_device_graphs_view,
        name='user_device_graphs_data'
    ),
    
    # Asset Tracking Map - Page (renders template)
    path(
        'devices/<int:device_id>/map/',
        views.user_device_asset_map_view,
        name='user_device_asset_map'
    ),
    
    # Asset Tracking Map - Data API (returns JSON)
    path(
        'devices/<int:device_id>/map/data/',
        views.user_device_asset_map_data_view,
        name='user_device_asset_map_data'
    ),
    
    # Authentication
    path('logout/', views.logout_view, name='logout'),
]