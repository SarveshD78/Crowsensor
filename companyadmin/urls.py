# companyadmin/urls.py - VERIFIED URLS

from django.urls import path
from . import views

app_name = 'companyadmin'

urlpatterns = [
    # Authentication
    path('logout/', views.company_logout_view, name='logout'),
    
    # Dashboard
    path('dashboard/', views.dashboard_view, name='dashboard'),
    
    # Department Management
    path('departments/', views.departments_view, name='departments'),
    
    # User Management (Department Admins Only)
    path('users/', views.users_view, name='users'),
    path('influx/config/', views.influx_config_view, name='influx_config'),
    path('influx/fetch/', views.influx_fetch_measurements_view, name='influx_fetch'),
    # 🆕 NEW: Device Management
    path('devices/', views.device_list_view, name='device_list'),
    path('devices/edit/<int:device_id>/', views.device_edit_modal_view, name='device_edit_modal'),
    path('devices/sensors/<int:device_id>/', views.device_sensors_modal_view, name='device_sensors_modal'),
    path('devices/delete/<int:device_id>/', views.device_delete_view, name='device_delete'),
    # ✅ Sensor Metadata Configuration
# ✅ Sensor Metadata Configuration
path('devices/<int:device_id>/configure/', views.configure_sensors_view, name='configure_sensors'),
path('sensors/<int:sensor_id>/metadata/', views.add_edit_sensor_metadata_view, name='add_edit_sensor_metadata'),
path('sensors/<int:sensor_id>/metadata/reset/', views.reset_sensor_metadata_view, name='reset_sensor_metadata'),
    
    
    # Device Setup Wizard (placeholder for now)
    path('influx/setup-wizard/', views.device_setup_wizard_view, name='device_setup_wizard'),
    
]