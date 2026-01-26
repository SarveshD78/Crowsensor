"""
userdashboard/views.py

User Dashboard views (read-only access).
Provides device visualization, alerts, and reports for assigned devices.
"""

import logging
from datetime import datetime

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from accounts.decorators import require_user
from companyadmin.models import (
    AssetConfig,
    AssetTrackingConfig,
    DepartmentMembership,
    Device,
    Sensor,
    SensorMetadata,
)
from departmentadmin.models import (
    DailyDeviceReport,
    DeviceUserAssignment,
    SensorAlert,
)

from .graph_helpers import (
    fetch_asset_tracking_data_for_user,
    fetch_sensor_data_for_user,
    INTERVAL_LOOKUP,
)

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_user_device_assignment(user, device_id):
    """
    Check if user has access to a device via DeviceUserAssignment.
    
    Args:
        user: User instance
        device_id: Device ID
        
    Returns:
        DeviceUserAssignment or None
    """
    try:
        return DeviceUserAssignment.objects.select_related(
            'device', 'department'
        ).get(
            user=user,
            device_id=device_id,
            is_active=True
        )
    except DeviceUserAssignment.DoesNotExist:
        return None


def get_user_departments(user):
    """
    Get user's active department memberships.
    
    Args:
        user: User instance
        
    Returns:
        QuerySet of DepartmentMembership objects
    """
    return DepartmentMembership.objects.filter(
        user=user,
        is_active=True,
        department__is_active=True
    ).select_related('department')


def get_user_assigned_device_ids(user, department_ids):
    """
    Get IDs of devices assigned to user.
    
    Args:
        user: User instance
        department_ids: List of department IDs
        
    Returns:
        list: Device IDs
    """
    return list(DeviceUserAssignment.objects.filter(
        user=user,
        department_id__in=department_ids,
        is_active=True
    ).values_list('device_id', flat=True))


# =============================================================================
# AUTHENTICATION
# =============================================================================

@require_user
def logout_view(request):
    """Logout user."""
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
    User Dashboard Home.
    
    Shows summary stats and quick access to all features.
    """
    # Get user's department memberships
    user_departments = get_user_departments(request.user)
    department_ids = list(user_departments.values_list('department_id', flat=True))
    
    # Get user's assigned devices
    assigned_devices = DeviceUserAssignment.objects.filter(
        user=request.user,
        department_id__in=department_ids,
        is_active=True
    ).select_related('device', 'department')
    
    device_ids = list(assigned_devices.values_list('device_id', flat=True))
    
    # Get alert counts
    active_alerts, recent_alerts = _get_alert_counts(device_ids)
    
    # Get available reports count
    available_reports = 0
    if device_ids:
        available_reports = DailyDeviceReport.objects.filter(
            department_id__in=department_ids,
            device_id__in=device_ids
        ).count()
    
    # Add stats to recent device assignments
    assigned_devices_with_stats = _add_device_stats(list(assigned_devices[:5]))
    
    stats = {
        'total_departments': user_departments.count(),
        'total_devices': assigned_devices.count(),
        'active_alerts': active_alerts,
        'recent_alerts': recent_alerts,
        'available_reports': available_reports,
    }
    
    context = {
        'user_departments': user_departments,
        'assigned_devices': assigned_devices_with_stats,
        'stats': stats,
        'page_title': 'Dashboard',
        'active_tab': 'home',
    }
    
    return render(request, 'userdashboard/dashboard.html', context)


def _get_alert_counts(device_ids):
    """
    Get active and recent alert counts for devices.
    
    Args:
        device_ids: List of device IDs
        
    Returns:
        tuple: (active_alerts, recent_alerts)
    """
    if not device_ids:
        return 0, 0
    
    active_alerts = SensorAlert.objects.filter(
        sensor_metadata__sensor__device_id__in=device_ids,
        status__in=['initial', 'medium', 'high']
    ).count()
    
    recent_alerts = SensorAlert.objects.filter(
        sensor_metadata__sensor__device_id__in=device_ids,
        created_at__gte=timezone.now() - timezone.timedelta(days=7)
    ).count()
    
    return active_alerts, recent_alerts


def _add_device_stats(assignments):
    """
    Add sensor_count and alert_count to device assignments.
    
    Args:
        assignments: List of DeviceUserAssignment objects
        
    Returns:
        list: Assignments with stats added
    """
    for assignment in assignments:
        assignment.sensor_count = Sensor.objects.filter(
            device=assignment.device,
            is_active=True
        ).count()
        
        assignment.alert_count = SensorAlert.objects.filter(
            sensor_metadata__sensor__device=assignment.device,
            status__in=['initial', 'medium', 'high']
        ).count()
    
    return assignments


# =============================================================================
# DEVICES VIEW
# =============================================================================

@require_user
def user_devices_view(request):
    """
    View all devices assigned to the user.
    
    Read-only - can view details and graphs.
    """
    # Get user's department memberships
    user_departments = get_user_departments(request.user)
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
    devices_by_department = _group_devices_by_department(assigned_devices)
    
    context = {
        'devices_by_department': devices_by_department,
        'total_devices': assigned_devices.count(),
        'page_title': 'My Devices',
        'active_tab': 'devices',
    }
    
    return render(request, 'userdashboard/devices.html', context)


def _group_devices_by_department(assigned_devices):
    """
    Group device assignments by department.
    
    Args:
        assigned_devices: QuerySet of DeviceUserAssignment objects
        
    Returns:
        dict: {dept_name: {'department': ..., 'devices': [...]}}
    """
    devices_by_department = {}
    
    for assignment in assigned_devices:
        dept_name = assignment.department.name
        
        if dept_name not in devices_by_department:
            devices_by_department[dept_name] = {
                'department': assignment.department,
                'devices': []
            }
        
        # Get stats for device
        sensor_count = Sensor.objects.filter(
            device=assignment.device,
            is_active=True
        ).count()
        
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
    
    return devices_by_department


# =============================================================================
# ALERTS VIEW
# =============================================================================

@require_user
def user_alerts_view(request):
    """
    View alerts for assigned devices.
    
    Read-only - cannot acknowledge or resolve.
    """
    # Get user's department memberships
    user_departments = get_user_departments(request.user)
    department_ids = list(user_departments.values_list('department_id', flat=True))
    
    # Get assigned device IDs
    assigned_device_ids = get_user_assigned_device_ids(request.user, department_ids)
    
    # Handle empty device list
    if not assigned_device_ids:
        return render(request, 'userdashboard/alerts.html', _get_empty_alerts_context())
    
    # Filter by status from URL
    status_filter = request.GET.get('status', 'all')
    
    # Base filter
    base_filter = {'sensor_metadata__sensor__device_id__in': assigned_device_ids}
    
    # Get ALL alerts for client-side filtering (limit to 100)
    all_alerts = SensorAlert.objects.filter(
        **base_filter
    ).select_related(
        'sensor_metadata',
        'sensor_metadata__sensor',
        'sensor_metadata__sensor__device'
    ).order_by('-created_at')[:100]
    
    # Apply status filter
    if status_filter == 'active':
        alerts_queryset = all_alerts.filter(status__in=['initial', 'medium', 'high'])
    elif status_filter == 'resolved':
        alerts_queryset = all_alerts.filter(status='resolved')
    else:
        alerts_queryset = all_alerts
    
    # Calculate stats
    stats = _calculate_alert_stats(base_filter)
    
    context = {
        'alerts': alerts_queryset,
        'all_alerts': all_alerts,
        'status_filter': status_filter,
        'stats': stats,
        'alert_counts': {
            'high': stats['high'],
            'medium': stats['medium'],
            'initial': stats['initial'],
            'total_resolved': stats['resolved'],
        },
        'page_title': 'Alerts',
        'active_tab': 'alerts',
    }
    
    return render(request, 'userdashboard/alerts.html', context)


def _get_empty_alerts_context():
    """Get context for empty alerts page."""
    return {
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


def _calculate_alert_stats(base_filter):
    """
    Calculate alert statistics.
    
    Args:
        base_filter: Dict with base filter criteria
        
    Returns:
        dict: Alert statistics
    """
    return {
        'total': SensorAlert.objects.filter(**base_filter).count(),
        'active': SensorAlert.objects.filter(**base_filter, status__in=['initial', 'medium', 'high']).count(),
        'resolved': SensorAlert.objects.filter(**base_filter, status='resolved').count(),
        'high': SensorAlert.objects.filter(**base_filter, status='high').count(),
        'medium': SensorAlert.objects.filter(**base_filter, status='medium').count(),
        'initial': SensorAlert.objects.filter(**base_filter, status='initial').count(),
    }


# =============================================================================
# REPORTS VIEW
# =============================================================================

@require_user
def user_reports_view(request):
    """
    View and download reports for user's assigned devices.
    
    Download only - cannot create reports.
    """
    # Get user's department memberships
    user_departments = get_user_departments(request.user)
    department_ids = list(user_departments.values_list('department_id', flat=True))
    
    # Get first department for display
    first_department = user_departments.first()
    department_name = first_department.department.name if first_department else "No Department"
    
    # Get assigned device IDs
    assigned_device_ids = get_user_assigned_device_ids(request.user, department_ids)
    
    # Handle empty device list
    if not assigned_device_ids:
        return render(request, 'userdashboard/reports.html', _get_empty_reports_context(department_name))
    
    # Get filter parameters
    filter_type = request.GET.get('type', 'all')
    filter_date_from = request.GET.get('date_from', '')
    filter_date_to = request.GET.get('date_to', '')
    page_number = request.GET.get('page', 1)
    
    # Build base queryset
    reports_queryset = DailyDeviceReport.objects.filter(
        department_id__in=department_ids,
        device_id__in=assigned_device_ids
    ).select_related('department', 'device', 'generated_by', 'generated_by__user')
    
    # Apply filters
    reports_queryset = _apply_report_filters(
        reports_queryset, filter_type, filter_date_from, filter_date_to
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
    stats = _calculate_report_stats(department_ids, assigned_device_ids)
    
    context = {
        'reports': reports_page,
        'paginator': paginator,
        'department_name': department_name,
        'assigned_devices_count': len(assigned_device_ids),
        'total_reports': stats['total'],
        'daily_reports_count': stats['daily'],
        'custom_reports_count': stats['custom'],
        'filtered_count': paginator.count,
        'filter_type': filter_type,
        'filter_date_from': filter_date_from,
        'filter_date_to': filter_date_to,
        'page_title': 'Reports',
        'active_tab': 'reports',
    }
    
    return render(request, 'userdashboard/reports.html', context)


def _get_empty_reports_context(department_name):
    """Get context for empty reports page."""
    return {
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


def _apply_report_filters(queryset, filter_type, filter_date_from, filter_date_to):
    """
    Apply filters to reports queryset.
    
    Args:
        queryset: Base reports queryset
        filter_type: 'all', 'daily', or 'custom'
        filter_date_from: Date string (YYYY-MM-DD)
        filter_date_to: Date string (YYYY-MM-DD)
        
    Returns:
        QuerySet: Filtered queryset
    """
    if filter_type == 'daily':
        queryset = queryset.filter(report_type='daily')
    elif filter_type == 'custom':
        queryset = queryset.filter(report_type='custom')
    
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


def _calculate_report_stats(department_ids, device_ids):
    """
    Calculate report statistics.
    
    Args:
        department_ids: List of department IDs
        device_ids: List of device IDs
        
    Returns:
        dict: Report statistics
    """
    base_filter = {
        'department_id__in': department_ids,
        'device_id__in': device_ids
    }
    
    return {
        'total': DailyDeviceReport.objects.filter(**base_filter).count(),
        'daily': DailyDeviceReport.objects.filter(**base_filter, report_type='daily').count(),
        'custom': DailyDeviceReport.objects.filter(**base_filter, report_type='custom').count(),
    }


@require_user
def download_report_view(request, report_id):
    """
    Download a specific report file.
    
    Validates user has access to the report's device.
    """
    # Get user's department IDs
    department_ids = list(DepartmentMembership.objects.filter(
        user=request.user,
        is_active=True,
        department__is_active=True
    ).values_list('department_id', flat=True))
    
    # Get assigned device IDs
    assigned_device_ids = get_user_assigned_device_ids(request.user, department_ids)
    
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
        logger.error(f"Error downloading report {report_id}: {e}", exc_info=True)
        messages.error(request, f'Error downloading report: {str(e)}')
        return redirect('userdashboard:user_reports')


# =============================================================================
# DEVICE VISUALIZATION ROUTER
# =============================================================================

@require_user
@require_GET
def user_device_visualization_view(request, device_id):
    """
    Router view that redirects to appropriate visualization.
    
    - industrial_sensor -> graphs page
    - asset_tracking -> asset map page
    """
    assignment = get_user_device_assignment(request.user, device_id)
    if not assignment:
        raise PermissionDenied("You don't have access to this device.")
    
    device = assignment.device
    
    if device.device_type == 'asset_tracking':
        return redirect('userdashboard:user_device_asset_map', device_id=device_id)
    else:
        return redirect('userdashboard:user_device_graphs', device_id=device_id)


# =============================================================================
# INDUSTRIAL SENSOR GRAPHS
# =============================================================================

@require_user
@require_GET
def user_device_graphs_page_view(request, device_id):
    """
    Renders the industrial sensor graphs page.
    
    Template makes AJAX calls to user_device_graphs_data for data.
    """
    assignment = get_user_device_assignment(request.user, device_id)
    if not assignment:
        raise PermissionDenied("You don't have access to this device.")
    
    device = assignment.device
    
    # Get sensor counts
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


@require_user
@require_GET
def user_device_graphs_view(request, device_id):
    """
    API endpoint that returns sensor data for charts (JSON).
    
    Called via AJAX from the graphs template.
    """
    assignment = get_user_device_assignment(request.user, device_id)
    if not assignment:
        return JsonResponse({
            'success': False,
            'message': 'Access denied to this device'
        }, status=403)
    
    device = assignment.device
    time_range = request.GET.get('time_range', 'now() - 1h')
    
    try:
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
        logger.error(f"Error fetching sensor data for device {device_id}: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)


# =============================================================================
# ASSET TRACKING MAP
# =============================================================================

@require_user
@require_GET
def user_device_asset_map_view(request, device_id):
    """
    Renders the asset tracking map page.
    
    Template makes AJAX calls to user_device_asset_map_data for location data.
    """
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


@require_user
@require_GET
def user_device_asset_map_data_view(request, device_id):
    """
    API endpoint that returns asset tracking location data (JSON).
    
    Called via AJAX from the asset map template.
    """
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
    
    time_range = request.GET.get('time_range', 'now() - 24h')
    
    try:
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
        logger.error(f"Error fetching asset tracking data for device {device_id}: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)