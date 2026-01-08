# userdashboard/views.py - USER DASHBOARD (READ-ONLY)

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import logout
from django.http import FileResponse, Http404, JsonResponse
from django.db.models import Q, Count
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from django.core.exceptions import PermissionDenied

import json
import logging
from datetime import datetime

from accounts.decorators import require_user
from companyadmin.models import (
    DepartmentMembership,
    Sensor,
    SensorMetadata,
    Device,
    AssetTrackingConfig,
    AssetConfig,
)
from departmentadmin.models import (
    DeviceUserAssignment,
    SensorAlert,
    DailyDeviceReport,
)

# Import from separate graph_helpers file (uses metadata_config)
from .graph_helpers import (
    fetch_sensor_data_for_user,
    fetch_asset_tracking_data_for_user,
    INTERVAL_LOOKUP,
)

logger = logging.getLogger(__name__)


# =============================================================================
# AUTHENTICATION
# =============================================================================

@require_user
def logout_view(request):
    """Logout user"""
    username = request.user.get_full_name_or_username()
    logout(request)
    messages.success(request, f'👋 Goodbye {username}! You have been logged out successfully.')
    return redirect('accounts:login')


# =============================================================================
# DASHBOARD HOME
# =============================================================================
@require_user
def user_home_view(request):
    """
    User Dashboard Home
    Shows summary stats and quick access to all features
    """
    
    # Get user's department memberships
    user_departments = DepartmentMembership.objects.filter(
        user=request.user,
        is_active=True,
        department__is_active=True
    ).select_related('department')
    
    department_ids = list(user_departments.values_list('department_id', flat=True))
    
    # Get user's assigned devices
    assigned_devices = DeviceUserAssignment.objects.filter(
        user=request.user,
        department_id__in=department_ids,
        is_active=True
    ).select_related('device', 'department')
    
    device_ids = list(assigned_devices.values_list('device_id', flat=True))
    
    # Get active alerts for assigned devices
    active_alerts = 0
    recent_alerts = 0
    
    if device_ids:
        active_alerts = SensorAlert.objects.filter(
            sensor_metadata__sensor__device_id__in=device_ids,
            status__in=['initial', 'medium', 'high']
        ).count()
        
        # Get recent alerts (last 7 days)
        recent_alerts = SensorAlert.objects.filter(
            sensor_metadata__sensor__device_id__in=device_ids,
            created_at__gte=timezone.now() - timezone.timedelta(days=7)
        ).count()
    
    # Get available reports count
    available_reports = 0
    if device_ids:
        available_reports = DailyDeviceReport.objects.filter(
            department_id__in=department_ids,
            device_id__in=device_ids
        ).count()
    
    # ✅ FIX: Add sensor_count and alert_count to each assignment
    assigned_devices_with_stats = []
    for assignment in assigned_devices[:5]:
        # Get sensor count for device
        sensor_count = Sensor.objects.filter(
            device=assignment.device,
            is_active=True
        ).count()
        
        # Get active alerts for device
        alert_count = SensorAlert.objects.filter(
            sensor_metadata__sensor__device=assignment.device,
            status__in=['initial', 'medium', 'high']
        ).count()
        
        # Attach to assignment object
        assignment.sensor_count = sensor_count
        assignment.alert_count = alert_count
        assigned_devices_with_stats.append(assignment)
    
    # Stats
    stats = {
        'total_departments': user_departments.count(),
        'total_devices': assigned_devices.count(),
        'active_alerts': active_alerts,
        'recent_alerts': recent_alerts,
        'available_reports': available_reports,
    }
    
    context = {
        'user_departments': user_departments,
        'assigned_devices': assigned_devices_with_stats,  # ✅ Now has sensor_count & alert_count
        'stats': stats,
        'page_title': 'Dashboard',
        'active_tab': 'home',
    }
    
    return render(request, 'userdashboard/dashboard.html', context)
# =============================================================================
# DEVICES VIEW
# =============================================================================

@require_user
def user_devices_view(request):
    """
    View all devices assigned to the user
    Read-only - can view details and graphs
    """
    
    # Get user's department memberships
    user_departments = DepartmentMembership.objects.filter(
        user=request.user,
        is_active=True,
        department__is_active=True
    ).select_related('department')
    
    department_ids = list(user_departments.values_list('department_id', flat=True))
    
    # Get assigned devices with related data
    assigned_devices = DeviceUserAssignment.objects.filter(
        user=request.user,
        department_id__in=department_ids,
        is_active=True
    ).select_related(
        'device',
        'device__asset_config',
        'department'
    ).order_by('department__name', 'device__display_name')
    
    # Group devices by department
    devices_by_department = {}
    for assignment in assigned_devices:
        dept_name = assignment.department.name
        if dept_name not in devices_by_department:
            devices_by_department[dept_name] = {
                'department': assignment.department,
                'devices': []
            }
        
        # Get sensor count for device
        sensor_count = Sensor.objects.filter(
            device=assignment.device,
            is_active=True
        ).count()
        
        # Get active alerts for device
        alert_count = SensorAlert.objects.filter(
            sensor_metadata__sensor__device=assignment.device,
            status__in=['initial', 'medium', 'high']
        ).count()
        
        devices_by_department[dept_name]['devices'].append({
            'assignment': assignment,
            'device': assignment.device,
            'sensor_count': sensor_count,
            'alert_count': alert_count,
        })
    
    context = {
        'devices_by_department': devices_by_department,
        'total_devices': assigned_devices.count(),
        'page_title': 'My Devices',
        'active_tab': 'devices',
    }
    
    return render(request, 'userdashboard/devices.html', context)


# =============================================================================
# ALERTS VIEW
# =============================================================================

@require_user
def user_alerts_view(request):
    """
    View alerts for assigned devices
    Read-only - cannot acknowledge or resolve
    Matches department admin alerts UI/UX
    """
    
    # Get user's department memberships
    user_departments = DepartmentMembership.objects.filter(
        user=request.user,
        is_active=True,
        department__is_active=True
    ).select_related('department')
    
    department_ids = list(user_departments.values_list('department_id', flat=True))
    
    # Get assigned device IDs
    assigned_device_ids = list(DeviceUserAssignment.objects.filter(
        user=request.user,
        department_id__in=department_ids,
        is_active=True
    ).values_list('device_id', flat=True))
    
    # Handle empty device list
    if not assigned_device_ids:
        context = {
            'alerts': [],
            'all_alerts': [],
            'status_filter': 'all',
            'stats': {
                'total': 0,
                'active': 0,
                'resolved': 0,
                'high': 0,
                'medium': 0,
                'initial': 0,
            },
            'alert_counts': {
                'high': 0,
                'medium': 0,
                'initial': 0,
                'total_resolved': 0,
            },
            'page_title': 'Alerts',
            'active_tab': 'alerts',
        }
        return render(request, 'userdashboard/alerts.html', context)
    
    # Filter by status from URL
    status_filter = request.GET.get('status', 'all')
    
    # Base queryset - Path: SensorAlert → sensor_metadata → sensor → device
    base_filter = {'sensor_metadata__sensor__device_id__in': assigned_device_ids}
    
    # Get ALL alerts for the user (for client-side filtering)
    all_alerts = SensorAlert.objects.filter(
        **base_filter
    ).select_related(
        'sensor_metadata',
        'sensor_metadata__sensor',
        'sensor_metadata__sensor__device'
    ).order_by('-created_at')[:100]  # Limit to 100 for performance
    
    # Apply status filter for backward compatibility
    if status_filter == 'active':
        alerts_queryset = all_alerts.filter(status__in=['initial', 'medium', 'high'])
    elif status_filter == 'resolved':
        alerts_queryset = all_alerts.filter(status='resolved')
    else:
        alerts_queryset = all_alerts
    
    # Calculate stats
    total_alerts = SensorAlert.objects.filter(**base_filter).count()
    active_alerts = SensorAlert.objects.filter(**base_filter, status__in=['initial', 'medium', 'high']).count()
    resolved_alerts = SensorAlert.objects.filter(**base_filter, status='resolved').count()
    
    # Alert status counts
    high_alerts = SensorAlert.objects.filter(**base_filter, status='high').count()
    medium_alerts = SensorAlert.objects.filter(**base_filter, status='medium').count()
    initial_alerts = SensorAlert.objects.filter(**base_filter, status='initial').count()
    
    context = {
        'alerts': alerts_queryset,
        'all_alerts': all_alerts,
        'status_filter': status_filter,
        'stats': {
            'total': total_alerts,
            'active': active_alerts,
            'resolved': resolved_alerts,
            'high': high_alerts,
            'medium': medium_alerts,
            'initial': initial_alerts,
        },
        'alert_counts': {
            'high': high_alerts,
            'medium': medium_alerts,
            'initial': initial_alerts,
            'total_resolved': resolved_alerts,
        },
        'page_title': 'Alerts',
        'active_tab': 'alerts',
    }
    
    return render(request, 'userdashboard/alerts.html', context)


# =============================================================================
# REPORTS VIEW
# =============================================================================

@require_user
def user_reports_view(request):
    """
    View and download reports for user's assigned devices
    Download only - cannot create reports
    """
    
    # Get user's department memberships
    user_departments = DepartmentMembership.objects.filter(
        user=request.user,
        is_active=True,
        department__is_active=True
    ).select_related('department')
    
    department_ids = list(user_departments.values_list('department_id', flat=True))
    
    # Get first department for display
    first_department = user_departments.first()
    department_name = first_department.department.name if first_department else "No Department"
    
    # Get assigned device IDs
    assigned_device_ids = list(DeviceUserAssignment.objects.filter(
        user=request.user,
        department_id__in=department_ids,
        is_active=True
    ).values_list('device_id', flat=True))
    
    # Handle empty device list
    if not assigned_device_ids:
        context = {
            'reports': [],
            'paginator': None,
            'department_name': department_name,
            'total_reports': 0,
            'daily_reports_count': 0,
            'custom_reports_count': 0,
            'filtered_count': 0,
            'filter_type': 'all',
            'filter_date_from': '',
            'filter_date_to': '',
            'page_title': 'Reports',
            'active_tab': 'reports',
        }
        return render(request, 'userdashboard/reports.html', context)
    
    # GET FILTER PARAMETERS
    filter_type = request.GET.get('type', 'all')
    filter_date_from = request.GET.get('date_from', '')
    filter_date_to = request.GET.get('date_to', '')
    page_number = request.GET.get('page', 1)
    
    # BUILD BASE QUERYSET
    reports_queryset = DailyDeviceReport.objects.filter(
        department_id__in=department_ids,
        device_id__in=assigned_device_ids
    ).select_related('department', 'device', 'generated_by', 'generated_by__user')
    
    # APPLY FILTERS
    if filter_type == 'daily':
        reports_queryset = reports_queryset.filter(report_type='daily')
    elif filter_type == 'custom':
        reports_queryset = reports_queryset.filter(report_type='custom')
    
    if filter_date_from:
        try:
            date_from = datetime.strptime(filter_date_from, '%Y-%m-%d').date()
            reports_queryset = reports_queryset.filter(report_date__gte=date_from)
        except ValueError:
            pass
    
    if filter_date_to:
        try:
            date_to = datetime.strptime(filter_date_to, '%Y-%m-%d').date()
            reports_queryset = reports_queryset.filter(report_date__lte=date_to)
        except ValueError:
            pass
    
    # ORDER AND PAGINATE
    reports_queryset = reports_queryset.order_by('-created_at', '-report_date')
    
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    
    paginator = Paginator(reports_queryset, 20)
    
    try:
        reports_page = paginator.page(page_number)
    except PageNotAnInteger:
        reports_page = paginator.page(1)
    except EmptyPage:
        reports_page = paginator.page(paginator.num_pages)
    
    # CALCULATE STATISTICS
    total_reports = DailyDeviceReport.objects.filter(
        department_id__in=department_ids,
        device_id__in=assigned_device_ids
    ).count()
    
    daily_reports_count = DailyDeviceReport.objects.filter(
        department_id__in=department_ids,
        device_id__in=assigned_device_ids,
        report_type='daily'
    ).count()
    
    custom_reports_count = DailyDeviceReport.objects.filter(
        department_id__in=department_ids,
        device_id__in=assigned_device_ids,
        report_type='custom'
    ).count()
    
    filtered_count = paginator.count
    
    context = {
        'reports': reports_page,
        'paginator': paginator,
        'department_name': department_name,
        'assigned_devices_count': len(assigned_device_ids),
        'total_reports': total_reports,
        'daily_reports_count': daily_reports_count,
        'custom_reports_count': custom_reports_count,
        'filtered_count': filtered_count,
        'filter_type': filter_type,
        'filter_date_from': filter_date_from,
        'filter_date_to': filter_date_to,
        'page_title': 'Reports',
        'active_tab': 'reports',
    }
    
    return render(request, 'userdashboard/reports.html', context)


@require_user
def download_report_view(request, report_id):
    """
    Download a specific report file
    Validates user has access to the report's device
    """
    
    # Get user's department IDs
    department_ids = list(DepartmentMembership.objects.filter(
        user=request.user,
        is_active=True,
        department__is_active=True
    ).values_list('department_id', flat=True))
    
    # Get assigned device IDs
    assigned_device_ids = list(DeviceUserAssignment.objects.filter(
        user=request.user,
        department_id__in=department_ids,
        is_active=True
    ).values_list('device_id', flat=True))
    
    # Get report and verify access
    report = get_object_or_404(
        DailyDeviceReport,
        id=report_id,
        department_id__in=department_ids,
        device_id__in=assigned_device_ids
    )
    
    # Check if file exists
    if not report.csv_file or not report.csv_file.name:
        messages.error(request, 'Report file not found.')
        return redirect('userdashboard:user_reports')
    
    try:
        response = FileResponse(
            report.csv_file.open('rb'),
            as_attachment=True,
            filename=f"report_{report.device.display_name}_{report.report_date}.csv"
        )
        return response
    except Exception as e:
        messages.error(request, f'Error downloading report: {str(e)}')
        return redirect('userdashboard:user_reports')


# =============================================================================
# HELPER: Get user's device assignment (access control)
# =============================================================================

def get_user_device_assignment(user, device_id):
    """
    Check if user has access to this device via DeviceUserAssignment.
    Returns the assignment object if access granted, None otherwise.
    """
    try:
        assignment = DeviceUserAssignment.objects.select_related(
            'device', 'department'
        ).get(
            user=user,
            device_id=device_id,
            is_active=True
        )
        return assignment
    except DeviceUserAssignment.DoesNotExist:
        return None


# =============================================================================
# VIEW: DEVICE VISUALIZATION ROUTER
# =============================================================================

@require_user
@require_GET
def user_device_visualization_view(request, device_id):
    """
    Router view that checks device type and redirects to appropriate view.
    - industrial_sensor -> user_device_graphs_page
    - asset_tracking -> user_device_asset_map
    """
    # Check user has access to this device
    assignment = get_user_device_assignment(request.user, device_id)
    if not assignment:
        raise PermissionDenied("You don't have access to this device.")
    
    device = assignment.device
    
    # Route based on device type
    if device.device_type == 'asset_tracking':
        return redirect('userdashboard:user_device_asset_map', device_id=device_id)
    else:
        # Default to industrial sensor graphs
        return redirect('userdashboard:user_device_graphs', device_id=device_id)


# =============================================================================
# VIEW: INDUSTRIAL SENSOR GRAPHS PAGE
# =============================================================================

@require_user
@require_GET
def user_device_graphs_page_view(request, device_id):
    """
    Renders the industrial sensor graphs page.
    Template makes AJAX calls to user_device_graphs_data for data.
    """
    # Check user has access to this device
    assignment = get_user_device_assignment(request.user, device_id)
    if not assignment:
        raise PermissionDenied("You don't have access to this device.")
    
    device = assignment.device
    
    # Get sensor count for display - use metadata_config
    sensor_count = device.sensors.filter(is_active=True).count()
    configured_count = device.sensors.filter(
        is_active=True, 
        metadata_config__isnull=False
    ).count()
    
    context = {
        'device': device,
        'assignment': assignment,
        'sensor_count': sensor_count,
        'configured_count': configured_count,
        'page_title': f'Graphs - {device.display_name}',
    }
    
    return render(request, 'userdashboard/device_graphs.html', context)


# =============================================================================
# VIEW: INDUSTRIAL SENSOR GRAPHS DATA API (JSON)
# =============================================================================

@require_user
@require_GET
def user_device_graphs_view(request, device_id):
    """
    API endpoint that returns sensor data for charts.
    Called via AJAX from the graphs template.
    Returns JSON with timestamps and sensor values.
    """
    # Check user has access to this device
    assignment = get_user_device_assignment(request.user, device_id)
    if not assignment:
        return JsonResponse({
            'success': False,
            'message': 'Access denied to this device'
        }, status=403)
    
    device = assignment.device
    
    # Get time range from request
    time_range = request.GET.get('time_range', 'now() - 1h')
    
    try:
        # Fetch sensor data from InfluxDB using user-specific helper
        data = fetch_sensor_data_for_user(device, time_range)
        
        return JsonResponse({
            'success': True,
            'device': {
                'id': device.id,
                'device_id': device.device_id,
                'display_name': device.display_name,
                'measurement_name': device.measurement_name,
            },
            'time_range': time_range,
            'data': data
        })
        
    except Exception as e:
        logger.error(f"Error fetching sensor data for device {device_id}: {e}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


# =============================================================================
# VIEW: ASSET TRACKING MAP PAGE
# =============================================================================

@require_user
@require_GET
def user_device_asset_map_view(request, device_id):
    """
    Renders the asset tracking map page.
    Template makes AJAX calls to user_device_asset_map_data for location data.
    """
    # Check user has access to this device
    assignment = get_user_device_assignment(request.user, device_id)
    if not assignment:
        raise PermissionDenied("You don't have access to this device.")
    
    device = assignment.device
    
    # Verify this is an asset tracking device
    if device.device_type != 'asset_tracking':
        return redirect('userdashboard:user_device_graphs_page', device_id=device_id)
    
    # Get asset tracking configuration
    try:
        tracking_config = AssetTrackingConfig.objects.select_related(
            'latitude_sensor', 'longitude_sensor'
        ).prefetch_related(
            'map_popup_sensors', 'info_card_sensors', 'time_series_sensors'
        ).get(device=device)
    except AssetTrackingConfig.DoesNotExist:
        tracking_config = None
    
    context = {
        'device': device,
        'assignment': assignment,
        'tracking_config': tracking_config,
        'has_location_config': tracking_config.has_location_config if tracking_config else False,
        'page_title': f'Asset Map - {device.display_name}',
    }
    
    return render(request, 'userdashboard/device_asset_map.html', context)


# =============================================================================
# VIEW: ASSET TRACKING MAP DATA API (JSON)
# =============================================================================

@require_user
@require_GET
def user_device_asset_map_data_view(request, device_id):
    """
    API endpoint that returns asset tracking location data.
    Called via AJAX from the asset map template.
    Returns JSON with location history and current position.
    """
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
    
    # Get time range from request
    time_range = request.GET.get('time_range', 'now() - 24h')
    
    try:
        # Fetch asset tracking data from InfluxDB using user-specific helper
        data = fetch_asset_tracking_data_for_user(device, time_range)
        
        return JsonResponse({
            'success': True,
            'device': {
                'id': device.id,
                'device_id': device.device_id,
                'display_name': device.display_name,
            },
            'time_range': time_range,
            'data': data
        })
        
    except Exception as e:
        logger.error(f"Error fetching asset tracking data for device {device_id}: {e}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)