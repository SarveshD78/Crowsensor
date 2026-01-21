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
from .models import AssetConfig, Department, DepartmentMembership, Device, SensorMetadata
from requests.auth import HTTPBasicAuth
import requests
from django.utils import timezone
from companyadmin.models import Sensor,Device,AssetConfig,AssetTrackingConfig
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

@require_company_admin
def dashboard_view(request):
    """
    Company Admin Dashboard - UPDATED FOR MULTIPLE INFLUXDB INSTANCES
    Shows ALL configured InfluxDB instances with their status
    """
    from .models import Device, Sensor, SensorMetadata, AssetConfig
    from django.utils import timezone
    from datetime import timedelta
    import requests
    from requests.auth import HTTPBasicAuth
    
    # ========== USER STATS ==========
    total_users = User.objects.filter(is_active=True).exclude(role='company_admin').count()
    total_dept_admins = User.objects.filter(is_active=True, role='department_admin').count()
    total_read_only_users = User.objects.filter(is_active=True, role='user').count()
    total_departments = Department.objects.filter(is_active=True).count()
    
    # ========== DEVICE & SENSOR STATS ==========
    total_devices = Device.objects.count()
    total_sensors = Sensor.objects.filter(category='sensor').count()
    
    # Calculate configured sensors (has metadata with display_name AND unit)
    configured_sensors = SensorMetadata.objects.filter(
        display_name__isnull=False,
        unit__isnull=False
    ).exclude(display_name='').exclude(unit='').count()
    
    # ========== ✨ NEW: ALL INFLUXDB CONFIGS WITH STATUS ==========
    influx_configs = []
    all_configs = AssetConfig.objects.filter(is_active=True).order_by('config_name')
    
    total_influx_online = 0
    total_influx_offline = 0
    
    for config in all_configs:
        # Test connection for each config
        status = 'offline'
        last_checked = None
        error_message = None
        
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
                total_influx_online += 1
                
                # Update is_connected if it was false
                if not config.is_connected:
                    config.mark_connected()
            else:
                status = 'offline'
                total_influx_offline += 1
                error_message = f"HTTP {response.status_code}"
                
            last_checked = timezone.now()
            
        except requests.exceptions.Timeout:
            status = 'offline'
            total_influx_offline += 1
            error_message = "Connection timeout"
            last_checked = timezone.now()
            
            # Update is_connected to false
            if config.is_connected:
                config.mark_disconnected("Connection timeout")
                
        except requests.exceptions.ConnectionError:
            status = 'offline'
            total_influx_offline += 1
            error_message = "Cannot connect to server"
            last_checked = timezone.now()
            
            # Update is_connected to false
            if config.is_connected:
                config.mark_disconnected("Connection refused")
                
        except Exception as e:
            status = 'offline'
            total_influx_offline += 1
            error_message = str(e)[:100]  # Limit error message length
            last_checked = timezone.now()
            
            # Update is_connected to false
            if config.is_connected:
                config.mark_disconnected(str(e))
        
        # Count devices for this config
        device_count = Device.objects.filter(asset_config=config).count()
        sensor_count = Sensor.objects.filter(
            device__asset_config=config,
            category='sensor'
        ).count()
        
        influx_configs.append({
            'config': config,
            'status': status,
            'last_checked': last_checked,
            'error_message': error_message,
            'device_count': device_count,
            'sensor_count': sensor_count,
        })
    
    # ========== RECENT ACTIVITY (Last 7 days) ==========
    recent_activities = []
    seven_days_ago = timezone.now() - timedelta(days=7)
    
    # Get recent users
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
    
    # Get recent devices
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
    
    # Get recent departments
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
    
    # Get recent metadata updates
    recent_metadata = SensorMetadata.objects.filter(
        updated_at__gte=seven_days_ago
    ).select_related('sensor', 'sensor__device', 'sensor__device__asset_config').order_by('-updated_at')[:5]
    
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
    
    # Get recent InfluxDB config changes
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
    
    # Sort all activities by time and take top 10
    recent_activities.sort(key=lambda x: x['time'], reverse=True)
    recent_activities = recent_activities[:10]
    
    # ========== CONTEXT ==========
    context = {
        'total_users': total_users,
        'total_dept_admins': total_dept_admins,
        'total_read_only_users': total_read_only_users,
        'total_departments': total_departments,
        'total_devices': total_devices,
        'total_sensors': total_sensors,
        'configured_sensors': configured_sensors,
        
        # ✨ NEW: Multiple InfluxDB config support
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
        # FIX: Changed from 'user_count' to 'total_users' to match template
        # FIX: Now counts ALL users (department_admin + user) excluding company_admin
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
                
                # Check if has users (using total_users logic - all except company_admin)
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
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch
import json

from accounts.models import User
from accounts.decorators import require_company_admin
from companyadmin.models import Department, DepartmentMembership

# =============================================================================
# USER MANAGEMENT - COMPANY ADMIN
# MULTI-DEPARTMENT SUPPORT FOR WORKSPACE SUPERVISORS
# =============================================================================
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch
import json

from accounts.models import User
from accounts.decorators import require_company_admin
from companyadmin.models import Department, DepartmentMembership


@login_required
@require_company_admin
def users_view(request):
    """
    ✅ COMPLETE MULTI-DEPARTMENT SUPPORT
    Create and manage department_admin users with multiple department assignments
    """
    
    print("\n" + "="*80)
    print("🔍 COMPANY ADMIN - USERS VIEW DEBUG START")
    print("="*80)
    
    # ==========================================
    # FETCH DATA WITH PROPER PREFETCHING
    # ==========================================
    
    # Get all department admin users with their department memberships
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
    
    print(f"📊 Total users found: {users.count()}")
    print(f"📊 Total departments: {departments.count()}")
    
    # Stats
    total_dept_admins = users.count()
    total_departments = departments.count()
    
    # ==========================================
    # POST HANDLING
    # ==========================================
    if request.method == 'POST':
        print(f"\n📬 POST Request Received")
        print(f"📋 POST Keys: {list(request.POST.keys())}")
        
        # ADD USER
        if 'add_user' in request.POST:
            print("\n➕ ADD USER REQUEST")
            try:
                username = request.POST.get('username', '').strip()
                first_name = request.POST.get('first_name', '').strip()
                last_name = request.POST.get('last_name', '').strip()
                email = request.POST.get('email', '').strip()
                phone = request.POST.get('phone', '').strip()
                
                print(f"   Username: {username}")
                print(f"   First Name: {first_name}")
                print(f"   Email: {email}")
                
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
                
                print(f"✅ User created: ID={user.id}, Username={user.username}")
                
                messages.success(
                    request,
                    f'✅ Workspace Supervisor "{user.username}" created! '
                    f'Default password: User@2025. '
                    f'⚠️ Click "Assign" to assign workspaces now.'
                )
                
            except Exception as e:
                print(f"❌ Error creating user: {e}")
                import traceback
                traceback.print_exc()
                messages.error(request, f'⛔ Error: {str(e)}')
            
            return redirect('companyadmin:users')
        
        # EDIT USER
        elif 'edit_user' in request.POST:
            print("\n✏️ EDIT USER REQUEST")
            try:
                user_id = request.POST.get('user_id')
                print(f"   User ID: {user_id}")
                
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
                
                print(f"✅ User updated: {user.username}")
                messages.success(request, f'✅ User "{user.username}" updated!')
                
            except Exception as e:
                print(f"❌ Error updating user: {e}")
                import traceback
                traceback.print_exc()
                messages.error(request, f'⛔ Error: {str(e)}')
            
            return redirect('companyadmin:users')
        
        # DELETE USER
        elif 'delete_user' in request.POST:
            print("\n🗑️ DELETE USER REQUEST")
            try:
                user_id = request.POST.get('user_id')
                user = get_object_or_404(User, id=user_id, is_active=True, role='department_admin')
                username = user.username
                
                # Soft delete
                user.is_active = False
                user.save()
                
                print(f"✅ User deleted: {username}")
                messages.success(request, f'✅ User "{username}" deleted!')
                
            except Exception as e:
                print(f"❌ Error deleting user: {e}")
                import traceback
                traceback.print_exc()
                messages.error(request, f'⛔ Error: {str(e)}')
            
            return redirect('companyadmin:users')
        
        # ✅ ASSIGN MULTIPLE DEPARTMENTS
        elif 'assign_departments' in request.POST:
            print("\n🏢 ASSIGN DEPARTMENTS REQUEST (MULTIPLE)")
            try:
                user_id = request.POST.get('user_id')
                print(f"   User ID: {user_id}")
                
                # ✅ CRITICAL: Get array of department IDs
                department_ids = request.POST.getlist('department_ids[]')
                print(f"   Department IDs received: {department_ids}")
                print(f"   Type: {type(department_ids)}")
                print(f"   Count: {len(department_ids)}")
                
                user = get_object_or_404(User, id=user_id, is_active=True, role='department_admin')
                print(f"   User: {user.username}")
                
                with transaction.atomic():
                    # Step 1: Deactivate ALL existing memberships
                    existing_count = DepartmentMembership.objects.filter(user=user, is_active=True).count()
                    DepartmentMembership.objects.filter(user=user).update(is_active=False)
                    print(f"   Deactivated {existing_count} existing memberships")
                    
                    # Step 2: Create/reactivate selected departments
                    assigned_count = 0
                    assigned_names = []
                    
                    for dept_id in department_ids:
                        try:
                            dept_id_int = int(dept_id)
                            department = Department.objects.get(id=dept_id_int, is_active=True)
                            print(f"   Processing department: {department.name} (ID: {dept_id_int})")
                            
                            # Get or create membership
                            membership, created = DepartmentMembership.objects.get_or_create(
                                user=user,
                                department=department,
                                defaults={'is_active': True}
                            )
                            
                            if not created:
                                # Reactivate existing membership
                                membership.is_active = True
                                membership.save()
                                print(f"      ✅ Reactivated existing membership")
                            else:
                                print(f"      ✅ Created new membership")
                            
                            assigned_count += 1
                            assigned_names.append(department.name)
                            
                        except (ValueError, Department.DoesNotExist) as e:
                            print(f"   ⚠️ Skipping invalid department ID: {dept_id} - {e}")
                            continue
                    
                    print(f"   ✅ Total assigned: {assigned_count} departments")
                    print(f"   📋 Department names: {assigned_names}")
                    
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
                print("❌ User not found")
                messages.error(request, '⛔ User not found.')
            except Exception as e:
                print(f"❌ Error assigning departments: {e}")
                import traceback
                traceback.print_exc()
                messages.error(request, f'⛔ Error: {str(e)}')
            
            return redirect('companyadmin:users')
    
    # ==========================================
    # PREPARE USER DATA FOR TEMPLATE
    # ==========================================
    print(f"\n📦 Preparing user data for template...")
    
    users_data = []
    for user in users:
        # Get active department memberships
        memberships = user.department_memberships.filter(is_active=True)
        user_departments = [m.department for m in memberships]
        department_ids = [dept.id for dept in user_departments]
        department_names = [dept.name for dept in user_departments]
        
        print(f"\n👤 User: {user.username}")
        print(f"   Departments ({len(user_departments)}): {department_names}")
        print(f"   Department IDs: {department_ids}")
        
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
            'department_ids_json': json.dumps(department_ids),  # ✅ JSON for JavaScript
            'department_names': ', '.join(department_names) if department_names else 'No workspaces',
        })
    
    print(f"\n✅ Prepared {len(users_data)} users for template")
    print("="*80)
    print("🔍 USERS VIEW DEBUG END")
    print("="*80 + "\n")
    
    context = {
        'users': users_data,
        'departments': departments,
        'total_dept_admins': total_dept_admins,
        'total_departments': total_departments,
        'page_title': 'Manage Workspace Supervisors',
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
"""
✅ ISSUE #8: Updated influx_config_view with AJAX support
==========================================================
Minimal changes - same logic, just returns JSON for AJAX requests

⚠️ IMPORTANT: Add this import at the TOP of your views.py file:
    from django.http import JsonResponse
"""

# ============================================================
# ⚠️ ADD THIS IMPORT TO THE TOP OF YOUR views.py FILE:
# ============================================================
# from django.http import JsonResponse
# ============================================================


def is_ajax(request):
    """✅ ISSUE #8: Helper to check if request is AJAX"""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


@require_company_admin
def influx_config_view(request):
    """
    ✨ UPDATED: Manage MULTIPLE InfluxDB configurations
    ✅ ISSUE #8: Now supports AJAX requests - returns JSON instead of redirect
    """
    
    # ✅ ISSUE #8: Import JsonResponse here if not at top of file
    from django.http import JsonResponse
    
    debug_print("=" * 80)
    debug_print("influx_config_view() called")
    debug_print(f"User: {request.user.username}")
    debug_print(f"Method: {request.method}")
    debug_print(f"Is AJAX: {is_ajax(request)}")
    
    # Get ALL active configs
    configs = AssetConfig.objects.filter(is_active=True).order_by('config_name')
    debug_print(f"Found {configs.count()} active configurations")
    
    # ==========================================
    # POST HANDLING
    # ==========================================
    if request.method == 'POST':
        debug_print("POST request detected")
        debug_print(f"POST keys: {list(request.POST.keys())}")
        
        # ========== CREATE CONFIG ==========
        if 'create_config' in request.POST:
            debug_print("CREATE CONFIG action triggered")
            
            form = AssetConfigForm(request.POST)
            debug_print(f"Form is_valid: {form.is_valid()}")
            
            if form.is_valid():
                try:
                    config = form.save()
                    debug_print(f"Config saved! ID: {config.id}")
                    
                    # ✅ ISSUE #8: Return JSON for AJAX requests
                    if is_ajax(request):
                        return JsonResponse({
                            'success': True,
                            'message': f'Configuration "{config.config_name}" created successfully!',
                            'config_id': config.id
                        })
                    
                    messages.success(request, f'✅ Configuration "{config.config_name}" created successfully!')
                    
                except Exception as e:
                    debug_print(f"ERROR: {str(e)}")
                    
                    if is_ajax(request):
                        return JsonResponse({
                            'success': False,
                            'message': f'Error creating configuration: {str(e)}'
                        })
                    
                    messages.error(request, f'⛔ Error creating configuration: {str(e)}')
            else:
                debug_print(f"Form errors: {form.errors}")
                
                # ✅ ISSUE #8: Return JSON with field errors for AJAX
                if is_ajax(request):
                    errors = {}
                    for field, error_list in form.errors.items():
                        errors[field] = error_list[0]
                    
                    return JsonResponse({
                        'success': False,
                        'message': 'Please correct the errors below.',
                        'errors': errors
                    })
                
                messages.error(request, '⛔ Please correct the errors in the form.')
            
            return redirect('companyadmin:influx_config')
        
        # ========== EDIT CONFIG ==========
        elif 'edit_config' in request.POST:
            debug_print("EDIT CONFIG action triggered")
            
            config_id = request.POST.get('config_id')
            config = get_object_or_404(AssetConfig, id=config_id)
            debug_print(f"Editing config: {config.config_name}")
            
            form = AssetConfigEditForm(request.POST, instance=config)
            
            if form.is_valid():
                try:
                    updated_config = form.save()
                    debug_print(f"Config updated: {updated_config.config_name}")
                    
                    if is_ajax(request):
                        return JsonResponse({
                            'success': True,
                            'message': f'Configuration "{updated_config.config_name}" updated successfully!',
                            'config_id': updated_config.id
                        })
                    
                    messages.success(request, f'✅ Configuration "{updated_config.config_name}" updated successfully!')
                    
                except Exception as e:
                    debug_print(f"ERROR: {str(e)}")
                    
                    if is_ajax(request):
                        return JsonResponse({
                            'success': False,
                            'message': f'Error updating configuration: {str(e)}'
                        })
                    
                    messages.error(request, f'⛔ Error updating configuration: {str(e)}')
            else:
                debug_print(f"Form errors: {form.errors}")
                
                if is_ajax(request):
                    errors = {}
                    for field, error_list in form.errors.items():
                        errors[field] = error_list[0]
                    
                    return JsonResponse({
                        'success': False,
                        'message': 'Please correct the errors below.',
                        'errors': errors
                    })
                
                messages.error(request, '⛔ Please correct the errors in the form.')
            
            return redirect('companyadmin:influx_config')
        
        # ========== DELETE CONFIG ==========
        elif 'delete_config' in request.POST:
            debug_print("DELETE CONFIG action triggered")
            
            config_id = request.POST.get('config_id')
            config = get_object_or_404(AssetConfig, id=config_id)
            
            # Check for associated devices
            device_count = Device.objects.filter(asset_config=config).count()
            
            if device_count > 0:
                debug_print(f"Cannot delete - has {device_count} devices")
                
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
                
                debug_print(f"Config deactivated: {config_name}")
                
                if is_ajax(request):
                    return JsonResponse({
                        'success': True,
                        'message': f'Configuration "{config_name}" deleted successfully!'
                    })
                
                messages.success(request, f'✅ Configuration "{config_name}" deleted successfully!')
                
            except Exception as e:
                debug_print(f"ERROR: {str(e)}")
                
                if is_ajax(request):
                    return JsonResponse({
                        'success': False,
                        'message': f'Error deleting configuration: {str(e)}'
                    })
                
                messages.error(request, f'⛔ Error deleting configuration: {str(e)}')
            
            return redirect('companyadmin:influx_config')
        
        # ========== TEST CONNECTION ==========
        elif 'test_connection' in request.POST:
            debug_print("TEST CONNECTION action triggered")
            
            config_id = request.POST.get('config_id')
            config = get_object_or_404(AssetConfig, id=config_id)
            debug_print(f"Testing: {config.config_name} at {config.base_api}")
            
            try:
                url = f"{config.base_api}/ping"
                debug_print(f"Ping URL: {url}")
                
                response = requests.get(
                    url,
                    auth=HTTPBasicAuth(config.api_username, config.api_password),
                    verify=False,
                    timeout=5
                )
                
                debug_print(f"Response status: {response.status_code}")
                
                if response.status_code == 204:
                    config.mark_connected()
                    debug_print("Connection SUCCESSFUL")
                    
                    if is_ajax(request):
                        return JsonResponse({
                            'success': True,
                            'message': f'Connection successful! InfluxDB is reachable.',
                            'is_connected': True
                        })
                    
                    messages.success(request, f'✅ "{config.config_name}" connection successful!')
                    
                else:
                    error_msg = f'HTTP {response.status_code}'
                    config.mark_disconnected(error_msg)
                    debug_print(f"Connection FAILED: {error_msg}")
                    
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
        
        # ========== TEST CONNECTION LIVE (without saving) ==========
        # ✅ ISSUE #8: New action - test credentials before saving
        elif 'test_live' in request.POST:
            debug_print("TEST LIVE action triggered")
            
            base_api = request.POST.get('base_api', '').strip()
            api_username = request.POST.get('api_username', '').strip()
            api_password = request.POST.get('api_password', '').strip()
            
            debug_print(f"Testing live: {base_api} with user {api_username}")
            
            # Validate required fields
            if not base_api or not api_username or not api_password:
                return JsonResponse({
                    'success': False,
                    'message': 'Please fill in API Endpoint, Username, and Password.'
                })
            
            try:
                url = f"{base_api.rstrip('/')}/ping"
                debug_print(f"Ping URL: {url}")
                
                response = requests.get(
                    url,
                    auth=HTTPBasicAuth(api_username, api_password),
                    verify=False,
                    timeout=5
                )
                
                debug_print(f"Response status: {response.status_code}")
                
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
    
    # ==========================================
    # GET - Show all configs
    # ==========================================
    
    debug_print("Preparing GET response")
    
    # Prepare data for all configs
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
    
    debug_print(f"Rendering template with {total_configs} configs")
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

# companyadmin/views.py
# ... (keep all existing imports)

# ✅ ADD THIS IMPORT
from .device_func import (
    analyze_device_sensors_from_influx,
    detect_column_type,
    fetch_measurements_from_influx,
    fetch_device_ids_from_measurement,
    analyze_measurement_columns,
    save_device_with_sensors,
    debug_print
)

@require_company_admin
def device_list_view(request):
    """
    Display all devices grouped by InfluxDB Config → Measurement
    Structure: Config (collapsible) → Measurement → Devices (3 per row)
    """
    from companyadmin.models import Device, AssetConfig
    from django.db.models import Count, Q
    
    # Get all active InfluxDB configurations
    configs = AssetConfig.objects.filter(is_active=True).annotate(
        device_count=Count('devices', filter=Q(devices__is_active=True))
    ).order_by('config_name')
    
    # Build hierarchical structure: Config → Measurement → Devices
    config_data = []
    
    for config in configs:
        # Get devices for this config
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
        
        # Convert to list with measurement name
        measurements_list = []
        for meas_name, meas_devices in measurements_dict.items():
            measurements_list.append({
                'measurement_name': meas_name,
                'devices': meas_devices,
                'device_count': len(meas_devices)
            })
        
        config_data.append({
            'config': config,
            'measurements': measurements_list,
            'total_measurements': len(measurements_list),
            'total_devices': devices.count()
        })
    
    # Calculate totals
    total_configs = configs.count()
    total_devices = Device.objects.filter(is_active=True).count()
    total_measurements = Device.objects.filter(is_active=True).values('measurement_name').distinct().count()
    
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
def device_setup_wizard_view(request):
    """
    Device Setup Wizard - Multi-InfluxDB Support
    ✅ FIXED: Removed is_default references
    """
    from companyadmin.models import AssetConfig, Device
    from requests.auth import HTTPBasicAuth
    
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
    
    # ==========================================
    # STEP 0: SELECT INFLUXDB INSTANCE
    # ==========================================
    if current_step == 0:
        # ✅ FIXED: Removed -is_default from ordering
        configs = AssetConfig.objects.filter(is_active=True).order_by('config_name')
        
        if not configs.exists():
            messages.error(request, '⛔ No InfluxDB configurations found. Please configure at least one InfluxDB instance first.')
            return redirect('companyadmin:influx_config')
        
        # Handle config selection
        if request.method == 'POST' and 'select_config' in request.POST:
            selected_config_id = request.POST.get('config_id')
            
            if not selected_config_id:
                messages.error(request, '⛔ Please select an InfluxDB instance')
            else:
                try:
                    config = AssetConfig.objects.get(id=selected_config_id, is_active=True)
                    
                    # Test connection
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
        
        # Show config selection page
        context = {
            'configs': configs,
            'wizard_data': wizard_data,
            'current_step': 0,
            'page_title': 'Device Setup Wizard - Select InfluxDB',
        }
        return render(request, 'companyadmin/device_setup_wizard.html', context)
    
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
    
    # Verify connection before proceeding
    if not config.is_connected:
        messages.error(request, f'⛔ Lost connection to "{config.config_name}". Please reconfigure.')
        wizard_data['step'] = 0
        wizard_data['selected_config_id'] = None
        request.session.modified = True
        return redirect('companyadmin:device_setup_wizard')
    
    base_url = f"{config.base_api}/query"
    auth = HTTPBasicAuth(config.api_username, config.api_password)
    
    # ==========================================
    # STEP 1: SELECT MEASUREMENTS
    # ==========================================
    if current_step == 1:
        if request.method == 'POST' and 'fetch_measurements' in request.POST:
            try:
                measurements = fetch_measurements_from_influx(config)
                
                if measurements:
                    wizard_data['measurements'] = measurements
                    request.session.modified = True
                    messages.success(request, f'✅ Found {len(measurements)} measurements in "{config.config_name}"')
                else:
                    messages.info(request, f'ℹ️ No measurements found in "{config.config_name}"')
            
            except Exception as e:
                messages.error(request, f'⛔ Error: {str(e)}')
        
        elif request.method == 'POST' and 'select_measurements' in request.POST:
            selected = request.POST.getlist('selected_measurements')
            if selected:
                wizard_data['selected_measurements'] = selected
                wizard_data['step'] = 2
                request.session.modified = True
                return redirect('companyadmin:device_setup_wizard')
            else:
                messages.error(request, '⛔ Please select at least one measurement')
        
        elif request.method == 'POST' and 'back_to_config' in request.POST:
            wizard_data['step'] = 0
            wizard_data['selected_config_id'] = None
            wizard_data['measurements'] = []
            request.session.modified = True
            return redirect('companyadmin:device_setup_wizard')
    
    # ==========================================
    # STEP 2: ANALYZE COLUMNS
    # ==========================================
    elif current_step == 2:
        if request.method == 'POST' and 'select_device_columns' in request.POST:
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
        
        elif request.method == 'POST' and 'back_to_step1' in request.POST:
            wizard_data['step'] = 1
            request.session.modified = True
            return redirect('companyadmin:device_setup_wizard')
        
        if not wizard_data.get('column_analysis'):
            column_analysis = {}
            
            for measurement in wizard_data['selected_measurements']:
                column_info = analyze_measurement_columns(config, measurement)
                column_analysis[measurement] = column_info
            
            wizard_data['column_analysis'] = column_analysis
            request.session.modified = True
    
    # ==========================================
    # STEP 3: PREVIEW
    # ==========================================
    elif current_step == 3:
        if request.method == 'POST' and 'confirm_save' in request.POST:
            wizard_data['step'] = 4
            request.session.modified = True
            return redirect('companyadmin:device_setup_wizard')
        
        elif request.method == 'POST' and 'back_to_step2' in request.POST:
            wizard_data['step'] = 2
            request.session.modified = True
            return redirect('companyadmin:device_setup_wizard')
        
        if not wizard_data.get('preview_data'):
            preview_data = []
            total_devices = 0
            total_sensors = 0
            
            for measurement in wizard_data['selected_measurements']:
                device_column = wizard_data['device_columns'][measurement]
                
                device_ids = fetch_device_ids_from_measurement(config, measurement, device_column)
                
                devices_with_sensors = []
                for device_id in device_ids[:10]:
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
    
    # ==========================================
    # STEP 4: SAVE TO DATABASE
    # ==========================================
    elif current_step == 4:
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
            
            del request.session['wizard_data']
            request.session.modified = True
            
            messages.success(
                request,
                f'🎉 Success! Created {devices_created} devices, updated {devices_updated} devices, and created {sensors_created} sensors from "{config.config_name}"!'
            )
            return redirect('companyadmin:device_list')
        
        except Exception as e:
            messages.error(request, f'⛔ Error: {str(e)}')
            wizard_data['step'] = 0
            wizard_data['selected_config_id'] = None
            request.session.modified = True
            return redirect('companyadmin:device_setup_wizard')
    
    # Reset wizard completely
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
def device_edit_modal_view(request, device_id):
    """Handle device edit via AJAX (for modal)"""
    from django.http import JsonResponse
    from companyadmin.models import Device, Department
    
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
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@require_company_admin
def device_sensors_modal_view(request, device_id):
    """Return all sensors for a device (for modal display)"""
    from django.http import JsonResponse
    from companyadmin.models import Device
    
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
        
        # ✅ FIX: Add sensor_breakdown that JavaScript expects
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
            'sensor_breakdown': sensor_breakdown,  # ✅ ADD THIS
            'total_sensors': sensor_breakdown['sensors'],
            'total_fields': len(sensor_list)
        })
    
    except Device.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Device not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
@require_company_admin
def device_delete_view(request, device_id):
    """Delete device and all associated sensors"""
    from django.http import JsonResponse
    from companyadmin.models import Device
    
    if request.method == 'POST':
        try:
            device = Device.objects.get(id=device_id)
            device_name = device.display_name
            sensor_count = device.sensors.count()
            
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

# ADD THIS FORM IMPORT - THIS WAS MISSING!
from .forms import SensorMetadataForm

# Your decorator



# =============================================================================
# DEVICE CONFIGURATION ROUTER
# =============================================================================

@require_company_admin
def configure_device_router(request, device_id):
    """
    Smart router - redirects to correct config page based on device_type
    """
    device = get_object_or_404(Device, id=device_id)
    
    if device.device_type == 'asset_tracking':
        return redirect('companyadmin:asset_tracking_config', device_id=device.id)
    else:  # industrial_sensor (default)
        return redirect('companyadmin:configure_sensors', device_id=device.id)


# =============================================================================
# INDUSTRIAL SENSOR CONFIGURATION
# =============================================================================

# companyadmin/views.py

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required


from .models import Device, Sensor, SensorMetadata
from .forms import SensorMetadataForm


@require_company_admin
def configure_sensors_view(request, device_id):
    """
    Configure metadata for sensor-category fields only
    
    Shows ONLY sensors with category='sensor' (not 'info' or 'slave')
    """
    
    # Get device (no tenant filter - schema isolation handles it)
    device = get_object_or_404(Device, id=device_id)
    
    # ✅ CRITICAL: Only get sensors with category='sensor'
    sensors = Sensor.objects.filter(
        device=device,
        is_active=True,
        category='sensor'  # ✅ ONLY sensor data fields (NOT info/slave)
    ).select_related('metadata_config').order_by('field_name')
    
    if request.method == 'POST':
        sensor_id = request.POST.get('sensor_id')
        
        if not sensor_id:
            messages.error(request, "No sensor selected")
            return redirect('companyadmin:configure_sensors', device_id=device.id)
        
        try:
            # Get sensor (with category validation)
            sensor = get_object_or_404(
                Sensor, 
                id=sensor_id, 
                device=device,
                category='sensor'  # ✅ Extra validation
            )
            
            # Get or create metadata config
            metadata_config, created = SensorMetadata.objects.get_or_create(
                sensor=sensor
            )
            
            # ✅ FIXED: Convert checkbox fields to data_types list
            data_types = []
            if request.POST.get('show_time_series'):
                data_types.append('trend')
            if request.POST.get('show_latest_value'):
                data_types.append('latest_value')
            if request.POST.get('show_digital'):
                data_types.append('digital')
            
            # Default to 'trend' if nothing selected
            if not data_types:
                data_types = ['trend']
            
            # ✅ FIXED: Update metadata fields manually (bypass form for data_types)
            metadata_config.display_name = request.POST.get('display_name', sensor.field_name)
            metadata_config.unit = request.POST.get('unit', '') or None
            metadata_config.data_types = data_types  # ✅ Set as list
            
            # Handle numeric fields (allow empty)
                        # Handle numeric fields (allow empty)
            lower_limit = request.POST.get('lower_limit', '').strip()
            center_line = request.POST.get('center_line', '').strip()  # ✅ ADD THIS LINE
            upper_limit = request.POST.get('upper_limit', '').strip()

            metadata_config.lower_limit = float(lower_limit) if lower_limit else None
            metadata_config.center_line = float(center_line) if center_line else None  # ✅ Use center_line
            metadata_config.upper_limit = float(upper_limit) if upper_limit else None
                        
            # Validate limits
            if (metadata_config.lower_limit is not None and 
                metadata_config.upper_limit is not None and 
                metadata_config.lower_limit >= metadata_config.upper_limit):
                messages.error(request, "Lower limit must be less than upper limit")
                return redirect('companyadmin:configure_sensors', device_id=device.id)
            
            metadata_config.save()
            
            action = "created" if created else "updated"
            messages.success(
                request, 
                f"✅ Sensor metadata {action}: {sensor.field_name}"
            )
            
        except ValueError as e:
            messages.error(request, f"Invalid number format: {str(e)}")
        except Exception as e:
            messages.error(request, f"Error saving metadata: {str(e)}")
        
        return redirect('companyadmin:configure_sensors', device_id=device.id)
    
    # GET request - prepare sensor list with metadata
    sensors_with_metadata = []
    configured_count = 0
    
    for sensor in sensors:
        # Check if metadata exists
        try:
            metadata = sensor.metadata_config
            has_metadata = True
            configured_count += 1
            
            # ✅ FIXED: Convert data_types list to individual flags for template
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
    }
    
    return render(request, 'companyadmin/configure_sensors.html', context)
# =============================================================================
# ASSET TRACKING CONFIGURATION
# =============================================================================
@require_company_admin
def asset_tracking_config_view(request, device_id):
    """
    Asset Tracking Configuration - Location sensors and display groups
    """
    device = get_object_or_404(
        Device.objects.prefetch_related('sensors'),
        id=device_id,
        device_type='asset_tracking'
    )
    
    asset_config, created = AssetTrackingConfig.objects.get_or_create(device=device)
    
    # ===== POST: SAVE CONFIGURATION =====
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # 1. Location sensors
                lat_id = request.POST.get('latitude_sensor_id')  # ✅ FIXED: Added _id suffix
                lng_id = request.POST.get('longitude_sensor_id')  # ✅ FIXED: Added _id suffix
                
                asset_config.latitude_sensor = device.sensors.get(id=lat_id) if lat_id else None
                asset_config.longitude_sensor = device.sensors.get(id=lng_id) if lng_id else None
                asset_config.save()
                
                # 2. Map popup sensors - ✅ FIXED: Use correct field name with _ids
                map_popup_ids = request.POST.getlist('map_popup_sensor_ids')
                if map_popup_ids:
                    asset_config.map_popup_sensors.set(device.sensors.filter(id__in=map_popup_ids))
                else:
                    asset_config.map_popup_sensors.clear()
                
                # 3. Info card sensors - ✅ FIXED: Use correct field name with _ids
                info_card_ids = request.POST.getlist('info_card_sensor_ids')
                if info_card_ids:
                    asset_config.info_card_sensors.set(device.sensors.filter(id__in=info_card_ids))
                else:
                    asset_config.info_card_sensors.clear()
                
                # 4. Time series sensors - ✅ FIXED: Use correct field name with _ids
                time_series_ids = request.POST.getlist('time_series_sensor_ids')
                if time_series_ids:
                    asset_config.time_series_sensors.set(device.sensors.filter(id__in=time_series_ids))
                else:
                    asset_config.time_series_sensors.clear()
            
            messages.success(request, f'✅ Configuration saved for {device.display_name}')
            return redirect('companyadmin:device_list')
            
        except Exception as e:
            messages.error(request, f'❌ Error: {str(e)}')
            import traceback
            print(f"ERROR saving config: {traceback.format_exc()}")  # Debug
    
    # ===== GET: DISPLAY CONFIGURATION PAGE =====
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
    
    # ✅ DEBUG: Print what we're sending to template
    print(f"\n=== CONFIG VIEW DEBUG ===")
    print(f"Device: {device.display_name}")
    print(f"Total sensors: {all_sensors.count()}")
    print(f"Selected latitude: {asset_config.latitude_sensor.id if asset_config.latitude_sensor else None}")
    print(f"Selected longitude: {asset_config.longitude_sensor.id if asset_config.longitude_sensor else None}")
    print(f"Selected map popup: {selected_map_popup_ids}")
    print(f"Selected info cards: {selected_info_card_ids}")
    print(f"Selected time series: {selected_time_series_ids}")
    print(f"========================\n")
    
    context = {
        'device': device,
        'asset_config': asset_config,
        'all_sensors': all_sensors,  # ✅ FIXED: Added missing context variable
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
    }
    
    return render(request, 'companyadmin/asset_tracking_config.html', context)
# =============================================================================
# AJAX ENDPOINTS
# =============================================================================

@require_company_admin
def add_edit_sensor_metadata_view(request, sensor_id):
    """AJAX: Edit sensor metadata via modal"""
    sensor = get_object_or_404(Sensor, id=sensor_id)
    
    if request.method == 'POST':
        try:
            metadata = sensor.metadata if hasattr(sensor, 'metadata') else SensorMetadata(sensor=sensor)
            form = SensorMetadataForm(request.POST, instance=metadata)
            
            if form.is_valid():
                form.save()
                return JsonResponse({'success': True, 'message': f'✅ Saved: {sensor.field_name}'})
            else:
                return JsonResponse({'success': False, 'errors': form.errors}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    # GET: Return sensor data
    has_metadata = hasattr(sensor, 'metadata')
    
    if has_metadata:
        data = {
            'id': sensor.id,
            'field_name': sensor.field_name,
            'field_type': sensor.field_type,
            'display_name': sensor.metadata.display_name,
            'unit': sensor.metadata.unit,
            'data_types': sensor.metadata.data_types,
            'data_nature': sensor.metadata.data_nature,
            'lower_limit': sensor.metadata.lower_limit,
            'upper_limit': sensor.metadata.upper_limit,
            'center_line': sensor.metadata.center_line,
            'description': sensor.metadata.description,
            'notes': sensor.metadata.notes,
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
    """AJAX: Reset sensor metadata"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid method'}, status=400)
    
    try:
        sensor = get_object_or_404(Sensor, id=sensor_id)
        
        if hasattr(sensor, 'metadata'):
            sensor.metadata.delete()
            return JsonResponse({'success': True, 'message': f'✅ Reset: {sensor.field_name}'})
        else:
            return JsonResponse({'success': False, 'message': 'No metadata to reset'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    

