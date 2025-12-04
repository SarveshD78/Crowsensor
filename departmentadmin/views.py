# departmentadmin/views.py - UPDATED WITH AUTO-ASSIGNMENT

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import logout
from django.db import transaction
from accounts.decorators import require_department_admin
from companyadmin.models import Department, DepartmentMembership, Device
from accounts.models import User


# =============================================================================
# AUTHENTICATION
# =============================================================================

@require_department_admin
def logout_view(request):
    """Logout department admin"""
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
    Department Admin Dashboard
    Shows only departments assigned to this user
    """
    
    # Get user's assigned departments
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
        'user_departments': user_departments,
        'total_departments': total_departments,
        'total_users': total_users,
        'user_role': request.user.get_role_display(),
        'page_title': 'Department Admin Dashboard',
    }
    
    return render(request, 'departmentadmin/dashboard.html', context)


# =============================================================================
# USER MANAGEMENT - WITH AUTO-ASSIGNMENT
# =============================================================================

@require_department_admin
def users_view(request):
    """
    Department Admin User Management
    Can create: user (read-only role)
    Users are automatically assigned to all departments the admin manages
    """
    
    # Get departments this admin manages
    user_departments = DepartmentMembership.objects.filter(
        user=request.user,
        is_active=True
    ).select_related('department').filter(
        department__is_active=True
    )
    
    dept_ids = [m.department.id for m in user_departments]
    
    # Get ALL users with 'user' role assigned to these departments
    all_users = User.objects.filter(
        is_active=True,
        role='user',
        department_memberships__department_id__in=dept_ids,
        department_memberships__is_active=True
    ).prefetch_related(
        'department_memberships__department'
    ).distinct().order_by('-created_at')
    
    # Get departments for display
    departments = [m.department for m in user_departments]
    
    # Stats
    total_users = all_users.count()
    total_departments = len(departments)
    
    # ==========================================
    # POST HANDLING
    # ==========================================
    if request.method == 'POST':
        
        # ADD USER - AUTO-ASSIGN TO ALL ADMIN'S DEPARTMENTS
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
                
                # ✅ CREATE USER AND AUTO-ASSIGN TO ALL DEPARTMENTS
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
                    
                    # Auto-assign to ALL departments managed by this admin
                    for dept_membership in user_departments:
                        DepartmentMembership.objects.create(
                            user=user,
                            department=dept_membership.department,
                            is_active=True
                        )
                
                messages.success(
                    request,
                    f'✅ User "{user.username}" created and assigned to {total_departments} department(s)! '
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
                
                # Get user
                user = get_object_or_404(
                    User, 
                    id=user_id, 
                    is_active=True,
                    role='user'
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
                messages.error(request, '⛔ User not found.')
            except Exception as e:
                messages.error(request, f'⛔ Error updating user: {str(e)}')
            
            return redirect('departmentadmin:users')
        
        # DELETE USER
        elif 'delete_user' in request.POST:
            try:
                user_id = request.POST.get('user_id')
                user = get_object_or_404(
                    User, 
                    id=user_id, 
                    is_active=True,
                    role='user'
                )
                
                username = user.username
                
                # Soft delete
                user.is_active = False
                user.save()
                
                messages.success(request, f'✅ User "{username}" deleted successfully!')
                
            except User.DoesNotExist:
                messages.error(request, '⛔ User not found.')
            except Exception as e:
                messages.error(request, f'⛔ Error deleting user: {str(e)}')
            
            return redirect('departmentadmin:users')
    
    # Prepare user data with department info
    users_data = []
    for user in all_users:
        user_depts = user.department_memberships.filter(
            is_active=True,
            department_id__in=dept_ids
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
        })
    
    context = {
        'users': users_data,
        'departments': departments,
        'total_users': total_users,
        'total_departments': total_departments,
        'page_title': 'Manage Users',
        'user_role': request.user.get_role_display(),
    }
    
    return render(request, 'departmentadmin/users.html', context)
@require_department_admin
def devices_view(request):

    # Get user's department
    try:
        membership = DepartmentMembership.objects.select_related('department').get(
            user=request.user,
            is_active=True,
            department__is_active=True
        )
        dept = membership.department
    except DepartmentMembership.DoesNotExist:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect('departmentadmin:dashboard')
    
    # Get ALL devices assigned to this department (active + inactive)
    devices = Device.objects.filter(
        departments=dept
    ).prefetch_related('sensors', 'departments').order_by('measurement_name', 'device_id')
    
    # Get InfluxDB config (read-only)
    from companyadmin.models import AssetConfig
    config = AssetConfig.get_active_config()
    
    # Add computed data to each device
    devices_list = []
    for device in devices:
        # Add computed data
        device.total_sensors_only = device.sensors.filter(category='sensor').count()
        device.sensor_breakdown = {
            'sensors': device.sensors.filter(category='sensor').count(),
            'slaves': device.sensors.filter(category='slave').count(),
            'info': device.sensors.filter(category='info').count(),
        }
        device.device_column = device.metadata.get('device_column', 'N/A')
        device.auto_discovered = device.metadata.get('auto_discovered', False)
        
        devices_list.append(device)
    
    context = {
        'devices': devices_list,
        'total_devices': devices.count(),
        'active_devices': devices.filter(is_active=True).count(),
        'inactive_devices': devices.filter(is_active=False).count(),
        'has_config': config is not None,
        'config': config,
        'department': dept,
        'page_title': 'My Devices',
    }
    
    return render(request, 'departmentadmin/devices.html', context)

@require_department_admin
def device_sensors_view(request, device_id):
    """
    View all sensors for a specific device with METADATA (READ-ONLY)
    Returns JSON for modal table display
    """
    from django.http import JsonResponse
    from companyadmin.models import Sensor
    
    try:
        # Get user's department
        membership = DepartmentMembership.objects.select_related('department').get(
            user=request.user,
            is_active=True,
            department__is_active=True
        )
        dept = membership.department
        
        # Get device - MUST be assigned to this department
        device = Device.objects.filter(
            id=device_id,
            departments=dept,
            is_active=True
        ).first()
        
        if not device:
            return JsonResponse({'success': False, 'message': 'Device not found or not accessible'}, status=404)
        
        sensors = device.sensors.filter(category='sensor').select_related('metadata_config').order_by('field_name')
        
        sensor_list = []
        for sensor in sensors:
            # Get metadata if exists
            if hasattr(sensor, 'metadata_config'):
                metadata = sensor.metadata_config
                sensor_data = {
                    'id': sensor.id,
                    'field_name': sensor.field_name,
                    'display_name': metadata.display_name or sensor.field_name,
                    'field_type': sensor.field_type,
                    'category': sensor.category,
                    'unit': metadata.unit,
                    'upper_limit': metadata.upper_limit,
                    'lower_limit': metadata.lower_limit,
                    'central_line': metadata.central_line,
                    'show_time_series': metadata.show_time_series,
                    'show_latest_value': metadata.show_latest_value,
                    'show_digital': metadata.show_digital,
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
    
    except DepartmentMembership.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Department not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse

from accounts.decorators import require_department_admin

from companyadmin.models import Device, AssetConfig,DepartmentMembership
from .graph_func import fetch_sensor_data_from_influx, INTERVAL_LOOKUP


# ==========================================
# VIEW 1: Graph Page (Returns HTML)
# ==========================================
@require_department_admin
def device_graphs_page_view(request, device_id):
    """
    Display full page with graphs for a device
    This renders the HTML template with empty containers
    JavaScript will then call device_graphs_view to fetch data
    """
    
    try:
        # Get user's department
        membership = DepartmentMembership.objects.select_related('department').get(
            user=request.user,
            is_active=True,
            department__is_active=True
        )
        dept = membership.department
        
        # Get device - MUST be assigned to this department
        device = Device.objects.filter(
            id=device_id,
            departments=dept,
            is_active=True
        ).first()
        
        if not device:
            messages.error(request, '⛔ Device not found or not assigned to your department')
            return redirect('departmentadmin:devices')
        
        context = {
            'device': device,
            'department': dept,
            'page_title': f'Graphs - {device.display_name}',
        }
        
        return render(request, 'departmentadmin/device_graphs.html', context)
    
    except DepartmentMembership.DoesNotExist:
        messages.error(request, '⛔ You are not assigned to any department')
        return redirect('departmentadmin:dashboard')


# ==========================================
# VIEW 2: Graph Data API (Returns JSON)
# ==========================================
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
        membership = DepartmentMembership.objects.select_related('department').get(
            user=request.user,
            is_active=True,
            department__is_active=True
        )
        dept = membership.department
        
        print(f"Department: {dept.name}")
        
        # Get device - MUST be assigned to this department
        device = Device.objects.filter(
            id=device_id,
            departments=dept,
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
        print(f"   Metadata: {device.metadata}")
        
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
        
        for sensor in sensors:
            print(f"   - {sensor.field_name}: {sensor.display_name}")
            # METADATA: Log metadata configuration
            if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
                meta = sensor.metadata_config
                print(f"     Metadata: TimeSeries={meta.show_time_series}, Latest={meta.show_latest_value}, Digital={meta.show_digital}")
            else:
                print(f"     Metadata: NOT CONFIGURED (will show time series only)")
        
        # Get InfluxDB config - KEEP YOUR ORIGINAL WORKING CODE
        config = AssetConfig.get_active_config()
        
        if not config or not config.is_connected:
            print(f"❌ InfluxDB not configured")
            return JsonResponse({
                'success': False,
                'message': 'InfluxDB not configured'
            }, status=500)
        
        print(f"✅ InfluxDB config found")
        print(f"   URL: {config.base_api}")
        print(f"   DB: {config.db_name}")
        
        # Fetch data from InfluxDB
        print(f"\n🔄 Calling fetch_sensor_data_from_influx...")
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
    
    except DepartmentMembership.DoesNotExist:
        print(f"❌ User not assigned to any department")
        return JsonResponse({
            'success': False,
            'message': 'You are not assigned to any department. Contact your Company Admin.'
        }, status=403)
    
    except Exception as e:
        print(f"\n❌ EXCEPTION in device_graphs_view")
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return JsonResponse({
            'success': False,
            'message': f'An error occurred: {str(e)}'
        }, status=500)