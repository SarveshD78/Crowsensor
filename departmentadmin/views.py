# departmentadmin/views.py - COMPLETE FIXED VERSION
# ============================================================================
# ALL VIEWS NOW PASS: department, all_departments, show_department_switcher
# ============================================================================

import traceback
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import logout
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from datetime import datetime, timedelta
import time
import os

from accounts.decorators import require_department_admin
from companyadmin.models import (
    Department, DepartmentMembership, Device, 
    AssetConfig, AssetTrackingConfig, Sensor
)
from accounts.models import User
from departmentadmin.models import DeviceUserAssignment, SensorAlert, DailyDeviceReport

# ============================================================================
# IMPORT HELPER FUNCTIONS
# ============================================================================
from .utils import get_current_department, get_department_or_redirect
from .graph_func import fetch_sensor_data_from_influx, INTERVAL_LOOKUP
from .asset_map_func import fetch_asset_tracking_data_from_influx
from .reports_func import generate_device_daily_report, generate_custom_device_report


# ============================================================================
# DEPARTMENT SWITCHER VIEW
# ============================================================================

@require_department_admin
def switch_department(request):
    """
    🌍 GLOBAL DEPARTMENT SWITCHER
    Handles department switching across all views
    Stores selection in session
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
            
            # ✅ STORE IN SESSION
            request.session['selected_department_id'] = int(department_id)
            request.session['selected_department_name'] = membership.department.name
            
            print(f"\n{'='*80}")
            print(f"🔄 DEPARTMENT SWITCHED")
            print(f"{'='*80}")
            print(f"User: {request.user.email}")
            print(f"To: {membership.department.name} (ID: {membership.department.id})")
            print(f"Session ID: {request.session.session_key}")
            print(f"{'='*80}\n")
            
            messages.success(request, f'✅ Switched to {membership.department.name}')
            
        except DepartmentMembership.DoesNotExist:
            messages.error(request, '⛔ You do not have access to this department.')
        
        # Redirect back to previous page
        return redirect(request.META.get('HTTP_REFERER', 'departmentadmin:dashboard'))
    
    # GET request - redirect to dashboard
    return redirect('departmentadmin:dashboard')


# ============================================================================
# AUTHENTICATION
# ============================================================================

@require_department_admin
def logout_view(request):
    """Logout department admin"""
    username = request.user.get_full_name_or_username()
    logout(request)
    messages.success(request, f'👋 Goodbye {username}! You have been logged out successfully.')
    return redirect('accounts:login')


# ============================================================================
# DASHBOARD VIEW - FIXED ✅
# ============================================================================

@require_department_admin
def dashboard_view(request):
    """
    Department Admin Dashboard
    Shows only departments assigned to this user
    """
    
    # ✅ USE GLOBAL HELPER - Gets department + switcher data
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
        # ✅ REQUIRED FOR DEPARTMENT SWITCHER
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


# ============================================================================
# USER MANAGEMENT VIEW - FIXED ✅
# ============================================================================
@require_department_admin
def users_view(request):
    """
    Department Admin User Management
    Can create: user (read-only role)
    Users are assigned to the CURRENTLY SELECTED department only
    """
    
    # ✅ USE GLOBAL HELPER - Gets department + switcher data
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('departmentadmin:dashboard')
    
    # ==========================================
    # GET USERS FOR CURRENT DEPARTMENT ONLY
    # ==========================================
    
    # CHANGED: Filter users by CURRENT department only (not all admin's departments)
    all_users = User.objects.filter(
        is_active=True,
        role='user',
        department_memberships__department=department,  # CHANGED: Current department only
        department_memberships__is_active=True
    ).prefetch_related(
        'department_memberships__department'
    ).distinct().order_by('-created_at')
    
    # Stats for CURRENT department
    total_users = all_users.count()
    
    # ==========================================
    # POST HANDLING
    # ==========================================
    if request.method == 'POST':
        
        # ADD USER - ASSIGN TO CURRENT DEPARTMENT ONLY
        if 'add_user' in request.POST:
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
                
                # ✅ CREATE USER AND ASSIGN TO CURRENT DEPARTMENT ONLY
                with transaction.atomic():
                    # Create user
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password='User@2025',  # Default password
                        first_name=first_name,
                        last_name=last_name,
                        role='user',
                        phone=phone,
                        is_active=True
                    )
                    
                    # CHANGED: Assign to CURRENT department only (from switcher)
                    DepartmentMembership.objects.create(
                        user=user,
                        department=department,  # Current selected department
                        is_active=True
                    )
                
                messages.success(
                    request,
                    f'✅ User "{user.username}" created and assigned to "{department.name}"! '
                    f'Default password: User@2025'
                )
                
            except Exception as e:
                messages.error(request, f'⛔ Error creating user: {str(e)}')
            
            return redirect('departmentadmin:users')
        
        # EDIT USER
        elif 'edit_user' in request.POST:
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
                
                # CHANGED: Get user from CURRENT department only
                user = get_object_or_404(
                    User, 
                    id=user_id, 
                    is_active=True,
                    role='user',
                    department_memberships__department=department,  # Must be in current department
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
                
                messages.success(request, f'✅ User "{user.username}" updated successfully!')
                
            except User.DoesNotExist:
                messages.error(request, '⛔ User not found in this department.')
            except Exception as e:
                messages.error(request, f'⛔ Error updating user: {str(e)}')
            
            return redirect('departmentadmin:users')
        
        # DELETE USER (Remove from current department only)
        elif 'delete_user' in request.POST:
            try:
                user_id = request.POST.get('user_id')
                
                # CHANGED: Verify user belongs to current department
                user = get_object_or_404(
                    User, 
                    id=user_id, 
                    is_active=True,
                    role='user',
                    department_memberships__department=department,
                    department_memberships__is_active=True
                )
                
                username = user.username
                
                # CHANGED: Remove from CURRENT department only (not full delete)
                # This way if user is in multiple departments, they're only removed from this one
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
                        messages.success(request, f'✅ User "{username}" removed from "{department.name}" and deactivated.')
                    else:
                        messages.success(request, f'✅ User "{username}" removed from "{department.name}".')
                else:
                    messages.error(request, '⛔ User membership not found.')
                
            except User.DoesNotExist:
                messages.error(request, '⛔ User not found in this department.')
            except Exception as e:
                messages.error(request, f'⛔ Error removing user: {str(e)}')
            
            return redirect('departmentadmin:users')
    
    # ==========================================
    # PREPARE USER DATA FOR TEMPLATE
    # ==========================================
    
    # Get all department IDs this admin manages (for showing user's other departments)
    admin_dept_ids = DepartmentMembership.objects.filter(
        user=request.user,
        is_active=True,
        department__is_active=True
    ).values_list('department_id', flat=True)
    
    users_data = []
    for user in all_users:
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
            'is_multi_dept': user_depts.count() > 1,  # Flag for UI
        })
    
    context = {
        # ✅ REQUIRED FOR DEPARTMENT SWITCHER
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
# ============================================================================
# DEVICES VIEW - FIXED ✅
# ============================================================================
# ============================================================================
# DEVICES VIEW - UPDATED WITH ASSIGNMENT SUPPORT
# ============================================================================

@require_department_admin
def devices_view(request):
    """
    View all devices assigned to user's department
    Includes user assignment functionality
    """
    
    # ✅ USE GLOBAL HELPER - Gets department + switcher data
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('departmentadmin:dashboard')
    
    # Get ALL devices assigned to this department (active + inactive)
    devices = Device.objects.filter(
        departments=department
    ).prefetch_related(
        'sensors', 
        'departments',
        'user_assignments'  # ADDED: Prefetch assignments
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
    devices_list = []
    for device in devices:
        # Existing computed data
        device.total_sensors_only = device.sensors.filter(category='sensor').count()
        device.sensor_breakdown = {
            'sensors': device.sensors.filter(category='sensor').count(),
            'slaves': device.sensors.filter(category='slave').count(),
            'info': device.sensors.filter(category='info').count(),
        }
        device.device_column = device.metadata.get('device_column', 'N/A')
        device.auto_discovered = device.metadata.get('auto_discovered', False)
        
        # ADDED: Assignment data
        active_assignments = device.user_assignments.filter(
            department=department,
            is_active=True
        ).select_related('user')
        
        device.assigned_users = [a.user for a in active_assignments]
        device.assigned_users_count = active_assignments.count()
        device.assigned_user_ids = [a.user.id for a in active_assignments]
        
        devices_list.append(device)
    
    context = {
        # ✅ REQUIRED FOR DEPARTMENT SWITCHER
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
        
        # ADDED: Users for assignment
        'department_users': department_users,
        'total_users': department_users.count(),
    }
    
    return render(request, 'departmentadmin/devices.html', context)


# ============================================================================
# ASSIGN DEVICE VIEW - NEW
# ============================================================================

@require_department_admin
def assign_device_view(request, device_id):
    """
    Handle device-to-user assignment
    POST: Assign/unassign users to device
    GET: Return current assignments (JSON)
    """
    
    # Get department
    department, _, _ = get_current_department(request)
    
    if not department:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': 'Department not found'}, status=404)
        messages.error(request, '⛔ Department not found.')
        return redirect('departmentadmin:devices')
    
    # Get device - must be in this department
    device = Device.objects.filter(
        id=device_id,
        departments=department
    ).first()
    
    if not device:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': 'Device not found'}, status=404)
        messages.error(request, '⛔ Device not found.')
        return redirect('departmentadmin:devices')
    
    # ==========================================
    # GET REQUEST - Return current assignments
    # ==========================================
    if request.method == 'GET':
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
    
    # ==========================================
    # POST REQUEST - Update assignments
    # ==========================================
    if request.method == 'POST':
        try:
            # Get selected user IDs from form
            selected_user_ids = request.POST.getlist('user_ids')
            selected_user_ids = [int(uid) for uid in selected_user_ids if uid]
            
            # Get all users in department for validation
            valid_user_ids = User.objects.filter(
                is_active=True,
                role='user',
                department_memberships__department=department,
                department_memberships__is_active=True
            ).values_list('id', flat=True)
            
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
            if added_count > 0 and removed_count > 0:
                msg = f'✅ Device "{device.display_name}": Added {added_count} user(s), removed {removed_count} user(s).'
            elif added_count > 0:
                msg = f'✅ Device "{device.display_name}" assigned to {added_count} user(s).'
            elif removed_count > 0:
                msg = f'✅ Removed {removed_count} user(s) from "{device.display_name}".'
            else:
                msg = f'ℹ️ No changes made to "{device.display_name}" assignments.'
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
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
            import traceback
            traceback.print_exc()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': str(e)}, status=500)
            
            messages.error(request, f'⛔ Error updating assignments: {str(e)}')
            return redirect('departmentadmin:devices')
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
# ============================================================================
# DEVICE SENSORS VIEW (JSON API - NO CHANGES NEEDED)
# ============================================================================
@require_department_admin
def device_sensors_view(request, device_id):
    """
    View all sensors for a specific device with METADATA (READ-ONLY)
    Returns JSON for modal table display
    
    ✅ FIXED: Updated to match SensorMetadata model fields
    """
    
    try:
        # Get user's department
        department, _, _ = get_current_department(request)
        
        if not department:
            return JsonResponse({'success': False, 'message': 'Department not found'}, status=404)
        
        # Get device - MUST be assigned to this department
        device = Device.objects.filter(
            id=device_id,
            departments=department,
            is_active=True
        ).first()
        
        if not device:
            return JsonResponse({'success': False, 'message': 'Device not found or not accessible'}, status=404)
        
        # Get sensors with metadata
        sensors = device.sensors.filter(
            category='sensor'
        ).select_related('metadata_config').order_by('field_name')
        
        sensor_list = []
        for sensor in sensors:
            # Check if metadata exists
            if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
                metadata = sensor.metadata_config
                
                # ✅ FIX: data_types is a JSON list like ['trend', 'latest_value', 'digital']
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
                    'central_line': metadata.center_line,  # ✅ FIX: center_line not central_line
                    # ✅ FIX: Check if type is in the data_types list
                    'show_time_series': 'trend' in data_types,
                    'show_latest_value': 'latest_value' in data_types,
                    'show_digital': 'digital' in data_types,
                    'has_metadata': True,
                }
            else:
                # No metadata configured
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
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
# ============================================================================
# DEVICE GRAPHS PAGE VIEW - FIXED ✅
# ============================================================================

@require_department_admin
def device_graphs_page_view(request, device_id):
    """
    Display full page with graphs for a device
    This renders the HTML template with empty containers
    JavaScript will then call device_graphs_view to fetch data
    """
    
    # ✅ USE GLOBAL HELPER - Gets department + switcher data
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
        # ✅ REQUIRED FOR DEPARTMENT SWITCHER
        'department': department,
        'all_departments': all_departments,
        'show_department_switcher': show_department_switcher,
        
        # Page-specific data
        'device': device,
        'page_title': f'Graphs - {device.display_name}',
    }
    
    return render(request, 'departmentadmin/device_graphs.html', context)


# ============================================================================
# DEVICE GRAPHS DATA VIEW (JSON API - NO CHANGES NEEDED)
# ============================================================================

@require_department_admin
def device_graphs_view(request, device_id):
    """
    Fetch graph data for a device's sensors
    Returns JSON data for frontend chart rendering
    Called by JavaScript on the graph page
    """
    
    print(f"\n{'='*80}")
    print(f"📊 DEVICE GRAPHS API VIEW CALLED")
    print(f"{'='*80}")
    print(f"User: {request.user.email}")
    print(f"Device ID: {device_id}")
    print(f"Time Range: {request.GET.get('time_range', 'now() - 24h')}")
    
    try:
        # Get user's department
        department, _, _ = get_current_department(request)
        
        if not department:
            return JsonResponse({
                'success': False,
                'message': 'You are not assigned to any department.'
            }, status=403)
        
        print(f"Department: {department.name}")
        
        # Get device - MUST be assigned to this department
        device = Device.objects.filter(
            id=device_id,
            departments=department,
            is_active=True
        ).first()
        
        if not device:
            print(f"❌ Device not found or not assigned to department")
            return JsonResponse({
                'success': False,
                'message': 'Device not found or not assigned to your department'
            }, status=404)
        
        print(f"✅ Device found: {device.display_name}")
        print(f"   Measurement: {device.measurement_name}")
        print(f"   Device ID: {device.device_id}")
        
        # Get time range from request (default: 24h)
        time_range = request.GET.get('time_range', 'now() - 24h')
        
        # Validate time range
        if time_range not in INTERVAL_LOOKUP:
            print(f"⚠️  Invalid time range '{time_range}', using default")
            time_range = 'now() - 24h'
        
        print(f"Time range: {time_range}")
        
        # Get all sensors for this device (only 'sensor' category)
        sensors = device.sensors.filter(
            category='sensor',
            is_active=True
        ).select_related('metadata_config')
        
        print(f"Sensors found: {sensors.count()}")
        
        if not sensors.exists():
            print(f"❌ No sensors found for this device")
            return JsonResponse({
                'success': False,
                'message': 'No sensors found for this device'
            }, status=404)
        
        # Get InfluxDB config
        config = AssetConfig.get_default_config()
        
        if not config or not config.is_connected:
            print(f"❌ InfluxDB not configured")
            return JsonResponse({
                'success': False,
                'message': 'InfluxDB not configured'
            }, status=500)
        
        print(f"✅ InfluxDB config found")
        
        # Fetch data from InfluxDB
        result = fetch_sensor_data_from_influx(device, sensors, config, time_range)
        
        print(f"\n📊 InfluxDB fetch result:")
        print(f"   Success: {result['success']}")
        print(f"   Message: {result['message']}")
        
        if not result['success']:
            print(f"❌ Failed to fetch data from InfluxDB")
            return JsonResponse({
                'success': False,
                'message': result['message']
            }, status=500)
        
        # Add device info to response
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
        
        print(f"\n✅ SUCCESS - Returning data")
        print(f"   Timestamps: {len(response_data['data']['timestamps'])}")
        print(f"   Sensors: {len(response_data['data']['sensors'])}")
        print(f"{'='*80}\n")
        
        return JsonResponse(response_data)
    
    except Exception as e:
        print(f"\n❌ EXCEPTION in device_graphs_view")
        print(f"Error: {str(e)}")
        traceback.print_exc()
        
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        }, status=500)


# ============================================================================
# DEVICE VISUALIZATION ROUTER (REDIRECT - NO CHANGES NEEDED)
# ============================================================================

@require_department_admin
def device_visualization_view(request, device_id):
    """
    ✨ SMART ROUTER: Routes to correct visualization based on device type
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
    
    # ✨ SMART ROUTING BASED ON DEVICE TYPE
    if device.device_type == 'asset_tracking':
        # Route to asset map view
        return redirect('departmentadmin:device_asset_map', device_id=device.id)
    else:
        # Route to industrial graphs view (default for 'industrial' and any other type)
        return redirect('departmentadmin:device_graphs_page', device_id=device.id)


# ============================================================================
# DEVICE ASSET MAP VIEW - FIXED ✅
# ============================================================================

@require_department_admin
def device_asset_map_view(request, device_id):
    """
    Asset Map Page View - Shows map with location tracking
    """
    
    # ✅ USE GLOBAL HELPER - Gets department + switcher data
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
        config = AssetTrackingConfig.objects.get(device=device)
    except AssetTrackingConfig.DoesNotExist:
        config = None
    
    # Get InfluxDB config
    influx_config = device.asset_config
    
    if not influx_config or not influx_config.is_connected:
        messages.error(request, '⛔ InfluxDB not configured. Contact your Company Admin.')
        return redirect('departmentadmin:devices')
    
    context = {
        # ✅ REQUIRED FOR DEPARTMENT SWITCHER
        'department': department,
        'all_departments': all_departments,
        'show_department_switcher': show_department_switcher,
        
        # Page-specific data
        'device': device,
        'asset_config': config,
        'has_config': config is not None,
        'has_location': config.has_location_config if config else False,
        'has_map_popup': config.map_popup_sensors.exists() if config else False,
'has_info_cards': config.info_card_sensors.exists() if config else False,
'has_time_series': config.time_series_sensors.exists() if config else False,
        'page_title': f'Asset Map - {device.display_name}',
    }
    
    return render(request, 'departmentadmin/device_asset_map.html', context)


# ============================================================================
# DEVICE ASSET MAP DATA VIEW (JSON API - NO CHANGES NEEDED)
# ============================================================================


def device_asset_map_data_view(request, device_id):
    """
    ✨ API ENDPOINT: Fetch asset tracking data for map
    Returns JSON with location points for Leaflet.js
    """
    
    print(f"\n{'='*80}")
    print(f"🗺️  USER ASSET MAP DATA API CALLED")
    print(f"{'='*80}")
    print(f"User: {request.user.email}")
    print(f"Device ID: {device_id}")
    
    try:
        # Check user has access to this device
        assignment = get_user_device_assignment(request.user, device_id)
        if not assignment:
            return JsonResponse({
                'success': False,
                'message': 'Access denied to this device'
            }, status=403)
        
        device = assignment.device
        
        # Verify this is an asset tracking device
        if device.device_type != 'asset_tracking':
            return JsonResponse({
                'success': False,
                'message': 'This device is not configured for asset tracking'
            }, status=400)
        
        # Get time range from request (default: 24 hours)
        time_range = request.GET.get('time_range', 'now() - 24h')
        
        print(f"⏱️  Time range: {time_range}")
        
        # Fetch asset tracking data from InfluxDB using user-specific helper
        data = fetch_asset_tracking_data_for_user(device, time_range)
        
        # Return data with flattened structure
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
                'locations': data.get('locations', []),
                'info_card_data': data.get('info_card_data', {}),
                'total_points': data.get('total_points', 0),
                'start_point': data.get('start_point'),
                'end_point': data.get('end_point'),
                'current_location': data.get('current_location'),
            }
        }
        
        print(f"✅ Returning {data.get('total_points', 0)} location points")
        print(f"📊 Info card data: {data.get('info_card_data', {})}")
        print(f"{'='*80}\n")
        
        return JsonResponse(response_data)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        }, status=500)
# ============================================================================
# ALERTS VIEW - FIXED ✅
# ============================================================================

@require_department_admin
def alerts_view(request):
    """Alert monitoring view with all alerts for client-side filtering"""
    
    # ✅ USE GLOBAL HELPER - Gets department + switcher data
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('departmentadmin:dashboard')
    
    # ✅ FIXED: Get ALL alerts for industrial_sensor devices ONLY
    all_alerts = SensorAlert.objects.filter(
        sensor_metadata__sensor__device__departments=department,
        sensor_metadata__sensor__device__device_type='industrial_sensor'  # ✅ Only industrial
    ).select_related(
        'sensor_metadata__sensor__device__asset_config'  # ✅ Prefetch asset_config
    ).order_by('-created_at')  # Most recent first
    
    # Calculate counts
    alert_counts = {
        'high': all_alerts.filter(status='high').count(),
        'medium': all_alerts.filter(status='medium').count(),
        'initial': all_alerts.filter(status='initial').count(),
        'total_active': all_alerts.filter(status__in=['initial', 'medium', 'high']).count(),
        'total_resolved': all_alerts.filter(status='resolved').count(),
    }
    
    context = {
        # ✅ REQUIRED FOR DEPARTMENT SWITCHER
        'department': department,
        'all_departments': all_departments,
        'show_department_switcher': show_department_switcher,
        
        # Page-specific data
        'all_alerts': all_alerts,
        'alert_counts': alert_counts,
        'page_title': 'Alert Monitoring',
    }
    
    return render(request, 'departmentadmin/alerts.html', context)



# ============================================================================
# REPORTS VIEW - COMPLETE REWRITE ✅
# Separate queries for Daily (30 days) and Custom (ALL) reports
# Alerts-style table with pagination
# ============================================================================
@require_department_admin
def reports_view(request):
    """
    Reports management view - Generate, view, download, and delete device reports
    Supports both Daily Reports and Custom Date/Time Range Reports
    
    UPDATED: 
    - Daily reports: Last 30 days only
    - Custom reports: ALL (no date restriction)
    - Alerts-style table with pagination
    """
    
    print(f"\n{'='*100}")
    print(f"📊 REPORTS VIEW CALLED")
    print(f"👤 User: {request.user.username}")
    print(f"🏛️  Tenant: {request.tenant.company_name}")
    print(f"📂 Schema: {request.tenant.schema_name}")
    print(f"🔗 Method: {request.method}")
    print(f"{'='*100}\n")
    
    # ✅ USE GLOBAL HELPER - Gets department + switcher data
    department, all_departments, show_department_switcher = get_current_department(request)
    
    if not department:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('departmentadmin:dashboard')
    
    print(f"✅ Department found: {department.name} (ID: {department.id})")
    
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
    
    # ===================================
    # POST REQUEST HANDLING
    # ===================================
    if request.method == 'POST':
        print(f"\n{'='*100}")
        print(f"📥 POST REQUEST - Processing action")
        print(f"{'='*100}\n")
        
        action = request.POST.get('action')
        print(f"🎯 Action: {action}")
        
        # ===================================
        # ACTION 1: Generate All Daily Reports
        # ===================================
        if action == 'generate_all':
            print(f"\n{'='*100}")
            print(f"🔄 BATCH GENERATION - All Devices Daily Reports")
            print(f"{'='*100}\n")
            
            yesterday = timezone.now().date() - timedelta(days=1)
            print(f"📅 Target date: {yesterday}")
            
            devices = Device.objects.filter(
                departments=department,
                is_active=True
            ).order_by('display_name')
            
            total_devices = devices.count()
            print(f"📱 Found {total_devices} active devices in department\n")
            
            if total_devices == 0:
                messages.warning(request, "No active devices found in this department.")
                return redirect('departmentadmin:reports')
            
            success_count = 0
            skipped_count = 0
            failed_count = 0
            results = []
            
            for idx, device in enumerate(devices, 1):
                print(f"{'─'*100}")
                print(f"📱 DEVICE {idx}/{total_devices}: {device.display_name} - {device.device_id}")
                print(f"{'─'*100}")
                
                try:
                    print(f"🔍 Checking for existing DAILY report...")
                    
                    # ✅ Only check for DAILY reports (custom reports don't block daily generation)
                    existing_report = DailyDeviceReport.objects.filter(
                        tenant=request.tenant,
                        department=department,
                        device=device,
                        report_date=yesterday,
                        report_type='daily'
                    ).first()
                    
                    if existing_report:
                        print(f"   ⏭️  DAILY report already exists (ID: {existing_report.id}) - Skipping")
                        skipped_count += 1
                        results.append({
                            'device': device.display_name,
                            'status': 'skipped',
                            'message': 'Daily report already exists'
                        })
                        continue
                    
                    print(f"   ✅ No existing daily report - proceeding with generation")
                    
                    generation_start = time.time()
                    
                    report = generate_device_daily_report(
                        device=device,
                        report_date=yesterday,
                        department=department,
                        generated_by=membership,
                        tenant=request.tenant
                    )
                    
                    generation_time = time.time() - generation_start
                    
                    print(f"\n✅ SUCCESS for {device.display_name}!")
                    print(f"   • Report ID: {report.id}")
                    print(f"   • Report Type: {report.report_type}")
                    print(f"   • Filename: {report.csv_file.name}")
                    print(f"   • File Size: {report.file_size_mb} MB")
                    print(f"   • Generation Time: {generation_time:.2f}s")
                    
                    success_count += 1
                    results.append({
                        'device': device.display_name,
                        'status': 'success',
                        'report_id': report.id,
                        'generation_time': generation_time
                    })
                    
                except Exception as e:
                    print(f"\n❌ FAILED for {device.display_name}: {str(e)}")
                    traceback.print_exc()
                    
                    failed_count += 1
                    results.append({
                        'device': device.display_name,
                        'status': 'failed',
                        'error': str(e)
                    })
            
            print(f"\n{'='*100}")
            print(f"📊 BATCH GENERATION COMPLETE")
            print(f"{'='*100}")
            print(f"✅ Successful: {success_count}")
            print(f"⏭️  Skipped: {skipped_count}")
            print(f"❌ Failed: {failed_count}")
            print(f"{'='*100}\n")
            
            if success_count > 0:
                messages.success(request, f"✅ Successfully generated {success_count} daily report(s).")
            if skipped_count > 0:
                messages.info(request, f"⏭️  Skipped {skipped_count} device(s) - daily reports already exist.")
            if failed_count > 0:
                messages.error(request, f"❌ Failed to generate {failed_count} report(s). Check logs for details.")
            
            return redirect('departmentadmin:reports')
        
        # ===================================
        # ACTION 2: Generate Custom Date/Time Range Report
        # ===================================
        elif action == 'generate_custom':
            print(f"\n{'='*100}")
            print(f"🔄 CUSTOM REPORT GENERATION")
            print(f"{'='*100}\n")
            
            try:
                device_id = request.POST.get('device_id')
                start_date = request.POST.get('start_date')
                start_time = request.POST.get('start_time', '00:00')
                end_date = request.POST.get('end_date')
                end_time = request.POST.get('end_time', '23:59')
                
                print(f"📥 Form Data:")
                print(f"   Device ID: {device_id}")
                print(f"   Start: {start_date} {start_time}")
                print(f"   End: {end_date} {end_time}")
                
                if not all([device_id, start_date, end_date]):
                    print(f"❌ Validation failed: Missing required fields")
                    messages.error(request, "Please fill in all required fields.")
                    return redirect('departmentadmin:reports')
                
                device = Device.objects.get(
                    id=device_id,
                    departments=department,
                    is_active=True
                )
                print(f"✅ Device found: {device.display_name}")
                
                start_datetime_str = f"{start_date} {start_time}"
                end_datetime_str = f"{end_date} {end_time}"
                
                start_datetime = datetime.strptime(start_datetime_str, '%Y-%m-%d %H:%M')
                end_datetime = datetime.strptime(end_datetime_str, '%Y-%m-%d %H:%M')
                
                print(f"📅 Parsed datetime range:")
                print(f"   Start: {start_datetime}")
                print(f"   End: {end_datetime}")
                
                if start_datetime >= end_datetime:
                    print(f"❌ Validation failed: Start date must be before end date")
                    messages.error(request, "Start date/time must be before end date/time.")
                    return redirect('departmentadmin:reports')
                
                print(f"\n🚀 Calling generate_custom_device_report()...")
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
                
                print(f"\n✅ CUSTOM REPORT SUCCESS!")
                print(f"   • Report ID: {report.id}")
                print(f"   • Report Type: {report.report_type}")
                print(f"   • Generation Time: {generation_time:.2f}s")
                print(f"{'='*100}\n")
                
                messages.success(
                    request, 
                    f"✅ Custom report generated successfully! ({generation_time:.1f}s)"
                )
                
                return redirect('departmentadmin:reports')
                
            except Device.DoesNotExist:
                print(f"❌ Device not found or access denied")
                messages.error(request, "Device not found or you don't have access to it.")
                return redirect('departmentadmin:reports')
                
            except ValueError as e:
                print(f"❌ Invalid date/time format: {e}")
                messages.error(request, "Invalid date/time format. Please check your inputs.")
                return redirect('departmentadmin:reports')
                
            except Exception as e:
                print(f"❌ Error generating custom report: {e}")
                traceback.print_exc()
                messages.error(request, f"Error generating custom report: {str(e)}")
                return redirect('departmentadmin:reports')
        
        # ===================================
        # ACTION 3: Download Report
        # ===================================
        elif action == 'download':
            report_id = request.POST.get('report_id')
            print(f"📥 Download request for report ID: {report_id}")
            
            try:
                report = DailyDeviceReport.objects.get(
                    id=report_id,
                    tenant=request.tenant,
                    department=department
                )
                
                print(f"✅ Report found: {report.csv_file.name}")
                print(f"   • Report Type: {report.report_type}")
                
                if not report.csv_file:
                    print(f"❌ No file attached to report")
                    messages.error(request, "Report file not found.")
                    return redirect('departmentadmin:reports')
                
                response = HttpResponse(
                    report.csv_file.read(),
                    content_type='text/csv'
                )
                
                filename = os.path.basename(report.csv_file.name)
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                
                print(f"✅ Serving file: {filename}")
                return response
                
            except DailyDeviceReport.DoesNotExist:
                print(f"❌ Report not found")
                messages.error(request, "Report not found.")
                return redirect('departmentadmin:reports')
            except Exception as e:
                print(f"❌ Download error: {e}")
                messages.error(request, f"Error downloading report: {str(e)}")
                return redirect('departmentadmin:reports')
        
        # ===================================
        # ACTION 4: Delete Report
        # ===================================
        elif action == 'delete':
            report_id = request.POST.get('report_id')
            print(f"🗑️  Delete request for report ID: {report_id}")
            
            try:
                report = DailyDeviceReport.objects.get(
                    id=report_id,
                    tenant=request.tenant,
                    department=department
                )
                
                filename = os.path.basename(report.csv_file.name) if report.csv_file else "Unknown"
                report_type = report.report_type
                print(f"✅ Report found: {filename}")
                print(f"   • Report Type: {report_type}")
                
                if report.csv_file:
                    try:
                        report.csv_file.delete(save=False)
                        print(f"   ✅ File deleted from storage")
                    except Exception as e:
                        print(f"   ⚠️  File deletion warning: {e}")
                
                report.delete()
                print(f"✅ Report deleted successfully")
                
                messages.success(request, f"✅ {report_type.title()} report '{filename}' deleted successfully.")
                return redirect('departmentadmin:reports')
                
            except DailyDeviceReport.DoesNotExist:
                print(f"❌ Report not found")
                messages.error(request, "Report not found.")
                return redirect('departmentadmin:reports')
            except Exception as e:
                print(f"❌ Delete error: {e}")
                messages.error(request, f"Error deleting report: {str(e)}")
                return redirect('departmentadmin:reports')
    
    # ===================================
    # GET REQUEST - Display Reports Page
    # ===================================
    print(f"\n{'='*100}")
    print(f"📄 GET REQUEST - Loading reports page")
    print(f"{'='*100}\n")
    
    # ===================================
    # GET FILTER PARAMETERS (Alerts-style)
    # ===================================
    filter_type = request.GET.get('type', 'all')  # all, daily, custom
    filter_device = request.GET.get('device', '')
    filter_date_from = request.GET.get('date_from', '')
    filter_date_to = request.GET.get('date_to', '')
    page_number = request.GET.get('page', 1)
    
    print(f"📋 Filter Parameters:")
    print(f"   • Type: {filter_type}")
    print(f"   • Device: {filter_device}")
    print(f"   • Date From: {filter_date_from}")
    print(f"   • Date To: {filter_date_to}")
    print(f"   • Page: {page_number}")
    
    # ===================================
    # FETCH DEVICES
    # ===================================
    print(f"\n🔍 Fetching devices for department: {department.name}")
    devices = Device.objects.filter(
        departments=department,
        is_active=True
    ).order_by('display_name')
    
    total_devices = devices.count()
    print(f"   ✅ Found {total_devices} active devices")
    
    # ===================================
    # BUILD BASE QUERYSET
    # ===================================
    # ✅ KEY FIX: No date restriction - fetch ALL reports
    reports_queryset = DailyDeviceReport.objects.filter(
        tenant=request.tenant,
        department=department
    ).select_related('device', 'generated_by', 'generated_by__user')
    
    print(f"\n🔍 Base queryset: {reports_queryset.count()} total reports")
    
    # ===================================
    # APPLY FILTERS
    # ===================================
    
    # Filter by report type
    if filter_type == 'daily':
        reports_queryset = reports_queryset.filter(report_type='daily')
        print(f"   ✅ Filtered by type=daily: {reports_queryset.count()} reports")
    elif filter_type == 'custom':
        reports_queryset = reports_queryset.filter(report_type='custom')
        print(f"   ✅ Filtered by type=custom: {reports_queryset.count()} reports")
    
    # Filter by device
    if filter_device:
        try:
            reports_queryset = reports_queryset.filter(device_id=int(filter_device))
            print(f"   ✅ Filtered by device={filter_device}: {reports_queryset.count()} reports")
        except ValueError:
            pass
    
    # Filter by date range
    if filter_date_from:
        try:
            date_from = datetime.strptime(filter_date_from, '%Y-%m-%d').date()
            reports_queryset = reports_queryset.filter(report_date__gte=date_from)
            print(f"   ✅ Filtered by date_from={date_from}: {reports_queryset.count()} reports")
        except ValueError:
            pass
    
    if filter_date_to:
        try:
            date_to = datetime.strptime(filter_date_to, '%Y-%m-%d').date()
            reports_queryset = reports_queryset.filter(report_date__lte=date_to)
            print(f"   ✅ Filtered by date_to={date_to}: {reports_queryset.count()} reports")
        except ValueError:
            pass
    
    # ===================================
    # ORDER AND PAGINATE
    # ===================================
    reports_queryset = reports_queryset.order_by('-created_at', '-report_date')
    
    # Pagination (20 per page like alerts)
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    
    paginator = Paginator(reports_queryset, 20)  # 20 reports per page
    
    try:
        reports_page = paginator.page(page_number)
    except PageNotAnInteger:
        reports_page = paginator.page(1)
    except EmptyPage:
        reports_page = paginator.page(paginator.num_pages)
    
    print(f"\n📊 Pagination:")
    print(f"   • Total reports: {paginator.count}")
    print(f"   • Total pages: {paginator.num_pages}")
    print(f"   • Current page: {reports_page.number}")
    print(f"   • Reports on page: {len(reports_page)}")
    
    # ===================================
    # CALCULATE STATISTICS
    # ===================================
    
    # Total counts (all time)
    total_reports = DailyDeviceReport.objects.filter(
        tenant=request.tenant,
        department=department
    ).count()
    
    daily_reports_count = DailyDeviceReport.objects.filter(
        tenant=request.tenant,
        department=department,
        report_type='daily'
    ).count()
    
    custom_reports_count = DailyDeviceReport.objects.filter(
        tenant=request.tenant,
        department=department,
        report_type='custom'
    ).count()
    
    # Yesterday's daily reports (for pending calculation)
    yesterday = timezone.now().date() - timedelta(days=1)
    
    devices_with_yesterday_report = DailyDeviceReport.objects.filter(
        tenant=request.tenant,
        department=department,
        report_date=yesterday,
        report_type='daily'
    ).values_list('device_id', flat=True)
    
    devices_with_yesterday_count = len(set(devices_with_yesterday_report))
    devices_without_yesterday_report = total_devices - devices_with_yesterday_count
    
    # Filtered count
    filtered_count = paginator.count
    
    print(f"\n📊 Statistics:")
    print(f"   • Total Devices: {total_devices}")
    print(f"   • Total Reports (all time): {total_reports}")
    print(f"     - Daily: {daily_reports_count}")
    print(f"     - Custom: {custom_reports_count}")
    print(f"   • Yesterday Daily Reports: {devices_with_yesterday_count}")
    print(f"   • Devices Pending: {devices_without_yesterday_report}")
    print(f"   • Filtered Results: {filtered_count}")
    
    # ===================================
    # BUILD CONTEXT
    # ===================================
    context = {
        # Department Switcher
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
        'total_reports': total_reports,
        'daily_reports_count': daily_reports_count,
        'custom_reports_count': custom_reports_count,
        'filtered_count': filtered_count,
        
        # Yesterday stats
        'yesterday': yesterday,
        'devices_with_yesterday_report': devices_with_yesterday_count,
        'devices_without_yesterday_report': devices_without_yesterday_report,
        
        # Current filters (for form persistence)
        'filter_type': filter_type,
        'filter_device': filter_device,
        'filter_date_from': filter_date_from,
        'filter_date_to': filter_date_to,
        
        'page_title': 'Reports',
    }
    
    print(f"\n✅ Rendering template with context")
    print(f"{'='*100}\n")
    
    return render(request, 'departmentadmin/reports.html', context)