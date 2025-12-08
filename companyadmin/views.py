# companyadmin/views.py - FIXED: ONE DEPT PER ADMIN + NEW ROLES

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import logout
from django.db import transaction
from django.db.models import Count, Q
from accounts.decorators import require_company_admin
from accounts.models import User
from companyadmin.forms import AssetConfigEditForm, AssetConfigForm
from .models import AssetConfig, Department, DepartmentMembership, Device
from requests.auth import HTTPBasicAuth
import requests
from django.utils import timezone
from companyadmin.models import Sensor,Device,AssetConfig
# =============================================================================
# AUTHENTICATION
# =============================================================================

@require_company_admin
def company_logout_view(request):
    """Logout company admin"""
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
    Company Admin Dashboard with REAL data only
    """
    from .models import Device, Sensor, SensorMetadata, AssetConfig
    from django.utils import timezone
    from datetime import timedelta
    
    # Get stats (schema-scoped automatically)
    total_users = User.objects.filter(is_active=True).exclude(role='company_admin').count()
    total_dept_admins = User.objects.filter(is_active=True, role='department_admin').count()
    total_read_only_users = User.objects.filter(is_active=True, role='user').count()
    total_departments = Department.objects.filter(is_active=True).count()
    
    # ✅ DEVICE & SENSOR STATS
    total_devices = Device.objects.count()
    total_sensors = Sensor.objects.filter(category='sensor').count()
    
    # ✅ Calculate configured sensors (has metadata with display_name AND unit)
    configured_sensors = SensorMetadata.objects.filter(
        display_name__isnull=False,
        unit__isnull=False
    ).exclude(display_name='').exclude(unit='').count()
    
    # ✅ INFLUXDB STATUS
    influx_config = AssetConfig.get_active_config()
    influx_status = 'offline'
    influx_last_checked = None
    
    if influx_config:
        # Test connection
        try:
            from .utils import get_influx_client
            client = get_influx_client(influx_config)
            # Try a simple query to verify connection
            client.query("SHOW DATABASES")
            influx_status = 'online'
            influx_last_checked = timezone.now()
        except Exception as e:
            influx_status = 'offline'
            influx_last_checked = timezone.now()
    
    # ✅ RECENT ACTIVITY (last 10 activities from last 7 days)
    recent_activities = []
    seven_days_ago = timezone.now() - timedelta(days=7)
    
    # Get recent users (last 7 days)
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
    
    # Get recent devices (last 7 days)
    recent_devices = Device.objects.filter(
        created_at__gte=seven_days_ago
    ).order_by('-created_at')[:5]
    
    for device in recent_devices:
        recent_activities.append({
            'type': 'device_added',
            'icon': 'fa-microchip',
            'color': '#d1ecf1',
            'icon_color': '#0c5460',
            'title': 'Device configured',
            'description': f'{device.display_name} added to system',
            'time': device.created_at
        })
    
    # Get recent departments (last 7 days)
    recent_departments = Department.objects.filter(
        created_at__gte=seven_days_ago
    ).order_by('-created_at')[:5]
    
    for dept in recent_departments:
        recent_activities.append({
            'type': 'department_added',
            'icon': 'fa-building',
            'color': '#fff3cd',
            'icon_color': '#856404',
            'title': 'Department created',
            'description': f'New department "{dept.name}" added',
            'time': dept.created_at
        })
    
    # Get recent metadata updates (last 7 days)
    recent_metadata = SensorMetadata.objects.filter(
        updated_at__gte=seven_days_ago
    ).select_related('sensor', 'sensor__device').order_by('-updated_at')[:5]
    
    for metadata in recent_metadata:
        recent_activities.append({
            'type': 'metadata_updated',
            'icon': 'fa-sliders-h',
            'color': '#e7f3ff',
            'icon_color': '#004085',
            'title': 'Sensor metadata updated',
            'description': f'{metadata.sensor.field_name} on {metadata.sensor.device.display_name}',
            'time': metadata.updated_at
        })
    
    # ✅ Sort all activities by time and take top 10
    recent_activities.sort(key=lambda x: x['time'], reverse=True)
    recent_activities = recent_activities[:10]
    
    context = {
        'total_users': total_users,
        'total_dept_admins': total_dept_admins,
        'total_read_only_users': total_read_only_users,
        'total_departments': total_departments,
        'total_devices': total_devices,
        'total_sensors': total_sensors,
        'configured_sensors': configured_sensors,
        'influx_status': influx_status,
        'influx_last_checked': influx_last_checked,
        'influx_config': influx_config,
        'recent_activities': recent_activities,
        'last_login': request.user.last_login,
        'page_title': 'Company Dashboard',
    }
    
    return render(request, 'companyadmin/dashboard.html', context)

# =============================================================================
# DEPARTMENT MANAGEMENT
# =============================================================================

@require_company_admin
def departments_view(request):
    """
    Department CRUD - List, Add, Edit, Delete
    
    RULES:
    - One Department → Many Department Admins (allowed)
    - One Department → Many Users (allowed)
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
        user_count=Count(  # ← Changed: Count 'user' role only
            'user_memberships',
            filter=Q(
                user_memberships__user__role='user',
                user_memberships__user__is_active=True,
                user_memberships__is_active=True
            ),
            distinct=True
        )
    ).order_by('name')
    
    # Stats
    total_departments = departments.count()
    total_users = User.objects.filter(is_active=True).exclude(role='company_admin').count()
    
    # ==========================================
    # POST HANDLING
    # ==========================================
    if request.method == 'POST':
        
        # ADD DEPARTMENT
        if 'add_department' in request.POST:
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
                messages.error(request, f'⛔ Error creating department: {str(e)}')
            
            return redirect('companyadmin:departments')
        
        # EDIT DEPARTMENT
        elif 'edit_department' in request.POST:
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
                messages.error(request, f'⛔ Error updating department: {str(e)}')
            
            return redirect('companyadmin:departments')
        
        # DELETE DEPARTMENT
        elif 'delete_department' in request.POST:
            try:
                dept_id = request.POST.get('department_id')
                department = get_object_or_404(Department, id=dept_id, is_active=True)
                
                # Check if has users
                user_count = department.user_memberships.filter(is_active=True).count()
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
                messages.error(request, f'⛔ Error deleting department: {str(e)}')
            
            return redirect('companyadmin:departments')
    
    context = {
        'departments': departments,
        'total_departments': total_departments,
        'total_users': total_users,
        'page_title': 'Manage Departments',
    }
    
    return render(request, 'companyadmin/departments.html', context)


# =============================================================================
# USER MANAGEMENT - DEPARTMENT ADMINS ONLY
# =============================================================================

@require_company_admin
def users_view(request):
    """
    User CRUD - Create ONLY department_admin users
    
    CRITICAL RULES:
    - Company admin can ONLY create department_admin role
    - Cannot create 'user' role (department admin does that)
    - Cannot create another company_admin (only 1 per tenant)
    - ✅ NEW: One Department Admin → ONE Department ONLY
    """
    
    # Get all department admin users (exclude company_admin)
    users = User.objects.filter(
        is_active=True,
        role='department_admin'  # ONLY show department admins
    ).prefetch_related(
        'department_memberships__department'
    ).order_by('-created_at')
    
    # Get departments for assignment dropdown
    departments = Department.objects.filter(is_active=True).order_by('name')
    
    # Stats
    total_dept_admins = users.count()
    total_departments = departments.count()
    
    # ==========================================
    # POST HANDLING
    # ==========================================
    if request.method == 'POST':
        
        # ADD USER (DEPARTMENT ADMIN ONLY)
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
                    return redirect('companyadmin:users')
                
                # Check duplicates
                if User.objects.filter(username__iexact=username).exists():
                    messages.error(request, f'⛔ Username "{username}" already exists.')
                    return redirect('companyadmin:users')
                
                if User.objects.filter(email__iexact=email).exists():
                    messages.error(request, f'⛔ Email "{email}" already exists.')
                    return redirect('companyadmin:users')
                
                # CRITICAL: Force role to department_admin
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password='User@2025',  # Default password
                    first_name=first_name,
                    last_name=last_name,
                    role='department_admin',  # FORCED - no choice!
                    phone=phone,
                    is_active=True
                )
                
                messages.success(
                    request,
                    f'✅ Department Admin "{user.username}" created successfully! '
                    f'Default password: User@2025. '
                    f'⚠️ Please assign them to a department.'
                )
                
            except Exception as e:
                messages.error(request, f'⛔ Error creating user: {str(e)}')
            
            return redirect('companyadmin:users')
        
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
                    return redirect('companyadmin:users')
                
                # Get user
                user = get_object_or_404(User, id=user_id, is_active=True, role='department_admin')
                
                # Check duplicates (excluding current user)
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
                # Role stays department_admin - cannot be changed
                user.save()
                
                messages.success(request, f'✅ User "{user.username}" updated successfully!')
                
            except User.DoesNotExist:
                messages.error(request, '⛔ User not found.')
            except Exception as e:
                messages.error(request, f'⛔ Error updating user: {str(e)}')
            
            return redirect('companyadmin:users')
        
        # DELETE USER
        elif 'delete_user' in request.POST:
            try:
                user_id = request.POST.get('user_id')
                user = get_object_or_404(User, id=user_id, is_active=True, role='department_admin')
                
                username = user.username
                
                # Soft delete
                user.is_active = False
                user.save()
                
                messages.success(request, f'✅ User "{username}" deleted successfully!')
                
            except User.DoesNotExist:
                messages.error(request, '⛔ User not found.')
            except Exception as e:
                messages.error(request, f'⛔ Error deleting user: {str(e)}')
            
            return redirect('companyadmin:users')
        
        # ✅ FIXED: ASSIGN ONE DEPARTMENT TO USER
        elif 'assign_department' in request.POST:  # ← Changed from 'assign_departments'
            try:
                user_id = request.POST.get('user_id')
                department_id = request.POST.get('department_id')  # ← Single department only!
                
                user = get_object_or_404(User, id=user_id, is_active=True, role='department_admin')
                
                # ✅ CRITICAL: Remove ALL old assignments (enforce ONE department only)
                DepartmentMembership.objects.filter(user=user).update(is_active=False)
                
                # Assign to new department
                if department_id:
                    department = get_object_or_404(Department, id=department_id, is_active=True)
                    
                    with transaction.atomic():
                        # Check if membership exists
                        membership, created = DepartmentMembership.objects.get_or_create(
                            user=user,
                            department=department,
                            defaults={'is_active': True}
                        )
                        
                        if not created:
                            membership.is_active = True
                            membership.save()
                    
                    messages.success(
                        request,
                        f'✅ Department Admin "{user.username}" assigned to "{department.name}"!'
                    )
                else:
                    messages.info(
                        request,
                        f'ℹ️ Department assignment cleared for "{user.username}". '
                        f'They won\'t be able to login until assigned to a department.'
                    )
                
            except User.DoesNotExist:
                messages.error(request, '⛔ User not found.')
            except Department.DoesNotExist:
                messages.error(request, '⛔ Department not found.')
            except Exception as e:
                messages.error(request, f'⛔ Error assigning department: {str(e)}')
            
            return redirect('companyadmin:users')
    
    # Prepare user data with department info
    users_data = []
    for user in users:
        # ✅ Get SINGLE department (should only have one)
        user_dept_membership = user.department_memberships.filter(
            is_active=True
        ).select_related('department').first()
        
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
            'has_department': user_dept_membership is not None,
            'department': user_dept_membership.department if user_dept_membership else None,
            'department_id': user_dept_membership.department.id if user_dept_membership else None,
        })
    
    context = {
        'users': users_data,
        'departments': departments,
        'total_dept_admins': total_dept_admins,
        'total_departments': total_departments,
        'page_title': 'Manage Department Admins',
    }
    
    return render(request, 'companyadmin/users.html', context)



# companyadmin/views.py - SIMPLIFIED SINGLE VIEW

# companyadmin/views.py - INFLUX CONFIG VIEW WITH DEBUG PRINTS

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from accounts.decorators import require_company_admin
from .models import AssetConfig
from .forms import AssetConfigForm, AssetConfigEditForm
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime


def debug_print(message):
    """Print debug message with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] 🔍 DEBUG: {message}")
    import sys
    sys.stdout.flush()


@require_company_admin
def influx_config_view(request):
    """
    Single view handles ALL InfluxDB configuration operations:
    - View current config
    - Create new config
    - Edit existing config
    - Delete config
    - Test connection
    """
    
    debug_print("=" * 80)
    debug_print("influx_config_view() called")
    debug_print(f"User: {request.user.username}")
    debug_print(f"Method: {request.method}")
    debug_print(f"Path: {request.path}")
    
    # Get existing config (should be only one active)
    config = AssetConfig.get_active_config()
    debug_print(f"Existing config: {config}")
    
    if config:
        debug_print(f"Config ID: {config.id}")
        debug_print(f"DB Name: {config.db_name}")
        debug_print(f"Base API: {config.base_api}")
        debug_print(f"Username: {config.api_username}")
        debug_print(f"Is Active: {config.is_active}")
        debug_print(f"Is Connected: {config.is_connected}")
    else:
        debug_print("No active config found")
    
    # ==========================================
    # POST HANDLING - All actions in one view
    # ==========================================
    if request.method == 'POST':
        debug_print("POST request detected")
        debug_print(f"POST keys: {list(request.POST.keys())}")
        
        # CREATE CONFIG
        if 'create_config' in request.POST:
            debug_print("CREATE CONFIG action triggered")
            
            # Check if active config already exists
            if AssetConfig.has_active_config():
                debug_print("Active config already exists - blocking creation")
                messages.warning(
                    request,
                    '⚠️ Active InfluxDB configuration already exists. '
                    'Please edit or delete the existing configuration first.'
                )
                return redirect('companyadmin:influx_config')
            
            debug_print("No active config - proceeding with creation")
            debug_print(f"POST data - db_name: {request.POST.get('db_name')}")
            debug_print(f"POST data - base_api: {request.POST.get('base_api')}")
            debug_print(f"POST data - api_username: {request.POST.get('api_username')}")
            debug_print(f"POST data - is_active: {request.POST.get('is_active')}")
            
            form = AssetConfigForm(request.POST)
            debug_print(f"Form created, is_valid: {form.is_valid()}")
            
            if form.is_valid():
                debug_print("Form validation passed")
                try:
                    config = form.save()
                    debug_print(f"Config saved successfully! ID: {config.id}")
                    debug_print(f"Saved config - DB: {config.db_name}, API: {config.base_api}")
                    
                    messages.success(
                        request,
                        f'✅ InfluxDB configuration created! Database: {config.db_name}'
                    )
                except Exception as e:
                    debug_print(f"ERROR saving config: {str(e)}")
                    import traceback
                    debug_print(f"Traceback: {traceback.format_exc()}")
                    messages.error(request, f'⛔ Error creating configuration: {str(e)}')
            else:
                debug_print("Form validation FAILED")
                debug_print(f"Form errors: {form.errors}")
                messages.error(request, '⛔ Please correct the errors in the form.')
            
            debug_print("Redirecting to influx_config")
            return redirect('companyadmin:influx_config')
        
        # EDIT CONFIG
        elif 'edit_config' in request.POST:
            debug_print("EDIT CONFIG action triggered")
            
            config_id = request.POST.get('config_id')
            debug_print(f"Config ID to edit: {config_id}")
            
            config = get_object_or_404(AssetConfig, id=config_id)
            debug_print(f"Found config: {config.db_name}")
            
            debug_print(f"POST data - db_name: {request.POST.get('db_name')}")
            debug_print(f"POST data - base_api: {request.POST.get('base_api')}")
            debug_print(f"POST data - api_username: {request.POST.get('api_username')}")
            debug_print(f"POST data - api_password: {'***' if request.POST.get('api_password') else '(blank)'}")
            debug_print(f"POST data - is_active: {request.POST.get('is_active')}")
            
            form = AssetConfigEditForm(request.POST, instance=config)
            debug_print(f"Edit form created, is_valid: {form.is_valid()}")
            
            if form.is_valid():
                debug_print("Form validation passed")
                try:
                    updated_config = form.save()
                    debug_print(f"Config updated successfully! ID: {updated_config.id}")
                    debug_print(f"Updated config - DB: {updated_config.db_name}, API: {updated_config.base_api}")
                    
                    messages.success(
                        request,
                        f'✅ Configuration updated! Database: {updated_config.db_name}'
                    )
                except Exception as e:
                    debug_print(f"ERROR updating config: {str(e)}")
                    import traceback
                    debug_print(f"Traceback: {traceback.format_exc()}")
                    messages.error(request, f'⛔ Error updating configuration: {str(e)}')
            else:
                debug_print("Form validation FAILED")
                debug_print(f"Form errors: {form.errors}")
                messages.error(request, '⛔ Please correct the errors in the form.')
            
            debug_print("Redirecting to influx_config")
            return redirect('companyadmin:influx_config')
        
        # DELETE CONFIG (soft delete)
        elif 'delete_config' in request.POST:
            debug_print("DELETE CONFIG action triggered")
            
            config_id = request.POST.get('config_id')
            debug_print(f"Config ID to delete: {config_id}")
            
            config = get_object_or_404(AssetConfig, id=config_id)
            debug_print(f"Found config: {config.db_name}")
            
            try:
                config_name = config.db_name
                debug_print(f"Deactivating config: {config_name}")
                
                config.is_active = False
                config.save()
                
                debug_print(f"Config deactivated successfully: {config_name}")
                
                messages.success(
                    request,
                    f'✅ Configuration "{config_name}" deactivated successfully!'
                )
            except Exception as e:
                debug_print(f"ERROR deactivating config: {str(e)}")
                import traceback
                debug_print(f"Traceback: {traceback.format_exc()}")
                messages.error(request, f'⛔ Error deactivating configuration: {str(e)}')
            
            debug_print("Redirecting to influx_config")
            return redirect('companyadmin:influx_config')
        
        # TEST CONNECTION
        elif 'test_connection' in request.POST:
            debug_print("TEST CONNECTION action triggered")
            
            config_id = request.POST.get('config_id')
            debug_print(f"Config ID to test: {config_id}")
            
            config = get_object_or_404(AssetConfig, id=config_id)
            debug_print(f"Found config: {config.db_name}")
            debug_print(f"Testing connection to: {config.base_api}")
            
            try:
                # Test InfluxDB connection via HTTP request
                url = f"{config.base_api}/ping"
                debug_print(f"Ping URL: {url}")
                debug_print(f"Auth username: {config.api_username}")
                debug_print("Sending GET request...")
                
                response = requests.get(
                    url,
                    auth=HTTPBasicAuth(config.api_username, config.api_password),
                    verify=False, 
                    timeout=5
                )
                
                debug_print(f"Response status code: {response.status_code}")
                debug_print(f"Response headers: {dict(response.headers)}")
                debug_print(f"Response text: {response.text[:200] if response.text else '(empty)'}")
                
                if response.status_code == 204:
                    debug_print("Connection test SUCCESSFUL (HTTP 204)")
                    config.mark_connected()
                    debug_print("Config marked as connected")
                    
                    messages.success(
                        request,
                        f'✅ Connection successful! InfluxDB is reachable at {config.base_api}'
                    )
                else:
                    error_msg = f'HTTP {response.status_code}: {response.text}'
                    debug_print(f"Connection test FAILED: {error_msg}")
                    config.mark_disconnected(error_msg)
                    debug_print("Config marked as disconnected")
                    
                    messages.error(request, f'⛔ Connection failed! {error_msg}')
            
            except requests.exceptions.Timeout:
                error_msg = 'Connection timeout - InfluxDB did not respond within 5 seconds'
                debug_print(f"Connection test TIMEOUT: {error_msg}")
                config.mark_disconnected(error_msg)
                messages.error(request, f'⛔ {error_msg}')
            
            except requests.exceptions.ConnectionError as e:
                error_msg = f'Connection refused - Cannot reach InfluxDB server: {str(e)}'
                debug_print(f"Connection test ERROR: {error_msg}")
                config.mark_disconnected(error_msg)
                messages.error(request, f'⛔ Connection refused - Cannot reach InfluxDB server')
            
            except Exception as e:
                error_msg = f'Unexpected error: {str(e)}'
                debug_print(f"Connection test EXCEPTION: {error_msg}")
                import traceback
                debug_print(f"Traceback: {traceback.format_exc()}")
                config.mark_disconnected(error_msg)
                messages.error(request, f'⛔ {error_msg}')
            
            debug_print("Redirecting to influx_config")
            return redirect('companyadmin:influx_config')
        
        else:
            debug_print("UNKNOWN POST action - no matching button name")
            debug_print(f"POST keys: {list(request.POST.keys())}")
    
    # ==========================================
    # GET - Show config page
    # ==========================================
    
    debug_print("Preparing GET response")
    
    # Prepare forms
    create_form = None
    edit_form = None
    
    if config:
        debug_print("Config exists - preparing EDIT form")
        edit_form = AssetConfigEditForm(instance=config)
        debug_print(f"Edit form fields: {list(edit_form.fields.keys())}")
    else:
        debug_print("No config - preparing CREATE form")
        create_form = AssetConfigForm(initial={'is_active': True})
        debug_print(f"Create form fields: {list(create_form.fields.keys())}")
    
    context = {
        'config': config,
        'has_config': config is not None,
        'create_form': create_form,
        'edit_form': edit_form,
        'page_title': 'InfluxDB Configuration',
    }
    
    debug_print(f"Context prepared - has_config: {context['has_config']}")
    debug_print("Rendering template: companyadmin/influx_config.html")
    debug_print("=" * 80)
    
    return render(request, 'companyadmin/influx_config.html', context)


# companyadmin/views.py - ADD THIS TO EXISTING FILE
# companyadmin/views.py

from django.shortcuts import render, redirect
from django.contrib import messages
from accounts.decorators import require_company_admin
from .models import AssetConfig
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
import json


def debug_print(message):
    """Debug print helper"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] 🔍 DEBUG: {message}")


@require_company_admin
def influx_fetch_measurements_view(request):
    """
    Fetch measurements, device IDs, and sensors from InfluxDB - TEST ONLY
    No model saving, just display results with expandable sensors
    """
    
    debug_print("=" * 80)
    debug_print("influx_fetch_measurements_view called")
    debug_print(f"User: {request.user.username}")
    debug_print(f"Method: {request.method}")
    
    # Get active config
    config = AssetConfig.get_active_config()
    
    if not config:
        messages.error(request, '⛔ No InfluxDB configuration found.')
        return redirect('companyadmin:influx_config')
    
    if not config.is_connected:
        messages.warning(request, '⚠️ InfluxDB connection not tested. Please test connection first.')
        return redirect('companyadmin:influx_config')
    
    measurements_data = []
    
    # Handle FETCH button click
    if request.method == 'POST' and 'fetch_measurements' in request.POST:
        debug_print("FETCH MEASUREMENTS triggered")
        
        try:
            base_url = f"{config.base_api}/query"
            auth = HTTPBasicAuth(config.api_username, config.api_password)
            
            # ============================================
            # STEP 1: Get All Measurements
            # ============================================
            debug_print("Step 1: Fetching measurements...")
            
            measurements_query = 'SHOW MEASUREMENTS'
            response = requests.get(
                base_url,
                params={'db': config.db_name, 'q': measurements_query},

                auth=auth,
                verify=False,
                timeout=10
            )
            
            if response.status_code != 200:
                raise Exception(f"Failed to fetch measurements: {response.text}")
            
            data = response.json()
            
            if 'results' not in data or not data['results'] or 'series' not in data['results'][0]:
                messages.warning(request, '⚠️ No measurements found in InfluxDB.')
                return render(request, 'companyadmin/influx_fetch.html', {
                    'config': config,
                    'measurements_data': measurements_data,
                })
            
            measurements = [row[0] for row in data['results'][0]['series'][0]['values']]
            debug_print(f"Found {len(measurements)} measurements: {measurements}")
            
            # ============================================
            # STEP 2: For Each Measurement, Get Device IDs
            # ============================================
            for measurement_name in measurements:
                debug_print(f"Processing measurement: {measurement_name}")
                
                device_ids = set()
                
                # Try Approach 1: SHOW TAG VALUES (for 'id' as tag)
                try:
                    tag_query = f'SHOW TAG VALUES FROM "{measurement_name}" WITH KEY = "id"'
                    tag_response = requests.get(
                        base_url,
                        params={'db': config.db_name, 'q': tag_query},
                        auth=auth,
                        verify=False,
                        timeout=10
                    )
                    
                    if tag_response.status_code == 200:
                        tag_data = tag_response.json()
                        if 'results' in tag_data and tag_data['results'] and 'series' in tag_data['results'][0]:
                            if tag_data['results'][0]['series']:
                                tag_values = [v[1] for v in tag_data['results'][0]['series'][0]['values']]
                                device_ids.update(tag_values)
                                debug_print(f"  TAG approach found {len(tag_values)} IDs")
                except Exception as e:
                    debug_print(f"  TAG query failed: {e}")
                
                # Try Approach 2: SELECT DISTINCT (for 'id' as field)
                try:
                    field_query = f'SELECT DISTINCT("id") FROM "{measurement_name}" LIMIT 10000'
                    field_response = requests.get(
                        base_url,
                        params={'db': config.db_name, 'q': field_query},
                        auth=auth,
                        timeout=10
                    )
                    
                    if field_response.status_code == 200:
                        field_data = field_response.json()
                        if 'results' in field_data and field_data['results'] and 'series' in field_data['results'][0]:
                            if field_data['results'][0]['series']:
                                field_values = [v[1] for v in field_data['results'][0]['series'][0]['values'] if len(v) > 1 and v[1] is not None]
                                device_ids.update([str(v) for v in field_values])
                                debug_print(f"  FIELD approach found {len(field_values)} IDs")
                except Exception as e:
                    debug_print(f"  FIELD query failed: {e}")
                
                # Try Approach 3: Sample data scan (fallback)
                if not device_ids:
                    try:
                        sample_query = f'SELECT * FROM "{measurement_name}" LIMIT 1000'
                        sample_response = requests.get(
                            base_url,
                            params={'db': config.db_name, 'q': sample_query},
                            auth=auth,
                            timeout=10
                        )
                        
                        if sample_response.status_code == 200:
                            sample_data = sample_response.json()
                            if 'results' in sample_data and sample_data['results'] and 'series' in sample_data['results'][0]:
                                if sample_data['results'][0]['series']:
                                    series = sample_data['results'][0]['series'][0]
                                    columns = series.get('columns', [])
                                    
                                    if 'id' in columns:
                                        id_index = columns.index('id')
                                        sample_values = [row[id_index] for row in series['values'] if row[id_index] is not None]
                                        device_ids.update([str(v) for v in sample_values])
                                        debug_print(f"  SAMPLE approach found {len(sample_values)} IDs")
                    except Exception as e:
                        debug_print(f"  SAMPLE query failed: {e}")
                
                # Sort device IDs
                sorted_ids = sorted(list(device_ids), key=lambda x: int(x) if str(x).isdigit() else x)
                
                # ============================================
                # STEP 3: For Each Device, Get Sensors
                # ============================================
                devices_list = []
                
                for device_id in sorted_ids:
                    debug_print(f"  Getting sensors for device {device_id}...")
                    
                    sensors = []
                    
                    try:
                        # Query device data to get columns (sensors)
                        device_query = f'SELECT * FROM "{measurement_name}" WHERE id=\'{device_id}\' LIMIT 1'
                        device_response = requests.get(
                            base_url,
                            params={'db': config.db_name, 'q': device_query},
                            auth=auth,
                            timeout=10
                        )
                        
                        if device_response.status_code == 200:
                            device_data = device_response.json()
                            if 'results' in device_data and device_data['results'] and 'series' in device_data['results'][0]:
                                if device_data['results'][0]['series']:
                                    series = device_data['results'][0]['series'][0]
                                    columns = series.get('columns', [])
                                    values = series.get('values', [[]])[0]
                                    
                                    # Skip metadata columns
                                    skip_columns = ['time', 'id', 'deviceID', 'device_id']
                                    
                                    for i, col in enumerate(columns):
                                        if col.lower() not in skip_columns:
                                            # Get value and determine type
                                            value = values[i] if i < len(values) else None
                                            
                                            # Determine field type
                                            field_type = 'unknown'
                                            if value is not None:
                                                if isinstance(value, bool):
                                                    field_type = 'boolean'
                                                elif isinstance(value, int):
                                                    field_type = 'integer'
                                                elif isinstance(value, float):
                                                    field_type = 'float'
                                                elif isinstance(value, str):
                                                    field_type = 'string'
                                            
                                            # Categorize as sensor or info
                                            is_sensor = field_type in ['integer', 'float', 'boolean']
                                            
                                            sensors.append({
                                                'name': col,
                                                'type': 'sensor' if is_sensor else 'info',
                                                'field_type': field_type,
                                                'sample_value': value
                                            })
                                    
                                    debug_print(f"    Found {len(sensors)} fields for device {device_id}")
                    except Exception as e:
                        debug_print(f"    Error getting sensors for device {device_id}: {e}")
                    
                    devices_list.append({
                        'id': device_id,
                        'sensors': sensors,
                        'sensors_count': len([s for s in sensors if s['type'] == 'sensor']),
                        'info_count': len([s for s in sensors if s['type'] == 'info'])
                    })
                
                measurements_data.append({
                    'name': measurement_name,
                    'count': len(sorted_ids),
                    'devices': devices_list
                })
            
            messages.success(
                request,
                f'✅ Successfully fetched {len(measurements)} measurements with {sum(m["count"] for m in measurements_data)} total devices!'
            )
        
        except requests.exceptions.Timeout:
            debug_print("Request TIMEOUT")
            messages.error(request, '⛔ Request timeout - InfluxDB did not respond.')
        
        except requests.exceptions.ConnectionError:
            debug_print("Connection ERROR")
            messages.error(request, '⛔ Connection error - Cannot reach InfluxDB.')
        
        except Exception as e:
            debug_print(f"EXCEPTION: {str(e)}")
            import traceback
            debug_print(f"Traceback: {traceback.format_exc()}")
            messages.error(request, f'⛔ Error: {str(e)}')
    
    context = {
        'config': config,
        'measurements_data': measurements_data,
        'page_title': 'Fetch Measurements from InfluxDB',
    }
    
    debug_print(f"Rendering template with {len(measurements_data)} measurements")
    debug_print("=" * 80)
    
    return render(request, 'companyadmin/influx_fetch.html', context)


# companyadmin/views.py
# companyadmin/views.py

import sys
import json
import requests
from requests.auth import HTTPBasicAuth
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from accounts.decorators import require_company_admin
from companyadmin.models import AssetConfig, Device, Sensor


def debug_print(msg, level=0):
    """Helper to print debug messages with indentation"""
    indent = "   " * level
    print(f"{indent}{msg}", flush=True)
    sys.stdout.flush()


def analyze_device_sensors_from_influx(measurement, device_column, device_id, base_url, db_name, auth):
    """
    Query InfluxDB for specific device and detect which sensors have data (not all NULL)
    WITH MAXIMUM DEBUG LOGGING
    """
    debug_print(f"\n{'='*100}", 0)
    debug_print(f"🔍 FUNCTION: analyze_device_sensors_from_influx()", 0)
    debug_print(f"{'='*100}", 0)
    debug_print(f"INPUTS:", 0)
    debug_print(f"measurement      = {measurement}", 1)
    debug_print(f"device_column    = {device_column}", 1)
    debug_print(f"device_id        = {device_id} (type: {type(device_id)})", 1)
    debug_print(f"base_url         = {base_url}", 1)
    debug_print(f"db_name          = {db_name}", 1)
    debug_print(f"auth             = <HTTPBasicAuth object>", 1)
    
    try:
        # Step 1: Build query
        debug_print(f"\n[STEP 1] Building InfluxDB query...", 0)
        device_query = f'SELECT * FROM "{measurement}" WHERE "{device_column}"=\'{device_id}\' ORDER BY time DESC LIMIT 1000'
        debug_print(f"Query built:", 1)
        debug_print(f"{device_query}", 2)
        
        # Step 2: Send request
        debug_print(f"\n[STEP 2] Sending HTTP request to InfluxDB...", 0)
        debug_print(f"URL: {base_url}", 1)
        debug_print(f"Method: GET", 1)
        debug_print(f"Params:", 1)
        debug_print(f"db = {db_name}", 2)
        debug_print(f"q  = {device_query}", 2)
        debug_print(f"Timeout: 10 seconds", 1)
        
        response = requests.get(
            base_url,
            params={'db': db_name, 'q': device_query},
            auth=auth,
            verify=False,
            timeout=10
        )
        
        debug_print(f"\n[STEP 3] Response received:", 0)
        debug_print(f"Status Code: {response.status_code}", 1)
        debug_print(f"Headers:", 1)
        for key, value in response.headers.items():
            debug_print(f"{key}: {value}", 2)
        
        # Step 3: Check status code
        if response.status_code != 200:
            debug_print(f"\n❌ ERROR: Bad HTTP status code", 0)
            debug_print(f"Expected: 200", 1)
            debug_print(f"Got: {response.status_code}", 1)
            debug_print(f"Response text (first 1000 chars):", 1)
            debug_print(response.text[:1000], 2)
            debug_print(f"{'='*100}\n", 0)
            return []
        
        # Step 4: Parse JSON
        debug_print(f"\n[STEP 4] Parsing JSON response...", 0)
        try:
            data = response.json()
            debug_print(f"✅ JSON parsed successfully", 1)
        except json.JSONDecodeError as e:
            debug_print(f"❌ JSON parse error: {e}", 1)
            debug_print(f"Response text:", 1)
            debug_print(response.text[:1000], 2)
            debug_print(f"{'='*100}\n", 0)
            return []
        
        # Step 5: Validate response structure
        debug_print(f"\n[STEP 5] Validating response structure...", 0)
        debug_print(f"Top-level keys: {list(data.keys())}", 1)
        
        if 'results' not in data:
            debug_print(f"❌ Missing 'results' key", 1)
            debug_print(f"Full response:", 1)
            debug_print(json.dumps(data, indent=2)[:2000], 2)
            debug_print(f"{'='*100}\n", 0)
            return []
        
        debug_print(f"✅ 'results' key found", 1)
        debug_print(f"Number of results: {len(data['results'])}", 1)
        
        if not data['results']:
            debug_print(f"❌ Empty results array", 1)
            debug_print(f"{'='*100}\n", 0)
            return []
        
        debug_print(f"✅ Results array not empty", 1)
        debug_print(f"Keys in results[0]: {list(data['results'][0].keys())}", 1)
        
        if 'series' not in data['results'][0]:
            debug_print(f"❌ Missing 'series' key in results[0]", 1)
            debug_print(f"results[0] content:", 1)
            debug_print(json.dumps(data['results'][0], indent=2)[:2000], 2)
            debug_print(f"{'='*100}\n", 0)
            return []
        
        debug_print(f"✅ 'series' key found in results[0]", 1)
        
        if not data['results'][0]['series']:
            debug_print(f"❌ Empty series array", 1)
            debug_print(f"This means the query returned no data", 1)
            debug_print(f"Possible reasons:", 1)
            debug_print(f"- Device ID '{device_id}' doesn't exist in measurement", 2)
            debug_print(f"- Wrong device_column '{device_column}'", 2)
            debug_print(f"- No data in time range", 2)
            debug_print(f"{'='*100}\n", 0)
            return []
        
        debug_print(f"✅ Series array contains data", 1)
        
        # Step 6: Extract data
        debug_print(f"\n[STEP 6] Extracting columns and values...", 0)
        series = data['results'][0]['series'][0]
        columns = series.get('columns', [])
        values = series.get('values', [])
        
        debug_print(f"Number of columns: {len(columns)}", 1)
        debug_print(f"Column names: {columns}", 1)
        debug_print(f"Number of rows: {len(values)}", 1)
        
        if values:
            debug_print(f"First row (sample):", 1)
            for i, col in enumerate(columns):
                value = values[0][i] if i < len(values[0]) else None
                debug_print(f"[{i}] {col} = {value} (type: {type(value).__name__})", 2)
        
        if not values:
            debug_print(f"❌ No values in series", 1)
            debug_print(f"{'='*100}\n", 0)
            return []
        
        # Step 7: NULL detection analysis
        debug_print(f"\n[STEP 7] Performing NULL detection analysis...", 0)
        debug_print(f"Skip columns: ['time', '{device_column}']", 1)
        
        skip_columns = ['time', device_column]
        device_sensors = []
        
        for i, col_name in enumerate(columns):
            debug_print(f"\n--- Analyzing column [{i}]: {col_name} ---", 1)
            
            if col_name in skip_columns:
                debug_print(f"⏭️  SKIPPED (in skip list)", 2)
                continue
            
            # Get all values for this column
            column_values = [row[i] if i < len(row) else None for row in values]
            
            # Count NULL vs non-NULL
            non_null_values = [v for v in column_values if v is not None]
            null_values = [v for v in column_values if v is None]
            
            non_null_count = len(non_null_values)
            null_count = len(null_values)
            total_count = len(column_values)
            
            debug_print(f"Statistics:", 2)
            debug_print(f"Total rows:    {total_count}", 3)
            debug_print(f"Non-NULL:      {non_null_count} ({non_null_count/total_count*100:.1f}%)", 3)
            debug_print(f"NULL:          {null_count} ({null_count/total_count*100:.1f}%)", 3)
            
            # Check if column has data
            has_data = non_null_count > 0
            
            if not has_data:
                debug_print(f"❌ EXCLUDED - All values are NULL", 2)
                continue
            
            debug_print(f"✅ INCLUDED - Has non-NULL data", 2)
            
            # Get sample value
            sample_value = non_null_values[0] if non_null_values else None
            debug_print(f"Sample value: {sample_value} (type: {type(sample_value).__name__})", 2)
            
            # Detect field type
            field_type = 'unknown'
            if sample_value is not None:
                if isinstance(sample_value, bool):
                    field_type = 'boolean'
                elif isinstance(sample_value, int):
                    field_type = 'integer'
                elif isinstance(sample_value, float):
                    field_type = 'float'
                elif isinstance(sample_value, str):
                    field_type = 'string'
            
            debug_print(f"Detected field_type: {field_type}", 2)
            
            # Detect category
            col_lower = col_name.lower()
            
            if col_lower in ['slave', 'slaveid', 'slave_id']:
                category = 'slave'
                reason = 'Slave identifier'
            elif any(k in col_lower for k in ['device', 'deviceid', 'mac', 'ip', 'location', 'name', 'description']):
                category = 'info'
                reason = 'Device information'
            elif field_type in ['integer', 'float', 'boolean']:
                category = 'sensor'
                reason = 'Numeric/boolean measurement'
            else:
                category = 'info'
                reason = 'Other information'
            
            debug_print(f"Detected category: {category} ({reason})", 2)
            
            # Add to sensors list
            sensor_dict = {
                'name': col_name,
                'type': field_type,
                'category': category,
                'sample_value': sample_value
            }
            device_sensors.append(sensor_dict)
            debug_print(f"✅ Added to sensor list", 2)
        
        # Step 8: Final results
        debug_print(f"\n[STEP 8] Analysis complete", 0)
        debug_print(f"Total sensors detected: {len(device_sensors)}", 1)
        
        if device_sensors:
            debug_print(f"Sensor breakdown:", 1)
            sensor_count = len([s for s in device_sensors if s['category'] == 'sensor'])
            slave_count = len([s for s in device_sensors if s['category'] == 'slave'])
            info_count = len([s for s in device_sensors if s['category'] == 'info'])
            
            debug_print(f"Sensors: {sensor_count}", 2)
            debug_print(f"Slaves:  {slave_count}", 2)
            debug_print(f"Info:    {info_count}", 2)
            
            debug_print(f"Sensor names:", 1)
            for idx, s in enumerate(device_sensors, 1):
                debug_print(f"[{idx}] {s['name']} ({s['category']}, {s['type']})", 2)
        else:
            debug_print(f"⚠️  WARNING: No sensors detected!", 1)
        
        debug_print(f"{'='*100}\n", 0)
        return device_sensors
    
    except Exception as e:
        debug_print(f"\n❌ EXCEPTION in analyze_device_sensors_from_influx", 0)
        debug_print(f"Exception type: {type(e).__name__}", 1)
        debug_print(f"Exception message: {str(e)}", 1)
        debug_print(f"Traceback:", 1)
        import traceback
        for line in traceback.format_exc().split('\n'):
            debug_print(line, 2)
        debug_print(f"{'='*100}\n", 0)
        return []


def detect_column_type(column_name, sample_values):
    """Column type detection for Step 2"""
    col_lower = column_name.lower()
    
    if col_lower == 'time':
        return {'category': 'hidden', 'type': 'timestamp', 'reason': 'Time column'}
    
    if col_lower == 'id':
        unique_values = set(sample_values)
        if len(unique_values) > 1:
            return {'category': 'device', 'type': 'integer', 'reason': 'Multiple unique IDs'}
        else:
            return {'category': 'slave', 'type': 'integer', 'reason': 'Single ID'}
    
    if col_lower in ['slave', 'slaveid', 'slave_id']:
        return {'category': 'slave', 'type': 'integer', 'reason': 'Slave identifier'}
    
    if any(k in col_lower for k in ['device', 'deviceid', 'mac', 'ip', 'location', 'name']):
        return {'category': 'info', 'type': 'string', 'reason': 'Device info'}
    
    if sample_values:
        valid_values = [v for v in sample_values if v is not None]
        if valid_values:
            first_value = valid_values[0]
            if isinstance(first_value, (int, float)):
                return {'category': 'sensor', 'type': 'float' if isinstance(first_value, float) else 'integer', 'reason': 'Numeric sensor'}
            elif isinstance(first_value, bool):
                return {'category': 'sensor', 'type': 'boolean', 'reason': 'Boolean sensor'}
            elif isinstance(first_value, str):
                return {'category': 'info', 'type': 'string', 'reason': 'Text info'}
    
    return {'category': 'info', 'type': 'string', 'reason': 'Unknown'}


@require_company_admin
def device_setup_wizard_view(request):
    """
    Device Setup Wizard with Maximum Debug Logging
    ✅ UPDATED: Saves influx_measurement_id and device_column in metadata
    """
    
    debug_print(f"\n{'#'*100}", 0)
    debug_print(f"# WIZARD VIEW CALLED", 0)
    debug_print(f"{'#'*100}", 0)
    debug_print(f"Request method: {request.method}", 0)
    if request.method == 'POST':
        debug_print(f"POST data keys: {list(request.POST.keys())}", 0)
    
    config = AssetConfig.get_active_config()
    
    if not config or not config.is_connected:
        debug_print(f"❌ No InfluxDB config or not connected", 0)
        messages.error(request, '⛔ Configure InfluxDB first.')
        return redirect('companyadmin:influx_config')
    
    debug_print(f"✅ InfluxDB config found and connected", 0)
    debug_print(f"   base_api: {config.base_api}", 1)
    debug_print(f"   db_name: {config.db_name}", 1)
    
    if 'wizard_data' not in request.session:
        debug_print(f"Initializing new wizard session", 0)
        request.session['wizard_data'] = {
            'step': 1,
            'measurements': [],
            'selected_measurements': [],
            'device_columns': {},
            'column_analysis': {},
            'preview_data': []
        }
    
    wizard_data = request.session['wizard_data']
    current_step = wizard_data.get('step', 1)
    
    debug_print(f"Current wizard step: {current_step}", 0)
    
    base_url = f"{config.base_api}/query"
    auth = HTTPBasicAuth(config.api_username, config.api_password)
    
    # ==========================================
    # STEP 1: SELECT MEASUREMENTS
    # ==========================================
    if current_step == 1:
        debug_print(f"\n[STEP 1: Select Measurements]", 0)
        
        if request.method == 'POST' and 'fetch_measurements' in request.POST:
            debug_print(f"Action: Fetching measurements", 0)
            debug_print(f"{'='*100}", 0)
            debug_print(f"[FETCH MEASUREMENTS REQUEST]", 0)
            debug_print(f"{'='*100}", 0)
            
            try:
                query = 'SHOW MEASUREMENTS'
                debug_print(f"Query: {query}", 1)
                debug_print(f"Database: {config.db_name}", 1)
                debug_print(f"Base URL: {base_url}", 1)
                
                response = requests.get(
                    base_url, 
                    params={'db': config.db_name, 'q': query}, 
                    auth=auth,
                    verify=False, 
                    timeout=10
                )
                
                debug_print(f"\n[RESPONSE]", 0)
                debug_print(f"Status Code: {response.status_code}", 1)
                
                if response.status_code != 200:
                    debug_print(f"❌ Bad status code: {response.status_code}", 1)
                    debug_print(f"Response text: {response.text[:500]}", 1)
                    messages.error(request, f'⛔ InfluxDB returned status {response.status_code}')
                    debug_print(f"{'='*100}\n", 0)
                else:
                    data = response.json()
                    debug_print(f"✅ JSON parsed", 1)
                    debug_print(f"Top-level keys: {list(data.keys())}", 1)
                    
                    # Step-by-step validation
                    if 'results' not in data:
                        debug_print(f"❌ Missing 'results' key", 1)
                        debug_print(f"Full response: {json.dumps(data, indent=2)[:1000]}", 1)
                        messages.error(request, '⛔ Invalid response: missing results')
                        debug_print(f"{'='*100}\n", 0)
                        
                    elif not data['results']:
                        debug_print(f"❌ Empty results array", 1)
                        messages.error(request, '⛔ No results from InfluxDB')
                        debug_print(f"{'='*100}\n", 0)
                        
                    elif not isinstance(data['results'], list):
                        debug_print(f"❌ results is not a list: {type(data['results'])}", 1)
                        messages.error(request, '⛔ Invalid results format')
                        debug_print(f"{'='*100}\n", 0)
                        
                    else:
                        debug_print(f"✅ results key found, length: {len(data['results'])}", 1)
                        debug_print(f"results[0] keys: {list(data['results'][0].keys())}", 1)
                        
                        if 'series' not in data['results'][0]:
                            debug_print(f"❌ Missing 'series' in results[0]", 1)
                            debug_print(f"results[0]: {json.dumps(data['results'][0], indent=2)[:1000]}", 1)
                            messages.error(request, '⛔ No measurements found in database')
                            debug_print(f"{'='*100}\n", 0)
                            
                        elif not data['results'][0]['series']:
                            debug_print(f"❌ Empty series array - no measurements in database", 1)
                            messages.info(request, 'ℹ️ Database has no measurements yet')
                            wizard_data['measurements'] = []
                            request.session.modified = True
                            debug_print(f"{'='*100}\n", 0)
                            
                        else:
                            debug_print(f"✅ series found, length: {len(data['results'][0]['series'])}", 1)
                            series = data['results'][0]['series'][0]
                            debug_print(f"series[0] keys: {list(series.keys())}", 1)
                            debug_print(f"values length: {len(series.get('values', []))}", 1)
                            
                            measurements = [row[0] for row in series['values']]
                            wizard_data['measurements'] = measurements
                            request.session.modified = True
                            
                            debug_print(f"✅ Found {len(measurements)} measurements", 1)
                            debug_print(f"Measurements: {measurements}", 1)
                            debug_print(f"{'='*100}\n", 0)
                            
                            messages.success(request, f'✅ Found {len(measurements)} measurements')
                            
            except Exception as e:
                debug_print(f"\n❌ EXCEPTION", 0)
                debug_print(f"Type: {type(e).__name__}", 1)
                debug_print(f"Message: {str(e)}", 1)
                debug_print(f"Traceback:", 1)
                import traceback
                for line in traceback.format_exc().split('\n'):
                    debug_print(line, 2)
                debug_print(f"{'='*100}\n", 0)
                messages.error(request, f'⛔ Error: {str(e)}')
        
        elif request.method == 'POST' and 'select_measurements' in request.POST:
            selected = request.POST.getlist('selected_measurements')
            debug_print(f"Action: User selected {len(selected)} measurements", 0)
            if selected:
                wizard_data['selected_measurements'] = selected
                wizard_data['step'] = 2
                request.session.modified = True
                return redirect('companyadmin:device_setup_wizard')
    
    # ==========================================
    # STEP 2: ANALYZE COLUMNS
    # ==========================================
    elif current_step == 2:
        debug_print(f"\n[STEP 2: Analyze Columns]", 0)
        
        if request.method == 'POST' and 'select_device_columns' in request.POST:
            device_columns = {}
            for measurement in wizard_data['selected_measurements']:
                column = request.POST.get(f'device_column_{measurement}')
                if column:
                    device_columns[measurement] = column
            
            wizard_data['device_columns'] = device_columns
            wizard_data['step'] = 3
            request.session.modified = True
            debug_print(f"✅ Device columns selected, moving to step 3", 0)
            return redirect('companyadmin:device_setup_wizard')
        
        elif request.method == 'POST' and 'back_to_step1' in request.POST:
            wizard_data['step'] = 1
            request.session.modified = True
            return redirect('companyadmin:device_setup_wizard')
        
        if not wizard_data.get('column_analysis'):
            debug_print(f"Analyzing columns...", 0)
            column_analysis = {}
            
            for measurement in wizard_data['selected_measurements']:
                try:
                    sample_query = f'SELECT * FROM "{measurement}" LIMIT 100'
                    response = requests.get(base_url, params={'db': config.db_name, 'q': sample_query}, auth=auth, verify=False, timeout=30)
                    
                    if response.status_code == 200:
                        data = response.json()
                        if 'results' in data and data['results'] and 'series' in data['results'][0]:
                            if data['results'][0]['series']:
                                series = data['results'][0]['series'][0]
                                columns = series.get('columns', [])
                                values = series.get('values', [])
                                
                                column_info = {}
                                for i, col in enumerate(columns):
                                    sample_values = [row[i] for row in values[:100] if i < len(row)]
                                    detection = detect_column_type(col, sample_values)
                                    column_info[col] = {
                                        'category': detection['category'],
                                        'type': detection['type'],
                                        'reason': detection['reason'],
                                        'unique_count': len(set(sample_values))
                                    }
                                
                                column_analysis[measurement] = column_info
                except Exception as e:
                    debug_print(f"Error analyzing {measurement}: {e}", 0)
            
            wizard_data['column_analysis'] = column_analysis
            request.session.modified = True
    
    # ==========================================
    # STEP 3: PREVIEW
    # ==========================================
    elif current_step == 3:
        debug_print(f"\n[STEP 3: Preview]", 0)
        
        if request.method == 'POST' and 'confirm_save' in request.POST:
            debug_print(f"User confirmed save, moving to step 4", 0)
            wizard_data['step'] = 4
            request.session.modified = True
            return redirect('companyadmin:device_setup_wizard')
        
        elif request.method == 'POST' and 'back_to_step2' in request.POST:
            wizard_data['step'] = 2
            request.session.modified = True
            return redirect('companyadmin:device_setup_wizard')
        
        if not wizard_data.get('preview_data'):
            debug_print(f"Building preview...", 0)
            preview_data = []
            
            for measurement in wizard_data['selected_measurements']:
                device_column = wizard_data['device_columns'][measurement]
                
                # Get device IDs
                try:
                    tag_query = f'SHOW TAG VALUES FROM "{measurement}" WITH KEY = "{device_column}"'
                    response = requests.get(base_url, params={'db': config.db_name, 'q': tag_query}, auth=auth, verify=False, timeout=10)
                    
                    device_ids = set()
                    if response.status_code == 200:
                        data = response.json()
                        if 'results' in data and data['results'] and 'series' in data['results'][0]:
                            if data['results'][0]['series']:
                                device_ids.update([v[1] for v in data['results'][0]['series'][0]['values']])
                except:
                    pass
                
                sorted_device_ids = sorted(list(device_ids), key=lambda x: int(x) if str(x).isdigit() else x)
                
                # Analyze devices
                devices_with_sensors = []
                for device_id in sorted_device_ids[:10]:
                    sensors = analyze_device_sensors_from_influx(measurement, device_column, device_id, base_url, config.db_name, auth)
                    
                    devices_with_sensors.append({
                        'device_id': device_id,
                        'sensors': sensors,
                        'sensor_count': len([s for s in sensors if s['category'] == 'sensor']),
                        'slave_count': len([s for s in sensors if s['category'] == 'slave']),
                        'info_count': len([s for s in sensors if s['category'] == 'info'])
                    })
                
                preview_data.append({
                    'measurement': measurement,
                    'device_column': device_column,
                    'device_count': len(sorted_device_ids),
                    'all_device_ids': sorted_device_ids,
                    'devices_with_sensors': devices_with_sensors
                })
            
            wizard_data['preview_data'] = preview_data
            request.session.modified = True
    
    # ==========================================
    # STEP 4: SAVE TO DATABASE
    # ==========================================
    elif current_step == 4:
        debug_print(f"\n{'='*100}", 0)
        debug_print(f"[STEP 4: SAVE TO DATABASE]", 0)
        debug_print(f"{'='*100}", 0)
        
        try:
            devices_created = 0
            devices_updated = 0
            sensors_created = 0
            
            with transaction.atomic():
                
                for item in wizard_data['preview_data']:
                    measurement = item['measurement']
                    device_column = item['device_column']
                    all_device_ids = item.get('all_device_ids', [])
                    
                    debug_print(f"\n📊 Measurement: {measurement}", 0)
                    debug_print(f"   Device Column: {device_column}", 1)
                    debug_print(f"   Total Devices: {len(all_device_ids)}", 1)
                    
                    for idx, device_id in enumerate(all_device_ids, 1):
                        
                        debug_print(f"\n{'─'*80}", 0)
                        debug_print(f"Device [{idx}/{len(all_device_ids)}]: ID = {device_id}", 0)
                        debug_print(f"{'─'*80}", 0)
                        
                        device, created = Device.objects.get_or_create(
                            measurement_name=measurement,
                            device_id=str(device_id),
                            defaults={
                                'display_name': f"{measurement} - Device {device_id}",
                                'is_active': True,
                                'metadata': {
                                    'influx_measurement_id': measurement,
                                    'device_column': device_column,
                                    'auto_discovered': True,
                                    'discovered_at': timezone.now().isoformat()
                                }
                            }
                        )
                        
                        if created:
                            devices_created += 1
                            debug_print(f"✅ Device CREATED (DB ID: {device.id})", 1)
                            debug_print(f"   metadata: {device.metadata}", 2)
                        else:
                            debug_print(f"ℹ️  Device EXISTS (DB ID: {device.id})", 1)
                            
                            updated = False
                            if 'influx_measurement_id' not in device.metadata:
                                device.metadata['influx_measurement_id'] = measurement
                                updated = True
                                debug_print(f"   Added influx_measurement_id to metadata", 2)
                            
                            if 'device_column' not in device.metadata:
                                device.metadata['device_column'] = device_column
                                updated = True
                                debug_print(f"   Added device_column to metadata", 2)
                            
                            if updated:
                                device.save()
                                devices_updated += 1
                                debug_print(f"   ✅ Metadata updated: {device.metadata}", 2)
                        
                        debug_print(f"\nCalling analyze_device_sensors_from_influx...", 1)
                        
                        sensors = analyze_device_sensors_from_influx(
                            measurement, 
                            device_column, 
                            device_id, 
                            base_url, 
                            config.db_name, 
                            auth
                        )
                        
                        debug_print(f"Function returned {len(sensors)} sensors", 1)
                        
                        if not sensors:
                            debug_print(f"⚠️  No sensors to save for this device", 1)
                            continue
                        
                        device_sensor_count = 0
                        debug_print(f"\nSaving {len(sensors)} sensors to database...", 1)
                        
                        for sensor_idx, sensor_info in enumerate(sensors, 1):
                            debug_print(f"Sensor [{sensor_idx}/{len(sensors)}]: {sensor_info['name']}", 2)
                            
                            sensor, sensor_created = Sensor.objects.get_or_create(
                                device=device,
                                field_name=sensor_info['name'],
                                defaults={
                                    'display_name': sensor_info['name'].replace('_', ' ').title(),
                                    'field_type': sensor_info['type'],
                                    'category': sensor_info['category'],
                                    'is_active': True,
                                    'metadata': {
                                        'sample_value': str(sensor_info['sample_value']) if sensor_info['sample_value'] is not None else None
                                    }
                                }
                            )
                            
                            if sensor_created:
                                sensors_created += 1
                                device_sensor_count += 1
                                debug_print(f"✅ CREATED (DB ID: {sensor.id})", 3)
                            else:
                                debug_print(f"ℹ️  EXISTS (DB ID: {sensor.id})", 3)
                        
                        debug_print(f"\n✅ Device complete: {device_sensor_count} new sensors", 1)
            
            del request.session['wizard_data']
            request.session.modified = True
            
            debug_print(f"\n{'='*100}", 0)
            debug_print(f"🎉 SUCCESS!", 0)
            debug_print(f"   Devices Created: {devices_created}", 1)
            debug_print(f"   Devices Updated: {devices_updated}", 1)
            debug_print(f"   Sensors Created: {sensors_created}", 1)
            debug_print(f"{'='*100}\n", 0)
            
            messages.success(request, f'🎉 Success! Created {devices_created} devices, updated {devices_updated} devices, and created {sensors_created} sensors!')
            return redirect('companyadmin:device_list')
        
        except Exception as e:
            debug_print(f"\n❌ EXCEPTION:", 0)
            debug_print(f"{str(e)}", 1)
            import traceback
            traceback.print_exc()
            messages.error(request, f'⛔ Error: {str(e)}')
    
    # Reset wizard
    if request.method == 'POST' and 'reset_wizard' in request.POST:
        del request.session['wizard_data']
        request.session.modified = True
        return redirect('companyadmin:device_setup_wizard')
    
    context = {
        'config': config,
        'wizard_data': wizard_data,
        'current_step': current_step,
        'page_title': 'Device Setup Wizard',
    }
    
    return render(request, 'companyadmin/device_setup_wizard.html', context)


@require_company_admin
def device_list_view(request):
    """
    Display all devices grouped by measurement with complete info
    """
    from .models import Device
    
    devices = Device.objects.all().prefetch_related('departments', 'sensors').order_by('measurement_name', 'device_id')
    config = AssetConfig.get_active_config()
    
    measurements = {}
    for device in devices:
        measurement_name = device.measurement_name
        if measurement_name not in measurements:
            measurements[measurement_name] = []
        
        device.total_sensors_only = device.sensors.filter(category='sensor').count()
        device.sensor_breakdown = {
            'sensors': device.sensors.filter(category='sensor').count(),
            'slaves': device.sensors.filter(category='slave').count(),
            'info': device.sensors.filter(category='info').count(),
        }
        device.device_column = device.metadata.get('device_column', 'N/A')
        device.auto_discovered = device.metadata.get('auto_discovered', False)
        
        measurements[measurement_name].append(device)
    
    context = {
        'measurements': measurements,
        'total_devices': devices.count(),
        'total_measurements': len(measurements),
        'has_config': config is not None,
        'config': config,
        'page_title': 'Device Management',
    }
    
    return render(request, 'companyadmin/device_list.html', context)

@require_company_admin
def device_list_view(request):
    """
    Display all devices grouped by measurement with complete info
    """
    from .models import Device
    
    devices = Device.objects.all().prefetch_related('departments', 'sensors').order_by('measurement_name', 'device_id')
    config = AssetConfig.get_active_config()
    
    # Group devices by measurement
    measurements = {}
    for device in devices:
        measurement_name = device.measurement_name
        if measurement_name not in measurements:
            measurements[measurement_name] = []
        
        # Add computed data (don't override sensor_count - it's a property)
        device.total_sensors_only = device.sensors.filter(category='sensor').count()  # Only sensors
        device.sensor_breakdown = {
            'sensors': device.sensors.filter(category='sensor').count(),
            'slaves': device.sensors.filter(category='slave').count(),
            'info': device.sensors.filter(category='info').count(),
        }
        device.device_column = device.metadata.get('device_column', 'N/A')
        device.auto_discovered = device.metadata.get('auto_discovered', False)
        
        measurements[measurement_name].append(device)
    
    context = {
        'measurements': measurements,
        'total_devices': devices.count(),
        'total_measurements': len(measurements),
        'has_config': config is not None,
        'config': config,
        'page_title': 'Device Management',
    }
    
    return render(request, 'companyadmin/device_list.html', context)


@require_company_admin
def device_edit_modal_view(request, device_id):
    """
    Handle device edit via AJAX (for modal)
    Edit: Display Name, Measurement Name, Active Status, Department Assignment
    """
    from django.http import JsonResponse
    from .models import Device, Department
    
    try:
        device = Device.objects.get(id=device_id)
        
        if request.method == 'POST':
            # Update device
            device.display_name = request.POST.get('display_name', device.display_name).strip()
            device.measurement_name = request.POST.get('measurement_name', device.measurement_name).strip()
            device.is_active = request.POST.get('is_active') == 'true'
            
            # Update departments
            department_ids = request.POST.getlist('departments[]')
            if department_ids:
                device.departments.set(Department.objects.filter(id__in=department_ids))
            else:
                device.departments.clear()
            
            device.save()
            
            return JsonResponse({
                'success': True,
                'message': f'✅ Device "{device.display_name}" updated successfully!'
            })
        
        else:
            # GET: Return device data for modal
            departments = Department.objects.filter(is_active=True)
            
            return JsonResponse({
                'success': True,
                'device': {
                    'id': device.id,
                    'display_name': device.display_name,
                    'measurement_name': device.measurement_name,
                    'device_id': device.device_id,
                    'is_active': device.is_active,
                    'departments': list(device.departments.values_list('id', flat=True))
                },
                'all_departments': list(departments.values('id', 'name'))
            })
    
    except Device.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Device not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@require_company_admin
def device_sensors_modal_view(request, device_id):
    """
    Return all sensors for a device (for modal display)
    """
    from django.http import JsonResponse
    from .models import Device
    
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
                'sample_value': sensor.metadata.get('sample_value', 'N/A')
            })
        
        return JsonResponse({
            'success': True,
            'device': {
                'display_name': device.display_name,
                'device_id': device.device_id,
                'measurement_name': device.measurement_name
            },
            'sensors': sensor_list,
            'total_sensors': len([s for s in sensor_list if s['category'] == 'sensor']),
            'total_fields': len(sensor_list)
        })
    
    except Device.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Device not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@require_company_admin
def device_delete_view(request, device_id):
    """
    Delete device and all associated sensors
    """
    from django.http import JsonResponse
    from .models import Device
    
    if request.method == 'POST':
        try:
            device = Device.objects.get(id=device_id)
            device_name = device.display_name
            sensor_count = device.sensors.count()
            
            # Delete device (CASCADE will delete sensors automatically)
            device.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'🗑️ Device "{device_name}" and {sensor_count} sensor(s) deleted successfully!'
            })
        
        except Device.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Device not found'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)


@require_company_admin
def configure_sensors_view(request, device_id):
    """
    Page to configure sensor metadata for a device
    Shows ONLY sensors (category='sensor') in a table format
    Actions: Add Metadata, Edit Metadata, Reset Metadata
    """
    from .models import Device, Sensor
    
    try:
        device = Device.objects.get(id=device_id)
        
        # ✅ ONLY get sensors, exclude info and slave categories
        sensors = device.sensors.filter(category='sensor').order_by('field_name')
        
        # Prepare sensor data with metadata status
        sensor_data = []
        for sensor in sensors:
            has_metadata = hasattr(sensor, 'metadata_config')
            
            sensor_data.append({
                'id': sensor.id,
                'field_name': sensor.field_name,
                'field_type': sensor.field_type,
                'has_metadata': has_metadata,
                'metadata': sensor.metadata_config if has_metadata else None
            })
        
        context = {
            'device': device,
            'sensors': sensor_data,
            'total_sensors': len(sensor_data),
            'page_title': f'Configure Sensors - {device.display_name}',
        }
        
        return render(request, 'companyadmin/configure_sensors.html', context)
    
    except Device.DoesNotExist:
        messages.error(request, 'Device not found')
        return redirect('companyadmin:device_list')


@require_company_admin
def add_edit_sensor_metadata_view(request, sensor_id):
    """
    Add or Edit sensor metadata via modal
    Returns sensor data for modal population
    """
    from django.http import JsonResponse
    from .models import Sensor
    
    try:
        sensor = Sensor.objects.get(id=sensor_id)
        
        if request.method == 'POST':
            # Get or create metadata
            metadata = sensor.get_or_create_metadata()
            
            # Update metadata fields
            metadata.display_name = request.POST.get('display_name', '').strip()
            metadata.unit = request.POST.get('unit', '').strip()
            
            # Handle numeric fields (convert empty strings to None)
            upper_limit = request.POST.get('upper_limit', '').strip()
            lower_limit = request.POST.get('lower_limit', '').strip()
            central_line = request.POST.get('central_line', '').strip()
            
            metadata.upper_limit = float(upper_limit) if upper_limit else None
            metadata.lower_limit = float(lower_limit) if lower_limit else None
            metadata.central_line = float(central_line) if central_line else None
            
            # Update boolean flags
            metadata.show_time_series = request.POST.get('show_time_series') == 'true'
            metadata.show_latest_value = request.POST.get('show_latest_value') == 'true'
            metadata.show_digital = request.POST.get('show_digital') == 'true'
            
            metadata.save()
            
            return JsonResponse({
                'success': True,
                'message': f'✅ Metadata saved for {sensor.field_name}'
            })
        
        else:
            # GET: Return sensor data for modal
            has_metadata = hasattr(sensor, 'metadata_config')
            
            if has_metadata:
                metadata = sensor.metadata_config
                response_data = {
                    'success': True,
                    'sensor': {
                        'id': sensor.id,
                        'field_name': sensor.field_name,
                        'field_type': sensor.field_type,
                        'display_name': metadata.display_name,
                        'unit': metadata.unit,
                        'upper_limit': metadata.upper_limit,
                        'lower_limit': metadata.lower_limit,
                        'central_line': metadata.central_line,
                        'show_time_series': metadata.show_time_series,
                        'show_latest_value': metadata.show_latest_value,
                        'show_digital': metadata.show_digital,
                    },
                    'has_metadata': True
                }
            else:
                # No metadata yet - return defaults
                response_data = {
                    'success': True,
                    'sensor': {
                        'id': sensor.id,
                        'field_name': sensor.field_name,
                        'field_type': sensor.field_type,
                        'display_name': sensor.field_name,  # Default to field name
                        'unit': '',
                        'upper_limit': None,
                        'lower_limit': None,
                        'central_line': None,
                        'show_time_series': True,  # Default enabled
                        'show_latest_value': False,
                        'show_digital': False,
                    },
                    'has_metadata': False
                }
            
            return JsonResponse(response_data)
    
    except Sensor.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Sensor not found'}, status=404)
    except ValueError as e:
        return JsonResponse({'success': False, 'message': f'Invalid number format: {str(e)}'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@require_company_admin
def reset_sensor_metadata_view(request, sensor_id):
    """
    Reset sensor metadata to default (null/empty values)
    """
    from django.http import JsonResponse
    from .models import Sensor
    
    if request.method == 'POST':
        try:
            sensor = Sensor.objects.get(id=sensor_id)
            
            # Check if metadata exists
            if hasattr(sensor, 'metadata_config'):
                metadata = sensor.metadata_config
                
                # Reset all fields to defaults/null
                metadata.display_name = ''
                metadata.unit = ''
                metadata.upper_limit = None
                metadata.lower_limit = None
                metadata.central_line = None
                metadata.show_time_series = True  # Default
                metadata.show_latest_value = False
                metadata.show_digital = False
                
                metadata.save()
                
                return JsonResponse({
                    'success': True,
                    'message': f'✅ Metadata reset for {sensor.field_name}'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'No metadata to reset'
                })
        
        except Sensor.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Sensor not found'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)