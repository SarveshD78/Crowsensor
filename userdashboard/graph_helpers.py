"""
userdashboard/graph_helpers.py

Graph helper functions for User Dashboard.
Fetches time-series data from InfluxDB with bucketing.
Uses metadata_config field for sensor metadata.
"""

import logging
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)


# Time range to bucket interval mapping (approximately 30 data points)
INTERVAL_LOOKUP = {
    'now() - 15m': '30s',
    'now() - 30m': '1m',
    'now() - 1h': '2m',
    'now() - 2h': '4m',
    'now() - 3h': '6m',
    'now() - 6h': '12m',
    'now() - 12h': '24m',
    'now() - 24h': '48m',
    'now() - 2d': '96m',
    'now() - 7d': '336m',
    'now() - 30d': '1440m'
}


# =============================================================================
# INFLUXDB CONFIGURATION
# =============================================================================

def get_influxdb_config_for_user(device):
    """
    Get InfluxDB configuration for a device.
    
    Args:
        device: Device model instance
        
    Returns:
        AssetConfig instance or None
    """
    from companyadmin.models import AssetConfig
    
    if device.asset_config:
        return device.asset_config
    
    # Fallback to default config
    return AssetConfig.objects.filter(is_active=True).first()


# =============================================================================
# SENSOR DATA FETCHING
# =============================================================================

def fetch_sensor_data_for_user(device, time_range='now() - 1h'):
    """
    Fetch sensor data from InfluxDB for all active sensors on a device.
    
    Returns structured data for frontend charts.
    Uses metadata_config field (correct related_name for SensorMetadata).
    
    Args:
        device: Device model instance
        time_range: InfluxDB time range string
        
    Returns:
        dict: {'timestamps': [...], 'sensors': [...]}
    """
    config = get_influxdb_config_for_user(device)
    if not config:
        raise Exception("No InfluxDB configuration found")
    
    # Get all active sensors for this device
    sensors = device.sensors.filter(is_active=True).select_related('metadata_config')
    
    if not sensors.exists():
        return {'timestamps': [], 'sensors': []}
    
    # Get InfluxDB details from device metadata
    influx_measurement_id = _get_measurement_id(device)
    device_column = _get_device_column(device)
    
    # Build field list for query
    field_names = [sensor.field_name for sensor in sensors]
    field_select = ', '.join([f'mean("{f}") AS "{f}"' for f in field_names])
    
    # Get interval for time bucketing
    interval = INTERVAL_LOOKUP.get(time_range, '2m')
    
    # Build and execute query
    query = f'''
        SELECT {field_select}
        FROM "{influx_measurement_id}"
        WHERE time >= {time_range}
        AND time <= now()
        AND "{device_column}" = '{device.device_id}'
        GROUP BY time({interval}) fill(null)
        ORDER BY time ASC
        tz('Asia/Kolkata')
    '''
    
    result = _execute_influx_query(config, query)
    
    # Parse response
    timestamps, sensor_data = _parse_sensor_response(result, sensors)
    
    # Fetch latest values separately for gauges
    latest_values = fetch_latest_values_for_user(device, config)
    
    # Build response structure
    sensors_response = _build_sensors_response(sensors, sensor_data, latest_values)
    
    return {
        'timestamps': timestamps,
        'sensors': sensors_response,
    }


def fetch_latest_values_for_user(device, config):
    """
    Fetch the most recent value for each sensor.
    
    Args:
        device: Device model instance
        config: AssetConfig instance
        
    Returns:
        dict: {field_name: latest_value, ...}
    """
    sensors = device.sensors.filter(is_active=True)
    if not sensors.exists():
        return {}
    
    influx_measurement_id = _get_measurement_id(device)
    device_column = _get_device_column(device)
    
    field_names = [sensor.field_name for sensor in sensors]
    field_select = ', '.join([f'last("{f}") AS "{f}"' for f in field_names])
    
    query = f'''
        SELECT {field_select}
        FROM "{influx_measurement_id}"
        WHERE "{device_column}" = '{device.device_id}'
        tz('Asia/Kolkata')
    '''
    
    try:
        result = _execute_influx_query(config, query, timeout=15)
    except Exception as e:
        logger.error(f"Error fetching latest values: {e}")
        return {}
    
    return _parse_latest_values(result)


# =============================================================================
# ASSET TRACKING DATA
# =============================================================================

def fetch_asset_tracking_data_for_user(device, time_range='now() - 24h'):
    """
    Fetch asset tracking location data from InfluxDB.
    
    Returns location history and additional sensor data.
    Uses metadata_config field (correct related_name for SensorMetadata).
    
    Args:
        device: Device model instance
        time_range: InfluxDB time range string
        
    Returns:
        dict: Location data with points, current location, info card data
    """
    from companyadmin.models import AssetTrackingConfig
    
    config = get_influxdb_config_for_user(device)
    if not config:
        raise Exception("No InfluxDB configuration found")
    
    # Get asset tracking configuration
    try:
        tracking_config = AssetTrackingConfig.objects.select_related(
            'latitude_sensor', 'longitude_sensor'
        ).prefetch_related(
            'map_popup_sensors', 'info_card_sensors', 'time_series_sensors'
        ).get(device=device)
    except AssetTrackingConfig.DoesNotExist:
        raise Exception("Asset tracking not configured for this device")
    
    if not tracking_config.has_location_config:
        raise Exception("Latitude/Longitude sensors not configured")
    
    # Build field list and sensor groups
    fields, all_sensors = _build_tracking_fields(tracking_config)
    
    # Get InfluxDB details
    influx_measurement_id = _get_measurement_id(device)
    device_column = _get_device_column(device)
    
    field_select = ', '.join([f'"{f}"' for f in fields])
    
    # Query for location history
    query = f'''
        SELECT {field_select}
        FROM "{influx_measurement_id}"
        WHERE time >= {time_range}
        AND time <= now()
        AND "{device_column}" = '{device.device_id}'
        ORDER BY time ASC
        tz('Asia/Kolkata')
    '''
    
    result = _execute_influx_query(config, query)
    
    # Parse location points
    lat_field = tracking_config.latitude_sensor.field_name
    lng_field = tracking_config.longitude_sensor.field_name
    
    points = _parse_location_points(result, lat_field, lng_field, all_sensors)
    
    # Mark start and end points
    if points:
        points[0]['is_start'] = True
        points[-1]['is_end'] = True
    
    # Get current location (latest)
    current_location = points[-1] if points else None
    
    # Fetch latest info card data
    info_sensors = tracking_config.info_card_sensors.all()
    info_card_data = {}
    if info_sensors:
        info_field_names = [s.field_name for s in info_sensors]
        info_card_data = fetch_latest_info_card_data_for_user(device, config, info_field_names)
    
    return {
        'points': points,
        'locations': points,  # Alias for compatibility
        'current_location': current_location,
        'info_card_data': info_card_data,
        'total_points': len(points),
        'start_point': points[0] if points else None,
        'end_point': points[-1] if points else None,
        'location_count': len(points),
    }


def fetch_latest_info_card_data_for_user(device, config, field_names):
    """
    Fetch latest values for info card display.
    
    Args:
        device: Device model instance
        config: AssetConfig instance
        field_names: List of field names to fetch
        
    Returns:
        dict: {field_name: value, ...}
    """
    if not field_names:
        return {}
    
    influx_measurement_id = _get_measurement_id(device)
    device_column = _get_device_column(device)
    
    field_select = ', '.join([f'last("{f}") AS "{f}"' for f in field_names])
    
    query = f'''
        SELECT {field_select}
        FROM "{influx_measurement_id}"
        WHERE "{device_column}" = '{device.device_id}'
        tz('Asia/Kolkata')
    '''
    
    try:
        result = _execute_influx_query(config, query, timeout=15)
    except Exception:
        return {}
    
    return _parse_latest_values(result)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_measurement_id(device):
    """Get InfluxDB measurement ID from device metadata."""
    if device.metadata:
        return device.metadata.get('influx_measurement_id', device.measurement_name)
    return device.measurement_name


def _get_device_column(device):
    """Get device column name from device metadata."""
    if device.metadata:
        return device.metadata.get('device_column', 'id')
    return 'id'


def _execute_influx_query(config, query, timeout=30):
    """
    Execute InfluxDB query.
    
    Args:
        config: AssetConfig instance
        query: InfluxDB query string
        timeout: Request timeout in seconds
        
    Returns:
        dict: Parsed JSON response
        
    Raises:
        Exception: On query failure
    """
    try:
        response = requests.get(
            f"{config.base_api}/query",
            params={'db': config.db_name, 'q': query},
            auth=HTTPBasicAuth(config.api_username, config.api_password),
            timeout=timeout,
            verify=False
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"InfluxDB query error: {e}")
        raise Exception(f"Failed to fetch data from InfluxDB: {e}")


def _parse_timestamp(timestamp_str):
    """
    Parse timestamp from InfluxDB format.
    
    Args:
        timestamp_str: Timestamp string from InfluxDB
        
    Returns:
        str: Formatted timestamp or original string on error
    """
    try:
        if '+' in timestamp_str:
            timestamp_str_naive = timestamp_str.split('+')[0]
        elif timestamp_str.endswith('Z'):
            timestamp_str_naive = timestamp_str.replace('Z', '')
        else:
            timestamp_str_naive = timestamp_str
        
        # Handle fractional seconds
        if '.' in timestamp_str_naive:
            parts = timestamp_str_naive.split('.')
            if len(parts) == 2:
                date_time_part = parts[0]
                fractional_part = parts[1][:6]
                timestamp_str_naive = f"{date_time_part}.{fractional_part}"
        
        try:
            dt = datetime.strptime(timestamp_str_naive, '%Y-%m-%dT%H:%M:%S.%f')
        except ValueError:
            dt = datetime.strptime(timestamp_str_naive, '%Y-%m-%dT%H:%M:%S')
        
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return timestamp_str


def _parse_sensor_response(result, sensors):
    """
    Parse InfluxDB response for sensor data.
    
    Args:
        result: InfluxDB JSON response
        sensors: QuerySet of Sensor objects
        
    Returns:
        tuple: (timestamps list, sensor_data dict)
    """
    timestamps = []
    sensor_data = {sensor.field_name: [] for sensor in sensors}
    
    if not result.get('results') or not result['results'][0].get('series'):
        return timestamps, sensor_data
    
    series = result['results'][0]['series'][0]
    columns = series.get('columns', [])
    values = series.get('values', [])
    
    time_idx = columns.index('time') if 'time' in columns else 0
    
    for row in values:
        timestamps.append(_parse_timestamp(row[time_idx]))
        
        for sensor in sensors:
            try:
                field_idx = columns.index(sensor.field_name)
                sensor_data[sensor.field_name].append(row[field_idx])
            except (ValueError, IndexError):
                sensor_data[sensor.field_name].append(None)
    
    return timestamps, sensor_data


def _parse_latest_values(result):
    """
    Parse latest values from InfluxDB response.
    
    Args:
        result: InfluxDB JSON response
        
    Returns:
        dict: {field_name: value, ...}
    """
    latest = {}
    
    if not result.get('results') or not result['results'][0].get('series'):
        return latest
    
    series = result['results'][0]['series'][0]
    columns = series.get('columns', [])
    values = series.get('values', [[]])[0]
    
    for i, col in enumerate(columns):
        if col != 'time' and i < len(values):
            latest[col] = values[i]
    
    return latest


def _build_sensors_response(sensors, sensor_data, latest_values):
    """
    Build sensors response structure with metadata.
    
    Args:
        sensors: QuerySet of Sensor objects
        sensor_data: Dict of sensor values
        latest_values: Dict of latest values
        
    Returns:
        list: Sensor response dictionaries
    """
    sensors_response = []
    
    for sensor in sensors:
        values_list = sensor_data.get(sensor.field_name, [])
        
        # Get metadata if exists
        metadata = None
        display_name = sensor.display_name or sensor.field_name
        unit = sensor.unit or ''
        
        if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
            sensor_metadata = sensor.metadata_config
            data_types = sensor_metadata.data_types or ['trend']
            
            metadata = {
                'data_types': data_types,
                'upper_limit': sensor_metadata.upper_limit,
                'lower_limit': sensor_metadata.lower_limit,
                'center_line': sensor_metadata.center_line,
                'data_nature': getattr(sensor_metadata, 'data_nature', 'spot'),
                'show_time_series': 'trend' in data_types,
                'show_latest_value': 'latest_value' in data_types,
                'show_digital': 'digital' in data_types,
            }
            
            display_name = sensor_metadata.display_name or sensor.display_name or sensor.field_name
            unit = sensor_metadata.unit or sensor.unit or ''
        
        sensors_response.append({
            'id': sensor.id,
            'field_name': sensor.field_name,
            'display_name': display_name,
            'unit': unit,
            'category': getattr(sensor, 'category', ''),
            'values': values_list,
            'latest_value': latest_values.get(sensor.field_name),
            'metadata': metadata,
        })
    
    return sensors_response


def _build_tracking_fields(tracking_config):
    """
    Build field list and sensor groups for asset tracking.
    
    Args:
        tracking_config: AssetTrackingConfig instance
        
    Returns:
        tuple: (fields list, all_sensors dict)
    """
    lat_field = tracking_config.latitude_sensor.field_name
    lng_field = tracking_config.longitude_sensor.field_name
    
    fields = [lat_field, lng_field]
    all_sensors = {}
    
    # Add popup sensors
    for sensor in tracking_config.map_popup_sensors.all():
        if sensor.field_name not in fields:
            fields.append(sensor.field_name)
        all_sensors[sensor.field_name] = {
            'sensor': sensor,
            'groups': ['popup']
        }
    
    # Add info card sensors
    for sensor in tracking_config.info_card_sensors.all():
        if sensor.field_name not in fields:
            fields.append(sensor.field_name)
        if sensor.field_name in all_sensors:
            all_sensors[sensor.field_name]['groups'].append('info')
        else:
            all_sensors[sensor.field_name] = {
                'sensor': sensor,
                'groups': ['info']
            }
    
    # Add time series sensors
    for sensor in tracking_config.time_series_sensors.all():
        if sensor.field_name not in fields:
            fields.append(sensor.field_name)
        if sensor.field_name in all_sensors:
            all_sensors[sensor.field_name]['groups'].append('timeseries')
        else:
            all_sensors[sensor.field_name] = {
                'sensor': sensor,
                'groups': ['timeseries']
            }
    
    return fields, all_sensors


def _parse_location_points(result, lat_field, lng_field, all_sensors):
    """
    Parse location points from InfluxDB response.
    
    Args:
        result: InfluxDB JSON response
        lat_field: Latitude field name
        lng_field: Longitude field name
        all_sensors: Dict of sensor info
        
    Returns:
        list: Location point dictionaries
    """
    points = []
    
    if not result.get('results') or not result['results'][0].get('series'):
        return points
    
    series = result['results'][0]['series'][0]
    columns = series.get('columns', [])
    values = series.get('values', [])
    
    time_idx = columns.index('time') if 'time' in columns else 0
    lat_idx = columns.index(lat_field) if lat_field in columns else -1
    lng_idx = columns.index(lng_field) if lng_field in columns else -1
    
    point_index = 0
    
    for row in values:
        try:
            # Parse timestamp
            timestamp_str = row[time_idx]
            parsed_time = _parse_location_timestamp(timestamp_str)
            if not parsed_time:
                continue
            
            lat = row[lat_idx] if lat_idx >= 0 else None
            lng = row[lng_idx] if lng_idx >= 0 else None
            
            if lat is None or lng is None:
                continue
            
            # Build data groups
            popup_data, info_data, timeseries_data = _extract_sensor_groups(
                columns, row, all_sensors
            )
            
            points.append({
                'point_index': point_index,
                'is_start': False,
                'is_end': False,
                'time': parsed_time['time'],
                'date': parsed_time['date'],
                'timestamp': parsed_time['full'],
                'lat': float(lat),
                'lng': float(lng),
                'popup_data': popup_data,
                'info_data': info_data,
                'timeseries_data': timeseries_data
            })
            
            point_index += 1
        
        except Exception:
            continue
    
    return points


def _parse_location_timestamp(timestamp_str):
    """
    Parse timestamp for location point.
    
    Args:
        timestamp_str: Timestamp string from InfluxDB
        
    Returns:
        dict: {'time': 'HH:MM', 'date': 'DD-MM-YYYY', 'full': '...'} or None
    """
    try:
        if '+' in timestamp_str:
            timestamp_str_naive = timestamp_str.split('+')[0]
        elif timestamp_str.endswith('Z'):
            timestamp_str_naive = timestamp_str.replace('Z', '')
        else:
            timestamp_str_naive = timestamp_str
        
        # Handle fractional seconds
        if '.' in timestamp_str_naive:
            parts = timestamp_str_naive.split('.')
            if len(parts) == 2:
                date_time_part = parts[0]
                fractional_part = parts[1][:6]
                timestamp_str_naive = f"{date_time_part}.{fractional_part}"
        
        try:
            dt = datetime.strptime(timestamp_str_naive, '%Y-%m-%dT%H:%M:%S.%f')
        except ValueError:
            dt = datetime.strptime(timestamp_str_naive, '%Y-%m-%dT%H:%M:%S')
        
        return {
            'time': dt.strftime('%H:%M'),
            'date': dt.strftime('%d-%m-%Y'),
            'full': f"{dt.strftime('%d-%m-%Y')} {dt.strftime('%H:%M')}"
        }
    except Exception:
        return None


def _extract_sensor_groups(columns, row, all_sensors):
    """
    Extract sensor values into their respective groups.
    
    Args:
        columns: List of column names
        row: Single value row from InfluxDB
        all_sensors: Dict mapping field names to sensor info
        
    Returns:
        tuple: (popup_data, info_data, timeseries_data)
    """
    popup_data = {}
    info_data = {}
    timeseries_data = {}
    
    for field_name, sensor_info in all_sensors.items():
        try:
            sensor = sensor_info['sensor']
            groups = sensor_info['groups']
            
            sensor_index = columns.index(field_name)
            value = row[sensor_index]
            
            # Get display name and unit
            if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
                display_name = sensor.metadata_config.display_name or sensor.display_name
                unit = sensor.metadata_config.unit or sensor.unit or ''
            else:
                display_name = sensor.display_name or sensor.field_name
                unit = sensor.unit or ''
            
            sensor_data = {
                'display_name': display_name,
                'value': value,
                'unit': unit
            }
            
            if 'popup' in groups:
                popup_data[field_name] = sensor_data
            if 'info' in groups:
                info_data[field_name] = sensor_data
            if 'timeseries' in groups:
                timeseries_data[field_name] = sensor_data
        
        except (ValueError, IndexError):
            continue
    
    return popup_data, info_data, timeseries_data