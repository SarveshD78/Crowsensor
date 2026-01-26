"""
departmentadmin/views.py

Department Admin views for workspace management.
Handles dashboard, users, devices, graphs, asset maps, alerts, and reports.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import require_department_admin
from accounts.models import User
from companyadmin.models import (
    AssetConfig,
    AssetTrackingConfig,
    Department,
    DepartmentMembership,
    Device,
    Sensor,
)

from .asset_map_func import fetch_asset_tracking_data_from_influx
from .graph_func import fetch_sensor_data_from_influx, INTERVAL_LOOKUP
from .models import DeviceUserAssignment, DailyDeviceReport, SensorAlert
from .reports_func import generate_custom_device_report, generate_device_daily_report
from .utils import get_current_department, get_department_or_redirect

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_ajax(request):
    """Check if request is an AJAX request."""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


# =============================================================================
# DEPARTMENT SWITCHER
# =============================================================================

@require_department_admin
def switch_department(request):
    """
    Handle department switching across all views.
    
    Stores selection in session for persistent department context.
    """
    if request.method == 'POST':
        department_id = request.POST.get('department_id')
        
        if not department_id:
            messages.error(request, '⛔ Invalid department selection.')
            return redirect(request.META.get('HTTP_REFERER', 'departmentadmin:dashboard'))
        
        try:
            # Verify user has access to this department
            membership = DepartmentMembership.objects.get(
                user=request.user,
                department_id=department_id,
                is_active=True,
                department__is_active=True
            )
            
            # Store in session
            request.session['selected_department_id'] = int(department_id)
            request.session['selected_department_name'] = membership.department.name
            
            logger.info(
                f"Department switched - User: {request.user.email}, "
                f"To: {membership.department.name} (ID: {membership.department.id})"
            )
            
            messages.success(request, f'✅ Switched to {membership.department.name}')
            
        except DepartmentMembership.DoesNotExist:
            messages.error(request, '⛔ You do not have access to this department.')
        
        return redirect(request.META.get('HTTP_REFERER', 'departmentadmin:dashboard'))
    
    return redirect('departmentadmin:dashboard')


# =============================================================================
# AUTHENTICATION
# =============================================================================

@require_department_admin
def logout_view(request):
    """Logout department admin."""
    username = request.user.get_full_name_or_username()
    logout(request)
    messages.success(request, f'👋 Goodbye {username}! You have been logged out successfully.')
    return redirect('accounts:login')


# =============================================================================
# DASHBOARD
# =============================================================================

@require_department_admin
def dashboard_view(request):
    """
    Department Admin Dashboard.
    
    Shows only departments assigned to this user with relevant statistics.
    """
    # Get department context
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('accounts:login')
    
    # Get user's assigned departments for stats
    user_departments = DepartmentMembership.objects.filter(
        user=request.user,
        is_active=True
    ).select_related('department').filter(
        department__is_active=True
    )
    
    # Get department IDs
    dept_ids = [m.department.id for m in user_departments]
    
    # Stats for assigned departments only
    total_departments = user_departments.count()
    
    # Count only 'user' role
    total_users = User.objects.filter(
        department_memberships__department_id__in=dept_ids,
        department_memberships__is_active=True,
        is_active=True,
        role='user'
    ).distinct().count()
    
    context = {
        # Department switcher
        'department': department,
        'all_departments': all_departments,
        'show_department_switcher': show_department_switcher,
        
        # Page-specific data
        'user_departments': user_departments,
        'total_departments': total_departments,
        'total_users': total_users,
        'user_role': request.user.get_role_display(),
        'page_title': 'Department Admin Dashboard',
    }
    
    return render(request, 'departmentadmin/dashboard.html', context)

# =============================================================================
# USER MANAGEMENT
# =============================================================================

@require_department_admin
def users_view(request):
    """
    Department Admin User Management.
    
    Can create users with 'user' role (read-only).
    Users are assigned to the CURRENTLY SELECTED department only.
    """
    # Get department context
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('departmentadmin:dashboard')
    
    # Get users for CURRENT department only
    all_users = User.objects.filter(
        is_active=True,
        role='user',
        department_memberships__department=department,
        department_memberships__is_active=True
    ).prefetch_related(
        'department_memberships__department'
    ).distinct().order_by('-created_at')
    
    total_users = all_users.count()
    
    # Handle POST requests
    if request.method == 'POST':
        if 'add_user' in request.POST:
            return _handle_add_user(request, department)
        elif 'edit_user' in request.POST:
            return _handle_edit_user(request, department)
        elif 'delete_user' in request.POST:
            return _handle_delete_user(request, department)
    
    # Prepare user data for template
    users_data = _prepare_users_data(all_users, request.user)
    
    context = {
        # Department switcher
        'department': department,
        'all_departments': all_departments,
        'show_department_switcher': show_department_switcher,
        
        # Page-specific data
        'users': users_data,
        'total_users': total_users,
        'page_title': 'Manage Users',
        'user_role': request.user.get_role_display(),
    }
    
    return render(request, 'departmentadmin/users.html', context)


def _handle_add_user(request, department):
    """Handle add user POST request."""
    try:
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        
        # Validation
        if not username or not email or not first_name:
            messages.error(request, '⛔ Username, first name, and email are required.')
            return redirect('departmentadmin:users')
        
        # Check duplicates
        if User.objects.filter(username__iexact=username).exists():
            messages.error(request, f'⛔ Username "{username}" already exists.')
            return redirect('departmentadmin:users')
        
        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, f'⛔ Email "{email}" already exists.')
            return redirect('departmentadmin:users')
        
        # Create user and assign to current department
        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password='User@2025',
                first_name=first_name,
                last_name=last_name,
                role='user',
                phone=phone,
                is_active=True
            )
            
            DepartmentMembership.objects.create(
                user=user,
                department=department,
                is_active=True
            )
        
        logger.info(f"User created: {user.username} in department {department.name}")
        
        messages.success(
            request,
            f'✅ User "{user.username}" created and assigned to "{department.name}"! '
            f'Default password: User@2025'
        )
        
    except Exception as e:
        logger.error(f"Error creating user: {e}", exc_info=True)
        messages.error(request, f'⛔ Error creating user: {str(e)}')
    
    return redirect('departmentadmin:users')


def _handle_edit_user(request, department):
    """Handle edit user POST request."""
    try:
        user_id = request.POST.get('user_id')
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        
        # Validation
        if not username or not email or not first_name:
            messages.error(request, '⛔ Username, first name, and email are required.')
            return redirect('departmentadmin:users')
        
        # Get user from current department only
        user = get_object_or_404(
            User,
            id=user_id,
            is_active=True,
            role='user',
            department_memberships__department=department,
            department_memberships__is_active=True
        )
        
        # Check duplicates (excluding current user)
        if User.objects.filter(username__iexact=username).exclude(id=user_id).exists():
            messages.error(request, f'⛔ Username "{username}" already exists.')
            return redirect('departmentadmin:users')
        
        if User.objects.filter(email__iexact=email).exclude(id=user_id).exists():
            messages.error(request, f'⛔ Email "{email}" already exists.')
            return redirect('departmentadmin:users')
        
        # Update
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        user.phone = phone
        user.save()
        
        logger.info(f"User updated: {user.username}")
        messages.success(request, f'✅ User "{user.username}" updated successfully!')
        
    except User.DoesNotExist:
        messages.error(request, '⛔ User not found in this department.')
    except Exception as e:
        logger.error(f"Error updating user: {e}", exc_info=True)
        messages.error(request, f'⛔ Error updating user: {str(e)}')
    
    return redirect('departmentadmin:users')


def _handle_delete_user(request, department):
    """Handle delete user POST request (remove from current department)."""
    try:
        user_id = request.POST.get('user_id')
        
        # Verify user belongs to current department
        user = get_object_or_404(
            User,
            id=user_id,
            is_active=True,
            role='user',
            department_memberships__department=department,
            department_memberships__is_active=True
        )
        
        username = user.username
        
        # Remove from current department only
        membership = DepartmentMembership.objects.filter(
            user=user,
            department=department,
            is_active=True
        ).first()
        
        if membership:
            membership.is_active = False
            membership.save()
            
            # Check if user has any other active memberships
            other_active = DepartmentMembership.objects.filter(
                user=user,
                is_active=True
            ).exists()
            
            # If no other departments, deactivate the user entirely
            if not other_active:
                user.is_active = False
                user.save()
                logger.info(f"User deactivated: {username}")
                messages.success(
                    request,
                    f'✅ User "{username}" removed from "{department.name}" and deactivated.'
                )
            else:
                logger.info(f"User removed from department: {username} from {department.name}")
                messages.success(request, f'✅ User "{username}" removed from "{department.name}".')
        else:
            messages.error(request, '⛔ User membership not found.')
        
    except User.DoesNotExist:
        messages.error(request, '⛔ User not found in this department.')
    except Exception as e:
        logger.error(f"Error removing user: {e}", exc_info=True)
        messages.error(request, f'⛔ Error removing user: {str(e)}')
    
    return redirect('departmentadmin:users')


def _prepare_users_data(users, admin_user):
    """
    Prepare user data for template with department information.
    
    Args:
        users: QuerySet of User objects
        admin_user: Current admin user (for filtering visible departments)
        
    Returns:
        list: User dictionaries with department data
    """
    # Get all department IDs this admin manages
    admin_dept_ids = DepartmentMembership.objects.filter(
        user=admin_user,
        is_active=True,
        department__is_active=True
    ).values_list('department_id', flat=True)
    
    users_data = []
    
    for user in users:
        # Get user's departments (only ones this admin can see)
        user_depts = user.department_memberships.filter(
            is_active=True,
            department_id__in=admin_dept_ids
        ).select_related('department')
        
        users_data.append({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'phone': user.phone,
            'role': user.role,
            'role_display': user.get_role_display(),
            'created_at': user.created_at,
            'department_count': user_depts.count(),
            'departments': [m.department for m in user_depts],
            'department_names': ', '.join([m.department.name for m in user_depts]),
            'is_multi_dept': user_depts.count() > 1,
        })
    
    return users_data

# =============================================================================
# DEVICE MANAGEMENT
# =============================================================================

@require_department_admin
def devices_view(request):
    """
    View all devices assigned to user's department.
    
    Includes user assignment functionality and device statistics.
    """
    # Get department context
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('departmentadmin:dashboard')
    
    # Get ALL devices assigned to this department
    devices = Device.objects.filter(
        departments=department
    ).prefetch_related(
        'sensors',
        'departments',
        'user_assignments'
    ).order_by('measurement_name', 'device_id')
    
    # Get asset config
    config = AssetConfig.get_default_config()
    
    # Get users in this department (for assignment modal)
    department_users = User.objects.filter(
        is_active=True,
        role='user',
        department_memberships__department=department,
        department_memberships__is_active=True
    ).distinct().order_by('first_name', 'last_name')
    
    # Add computed data to each device
    devices_list = _prepare_devices_data(devices, department)
    
    context = {
        # Department switcher
        'department': department,
        'all_departments': all_departments,
        'show_department_switcher': show_department_switcher,
        
        # Page-specific data
        'devices': devices_list,
        'total_devices': devices.count(),
        'active_devices': devices.filter(is_active=True).count(),
        'inactive_devices': devices.filter(is_active=False).count(),
        'has_config': config is not None,
        'config': config,
        'page_title': 'My Devices',
        
        # Users for assignment
        'department_users': department_users,
        'total_users': department_users.count(),
    }
    
    return render(request, 'departmentadmin/devices.html', context)


def _prepare_devices_data(devices, department):
    """
    Prepare device data with computed fields and assignment info.
    
    Args:
        devices: QuerySet of Device objects
        department: Current department
        
    Returns:
        list: Device objects with computed attributes
    """
    devices_list = []
    
    for device in devices:
        # Sensor breakdown
        device.total_sensors_only = device.sensors.filter(category='sensor').count()
        device.sensor_breakdown = {
            'sensors': device.sensors.filter(category='sensor').count(),
            'slaves': device.sensors.filter(category='slave').count(),
            'info': device.sensors.filter(category='info').count(),
        }
        device.device_column = device.metadata.get('device_column', 'N/A')
        device.auto_discovered = device.metadata.get('auto_discovered', False)
        
        # Assignment data
        active_assignments = device.user_assignments.filter(
            department=department,
            is_active=True
        ).select_related('user')
        
        device.assigned_users = [a.user for a in active_assignments]
        device.assigned_users_count = active_assignments.count()
        device.assigned_user_ids = [a.user.id for a in active_assignments]
        
        devices_list.append(device)
    
    return devices_list


# =============================================================================
# DEVICE ASSIGNMENT
# =============================================================================

@require_department_admin
def assign_device_view(request, device_id):
    """
    Handle device-to-user assignment.
    
    GET: Return current assignments (JSON)
    POST: Assign/unassign users to device
    """
    # Get department
    department, _, _ = get_current_department(request)
    
    if not department:
        if is_ajax(request):
            return JsonResponse({'success': False, 'message': 'Department not found'}, status=404)
        messages.error(request, '⛔ Department not found.')
        return redirect('departmentadmin:devices')
    
    # Get device - must be in this department
    device = Device.objects.filter(
        id=device_id,
        departments=department
    ).first()
    
    if not device:
        if is_ajax(request):
            return JsonResponse({'success': False, 'message': 'Device not found'}, status=404)
        messages.error(request, '⛔ Device not found.')
        return redirect('departmentadmin:devices')
    
    if request.method == 'GET':
        return _get_device_assignments(device, department)
    
    if request.method == 'POST':
        return _update_device_assignments(request, device, department)
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)


def _get_device_assignments(device, department):
    """
    Get current device assignments as JSON.
    
    Args:
        device: Device instance
        department: Department instance
        
    Returns:
        JsonResponse: Assignment data
    """
    # Get current assignments
    assignments = DeviceUserAssignment.objects.filter(
        device=device,
        department=department,
        is_active=True
    ).select_related('user', 'assigned_by')
    
    # Get all users in department
    all_users = User.objects.filter(
        is_active=True,
        role='user',
        department_memberships__department=department,
        department_memberships__is_active=True
    ).distinct().order_by('first_name', 'last_name')
    
    assigned_user_ids = [a.user.id for a in assignments]
    
    users_data = []
    for user in all_users:
        users_data.append({
            'id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'full_name': user.get_full_name() or user.username,
            'email': user.email,
            'is_assigned': user.id in assigned_user_ids,
        })
    
    return JsonResponse({
        'success': True,
        'device': {
            'id': device.id,
            'display_name': device.display_name,
            'device_id': device.device_id,
        },
        'users': users_data,
        'total_users': len(users_data),
        'assigned_count': len(assigned_user_ids),
    })


def _update_device_assignments(request, device, department):
    """
    Update device-to-user assignments.
    
    Args:
        request: HTTP request
        device: Device instance
        department: Department instance
        
    Returns:
        JsonResponse or redirect
    """
    try:
        # Get selected user IDs from form
        selected_user_ids = request.POST.getlist('user_ids')
        selected_user_ids = [int(uid) for uid in selected_user_ids if uid]
        
        # Get valid user IDs in department
        valid_user_ids = list(User.objects.filter(
            is_active=True,
            role='user',
            department_memberships__department=department,
            department_memberships__is_active=True
        ).values_list('id', flat=True))
        
        # Filter to only valid users
        selected_user_ids = [uid for uid in selected_user_ids if uid in valid_user_ids]
        
        # Get current assignments
        current_assignments = DeviceUserAssignment.objects.filter(
            device=device,
            department=department,
            is_active=True
        )
        current_user_ids = set(current_assignments.values_list('user_id', flat=True))
        selected_user_ids_set = set(selected_user_ids)
        
        # Calculate changes
        users_to_add = selected_user_ids_set - current_user_ids
        users_to_remove = current_user_ids - selected_user_ids_set
        
        added_count = 0
        removed_count = 0
        
        with transaction.atomic():
            # Add new assignments
            if users_to_add:
                users_to_assign = User.objects.filter(id__in=users_to_add)
                added_count, _ = DeviceUserAssignment.assign_device_to_users(
                    device=device,
                    users=users_to_assign,
                    department=department,
                    assigned_by=request.user
                )
            
            # Remove assignments
            if users_to_remove:
                users_to_unassign = User.objects.filter(id__in=users_to_remove)
                removed_count = DeviceUserAssignment.unassign_device_from_users(
                    device=device,
                    users=users_to_unassign,
                    department=department
                )
        
        # Build response message
        msg = _build_assignment_message(device, added_count, removed_count, len(selected_user_ids))
        
        logger.info(
            f"Device assignment updated: {device.display_name} - "
            f"Added: {added_count}, Removed: {removed_count}"
        )
        
        if is_ajax(request):
            return JsonResponse({
                'success': True,
                'message': msg,
                'added': added_count,
                'removed': removed_count,
                'total_assigned': len(selected_user_ids)
            })
        
        messages.success(request, msg)
        return redirect('departmentadmin:devices')
        
    except Exception as e:
        logger.error(f"Error updating assignments: {e}", exc_info=True)
        
        if is_ajax(request):
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
        
        messages.error(request, f'⛔ Error updating assignments: {str(e)}')
        return redirect('departmentadmin:devices')


def _build_assignment_message(device, added_count, removed_count, total_assigned):
    """
    Build user-friendly assignment message.
    
    Args:
        device: Device instance
        added_count: Number of users added
        removed_count: Number of users removed
        total_assigned: Total users now assigned
        
    Returns:
        str: Message string
    """
    if added_count > 0 and removed_count > 0:
        return (
            f'✅ Device "{device.display_name}": '
            f'Added {added_count} user(s), removed {removed_count} user(s).'
        )
    elif added_count > 0:
        return f'✅ Device "{device.display_name}" assigned to {added_count} user(s).'
    elif removed_count > 0:
        return f'✅ Removed {removed_count} user(s) from "{device.display_name}".'
    else:
        return f'ℹ️ No changes made to "{device.display_name}" assignments.'


# =============================================================================
# DEVICE SENSORS (JSON API)
# =============================================================================

@require_department_admin
def device_sensors_view(request, device_id):
    """
    View all sensors for a specific device with metadata (READ-ONLY).
    
    Returns JSON for modal table display.
    """
    try:
        # Get user's department
        department, _, _ = get_current_department(request)
        
        if not department:
            return JsonResponse(
                {'success': False, 'message': 'Department not found'},
                status=404
            )
        
        # Get device - MUST be assigned to this department
        device = Device.objects.filter(
            id=device_id,
            departments=department,
            is_active=True
        ).first()
        
        if not device:
            return JsonResponse(
                {'success': False, 'message': 'Device not found or not accessible'},
                status=404
            )
        
        # Get sensors with metadata
        sensors = device.sensors.filter(
            category='sensor'
        ).select_related('metadata_config').order_by('field_name')
        
        sensor_list = _prepare_sensor_list(sensors)
        
        return JsonResponse({
            'success': True,
            'device': {
                'display_name': device.display_name,
                'device_id': device.device_id,
                'measurement_name': device.measurement_name
            },
            'sensors': sensor_list,
            'total_sensors': len(sensor_list)
        })
    
    except Exception as e:
        logger.error(f"Error fetching sensors: {e}", exc_info=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def _prepare_sensor_list(sensors):
    """
    Prepare sensor list with metadata for JSON response.
    
    Args:
        sensors: QuerySet of Sensor objects
        
    Returns:
        list: Sensor dictionaries
    """
    sensor_list = []
    
    for sensor in sensors:
        if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
            metadata = sensor.metadata_config
            data_types = metadata.data_types or []
            
            sensor_data = {
                'id': sensor.id,
                'field_name': sensor.field_name,
                'display_name': metadata.display_name or sensor.field_name,
                'field_type': sensor.field_type,
                'category': sensor.category,
                'unit': metadata.unit,
                'upper_limit': metadata.upper_limit,
                'lower_limit': metadata.lower_limit,
                'central_line': metadata.center_line,
                'show_time_series': 'trend' in data_types,
                'show_latest_value': 'latest_value' in data_types,
                'show_digital': 'digital' in data_types,
                'has_metadata': True,
            }
        else:
            sensor_data = {
                'id': sensor.id,
                'field_name': sensor.field_name,
                'display_name': sensor.display_name or sensor.field_name,
                'field_type': sensor.field_type,
                'category': sensor.category,
                'unit': sensor.unit,
                'upper_limit': None,
                'lower_limit': None,
                'central_line': None,
                'show_time_series': False,
                'show_latest_value': False,
                'show_digital': False,
                'has_metadata': False,
            }
        
        sensor_list.append(sensor_data)
    
    return sensor_list

# =============================================================================
# DEVICE VISUALIZATION ROUTER
# =============================================================================

@require_department_admin
def device_visualization_view(request, device_id):
    """
    Smart router: Routes to correct visualization based on device type.
    
    - Industrial devices → Graphs page
    - Asset tracking devices → Asset map page
    """
    # Get user's department
    department, _, _ = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('departmentadmin:dashboard')
    
    # Get device
    device = Device.objects.filter(
        id=device_id,
        departments=department,
        is_active=True
    ).first()
    
    if not device:
        messages.error(request, '⛔ Device not found or not assigned to your department')
        return redirect('departmentadmin:devices')
    
    # Route based on device type
    if device.device_type == 'asset_tracking':
        return redirect('departmentadmin:device_asset_map', device_id=device.id)
    else:
        return redirect('departmentadmin:device_graphs_page', device_id=device.id)


# =============================================================================
# DEVICE GRAPHS
# =============================================================================

@require_department_admin
def device_graphs_page_view(request, device_id):
    """
    Display full page with graphs for a device.
    
    Renders HTML template with empty containers.
    JavaScript calls device_graphs_view to fetch data.
    """
    # Get department context
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('departmentadmin:dashboard')
    
    # Get device - MUST be assigned to this department
    device = Device.objects.filter(
        id=device_id,
        departments=department,
        is_active=True
    ).first()
    
    if not device:
        messages.error(request, '⛔ Device not found or not assigned to your department')
        return redirect('departmentadmin:devices')
    
    context = {
        # Department switcher
        'department': department,
        'all_departments': all_departments,
        'show_department_switcher': show_department_switcher,
        
        # Page-specific data
        'device': device,
        'page_title': f'Graphs - {device.display_name}',
    }
    
    return render(request, 'departmentadmin/device_graphs.html', context)


@require_department_admin
def device_graphs_view(request, device_id):
    """
    Fetch graph data for a device's sensors (JSON API).
    
    Returns JSON data for frontend chart rendering.
    Called by JavaScript on the graph page.
    """
    logger.debug(f"Graph data requested for device {device_id}")
    
    try:
        # Get user's department
        department, _, _ = get_current_department(request)
        
        if not department:
            return JsonResponse({
                'success': False,
                'message': 'You are not assigned to any department.'
            }, status=403)
        
        # Get device - MUST be assigned to this department
        device = Device.objects.filter(
            id=device_id,
            departments=department,
            is_active=True
        ).first()
        
        if not device:
            logger.warning(f"Device {device_id} not found or not assigned to department")
            return JsonResponse({
                'success': False,
                'message': 'Device not found or not assigned to your department'
            }, status=404)
        
        logger.debug(f"Device found: {device.display_name}")
        
        # Get time range from request (default: 24h)
        time_range = request.GET.get('time_range', 'now() - 24h')
        
        # Validate time range
        if time_range not in INTERVAL_LOOKUP:
            logger.debug(f"Invalid time range '{time_range}', using default")
            time_range = 'now() - 24h'
        
        # Get all sensors for this device (only 'sensor' category)
        sensors = device.sensors.filter(
            category='sensor',
            is_active=True
        ).select_related('metadata_config')
        
        if not sensors.exists():
            logger.warning(f"No sensors found for device {device_id}")
            return JsonResponse({
                'success': False,
                'message': 'No sensors found for this device'
            }, status=404)
        
        # Get InfluxDB config
        config = AssetConfig.get_default_config()
        
        if not config or not config.is_connected:
            logger.warning("InfluxDB not configured")
            return JsonResponse({
                'success': False,
                'message': 'InfluxDB not configured'
            }, status=500)
        
        # Fetch data from InfluxDB
        result = fetch_sensor_data_from_influx(device, sensors, config, time_range)
        
        if not result['success']:
            logger.warning(f"Failed to fetch data: {result['message']}")
            return JsonResponse({
                'success': False,
                'message': result['message']
            }, status=500)
        
        # Build response
        response_data = {
            'success': True,
            'device': {
                'id': device.id,
                'device_id': device.device_id,
                'display_name': device.display_name,
                'measurement_name': device.measurement_name
            },
            'time_range': time_range,
            'data': result['data']
        }
        
        logger.debug(
            f"Returning graph data - Timestamps: {len(response_data['data']['timestamps'])}, "
            f"Sensors: {len(response_data['data']['sensors'])}"
        )
        
        return JsonResponse(response_data)
    
    except Exception as e:
        logger.error(f"Error in device_graphs_view: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        }, status=500)


# =============================================================================
# ASSET MAP
# =============================================================================

@require_department_admin
def device_asset_map_view(request, device_id):
    """
    Asset Map Page View - Shows map with location tracking.
    
    Renders HTML template for Leaflet.js map display.
    """
    # Get department context
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('departmentadmin:dashboard')
    
    # Get device
    device = Device.objects.filter(
        id=device_id,
        departments=department,
        is_active=True
    ).prefetch_related('sensors').first()
    
    if not device:
        messages.error(request, '⛔ Device not found or not assigned to your department')
        return redirect('departmentadmin:devices')
    
    # Check device type
    if device.device_type != 'asset_tracking':
        messages.warning(request, '⚠️ This device is not an asset tracking device')
        return redirect('departmentadmin:device_graphs_page', device_id=device.id)
    
    # Get asset tracking config
    try:
        asset_config = AssetTrackingConfig.objects.get(device=device)
    except AssetTrackingConfig.DoesNotExist:
        asset_config = None
    
    # Get InfluxDB config
    influx_config = device.asset_config
    
    if not influx_config or not influx_config.is_connected:
        messages.error(request, '⛔ InfluxDB not configured. Contact your Company Admin.')
        return redirect('departmentadmin:devices')
    
    context = {
        # Department switcher
        'department': department,
        'all_departments': all_departments,
        'show_department_switcher': show_department_switcher,
        
        # Page-specific data
        'device': device,
        'asset_config': asset_config,
        'has_config': asset_config is not None,
        'has_location': asset_config.has_location_config if asset_config else False,
        'has_map_popup': asset_config.map_popup_sensors.exists() if asset_config else False,
        'has_info_cards': asset_config.info_card_sensors.exists() if asset_config else False,
        'has_time_series': asset_config.time_series_sensors.exists() if asset_config else False,
        'page_title': f'Asset Map - {device.display_name}',
    }
    
    return render(request, 'departmentadmin/device_asset_map.html', context)


@require_department_admin
def device_asset_map_data_view(request, device_id):
    """
    Fetch asset tracking data for map (JSON API).
    
    Returns JSON with location points for Leaflet.js.
    """
    logger.debug(f"Asset map data requested for device {device_id}")
    
    try:
        # Get department
        department, _, _ = get_current_department(request)
        
        if not department:
            return JsonResponse({
                'success': False,
                'message': 'You are not assigned to any department.'
            }, status=403)
        
        # Get device - must be in user's department
        device = Device.objects.filter(
            id=device_id,
            departments=department,
            is_active=True
        ).first()
        
        if not device:
            return JsonResponse({
                'success': False,
                'message': 'Device not found or access denied'
            }, status=404)
        
        # Verify this is an asset tracking device
        if device.device_type != 'asset_tracking':
            return JsonResponse({
                'success': False,
                'message': 'This device is not configured for asset tracking'
            }, status=400)
        
        # Get time range from request (default: 1 hour)
        time_range = request.GET.get('time_range', 'now() - 1h')
        
        logger.debug(f"Time range: {time_range}, Device: {device.display_name}")
        
        # Get asset tracking config
        try:
            asset_config = AssetTrackingConfig.objects.get(device=device)
        except AssetTrackingConfig.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Asset tracking not configured for this device'
            }, status=400)
        
        # Get InfluxDB config
        influx_config = device.asset_config
        if not influx_config or not influx_config.is_connected:
            return JsonResponse({
                'success': False,
                'message': 'InfluxDB not configured'
            }, status=500)
        
        # Fetch data from InfluxDB
        result = fetch_asset_tracking_data_from_influx(
            device=device,
            asset_config=asset_config,
            influx_config=influx_config,
            time_range=time_range
        )
        
        if not result['success']:
            return JsonResponse({
                'success': False,
                'message': result['message']
            }, status=500)
        
        # Build response
        data = result['data']
        response_data = {
            'success': True,
            'device': {
                'id': device.id,
                'device_id': device.device_id,
                'display_name': device.display_name,
            },
            'time_range': time_range,
            'data': {
                'points': data.get('points', []),
                'total_points': data.get('total_points', 0),
                'start_point': data.get('start_point'),
                'end_point': data.get('end_point'),
            }
        }
        
        logger.debug(f"Returning {data.get('total_points', 0)} location points")
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Error in device_asset_map_data_view: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        }, status=500)
    
# =============================================================================
# ALERTS
# =============================================================================

@require_department_admin
def alerts_view(request):
    """
    Alert monitoring view with all alerts for client-side filtering.
    
    Shows alerts for industrial_sensor devices only.
    """
    # Get department context
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('departmentadmin:dashboard')
    
    # Get ALL alerts for industrial_sensor devices ONLY
    all_alerts = SensorAlert.objects.filter(
        sensor_metadata__sensor__device__departments=department,
        sensor_metadata__sensor__device__device_type='industrial_sensor'
    ).select_related(
        'sensor_metadata__sensor__device__asset_config'
    ).order_by('-created_at')
    
    # Calculate counts
    alert_counts = {
        'high': all_alerts.filter(status='high').count(),
        'medium': all_alerts.filter(status='medium').count(),
        'initial': all_alerts.filter(status='initial').count(),
        'total_active': all_alerts.filter(status__in=['initial', 'medium', 'high']).count(),
        'total_resolved': all_alerts.filter(status='resolved').count(),
    }
    
    context = {
        # Department switcher
        'department': department,
        'all_departments': all_departments,
        'show_department_switcher': show_department_switcher,
        
        # Page-specific data
        'all_alerts': all_alerts,
        'alert_counts': alert_counts,
        'page_title': 'Alert Monitoring',
    }
    
    return render(request, 'departmentadmin/alerts.html', context)


# =============================================================================
# REPORTS
# =============================================================================

@require_department_admin
def reports_view(request):
    """
    Reports management view.
    
    Generate, view, download, and delete device reports.
    Supports both Daily Reports and Custom Date/Time Range Reports.
    
    - Daily reports: Last 30 days only
    - Custom reports: ALL (no date restriction)
    """
    logger.debug(f"Reports view accessed by {request.user.username}")
    
    # Get department context
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('departmentadmin:dashboard')
    
    # Get membership for reports generation
    try:
        membership = DepartmentMembership.objects.get(
            user=request.user,
            department=department,
            is_active=True
        )
    except DepartmentMembership.DoesNotExist:
        messages.error(request, '⛔ Department membership not found.')
        return redirect('departmentadmin:dashboard')
    
    # Handle POST requests
    if request.method == 'POST':
        action = request.POST.get('action')
        logger.debug(f"Reports POST action: {action}")
        
        if action == 'generate_all':
            return _handle_generate_all_reports(request, department, membership)
        elif action == 'generate_custom':
            return _handle_generate_custom_report(request, department, membership)
        elif action == 'download':
            return _handle_download_report(request, department)
        elif action == 'delete':
            return _handle_delete_report(request, department)
    
    # GET request - Display reports page
    return _render_reports_page(request, department, all_departments, show_department_switcher)


def _handle_generate_all_reports(request, department, membership):
    """Handle batch generation of daily reports for all devices."""
    yesterday = timezone.now().date() - timedelta(days=1)
    
    devices = Device.objects.filter(
        departments=department,
        is_active=True
    ).order_by('display_name')
    
    total_devices = devices.count()
    
    if total_devices == 0:
        messages.warning(request, "No active devices found in this department.")
        return redirect('departmentadmin:reports')
    
    success_count = 0
    skipped_count = 0
    failed_count = 0
    
    for device in devices:
        try:
            # Only check for DAILY reports
            existing_report = DailyDeviceReport.objects.filter(
                tenant=request.tenant,
                department=department,
                device=device,
                report_date=yesterday,
                report_type='daily'
            ).first()
            
            if existing_report:
                skipped_count += 1
                continue
            
            generation_start = time.time()
            
            report = generate_device_daily_report(
                device=device,
                report_date=yesterday,
                department=department,
                generated_by=membership,
                tenant=request.tenant
            )
            
            generation_time = time.time() - generation_start
            
            logger.info(
                f"Daily report generated: {device.display_name}, "
                f"ID: {report.id}, Time: {generation_time:.2f}s"
            )
            
            success_count += 1
            
        except Exception as e:
            logger.error(f"Failed to generate report for {device.display_name}: {e}", exc_info=True)
            failed_count += 1
    
    # Build result messages
    if success_count > 0:
        messages.success(request, f"✅ Successfully generated {success_count} daily report(s).")
    if skipped_count > 0:
        messages.info(request, f"⏭️ Skipped {skipped_count} device(s) - daily reports already exist.")
    if failed_count > 0:
        messages.error(request, f"❌ Failed to generate {failed_count} report(s). Check logs for details.")
    
    return redirect('departmentadmin:reports')


def _handle_generate_custom_report(request, department, membership):
    """Handle generation of custom date/time range report."""
    try:
        device_id = request.POST.get('device_id')
        start_date = request.POST.get('start_date')
        start_time = request.POST.get('start_time', '00:00')
        end_date = request.POST.get('end_date')
        end_time = request.POST.get('end_time', '23:59')
        
        logger.debug(
            f"Custom report request - Device: {device_id}, "
            f"Start: {start_date} {start_time}, End: {end_date} {end_time}"
        )
        
        # Validation
        if not all([device_id, start_date, end_date]):
            messages.error(request, "Please fill in all required fields.")
            return redirect('departmentadmin:reports')
        
        device = Device.objects.get(
            id=device_id,
            departments=department,
            is_active=True
        )
        
        # Parse datetime
        start_datetime_str = f"{start_date} {start_time}"
        end_datetime_str = f"{end_date} {end_time}"
        
        start_datetime = datetime.strptime(start_datetime_str, '%Y-%m-%d %H:%M')
        end_datetime = datetime.strptime(end_datetime_str, '%Y-%m-%d %H:%M')
        
        if start_datetime >= end_datetime:
            messages.error(request, "Start date/time must be before end date/time.")
            return redirect('departmentadmin:reports')
        
        # Generate report
        generation_start = time.time()
        
        report = generate_custom_device_report(
            device=device,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            department=department,
            generated_by=membership,
            tenant=request.tenant
        )
        
        generation_time = time.time() - generation_start
        
        logger.info(
            f"Custom report generated: {device.display_name}, "
            f"ID: {report.id}, Time: {generation_time:.2f}s"
        )
        
        messages.success(
            request,
            f"✅ Custom report generated successfully! ({generation_time:.1f}s)"
        )
        
        return redirect('departmentadmin:reports')
        
    except Device.DoesNotExist:
        logger.warning(f"Device not found: {device_id}")
        messages.error(request, "Device not found or you don't have access to it.")
        return redirect('departmentadmin:reports')
        
    except ValueError as e:
        logger.warning(f"Invalid date/time format: {e}")
        messages.error(request, "Invalid date/time format. Please check your inputs.")
        return redirect('departmentadmin:reports')
        
    except Exception as e:
        logger.error(f"Error generating custom report: {e}", exc_info=True)
        messages.error(request, f"Error generating custom report: {str(e)}")
        return redirect('departmentadmin:reports')


def _handle_download_report(request, department):
    """Handle report download."""
    report_id = request.POST.get('report_id')
    logger.debug(f"Download request for report ID: {report_id}")
    
    try:
        report = DailyDeviceReport.objects.get(
            id=report_id,
            tenant=request.tenant,
            department=department
        )
        
        if not report.csv_file:
            messages.error(request, "Report file not found.")
            return redirect('departmentadmin:reports')
        
        response = HttpResponse(
            report.csv_file.read(),
            content_type='text/csv'
        )
        
        filename = os.path.basename(report.csv_file.name)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        logger.debug(f"Serving file: {filename}")
        return response
        
    except DailyDeviceReport.DoesNotExist:
        messages.error(request, "Report not found.")
        return redirect('departmentadmin:reports')
    except Exception as e:
        logger.error(f"Download error: {e}", exc_info=True)
        messages.error(request, f"Error downloading report: {str(e)}")
        return redirect('departmentadmin:reports')


def _handle_delete_report(request, department):
    """Handle report deletion."""
    report_id = request.POST.get('report_id')
    logger.debug(f"Delete request for report ID: {report_id}")
    
    try:
        report = DailyDeviceReport.objects.get(
            id=report_id,
            tenant=request.tenant,
            department=department
        )
        
        filename = os.path.basename(report.csv_file.name) if report.csv_file else "Unknown"
        report_type = report.report_type
        
        # Delete file from storage
        if report.csv_file:
            try:
                report.csv_file.delete(save=False)
                logger.debug(f"File deleted from storage: {filename}")
            except Exception as e:
                logger.warning(f"File deletion warning: {e}")
        
        report.delete()
        logger.info(f"Report deleted: {filename}")
        
        messages.success(request, f"✅ {report_type.title()} report '{filename}' deleted successfully.")
        return redirect('departmentadmin:reports')
        
    except DailyDeviceReport.DoesNotExist:
        messages.error(request, "Report not found.")
        return redirect('departmentadmin:reports')
    except Exception as e:
        logger.error(f"Delete error: {e}", exc_info=True)
        messages.error(request, f"Error deleting report: {str(e)}")
        return redirect('departmentadmin:reports')


def _render_reports_page(request, department, all_departments, show_department_switcher):
    """Render reports page with filters and pagination."""
    # Get filter parameters
    filter_type = request.GET.get('type', 'all')
    filter_device = request.GET.get('device', '')
    filter_date_from = request.GET.get('date_from', '')
    filter_date_to = request.GET.get('date_to', '')
    page_number = request.GET.get('page', 1)
    
    logger.debug(
        f"Reports filters - Type: {filter_type}, Device: {filter_device}, "
        f"From: {filter_date_from}, To: {filter_date_to}"
    )
    
    # Fetch devices
    devices = Device.objects.filter(
        departments=department,
        is_active=True
    ).order_by('display_name')
    
    total_devices = devices.count()
    
    # Build base queryset (ALL reports, no date restriction)
    reports_queryset = DailyDeviceReport.objects.filter(
        tenant=request.tenant,
        department=department
    ).select_related('device', 'generated_by', 'generated_by__user')
    
    # Apply filters
    reports_queryset = _apply_report_filters(
        reports_queryset, filter_type, filter_device, filter_date_from, filter_date_to
    )
    
    # Order and paginate
    reports_queryset = reports_queryset.order_by('-created_at', '-report_date')
    
    paginator = Paginator(reports_queryset, 20)
    
    try:
        reports_page = paginator.page(page_number)
    except PageNotAnInteger:
        reports_page = paginator.page(1)
    except EmptyPage:
        reports_page = paginator.page(paginator.num_pages)
    
    # Calculate statistics
    stats = _calculate_report_stats(request.tenant, department, total_devices)
    
    context = {
        # Department switcher
        'department': department,
        'all_departments': all_departments,
        'show_department_switcher': show_department_switcher,
        
        # Devices
        'devices': devices,
        'total_devices': total_devices,
        
        # Reports (paginated)
        'reports': reports_page,
        'paginator': paginator,
        
        # Statistics
        'total_reports': stats['total_reports'],
        'daily_reports_count': stats['daily_reports_count'],
        'custom_reports_count': stats['custom_reports_count'],
        'filtered_count': paginator.count,
        
        # Yesterday stats
        'yesterday': stats['yesterday'],
        'devices_with_yesterday_report': stats['devices_with_yesterday_report'],
        'devices_without_yesterday_report': stats['devices_without_yesterday_report'],
        
        # Current filters (for form persistence)
        'filter_type': filter_type,
        'filter_device': filter_device,
        'filter_date_from': filter_date_from,
        'filter_date_to': filter_date_to,
        
        'page_title': 'Reports',
    }
    
    return render(request, 'departmentadmin/reports.html', context)


def _apply_report_filters(queryset, filter_type, filter_device, filter_date_from, filter_date_to):
    """
    Apply filters to reports queryset.
    
    Args:
        queryset: Base reports queryset
        filter_type: 'all', 'daily', or 'custom'
        filter_device: Device ID string
        filter_date_from: Date string (YYYY-MM-DD)
        filter_date_to: Date string (YYYY-MM-DD)
        
    Returns:
        QuerySet: Filtered queryset
    """
    # Filter by report type
    if filter_type == 'daily':
        queryset = queryset.filter(report_type='daily')
    elif filter_type == 'custom':
        queryset = queryset.filter(report_type='custom')
    
    # Filter by device
    if filter_device:
        try:
            queryset = queryset.filter(device_id=int(filter_device))
        except ValueError:
            pass
    
    # Filter by date range
    if filter_date_from:
        try:
            date_from = datetime.strptime(filter_date_from, '%Y-%m-%d').date()
            queryset = queryset.filter(report_date__gte=date_from)
        except ValueError:
            pass
    
    if filter_date_to:
        try:
            date_to = datetime.strptime(filter_date_to, '%Y-%m-%d').date()
            queryset = queryset.filter(report_date__lte=date_to)
        except ValueError:
            pass
    
    return queryset


def _calculate_report_stats(tenant, department, total_devices):
    """
    Calculate report statistics.
    
    Args:
        tenant: Tenant instance
        department: Department instance
        total_devices: Total device count
        
    Returns:
        dict: Statistics dictionary
    """
    # Total counts (all time)
    total_reports = DailyDeviceReport.objects.filter(
        tenant=tenant,
        department=department
    ).count()
    
    daily_reports_count = DailyDeviceReport.objects.filter(
        tenant=tenant,
        department=department,
        report_type='daily'
    ).count()
    
    custom_reports_count = DailyDeviceReport.objects.filter(
        tenant=tenant,
        department=department,
        report_type='custom'
    ).count()
    
    # Yesterday's daily reports (for pending calculation)
    yesterday = timezone.now().date() - timedelta(days=1)
    
    devices_with_yesterday_report = DailyDeviceReport.objects.filter(
        tenant=tenant,
        department=department,
        report_date=yesterday,
        report_type='daily'
    ).values_list('device_id', flat=True)
    
    devices_with_yesterday_count = len(set(devices_with_yesterday_report))
    devices_without_yesterday_report = total_devices - devices_with_yesterday_count
    
    return {
        'total_reports': total_reports,
        'daily_reports_count': daily_reports_count,
        'custom_reports_count': custom_reports_count,
        'yesterday': yesterday,
        'devices_with_yesterday_report': devices_with_yesterday_count,
        'devices_without_yesterday_report': devices_without_yesterday_report,
    }

# =============================================================================
# PROFILE MANAGEMENT
# =============================================================================

@require_department_admin
def profile_view(request):
    """
    Workspace Supervisor Profile View.
    
    View and edit own profile information.
    """
    # Get department context
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any workspace.')
        return redirect('accounts:login')
    
    user = request.user
    
    # Handle POST request
    if request.method == 'POST':
        return _handle_profile_update(request, user)
    
    # Get user's workspace memberships
    user_workspaces = DepartmentMembership.objects.filter(
        user=user,
        is_active=True,
        department__is_active=True
    ).select_related('department')
    
    context = {
        # Department switcher
        'department': department,
        'all_departments': all_departments,
        'show_department_switcher': show_department_switcher,
        
        # Profile data
        'profile_user': user,
        'user_workspaces': user_workspaces,
        'total_workspaces': user_workspaces.count(),
        'page_title': 'My Profile',
    }
    
    return render(request, 'departmentadmin/profile.html', context)


def _handle_profile_update(request, user):
    """
    Handle profile update POST request.
    
    Args:
        request: HTTP request
        user: User instance to update
        
    Returns:
        Redirect response
    """
    try:
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        
        # Validation
        if not first_name:
            messages.error(request, '⛔ First name is required.')
            return redirect('departmentadmin:profile')
        
        if not email:
            messages.error(request, '⛔ Email is required.')
            return redirect('departmentadmin:profile')
        
        # Check email uniqueness (excluding current user)
        if User.objects.filter(email__iexact=email).exclude(id=user.id).exists():
            messages.error(request, f'⛔ Email "{email}" is already in use.')
            return redirect('departmentadmin:profile')
        
        # Update user
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        user.phone = phone
        user.save()
        
        logger.info(f"Profile updated: {user.username}")
        messages.success(request, '✅ Profile updated successfully!')
        return redirect('departmentadmin:profile')
        
    except Exception as e:
        logger.error(f"Error updating profile: {e}", exc_info=True)
        messages.error(request, f'⛔ Error updating profile: {str(e)}')
        return redirect('departmentadmin:profile')


# =============================================================================
# CHANGE PASSWORD
# =============================================================================

@require_department_admin
def change_password_view(request):
    """
    Workspace Supervisor Change Password View.
    
    Allows user to change their own password.
    """
    # Get department context
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any workspace.')
        return redirect('accounts:login')
    
    user = request.user
    
    # Handle POST request
    if request.method == 'POST':
        return _handle_password_change(request, user)
    
    context = {
        # Department switcher
        'department': department,
        'all_departments': all_departments,
        'show_department_switcher': show_department_switcher,
        
        'page_title': 'Change Password',
    }
    
    return render(request, 'departmentadmin/change_password.html', context)


def _handle_password_change(request, user):
    """
    Handle password change POST request.
    
    Args:
        request: HTTP request
        user: User instance
        
    Returns:
        Redirect response
    """
    current_password = request.POST.get('current_password', '')
    new_password = request.POST.get('new_password', '')
    confirm_password = request.POST.get('confirm_password', '')
    
    # Validation
    if not current_password:
        messages.error(request, '⛔ Current password is required.')
        return redirect('departmentadmin:change_password')
    
    if not new_password:
        messages.error(request, '⛔ New password is required.')
        return redirect('departmentadmin:change_password')
    
    if len(new_password) < 8:
        messages.error(request, '⛔ Password must be at least 8 characters long.')
        return redirect('departmentadmin:change_password')
    
    if new_password != confirm_password:
        messages.error(request, '⛔ New passwords do not match.')
        return redirect('departmentadmin:change_password')
    
    # Verify current password
    if not user.check_password(current_password):
        messages.error(request, '⛔ Current password is incorrect.')
        return redirect('departmentadmin:change_password')
    
    # Check new password is different from current
    if current_password == new_password:
        messages.error(request, '⛔ New password must be different from current password.')
        return redirect('departmentadmin:change_password')
    
    try:
        # Set new password
        user.set_password(new_password)
        user.save()
        
        # Keep user logged in after password change
        update_session_auth_hash(request, user)
        
        logger.info(f"Password changed: {user.username}")
        messages.success(request, '✅ Password changed successfully!')
        return redirect('departmentadmin:profile')
        
    except Exception as e:
        logger.error(f"Error changing password: {e}", exc_info=True)
        messages.error(request, f'⛔ Error changing password: {str(e)}')
        return redirect('departmentadmin:change_password')