"""
companyadmin/views.py

Company Admin views for tenant management.
Handles dashboard, departments, users, InfluxDB config, devices, and sensors.
"""

import json
import logging
import random
import string
from datetime import timedelta

import requests
from requests.auth import HTTPBasicAuth

from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import require_company_admin
from accounts.models import User

from .device_func import (
    analyze_device_sensors_from_influx,
    analyze_measurement_columns,
    fetch_device_ids_from_measurement,
    fetch_measurements_from_influx,
    save_device_with_sensors,
)
from .forms import AssetConfigEditForm, AssetConfigForm, SensorMetadataForm
from .models import (
    AssetConfig,
    AssetTrackingConfig,
    Department,
    DepartmentMembership,
    Device,
    Sensor,
    SensorMetadata,
)

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_ajax(request):
    """Check if request is an AJAX request."""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


# =============================================================================
# AUTHENTICATION
# =============================================================================

@require_company_admin
def company_logout_view(request):
    """Logout company admin."""
    username = request.user.get_full_name_or_username()
    logout(request)
    messages.success(request, f'👋 Goodbye {username}! You have been logged out successfully.')
    return redirect('accounts:login')

# =============================================================================
# DASHBOARD
# =============================================================================

@require_company_admin
def dashboard_view(request):
    """
    Company Admin Dashboard.
    
    Shows:
    - User statistics (admins, read-only users)
    - Device and sensor counts
    - InfluxDB connection status for all configs
    - Recent activity feed
    """
    
    # ========== USER STATS ==========
    total_users = User.objects.filter(
        is_active=True
    ).exclude(role='company_admin').count()
    
    total_dept_admins = User.objects.filter(
        is_active=True,
        role='department_admin'
    ).count()
    
    total_read_only_users = User.objects.filter(
        is_active=True,
        role='user'
    ).count()
    
    total_departments = Department.objects.filter(is_active=True).count()
    
    # ========== DEVICE & SENSOR STATS ==========
    total_devices = Device.objects.count()
    total_sensors = Sensor.objects.filter(category='sensor').count()
    
    configured_sensors = SensorMetadata.objects.filter(
        display_name__isnull=False,
        unit__isnull=False
    ).exclude(display_name='').exclude(unit='').count()
    
    # ========== INFLUXDB CONFIGS WITH STATUS ==========
    influx_configs = []
    all_configs = AssetConfig.objects.filter(is_active=True).order_by('config_name')
    
    total_influx_online = 0
    total_influx_offline = 0
    
    for config in all_configs:
        status_info = _check_influx_connection(config)
        
        if status_info['status'] == 'online':
            total_influx_online += 1
        else:
            total_influx_offline += 1
        
        # Count devices and sensors for this config
        device_count = Device.objects.filter(asset_config=config).count()
        sensor_count = Sensor.objects.filter(
            device__asset_config=config,
            category='sensor'
        ).count()
        
        influx_configs.append({
            'config': config,
            'status': status_info['status'],
            'last_checked': status_info['last_checked'],
            'error_message': status_info['error_message'],
            'device_count': device_count,
            'sensor_count': sensor_count,
        })
    
    # ========== RECENT ACTIVITY ==========
    recent_activities = _get_recent_activities()
    
    # ========== CONTEXT ==========
    context = {
        'total_users': total_users,
        'total_dept_admins': total_dept_admins,
        'total_read_only_users': total_read_only_users,
        'total_departments': total_departments,
        'total_devices': total_devices,
        'total_sensors': total_sensors,
        'configured_sensors': configured_sensors,
        'influx_configs': influx_configs,
        'total_influx_configs': len(influx_configs),
        'total_influx_online': total_influx_online,
        'total_influx_offline': total_influx_offline,
        'has_influx_config': len(influx_configs) > 0,
        'recent_activities': recent_activities,
        'last_login': request.user.last_login,
        'page_title': 'Company Dashboard',
    }
    
    return render(request, 'companyadmin/dashboard.html', context)


def _check_influx_connection(config):
    """
    Test InfluxDB connection and update config status.
    
    Args:
        config: AssetConfig instance
        
    Returns:
        dict: Contains status, last_checked, error_message
    """
    status = 'offline'
    error_message = None
    last_checked = timezone.now()
    
    try:
        ping_url = f"{config.base_api}/ping"
        
        response = requests.get(
            ping_url,
            auth=HTTPBasicAuth(config.api_username, config.api_password),
            verify=False,
            timeout=5
        )
        
        if response.status_code == 204:
            status = 'online'
            if not config.is_connected:
                config.mark_connected()
        else:
            status = 'offline'
            error_message = f"HTTP {response.status_code}"
            
    except requests.exceptions.Timeout:
        status = 'offline'
        error_message = "Connection timeout"
        if config.is_connected:
            config.mark_disconnected("Connection timeout")
            
    except requests.exceptions.ConnectionError:
        status = 'offline'
        error_message = "Cannot connect to server"
        if config.is_connected:
            config.mark_disconnected("Connection refused")
            
    except Exception as e:
        status = 'offline'
        error_message = str(e)[:100]
        if config.is_connected:
            config.mark_disconnected(str(e))
    
    return {
        'status': status,
        'last_checked': last_checked,
        'error_message': error_message,
    }


def _get_recent_activities():
    """
    Get recent activity feed for dashboard.
    
    Returns:
        list: Activity items sorted by time (newest first)
    """
    recent_activities = []
    seven_days_ago = timezone.now() - timedelta(days=7)
    
    # Recent users
    recent_users = User.objects.filter(
        date_joined__gte=seven_days_ago
    ).exclude(role='company_admin').order_by('-date_joined')[:5]
    
    for user in recent_users:
        recent_activities.append({
            'type': 'user_added',
            'icon': 'fa-user-plus',
            'color': '#d4edda',
            'icon_color': '#155724',
            'title': 'New user added',
            'description': f'{user.username} ({user.get_role_display()}) created',
            'time': user.date_joined
        })
    
    # Recent devices
    recent_devices = Device.objects.filter(
        created_at__gte=seven_days_ago
    ).select_related('asset_config').order_by('-created_at')[:5]
    
    for device in recent_devices:
        sensor_count = device.sensors.count()
        recent_activities.append({
            'type': 'device_added',
            'icon': 'fa-microchip',
            'color': '#d1ecf1',
            'icon_color': '#0c5460',
            'title': 'Device configured',
            'description': f'{device.display_name} ({device.asset_config.config_name}) with {sensor_count} sensors',
            'time': device.created_at
        })
    
    # Recent departments
    recent_departments = Department.objects.filter(
        created_at__gte=seven_days_ago
    ).order_by('-created_at')[:5]
    
    for dept in recent_departments:
        recent_activities.append({
            'type': 'department_added',
            'icon': 'fa-building',
            'color': '#fff3cd',
            'icon_color': '#856404',
            'title': 'Workspace created',
            'description': f'New workspace "{dept.name}" added',
            'time': dept.created_at
        })
    
    # Recent metadata updates
    recent_metadata = SensorMetadata.objects.filter(
        updated_at__gte=seven_days_ago
    ).select_related(
        'sensor',
        'sensor__device',
        'sensor__device__asset_config'
    ).order_by('-updated_at')[:5]
    
    for metadata in recent_metadata:
        recent_activities.append({
            'type': 'metadata_updated',
            'icon': 'fa-sliders-h',
            'color': '#e7f3ff',
            'icon_color': '#004085',
            'title': 'Sensor metadata updated',
            'description': f'{metadata.display_name or metadata.sensor.field_name} on {metadata.sensor.device.display_name}',
            'time': metadata.updated_at
        })
    
    # Recent InfluxDB config changes
    recent_configs = AssetConfig.objects.filter(
        updated_at__gte=seven_days_ago
    ).order_by('-updated_at')[:3]
    
    for config in recent_configs:
        recent_activities.append({
            'type': 'config_updated',
            'icon': 'fa-database',
            'color': '#f8d7da',
            'icon_color': '#721c24',
            'title': 'InfluxDB config updated',
            'description': f'{config.config_name} configuration modified',
            'time': config.updated_at
        })
    
    # Sort by time and limit
    recent_activities.sort(key=lambda x: x['time'], reverse=True)
    return recent_activities[:10]

# =============================================================================
# DEPARTMENT MANAGEMENT
# =============================================================================

@require_company_admin
def departments_view(request):
    """
    Department CRUD - List, Add, Edit, Delete.
    
    Rules:
    - One Department can have many Department Admins
    - One Department can have many Users
    """
    
    # Get departments with user counts
    departments = Department.objects.filter(
        is_active=True
    ).annotate(
        admin_count=Count(
            'user_memberships',
            filter=Q(
                user_memberships__user__role='department_admin',
                user_memberships__user__is_active=True,
                user_memberships__is_active=True
            ),
            distinct=True
        ),
        total_users=Count(
            'user_memberships',
            filter=Q(
                user_memberships__user__is_active=True,
                user_memberships__is_active=True
            ) & ~Q(user_memberships__user__role='company_admin'),
            distinct=True
        )
    ).order_by('name')
    
    # Stats
    total_departments = departments.count()
    total_users = User.objects.filter(
        is_active=True
    ).exclude(role='company_admin').count()
    
    # Handle POST requests
    if request.method == 'POST':
        if 'add_department' in request.POST:
            return _handle_add_department(request)
        elif 'edit_department' in request.POST:
            return _handle_edit_department(request)
        elif 'delete_department' in request.POST:
            return _handle_delete_department(request)
    
    context = {
        'departments': departments,
        'total_departments': total_departments,
        'total_users': total_users,
        'page_title': 'Manage Departments',
    }
    
    return render(request, 'companyadmin/departments.html', context)


def _handle_add_department(request):
    """Handle add department POST request."""
    try:
        name = request.POST.get('name', '').strip()
        department_type = request.POST.get('department_type', '').strip()
        plant_location = request.POST.get('plant_location', '').strip()
        email = request.POST.get('email', '').strip()
        
        # Validation
        if not name or not department_type or not plant_location:
            messages.error(request, '⛔ Department name, type, and location are required.')
            return redirect('companyadmin:departments')
        
        # Check duplicate
        if Department.objects.filter(name__iexact=name, is_active=True).exists():
            messages.error(request, f'⛔ Department "{name}" already exists.')
            return redirect('companyadmin:departments')
        
        # Create
        Department.objects.create(
            name=name,
            department_type=department_type,
            plant_location=plant_location,
            email=email if email else None,
            is_active=True
        )
        
        messages.success(request, f'✅ Department "{name}" created successfully!')
        
    except Exception as e:
        logger.error(f"Error creating department: {e}")
        messages.error(request, f'⛔ Error creating department: {str(e)}')
    
    return redirect('companyadmin:departments')


def _handle_edit_department(request):
    """Handle edit department POST request."""
    try:
        dept_id = request.POST.get('department_id')
        name = request.POST.get('name', '').strip()
        department_type = request.POST.get('department_type', '').strip()
        plant_location = request.POST.get('plant_location', '').strip()
        email = request.POST.get('email', '').strip()
        
        # Validation
        if not name or not department_type or not plant_location:
            messages.error(request, '⛔ All required fields must be filled.')
            return redirect('companyadmin:departments')
        
        # Get department
        department = get_object_or_404(Department, id=dept_id, is_active=True)
        
        # Check duplicate (excluding current)
        if Department.objects.filter(
            name__iexact=name,
            is_active=True
        ).exclude(id=dept_id).exists():
            messages.error(request, f'⛔ Department "{name}" already exists.')
            return redirect('companyadmin:departments')
        
        # Update
        department.name = name
        department.department_type = department_type
        department.plant_location = plant_location
        department.email = email if email else None
        department.save()
        
        messages.success(request, f'✅ Department "{department.name}" updated successfully!')
        
    except Department.DoesNotExist:
        messages.error(request, '⛔ Department not found.')
    except Exception as e:
        logger.error(f"Error updating department: {e}")
        messages.error(request, f'⛔ Error updating department: {str(e)}')
    
    return redirect('companyadmin:departments')


def _handle_delete_department(request):
    """Handle delete department POST request."""
    try:
        dept_id = request.POST.get('department_id')
        department = get_object_or_404(Department, id=dept_id, is_active=True)
        
        # Check if has users
        user_count = department.user_memberships.filter(
            is_active=True,
            user__is_active=True
        ).exclude(user__role='company_admin').count()
        
        if user_count > 0:
            messages.warning(
                request,
                f'⛔ Cannot delete "{department.name}" - it has {user_count} assigned user(s). '
                f'Please unassign users first.'
            )
            return redirect('companyadmin:departments')
        
        dept_name = department.name
        department.deactivate()
        
        messages.success(request, f'✅ Department "{dept_name}" deleted successfully!')
        
    except Department.DoesNotExist:
        messages.error(request, '⛔ Department not found.')
    except Exception as e:
        logger.error(f"Error deleting department: {e}")
        messages.error(request, f'⛔ Error deleting department: {str(e)}')
    
    return redirect('companyadmin:departments')


# =============================================================================
# USER MANAGEMENT
# =============================================================================

@login_required
@require_company_admin
def users_view(request):
    """
    Manage department admin users with multi-department support.
    
    Features:
    - Create/edit/delete department admins
    - Assign multiple departments to each admin
    """
    
    logger.debug("Users view accessed")
    
    # Get all department admin users with their memberships
    users = User.objects.filter(
        is_active=True,
        role='department_admin'
    ).prefetch_related(
        Prefetch(
            'department_memberships',
            queryset=DepartmentMembership.objects.filter(
                is_active=True
            ).select_related('department').order_by('department__name')
        )
    ).order_by('-created_at')
    
    # Get all active departments
    departments = Department.objects.filter(is_active=True).order_by('name')
    
    # Stats
    total_dept_admins = users.count()
    total_departments = departments.count()
    
    # Handle POST requests
    if request.method == 'POST':
        if 'add_user' in request.POST:
            return _handle_add_user(request)
        elif 'edit_user' in request.POST:
            return _handle_edit_user(request)
        elif 'delete_user' in request.POST:
            return _handle_delete_user(request)
        elif 'assign_departments' in request.POST:
            return _handle_assign_departments(request)
    
    # Prepare user data for template
    users_data = _prepare_users_data(users)
    
    context = {
        'users': users_data,
        'departments': departments,
        'total_dept_admins': total_dept_admins,
        'total_departments': total_departments,
        'page_title': 'Manage Workspace Supervisors',
    }
    
    return render(request, 'companyadmin/users.html', context)


def _prepare_users_data(users):
    """
    Prepare user data for template with department information.
    
    Args:
        users: QuerySet of User objects
        
    Returns:
        list: User dictionaries with department data
    """
    users_data = []
    
    for user in users:
        memberships = user.department_memberships.filter(is_active=True)
        user_departments = [m.department for m in memberships]
        department_ids = [dept.id for dept in user_departments]
        department_names = [dept.name for dept in user_departments]
        
        users_data.append({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'phone': user.phone or '',
            'role': user.role,
            'role_display': user.get_role_display(),
            'created_at': user.created_at,
            'has_departments': len(user_departments) > 0,
            'department_count': len(user_departments),
            'departments': user_departments,
            'department_ids': department_ids,
            'department_ids_json': json.dumps(department_ids),
            'department_names': ', '.join(department_names) if department_names else 'No workspaces',
        })
    
    return users_data


def _handle_add_user(request):
    """Handle add user POST request."""
    try:
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        
        logger.debug(f"Adding user: {username}")
        
        # Validation
        if not username or not email or not first_name:
            messages.error(request, '⛔ Username, first name, and email are required.')
            return redirect('companyadmin:users')
        
        # Check duplicates
        if User.objects.filter(username__iexact=username).exists():
            messages.error(request, f'⛔ Username "{username}" already exists.')
            return redirect('companyadmin:users')
        
        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, f'⛔ Email "{email}" already exists.')
            return redirect('companyadmin:users')
        
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password='User@2025',
            first_name=first_name,
            last_name=last_name,
            role='department_admin',
            phone=phone,
            is_active=True
        )
        
        logger.info(f"User created: {user.username} (ID: {user.id})")
        
        messages.success(
            request,
            f'✅ Workspace Supervisor "{user.username}" created! '
            f'Default password: User@2025. '
            f'⚠️ Click "Assign" to assign workspaces now.'
        )
        
    except Exception as e:
        logger.error(f"Error creating user: {e}", exc_info=True)
        messages.error(request, f'⛔ Error: {str(e)}')
    
    return redirect('companyadmin:users')


def _handle_edit_user(request):
    """Handle edit user POST request."""
    try:
        user_id = request.POST.get('user_id')
        
        user = get_object_or_404(User, id=user_id, is_active=True, role='department_admin')
        
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        
        # Validation
        if not username or not email or not first_name:
            messages.error(request, '⛔ Username, first name, and email are required.')
            return redirect('companyadmin:users')
        
        # Check duplicates
        if User.objects.filter(username__iexact=username).exclude(id=user_id).exists():
            messages.error(request, f'⛔ Username "{username}" already exists.')
            return redirect('companyadmin:users')
        
        if User.objects.filter(email__iexact=email).exclude(id=user_id).exists():
            messages.error(request, f'⛔ Email "{email}" already exists.')
            return redirect('companyadmin:users')
        
        # Update
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        user.phone = phone
        user.save()
        
        logger.info(f"User updated: {user.username}")
        messages.success(request, f'✅ User "{user.username}" updated!')
        
    except Exception as e:
        logger.error(f"Error updating user: {e}", exc_info=True)
        messages.error(request, f'⛔ Error: {str(e)}')
    
    return redirect('companyadmin:users')


def _handle_delete_user(request):
    """Handle delete user POST request."""
    try:
        user_id = request.POST.get('user_id')
        user = get_object_or_404(User, id=user_id, is_active=True, role='department_admin')
        username = user.username
        
        # Soft delete
        user.is_active = False
        user.save()
        
        logger.info(f"User deleted: {username}")
        messages.success(request, f'✅ User "{username}" deleted!')
        
    except Exception as e:
        logger.error(f"Error deleting user: {e}", exc_info=True)
        messages.error(request, f'⛔ Error: {str(e)}')
    
    return redirect('companyadmin:users')


def _handle_assign_departments(request):
    """Handle assign departments POST request."""
    try:
        user_id = request.POST.get('user_id')
        department_ids = request.POST.getlist('department_ids[]')
        
        logger.debug(f"Assigning departments to user {user_id}: {department_ids}")
        
        user = get_object_or_404(User, id=user_id, is_active=True, role='department_admin')
        
        with transaction.atomic():
            # Deactivate all existing memberships
            DepartmentMembership.objects.filter(user=user).update(is_active=False)
            
            # Create/reactivate selected departments
            assigned_count = 0
            assigned_names = []
            
            for dept_id in department_ids:
                try:
                    dept_id_int = int(dept_id)
                    department = Department.objects.get(id=dept_id_int, is_active=True)
                    
                    membership, created = DepartmentMembership.objects.get_or_create(
                        user=user,
                        department=department,
                        defaults={'is_active': True}
                    )
                    
                    if not created:
                        membership.is_active = True
                        membership.save()
                    
                    assigned_count += 1
                    assigned_names.append(department.name)
                    
                except (ValueError, Department.DoesNotExist) as e:
                    logger.warning(f"Skipping invalid department ID {dept_id}: {e}")
                    continue
            
            logger.info(f"Assigned {assigned_count} departments to {user.username}")
            
            # Success message
            if assigned_count > 0:
                dept_list = ', '.join(assigned_names)
                messages.success(
                    request,
                    f'✅ "{user.username}" assigned to {assigned_count} workspace(s): {dept_list}'
                )
            else:
                messages.warning(
                    request,
                    f'⚠️ All workspaces cleared for "{user.username}". '
                    f'They cannot login without workspace assignment.'
                )
        
    except User.DoesNotExist:
        messages.error(request, '⛔ User not found.')
    except Exception as e:
        logger.error(f"Error assigning departments: {e}", exc_info=True)
        messages.error(request, f'⛔ Error: {str(e)}')
    
    return redirect('companyadmin:users')

# =============================================================================
# INFLUXDB CONFIGURATION
# =============================================================================

@require_company_admin
def influx_config_view(request):
    """
    Manage multiple InfluxDB configurations.
    
    Supports AJAX requests for create, edit, delete, and test operations.
    """
    
    logger.debug("InfluxDB config view accessed")
    
    # Get all active configs
    configs = AssetConfig.objects.filter(is_active=True).order_by('config_name')
    
    # Handle POST requests
    if request.method == 'POST':
        if 'create_config' in request.POST:
            return _handle_create_config(request)
        elif 'edit_config' in request.POST:
            return _handle_edit_config(request)
        elif 'delete_config' in request.POST:
            return _handle_delete_config(request)
        elif 'test_connection' in request.POST:
            return _handle_test_connection(request)
        elif 'test_live' in request.POST:
            return _handle_test_live(request)
    
    # Prepare config data
    configs_data = []
    for config in configs:
        device_count = Device.objects.filter(asset_config=config).count()
        sensor_count = Sensor.objects.filter(
            device__asset_config=config,
            category='sensor'
        ).count()
        
        configs_data.append({
            'config': config,
            'device_count': device_count,
            'sensor_count': sensor_count,
        })
    
    # Calculate stats
    total_configs = configs.count()
    connected_configs = configs.filter(is_connected=True).count()
    disconnected_configs = total_configs - connected_configs
    total_devices = Device.objects.filter(asset_config__in=configs).count()
    total_sensors = Sensor.objects.filter(
        device__asset_config__in=configs,
        category='sensor'
    ).count()
    
    context = {
        'configs_data': configs_data,
        'has_configs': total_configs > 0,
        'total_configs': total_configs,
        'connected_configs': connected_configs,
        'disconnected_configs': disconnected_configs,
        'total_devices': total_devices,
        'total_sensors': total_sensors,
        'page_title': 'InfluxDB Configurations',
    }
    
    return render(request, 'companyadmin/influx_config.html', context)


def _handle_create_config(request):
    """Handle create InfluxDB config POST request."""
    form = AssetConfigForm(request.POST)
    
    if form.is_valid():
        try:
            config = form.save()
            logger.info(f"InfluxDB config created: {config.config_name}")
            
            if is_ajax(request):
                return JsonResponse({
                    'success': True,
                    'message': f'Configuration "{config.config_name}" created successfully!',
                    'config_id': config.id
                })
            
            messages.success(request, f'✅ Configuration "{config.config_name}" created successfully!')
            
        except Exception as e:
            logger.error(f"Error creating config: {e}")
            
            if is_ajax(request):
                return JsonResponse({
                    'success': False,
                    'message': f'Error creating configuration: {str(e)}'
                })
            
            messages.error(request, f'⛔ Error creating configuration: {str(e)}')
    else:
        logger.debug(f"Form errors: {form.errors}")
        
        if is_ajax(request):
            errors = {field: error_list[0] for field, error_list in form.errors.items()}
            return JsonResponse({
                'success': False,
                'message': 'Please correct the errors below.',
                'errors': errors
            })
        
        messages.error(request, '⛔ Please correct the errors in the form.')
    
    return redirect('companyadmin:influx_config')


def _handle_edit_config(request):
    """Handle edit InfluxDB config POST request."""
    config_id = request.POST.get('config_id')
    config = get_object_or_404(AssetConfig, id=config_id)
    
    form = AssetConfigEditForm(request.POST, instance=config)
    
    if form.is_valid():
        try:
            updated_config = form.save()
            logger.info(f"InfluxDB config updated: {updated_config.config_name}")
            
            if is_ajax(request):
                return JsonResponse({
                    'success': True,
                    'message': f'Configuration "{updated_config.config_name}" updated successfully!',
                    'config_id': updated_config.id
                })
            
            messages.success(request, f'✅ Configuration "{updated_config.config_name}" updated successfully!')
            
        except Exception as e:
            logger.error(f"Error updating config: {e}")
            
            if is_ajax(request):
                return JsonResponse({
                    'success': False,
                    'message': f'Error updating configuration: {str(e)}'
                })
            
            messages.error(request, f'⛔ Error updating configuration: {str(e)}')
    else:
        if is_ajax(request):
            errors = {field: error_list[0] for field, error_list in form.errors.items()}
            return JsonResponse({
                'success': False,
                'message': 'Please correct the errors below.',
                'errors': errors
            })
        
        messages.error(request, '⛔ Please correct the errors in the form.')
    
    return redirect('companyadmin:influx_config')


def _handle_delete_config(request):
    """Handle delete InfluxDB config POST request."""
    config_id = request.POST.get('config_id')
    config = get_object_or_404(AssetConfig, id=config_id)
    
    # Check for associated devices
    device_count = Device.objects.filter(asset_config=config).count()
    
    if device_count > 0:
        logger.warning(f"Cannot delete config {config.config_name} - has {device_count} devices")
        
        if is_ajax(request):
            return JsonResponse({
                'success': False,
                'message': f'Cannot delete - has {device_count} associated devices. Please reassign or delete them first.',
                'device_count': device_count
            })
        
        messages.error(request, f'⛔ Cannot delete "{config.config_name}" - it has {device_count} associated devices.')
        return redirect('companyadmin:influx_config')
    
    try:
        config_name = config.config_name
        config.is_active = False
        config.save()
        
        logger.info(f"InfluxDB config deactivated: {config_name}")
        
        if is_ajax(request):
            return JsonResponse({
                'success': True,
                'message': f'Configuration "{config_name}" deleted successfully!'
            })
        
        messages.success(request, f'✅ Configuration "{config_name}" deleted successfully!')
        
    except Exception as e:
        logger.error(f"Error deleting config: {e}")
        
        if is_ajax(request):
            return JsonResponse({
                'success': False,
                'message': f'Error deleting configuration: {str(e)}'
            })
        
        messages.error(request, f'⛔ Error deleting configuration: {str(e)}')
    
    return redirect('companyadmin:influx_config')


def _handle_test_connection(request):
    """Handle test connection for existing config."""
    config_id = request.POST.get('config_id')
    config = get_object_or_404(AssetConfig, id=config_id)
    
    logger.debug(f"Testing connection for: {config.config_name}")
    
    try:
        url = f"{config.base_api}/ping"
        
        response = requests.get(
            url,
            auth=HTTPBasicAuth(config.api_username, config.api_password),
            verify=False,
            timeout=5
        )
        
        if response.status_code == 204:
            config.mark_connected()
            logger.info(f"Connection successful: {config.config_name}")
            
            if is_ajax(request):
                return JsonResponse({
                    'success': True,
                    'message': 'Connection successful! InfluxDB is reachable.',
                    'is_connected': True
                })
            
            messages.success(request, f'✅ "{config.config_name}" connection successful!')
        else:
            error_msg = f'HTTP {response.status_code}'
            config.mark_disconnected(error_msg)
            
            if is_ajax(request):
                return JsonResponse({
                    'success': False,
                    'message': f'Connection failed: {error_msg}',
                    'is_connected': False
                })
            
            messages.error(request, f'⛔ "{config.config_name}" connection failed: {error_msg}')
    
    except requests.exceptions.Timeout:
        error_msg = 'Connection timeout - server did not respond'
        config.mark_disconnected(error_msg)
        
        if is_ajax(request):
            return JsonResponse({
                'success': False,
                'message': error_msg,
                'is_connected': False
            })
        
        messages.error(request, f'⛔ "{config.config_name}" - {error_msg}')
    
    except requests.exceptions.ConnectionError:
        error_msg = 'Connection refused - cannot reach server'
        config.mark_disconnected(error_msg)
        
        if is_ajax(request):
            return JsonResponse({
                'success': False,
                'message': error_msg,
                'is_connected': False
            })
        
        messages.error(request, f'⛔ "{config.config_name}" - {error_msg}')
    
    except Exception as e:
        error_msg = f'Error: {str(e)}'
        config.mark_disconnected(error_msg)
        
        if is_ajax(request):
            return JsonResponse({
                'success': False,
                'message': error_msg,
                'is_connected': False
            })
        
        messages.error(request, f'⛔ "{config.config_name}" - {error_msg}')
    
    return redirect('companyadmin:influx_config')


def _handle_test_live(request):
    """Handle test connection without saving (live test)."""
    base_api = request.POST.get('base_api', '').strip()
    api_username = request.POST.get('api_username', '').strip()
    api_password = request.POST.get('api_password', '').strip()
    
    logger.debug(f"Testing live connection to: {base_api}")
    
    # Validate required fields
    if not base_api or not api_username or not api_password:
        return JsonResponse({
            'success': False,
            'message': 'Please fill in API Endpoint, Username, and Password.'
        })
    
    try:
        url = f"{base_api.rstrip('/')}/ping"
        
        response = requests.get(
            url,
            auth=HTTPBasicAuth(api_username, api_password),
            verify=False,
            timeout=5
        )
        
        if response.status_code == 204:
            return JsonResponse({
                'success': True,
                'message': 'Connection successful! Credentials are valid.'
            })
        elif response.status_code == 401:
            return JsonResponse({
                'success': False,
                'message': 'Authentication failed - invalid username or password.',
                'error_field': 'api_password'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': f'Unexpected response: HTTP {response.status_code}'
            })
    
    except requests.exceptions.Timeout:
        return JsonResponse({
            'success': False,
            'message': 'Connection timeout - server did not respond within 5 seconds.',
            'error_field': 'base_api'
        })
    
    except requests.exceptions.ConnectionError:
        return JsonResponse({
            'success': False,
            'message': 'Connection refused - cannot reach server. Check the URL.',
            'error_field': 'base_api'
        })
    
    except requests.exceptions.MissingSchema:
        return JsonResponse({
            'success': False,
            'message': 'Invalid URL - must start with http:// or https://',
            'error_field': 'base_api'
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        })


# =============================================================================
# DEVICE MANAGEMENT
# =============================================================================

@require_company_admin
def device_list_view(request):
    """
    Display all devices grouped by InfluxDB Config → Measurement.
    
    Structure: Config (collapsible) → Measurement → Devices (3 per row)
    """
    
    # Get all active InfluxDB configurations
    configs = AssetConfig.objects.filter(is_active=True).annotate(
        device_count=Count('devices', filter=Q(devices__is_active=True))
    ).order_by('config_name')
    
    # Build hierarchical structure
    config_data = []
    
    for config in configs:
        devices = Device.objects.filter(
            asset_config=config,
            is_active=True
        ).prefetch_related('departments', 'sensors').order_by('measurement_name', 'device_id')
        
        # Group devices by measurement
        measurements_dict = {}
        for device in devices:
            measurement_name = device.measurement_name
            if measurement_name not in measurements_dict:
                measurements_dict[measurement_name] = []
            
            # Add computed data
            device.sensor_breakdown = {
                'sensors': device.sensors.filter(category='sensor').count(),
                'slaves': device.sensors.filter(category='slave').count(),
                'info': device.sensors.filter(category='info').count(),
            }
            device.device_column = device.metadata.get('device_column', 'N/A')
            device.auto_discovered = device.metadata.get('auto_discovered', False)
            
            measurements_dict[measurement_name].append(device)
        
        # Convert to list
        measurements_list = [
            {
                'measurement_name': meas_name,
                'devices': meas_devices,
                'device_count': len(meas_devices)
            }
            for meas_name, meas_devices in measurements_dict.items()
        ]
        
        config_data.append({
            'config': config,
            'measurements': measurements_list,
            'total_measurements': len(measurements_list),
            'total_devices': devices.count()
        })
    
    # Calculate totals
    total_configs = configs.count()
    total_devices = Device.objects.filter(is_active=True).count()
    total_measurements = Device.objects.filter(
        is_active=True
    ).values('measurement_name').distinct().count()
    
    context = {
        'config_data': config_data,
        'total_configs': total_configs,
        'total_devices': total_devices,
        'total_measurements': total_measurements,
        'has_config': total_configs > 0,
        'page_title': 'Device Management',
    }
    
    return render(request, 'companyadmin/device_list.html', context)


@require_company_admin
def device_edit_modal_view(request, device_id):
    """Handle device edit via AJAX modal."""
    try:
        device = Device.objects.get(id=device_id)
        
        if request.method == 'POST':
            device.display_name = request.POST.get('display_name', device.display_name).strip()
            device.measurement_name = request.POST.get('measurement_name', device.measurement_name).strip()
            device.is_active = request.POST.get('is_active') == 'true'
            
            device_type = request.POST.get('device_type', '').strip()
            device.device_type = device_type if device_type else None
            
            department_ids = request.POST.getlist('departments[]')
            if department_ids:
                device.departments.set(Department.objects.filter(id__in=department_ids))
            else:
                device.departments.clear()
            
            device.save()
            
            logger.info(f"Device updated: {device.display_name}")
            
            return JsonResponse({
                'success': True,
                'message': f'✅ Device "{device.display_name}" updated successfully!'
            })
        
        else:
            departments = Department.objects.filter(is_active=True)
            
            return JsonResponse({
                'success': True,
                'device': {
                    'id': device.id,
                    'display_name': device.display_name,
                    'measurement_name': device.measurement_name,
                    'device_id': device.device_id,
                    'device_type': device.device_type or '',
                    'is_active': device.is_active,
                    'departments': list(device.departments.values_list('id', flat=True))
                },
                'all_departments': list(departments.values('id', 'name'))
            })
    
    except Device.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Device not found'}, status=404)
    except Exception as e:
        logger.error(f"Error in device edit: {e}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@require_company_admin
def device_sensors_modal_view(request, device_id):
    """Return all sensors for a device (modal display)."""
    try:
        device = Device.objects.get(id=device_id)
        sensors = device.sensors.all().order_by('category', 'field_name')
        
        sensor_list = []
        for sensor in sensors:
            sensor_list.append({
                'id': sensor.id,
                'field_name': sensor.field_name,
                'display_name': sensor.display_name,
                'field_type': sensor.field_type,
                'category': sensor.category,
                'unit': sensor.unit,
                'is_active': sensor.is_active,
                'sample_value': sensor.metadata.get('sample_value', 'N/A') if sensor.metadata else 'N/A'
            })
        
        sensor_breakdown = {
            'sensors': len([s for s in sensor_list if s['category'] == 'sensor']),
            'slaves': len([s for s in sensor_list if s['category'] == 'slave']),
            'info': len([s for s in sensor_list if s['category'] == 'info']),
        }
        
        return JsonResponse({
            'success': True,
            'device': {
                'display_name': device.display_name,
                'device_id': device.device_id,
                'measurement_name': device.measurement_name
            },
            'sensors': sensor_list,
            'sensor_breakdown': sensor_breakdown,
            'total_sensors': sensor_breakdown['sensors'],
            'total_fields': len(sensor_list)
        })
    
    except Device.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Device not found'}, status=404)
    except Exception as e:
        logger.error(f"Error fetching sensors: {e}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@require_company_admin
def device_delete_view(request, device_id):
    """Delete device and all associated sensors."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)
    
    try:
        device = Device.objects.get(id=device_id)
        device_name = device.display_name
        sensor_count = device.sensors.count()
        
        device.delete()
        
        logger.info(f"Device deleted: {device_name} with {sensor_count} sensors")
        
        return JsonResponse({
            'success': True,
            'message': f'🗑️ Device "{device_name}" and {sensor_count} sensor(s) deleted successfully!'
        })
    
    except Device.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Device not found'}, status=404)
    except Exception as e:
        logger.error(f"Error deleting device: {e}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
# =============================================================================
# DEVICE SETUP WIZARD
# =============================================================================

@require_company_admin
def device_setup_wizard_view(request):
    """
    Device Setup Wizard - Multi-InfluxDB Support.
    
    Steps:
    0. Select InfluxDB instance
    1. Select measurements
    2. Analyze columns
    3. Preview devices
    4. Save to database
    """
    
    # Initialize wizard session
    if 'wizard_data' not in request.session:
        request.session['wizard_data'] = {
            'step': 0,
            'selected_config_id': None,
            'measurements': [],
            'selected_measurements': [],
            'device_columns': {},
            'column_analysis': {},
            'preview_data': []
        }
    
    wizard_data = request.session['wizard_data']
    current_step = wizard_data.get('step', 0)
    
    # Handle reset
    if request.method == 'POST' and 'reset_wizard' in request.POST:
        del request.session['wizard_data']
        request.session.modified = True
        return redirect('companyadmin:device_setup_wizard')
    
    # Route to appropriate step handler
    if current_step == 0:
        return _wizard_step_0_select_config(request, wizard_data)
    
    # Get selected config for subsequent steps
    selected_config_id = wizard_data.get('selected_config_id')
    if not selected_config_id:
        wizard_data['step'] = 0
        request.session.modified = True
        return redirect('companyadmin:device_setup_wizard')
    
    try:
        config = AssetConfig.objects.get(id=selected_config_id, is_active=True)
    except AssetConfig.DoesNotExist:
        messages.error(request, '⛔ Selected InfluxDB configuration no longer exists')
        wizard_data['step'] = 0
        wizard_data['selected_config_id'] = None
        request.session.modified = True
        return redirect('companyadmin:device_setup_wizard')
    
    # Verify connection
    if not config.is_connected:
        messages.error(request, f'⛔ Lost connection to "{config.config_name}". Please reconfigure.')
        wizard_data['step'] = 0
        wizard_data['selected_config_id'] = None
        request.session.modified = True
        return redirect('companyadmin:device_setup_wizard')
    
    # Route to step handlers
    if current_step == 1:
        return _wizard_step_1_select_measurements(request, wizard_data, config)
    elif current_step == 2:
        return _wizard_step_2_analyze_columns(request, wizard_data, config)
    elif current_step == 3:
        return _wizard_step_3_preview(request, wizard_data, config)
    elif current_step == 4:
        return _wizard_step_4_save(request, wizard_data, config)
    
    # Fallback
    return redirect('companyadmin:device_setup_wizard')


def _wizard_step_0_select_config(request, wizard_data):
    """Wizard Step 0: Select InfluxDB instance."""
    configs = AssetConfig.objects.filter(is_active=True).order_by('config_name')
    
    if not configs.exists():
        messages.error(
            request,
            '⛔ No InfluxDB configurations found. Please configure at least one InfluxDB instance first.'
        )
        return redirect('companyadmin:influx_config')
    
    if request.method == 'POST' and 'select_config' in request.POST:
        selected_config_id = request.POST.get('config_id')
        
        if not selected_config_id:
            messages.error(request, '⛔ Please select an InfluxDB instance')
        else:
            try:
                config = AssetConfig.objects.get(id=selected_config_id, is_active=True)
                
                if not config.is_connected:
                    messages.error(request, f'⛔ Cannot connect to "{config.config_name}". Please check configuration.')
                else:
                    wizard_data['selected_config_id'] = int(selected_config_id)
                    wizard_data['step'] = 1
                    request.session.modified = True
                    messages.success(request, f'✅ Selected InfluxDB: {config.config_name}')
                    return redirect('companyadmin:device_setup_wizard')
            
            except AssetConfig.DoesNotExist:
                messages.error(request, '⛔ Selected configuration not found')
    
    context = {
        'configs': configs,
        'wizard_data': wizard_data,
        'current_step': 0,
        'page_title': 'Device Setup Wizard - Select InfluxDB',
    }
    return render(request, 'companyadmin/device_setup_wizard.html', context)


def _wizard_step_1_select_measurements(request, wizard_data, config):
    """Wizard Step 1: Select measurements."""
    if request.method == 'POST':
        if 'fetch_measurements' in request.POST:
            try:
                measurements = fetch_measurements_from_influx(config)
                
                if measurements:
                    wizard_data['measurements'] = measurements
                    request.session.modified = True
                    messages.success(request, f'✅ Found {len(measurements)} measurements in "{config.config_name}"')
                else:
                    messages.info(request, f'ℹ️ No measurements found in "{config.config_name}"')
            
            except Exception as e:
                logger.error(f"Error fetching measurements: {e}")
                messages.error(request, f'⛔ Error: {str(e)}')
        
        elif 'select_measurements' in request.POST:
            selected = request.POST.getlist('selected_measurements')
            if selected:
                wizard_data['selected_measurements'] = selected
                wizard_data['step'] = 2
                request.session.modified = True
                return redirect('companyadmin:device_setup_wizard')
            else:
                messages.error(request, '⛔ Please select at least one measurement')
        
        elif 'back_to_config' in request.POST:
            wizard_data['step'] = 0
            wizard_data['selected_config_id'] = None
            wizard_data['measurements'] = []
            request.session.modified = True
            return redirect('companyadmin:device_setup_wizard')
    
    context = {
        'config': config,
        'wizard_data': wizard_data,
        'current_step': 1,
        'page_title': 'Device Setup Wizard - Select Measurements',
    }
    return render(request, 'companyadmin/device_setup_wizard.html', context)


def _wizard_step_2_analyze_columns(request, wizard_data, config):
    """Wizard Step 2: Analyze and select device columns."""
    if request.method == 'POST':
        if 'select_device_columns' in request.POST:
            device_columns = {}
            for measurement in wizard_data['selected_measurements']:
                column = request.POST.get(f'device_column_{measurement}')
                if column:
                    device_columns[measurement] = column
            
            if len(device_columns) == len(wizard_data['selected_measurements']):
                wizard_data['device_columns'] = device_columns
                wizard_data['step'] = 3
                request.session.modified = True
                return redirect('companyadmin:device_setup_wizard')
            else:
                messages.error(request, '⛔ Please select device column for all measurements')
        
        elif 'back_to_step1' in request.POST:
            wizard_data['step'] = 1
            request.session.modified = True
            return redirect('companyadmin:device_setup_wizard')
    
    # Analyze columns if not already done
    if not wizard_data.get('column_analysis'):
        column_analysis = {}
        for measurement in wizard_data['selected_measurements']:
            column_info = analyze_measurement_columns(config, measurement)
            column_analysis[measurement] = column_info
        
        wizard_data['column_analysis'] = column_analysis
        request.session.modified = True
    
    context = {
        'config': config,
        'wizard_data': wizard_data,
        'current_step': 2,
        'page_title': 'Device Setup Wizard - Analyze Columns',
    }
    return render(request, 'companyadmin/device_setup_wizard.html', context)


def _wizard_step_3_preview(request, wizard_data, config):
    """Wizard Step 3: Preview devices and sensors."""
    base_url = f"{config.base_api}/query"
    auth = HTTPBasicAuth(config.api_username, config.api_password)
    
    if request.method == 'POST':
        if 'confirm_save' in request.POST:
            wizard_data['step'] = 4
            request.session.modified = True
            return redirect('companyadmin:device_setup_wizard')
        
        elif 'back_to_step2' in request.POST:
            wizard_data['step'] = 2
            request.session.modified = True
            return redirect('companyadmin:device_setup_wizard')
    
    # Generate preview data if not already done
    if not wizard_data.get('preview_data'):
        preview_data = []
        total_devices = 0
        total_sensors = 0
        
        for measurement in wizard_data['selected_measurements']:
            device_column = wizard_data['device_columns'][measurement]
            device_ids = fetch_device_ids_from_measurement(config, measurement, device_column)
            
            devices_with_sensors = []
            for device_id in device_ids[:10]:  # Limit preview to 10 devices
                sensors = analyze_device_sensors_from_influx(
                    measurement, device_column, device_id,
                    base_url, config.db_name, auth
                )
                
                devices_with_sensors.append({
                    'device_id': device_id,
                    'sensors': sensors,
                    'sensor_count': len([s for s in sensors if s['category'] == 'sensor']),
                    'slave_count': len([s for s in sensors if s['category'] == 'slave']),
                    'info_count': len([s for s in sensors if s['category'] == 'info'])
                })
                
                total_sensors += len(sensors)
            
            total_devices += len(device_ids)
            
            preview_data.append({
                'measurement': measurement,
                'device_column': device_column,
                'device_count': len(device_ids),
                'all_device_ids': device_ids,
                'devices_with_sensors': devices_with_sensors
            })
        
        wizard_data['preview_data'] = preview_data
        wizard_data['total_devices'] = total_devices
        wizard_data['total_sensors'] = total_sensors
        request.session.modified = True
    
    context = {
        'config': config,
        'wizard_data': wizard_data,
        'current_step': 3,
        'page_title': 'Device Setup Wizard - Preview',
    }
    return render(request, 'companyadmin/device_setup_wizard.html', context)


def _wizard_step_4_save(request, wizard_data, config):
    """Wizard Step 4: Save devices and sensors to database."""
    base_url = f"{config.base_api}/query"
    auth = HTTPBasicAuth(config.api_username, config.api_password)
    
    try:
        devices_created = 0
        devices_updated = 0
        sensors_created = 0
        
        for item in wizard_data['preview_data']:
            measurement = item['measurement']
            device_column = item['device_column']
            all_device_ids = item.get('all_device_ids', [])
            
            for device_id in all_device_ids:
                sensors = analyze_device_sensors_from_influx(
                    measurement, device_column, device_id,
                    base_url, config.db_name, auth
                )
                
                device, created, sensor_count = save_device_with_sensors(
                    measurement, device_column, device_id, sensors, config
                )
                
                if created:
                    devices_created += 1
                else:
                    devices_updated += 1
                
                sensors_created += sensor_count
        
        # Clear wizard session
        del request.session['wizard_data']
        request.session.modified = True
        
        logger.info(
            f"Wizard complete: {devices_created} created, {devices_updated} updated, "
            f"{sensors_created} sensors from {config.config_name}"
        )
        
        messages.success(
            request,
            f'🎉 Success! Created {devices_created} devices, updated {devices_updated} devices, '
            f'and created {sensors_created} sensors from "{config.config_name}"!'
        )
        return redirect('companyadmin:device_list')
    
    except Exception as e:
        logger.error(f"Wizard save error: {e}", exc_info=True)
        messages.error(request, f'⛔ Error: {str(e)}')
        wizard_data['step'] = 0
        wizard_data['selected_config_id'] = None
        request.session.modified = True
        return redirect('companyadmin:device_setup_wizard')


# =============================================================================
# DEVICE CONFIGURATION ROUTER
# =============================================================================

@require_company_admin
def configure_device_router(request, device_id):
    """Smart router - redirects to correct config page based on device_type."""
    device = get_object_or_404(Device, id=device_id)
    
    if device.device_type == 'asset_tracking':
        return redirect('companyadmin:asset_tracking_config', device_id=device.id)
    else:
        return redirect('companyadmin:configure_sensors', device_id=device.id)


# =============================================================================
# SENSOR CONFIGURATION
# =============================================================================

@require_company_admin
def configure_sensors_view(request, device_id):
    """
    Configure metadata for sensor-category fields only.
    
    Shows ONLY sensors with category='sensor' (not 'info' or 'slave').
    """
    device = get_object_or_404(Device, id=device_id)
    
    # Only get sensors with category='sensor'
    sensors = Sensor.objects.filter(
        device=device,
        is_active=True,
        category='sensor'
    ).select_related('metadata_config').order_by('field_name')
    
    if request.method == 'POST':
        sensor_id = request.POST.get('sensor_id')
        
        if not sensor_id:
            messages.error(request, "No sensor selected")
            return redirect('companyadmin:configure_sensors', device_id=device.id)
        
        try:
            sensor = get_object_or_404(Sensor, id=sensor_id, device=device, category='sensor')
            
            # Get or create metadata config
            metadata_config, created = SensorMetadata.objects.get_or_create(sensor=sensor)
            
            # Convert checkbox fields to data_types list
            data_types = []
            if request.POST.get('show_time_series'):
                data_types.append('trend')
            if request.POST.get('show_latest_value'):
                data_types.append('latest_value')
            if request.POST.get('show_digital'):
                data_types.append('digital')
            
            if not data_types:
                data_types = ['trend']
            
            # Update metadata fields
            metadata_config.display_name = request.POST.get('display_name', sensor.field_name)
            metadata_config.unit = request.POST.get('unit', '') or None
            metadata_config.data_types = data_types
            
            # Handle numeric fields
            lower_limit = request.POST.get('lower_limit', '').strip()
            center_line = request.POST.get('center_line', '').strip()
            upper_limit = request.POST.get('upper_limit', '').strip()
            
            metadata_config.lower_limit = float(lower_limit) if lower_limit else None
            metadata_config.center_line = float(center_line) if center_line else None
            metadata_config.upper_limit = float(upper_limit) if upper_limit else None
            
            # Validate limits
            if (metadata_config.lower_limit is not None and
                metadata_config.upper_limit is not None and
                metadata_config.lower_limit >= metadata_config.upper_limit):
                messages.error(request, "Lower limit must be less than upper limit")
                return redirect('companyadmin:configure_sensors', device_id=device.id)
            
            metadata_config.save()
            
            action = "created" if created else "updated"
            logger.info(f"Sensor metadata {action}: {sensor.field_name}")
            messages.success(request, f"✅ Sensor metadata {action}: {sensor.field_name}")
            
        except ValueError as e:
            messages.error(request, f"Invalid number format: {str(e)}")
        except Exception as e:
            logger.error(f"Error saving metadata: {e}")
            messages.error(request, f"Error saving metadata: {str(e)}")
        
        return redirect('companyadmin:configure_sensors', device_id=device.id)
    
    # GET request - prepare sensor list with metadata
    sensors_with_metadata = []
    configured_count = 0
    
    for sensor in sensors:
        try:
            metadata = sensor.metadata_config
            has_metadata = True
            configured_count += 1
            
            # Convert data_types list to individual flags for template
            metadata.show_time_series = 'trend' in (metadata.data_types or [])
            metadata.show_latest_value = 'latest_value' in (metadata.data_types or [])
            metadata.show_digital = 'digital' in (metadata.data_types or [])
            
        except SensorMetadata.DoesNotExist:
            metadata = None
            has_metadata = False
        
        sensors_with_metadata.append({
            'sensor': sensor,
            'has_metadata': has_metadata,
            'metadata': metadata,
        })
    
    # Calculate stats
    total_sensors = sensors.count()
    unconfigured_count = total_sensors - configured_count
    progress_percentage = round((configured_count / total_sensors * 100), 1) if total_sensors > 0 else 0
    
    context = {
        'device': device,
        'sensors_with_metadata': sensors_with_metadata,
        'total_sensors': total_sensors,
        'configured_count': configured_count,
        'unconfigured_count': unconfigured_count,
        'progress_percentage': progress_percentage,
        'page_title': f'Configure Sensors - {device.display_name}',
    }
    
    return render(request, 'companyadmin/configure_sensors.html', context)


# =============================================================================
# ASSET TRACKING CONFIGURATION
# =============================================================================

@require_company_admin
def asset_tracking_config_view(request, device_id):
    """
    Asset Tracking Configuration - Location sensors and display groups.
    """
    device = get_object_or_404(
        Device.objects.prefetch_related('sensors'),
        id=device_id,
        device_type='asset_tracking'
    )
    
    asset_config, created = AssetTrackingConfig.objects.get_or_create(device=device)
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Location sensors
                lat_id = request.POST.get('latitude_sensor_id')
                lng_id = request.POST.get('longitude_sensor_id')
                
                asset_config.latitude_sensor = device.sensors.get(id=lat_id) if lat_id else None
                asset_config.longitude_sensor = device.sensors.get(id=lng_id) if lng_id else None
                asset_config.save()
                
                # Map popup sensors
                map_popup_ids = request.POST.getlist('map_popup_sensor_ids')
                if map_popup_ids:
                    asset_config.map_popup_sensors.set(device.sensors.filter(id__in=map_popup_ids))
                else:
                    asset_config.map_popup_sensors.clear()
                
                # Info card sensors
                info_card_ids = request.POST.getlist('info_card_sensor_ids')
                if info_card_ids:
                    asset_config.info_card_sensors.set(device.sensors.filter(id__in=info_card_ids))
                else:
                    asset_config.info_card_sensors.clear()
                
                # Time series sensors
                time_series_ids = request.POST.getlist('time_series_sensor_ids')
                if time_series_ids:
                    asset_config.time_series_sensors.set(device.sensors.filter(id__in=time_series_ids))
                else:
                    asset_config.time_series_sensors.clear()
            
            logger.info(f"Asset tracking config saved: {device.display_name}")
            messages.success(request, f'✅ Configuration saved for {device.display_name}')
            return redirect('companyadmin:device_list')
            
        except Exception as e:
            logger.error(f"Error saving asset tracking config: {e}", exc_info=True)
            messages.error(request, f'❌ Error: {str(e)}')
    
    # GET - prepare context
    all_sensors = device.sensors.filter(is_active=True).order_by('field_name')
    
    # Get selected sensor IDs
    selected_lat_lng_ids = []
    if asset_config.latitude_sensor:
        selected_lat_lng_ids.append(asset_config.latitude_sensor.id)
    if asset_config.longitude_sensor:
        selected_lat_lng_ids.append(asset_config.longitude_sensor.id)
    
    selected_map_popup_ids = list(asset_config.map_popup_sensors.values_list('id', flat=True))
    selected_info_card_ids = list(asset_config.info_card_sensors.values_list('id', flat=True))
    selected_time_series_ids = list(asset_config.time_series_sensors.values_list('id', flat=True))
    
    # Smart cascading filters
    available_for_location = all_sensors
    available_for_map_popup = all_sensors.exclude(id__in=selected_lat_lng_ids)
    available_for_info_card = all_sensors.exclude(id__in=selected_lat_lng_ids + selected_map_popup_ids)
    available_for_time_series = all_sensors.exclude(
        id__in=selected_lat_lng_ids + selected_map_popup_ids + selected_info_card_ids
    )
    
    context = {
        'device': device,
        'asset_config': asset_config,
        'all_sensors': all_sensors,
        'available_for_location': available_for_location,
        'available_for_map_popup': available_for_map_popup,
        'available_for_info_card': available_for_info_card,
        'available_for_time_series': available_for_time_series,
        'selected_latitude_id': asset_config.latitude_sensor.id if asset_config.latitude_sensor else None,
        'selected_longitude_id': asset_config.longitude_sensor.id if asset_config.longitude_sensor else None,
        'selected_map_popup_ids': selected_map_popup_ids,
        'selected_info_card_ids': selected_info_card_ids,
        'selected_time_series_ids': selected_time_series_ids,
        'has_location_config': asset_config.has_location_config,
        'page_title': f'Asset Tracking Config - {device.display_name}',
    }
    
    return render(request, 'companyadmin/asset_tracking_config.html', context)


# =============================================================================
# SENSOR METADATA AJAX ENDPOINTS
# =============================================================================

@require_company_admin
def add_edit_sensor_metadata_view(request, sensor_id):
    """AJAX: Edit sensor metadata via modal."""
    sensor = get_object_or_404(Sensor, id=sensor_id)
    
    if request.method == 'POST':
        try:
            metadata = sensor.metadata_config if hasattr(sensor, 'metadata_config') else SensorMetadata(sensor=sensor)
            form = SensorMetadataForm(request.POST, instance=metadata)
            
            if form.is_valid():
                form.save()
                logger.info(f"Sensor metadata saved: {sensor.field_name}")
                return JsonResponse({'success': True, 'message': f'✅ Saved: {sensor.field_name}'})
            else:
                return JsonResponse({'success': False, 'errors': form.errors}, status=400)
        except Exception as e:
            logger.error(f"Error saving sensor metadata: {e}")
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    # GET: Return sensor data
    has_metadata = hasattr(sensor, 'metadata_config')
    
    if has_metadata:
        metadata = sensor.metadata_config
        data = {
            'id': sensor.id,
            'field_name': sensor.field_name,
            'field_type': sensor.field_type,
            'display_name': metadata.display_name,
            'unit': metadata.unit,
            'data_types': metadata.data_types,
            'data_nature': metadata.data_nature,
            'lower_limit': metadata.lower_limit,
            'upper_limit': metadata.upper_limit,
            'center_line': metadata.center_line,
            'description': metadata.description,
            'notes': metadata.notes,
        }
    else:
        data = {
            'id': sensor.id,
            'field_name': sensor.field_name,
            'field_type': sensor.field_type,
            'display_name': sensor.field_name,
            'unit': '',
            'data_types': [],
            'data_nature': 'spot',
            'lower_limit': None,
            'upper_limit': None,
            'center_line': None,
            'description': '',
            'notes': '',
        }
    
    return JsonResponse({'success': True, 'sensor': data, 'has_metadata': has_metadata})


@require_company_admin
def reset_sensor_metadata_view(request, sensor_id):
    """AJAX: Reset sensor metadata."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=400)
    
    try:
        sensor = get_object_or_404(Sensor, id=sensor_id)
        
        if hasattr(sensor, 'metadata_config'):
            sensor.metadata_config.delete()
            logger.info(f"Sensor metadata reset: {sensor.field_name}")
            return JsonResponse({'success': True, 'message': f'✅ Reset: {sensor.field_name}'})
        else:
            return JsonResponse({'success': False, 'message': 'No metadata to reset'})
    except Exception as e:
        logger.error(f"Error resetting metadata: {e}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


# =============================================================================
# PROFILE MANAGEMENT
# =============================================================================

@login_required
@require_company_admin
def profile_view(request):
    """Display and edit Company Admin profile."""
    user = request.user
    
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        
        # Validate email
        if not email:
            messages.error(request, '❌ Email is required.')
            return redirect('companyadmin:profile')
        
        # Check if email is already taken
        if User.objects.filter(email=email).exclude(id=user.id).exists():
            messages.error(request, '❌ This email is already in use by another account.')
            return redirect('companyadmin:profile')
        
        # Update user
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        
        if hasattr(user, 'phone'):
            user.phone = phone
        
        user.save()
        
        logger.info(f"Profile updated: {user.username}")
        messages.success(request, '✅ Profile updated successfully!')
        return redirect('companyadmin:profile')
    
    context = {
        'user': user,
        'page_title': 'My Profile',
    }
    
    return render(request, 'companyadmin/profile.html', context)


@login_required
@require_company_admin
def change_password_view(request):
    """Change password for Company Admin."""
    user = request.user
    
    if request.method == 'POST':
        current_password = request.POST.get('current_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        # Validate current password
        if not user.check_password(current_password):
            messages.error(request, '❌ Current password is incorrect.')
            return redirect('companyadmin:change_password')
        
        # Validate new password
        if not new_password:
            messages.error(request, '❌ New password is required.')
            return redirect('companyadmin:change_password')
        
        if len(new_password) < 8:
            messages.error(request, '❌ Password must be at least 8 characters long.')
            return redirect('companyadmin:change_password')
        
        if new_password != confirm_password:
            messages.error(request, '❌ New passwords do not match.')
            return redirect('companyadmin:change_password')
        
        if current_password == new_password:
            messages.error(request, '❌ New password must be different from current password.')
            return redirect('companyadmin:change_password')
        
        # Update password
        user.set_password(new_password)
        user.save()
        
        # Keep user logged in
        update_session_auth_hash(request, user)
        
        logger.info(f"Password changed: {user.username}")
        messages.success(request, '✅ Password changed successfully!')
        return redirect('companyadmin:profile')
    
    context = {
        'page_title': 'Change Password',
    }
    
    return render(request, 'companyadmin/change_password.html', context)