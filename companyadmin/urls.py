# companyadmin/urls.py - COMPLETE FILE

from django.urls import path
from . import views

app_name = 'companyadmin'

urlpatterns = [
    # =============================================================================
    # AUTHENTICATION
    # =============================================================================
    path('logout/', views.company_logout_view, name='logout'),
    
    # =============================================================================
    # DASHBOARD
    # =============================================================================
    path('dashboard/', views.dashboard_view, name='dashboard'),
    
    # =============================================================================
    # DEPARTMENT MANAGEMENT
    # =============================================================================
    path('departments/', views.departments_view, name='departments'),
    
    # =============================================================================
    # USER MANAGEMENT (Department Admins Only)
    # =============================================================================
    path('users/', views.users_view, name='users'),
    
    # =============================================================================
    # INFLUXDB CONFIGURATION
    # =============================================================================
    path('influx/config/', views.influx_config_view, name='influx_config'),
   
    
    # =============================================================================
    # DEVICE MANAGEMENT
    # =============================================================================
    path('devices/', views.device_list_view, name='device_list'),
    path('devices/edit/<int:device_id>/', views.device_edit_modal_view, name='device_edit_modal'),
    path('devices/sensors/<int:device_id>/', views.device_sensors_modal_view, name='device_sensors_modal'),
    path('devices/delete/<int:device_id>/', views.device_delete_view, name='device_delete'),
    
    # =============================================================================
    # DEVICE CONFIGURATION (Router + Type-Specific)
    # =============================================================================
    # 🆕 Router - Smart redirect based on device_type
    path('devices/<int:device_id>/configure/', 
         views.configure_device_router, 
         name='configure_device_router'),
    
    # Industrial Sensor Configuration
    path('devices/<int:device_id>/configure/sensors/', 
         views.configure_sensors_view, 
         name='configure_sensors'),
    
    # Asset Tracking Configuration
    path('devices/<int:device_id>/configure/asset-tracking/', 
         views.asset_tracking_config_view, 
         name='asset_tracking_config'),
    
    # Sensor Metadata Management (Industrial)
    path('sensors/<int:sensor_id>/metadata/', 
         views.add_edit_sensor_metadata_view, 
         name='add_edit_sensor_metadata'),
    path('sensors/<int:sensor_id>/metadata/reset/', 
         views.reset_sensor_metadata_view, 
         name='reset_sensor_metadata'),
         
    
    # =============================================================================
    # DEVICE SETUP WIZARD
    # =============================================================================
    path('influx/setup-wizard/', views.device_setup_wizard_view, name='device_setup_wizard'),

    path('profile/', views.profile_view, name='profile'),
    path('change-password/', views.change_password_view, name='change_password'),
]