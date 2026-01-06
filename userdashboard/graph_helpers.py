# userdashboard/graph_helpers.py
"""
Graph Helper Functions for User Dashboard
Fetches time-series data from InfluxDB with bucketing
Separate from department admin - uses metadata_config field
"""

import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Time range to bucket interval mapping (30 data points)
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


def get_influxdb_config_for_user(device):
    """Get InfluxDB configuration for a device."""
    from companyadmin.models import AssetConfig
    
    if device.asset_config:
        return device.asset_config
    # Fallback to default config
    return AssetConfig.objects.filter(is_active=True).first()


def fetch_sensor_data_for_user(device, time_range='now() - 1h'):
    """
    Fetch sensor data from InfluxDB for all active sensors on a device.
    Returns structured data for frontend charts.
    
    Uses metadata_config field (correct related_name for SensorMetadata)
    """
    
    config = get_influxdb_config_for_user(device)
    if not config:
        raise Exception("No InfluxDB configuration found")
    
    # Get all active sensors for this device
    # CORRECT: Use 'metadata_config' as the related_name
    sensors = device.sensors.filter(is_active=True).select_related('metadata_config')
    
    if not sensors.exists():
        return {'timestamps': [], 'sensors': []}
    
    # Get real InfluxDB measurement name and device column from metadata
    influx_measurement_id = device.metadata.get('influx_measurement_id', device.measurement_name) if device.metadata else device.measurement_name
    device_column = device.metadata.get('device_column', 'id') if device.metadata else 'id'
    
    # Build field list for query
    field_names = [sensor.field_name for sensor in sensors]
    field_select = ', '.join([f'mean("{f}") AS "{f}"' for f in field_names])
    
    # Get interval for time bucketing
    interval = INTERVAL_LOOKUP.get(time_range, '2m')
    
    # Build InfluxDB query
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
    
    # Execute query
    try:
        response = requests.get(
            f"{config.base_api}/query",
            params={
                'db': config.db_name,
                'q': query,
            },
            auth=HTTPBasicAuth(config.api_username, config.api_password),
            timeout=30,
            verify=False
        )
        response.raise_for_status()
        result = response.json()
    except Exception as e:
        logger.error(f"InfluxDB query error: {e}")
        raise Exception(f"Failed to fetch data from InfluxDB: {e}")
    
    # Parse response
    timestamps = []
    sensor_data = {sensor.field_name: [] for sensor in sensors}
    
    if result.get('results') and result['results'][0].get('series'):
        series = result['results'][0]['series'][0]
        columns = series.get('columns', [])
        values = series.get('values', [])
        
        # Find column indices
        time_idx = columns.index('time') if 'time' in columns else 0
        
        for row in values:
            # Parse timestamp
            timestamp_str = row[time_idx]
            try:
                if '+' in timestamp_str:
                    timestamp_str_naive = timestamp_str.split('+')[0]
                elif timestamp_str.endswith('Z'):
                    timestamp_str_naive = timestamp_str.replace('Z', '')
                else:
                    timestamp_str_naive = timestamp_str
                
                dt = datetime.strptime(timestamp_str_naive, '%Y-%m-%dT%H:%M:%S')
                formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                timestamps.append(formatted_time)
            except Exception:
                timestamps.append(timestamp_str)
            
            for sensor in sensors:
                try:
                    field_idx = columns.index(sensor.field_name)
                    value = row[field_idx]
                    sensor_data[sensor.field_name].append(value)
                except (ValueError, IndexError):
                    sensor_data[sensor.field_name].append(None)
    
    # Fetch latest values separately for gauges
    latest_values = fetch_latest_values_for_user(device, config)
    
    # Build response structure
    sensors_response = []
    for sensor in sensors:
        values_list = sensor_data.get(sensor.field_name, [])
        
        # Get metadata if exists - use metadata_config (CORRECT FIELD)
        metadata = None
        display_name = sensor.display_name or sensor.field_name
        unit = sensor.unit or ''
        
        if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
            sensor_metadata = sensor.metadata_config
            
            # Get data_types list
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
            
            # Override display name and unit from metadata
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
    
    return {
        'timestamps': timestamps,
        'sensors': sensors_response,
    }


def fetch_latest_values_for_user(device, config):
    """Fetch the most recent value for each sensor."""
    
    sensors = device.sensors.filter(is_active=True)
    if not sensors.exists():
        return {}
    
    # Get real InfluxDB measurement name and device column from metadata
    influx_measurement_id = device.metadata.get('influx_measurement_id', device.measurement_name) if device.metadata else device.measurement_name
    device_column = device.metadata.get('device_column', 'id') if device.metadata else 'id'
    
    field_names = [sensor.field_name for sensor in sensors]
    field_select = ', '.join([f'last("{f}") AS "{f}"' for f in field_names])
    
    query = f'''
        SELECT {field_select}
        FROM "{influx_measurement_id}"
        WHERE "{device_column}" = '{device.device_id}'
        tz('Asia/Kolkata')
    '''
    
    try:
        response = requests.get(
            f"{config.base_api}/query",
            params={
                'db': config.db_name,
                'q': query,
            },
            auth=HTTPBasicAuth(config.api_username, config.api_password),
            timeout=15,
            verify=False
        )
        response.raise_for_status()
        result = response.json()
    except Exception as e:
        logger.error(f"Error fetching latest values: {e}")
        return {}
    
    latest = {}
    if result.get('results') and result['results'][0].get('series'):
        series = result['results'][0]['series'][0]
        columns = series.get('columns', [])
        values = series.get('values', [[]])[0]
        
        for i, col in enumerate(columns):
            if col != 'time' and i < len(values):
                latest[col] = values[i]
    
    return latest


def fetch_asset_tracking_data_for_user(device, time_range='now() - 24h'):
    """
    Fetch asset tracking location data from InfluxDB.
    Returns location history and additional sensor data.
    
    Uses metadata_config field (correct related_name for SensorMetadata)
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
    
    # Get real InfluxDB measurement name and device column from metadata
    influx_measurement_id = device.metadata.get('influx_measurement_id', device.measurement_name) if device.metadata else device.measurement_name
    device_column = device.metadata.get('device_column', 'id') if device.metadata else 'id'
    
    # Build field list
    lat_field = tracking_config.latitude_sensor.field_name
    lng_field = tracking_config.longitude_sensor.field_name
    
    fields = [lat_field, lng_field]
    
    # Track all sensors for data grouping
    all_sensors = {}
    
    # Add popup sensors
    popup_sensors = tracking_config.map_popup_sensors.all()
    for sensor in popup_sensors:
        if sensor.field_name not in fields:
            fields.append(sensor.field_name)
        all_sensors[sensor.field_name] = {
            'sensor': sensor,
            'groups': ['popup']
        }
    
    # Add info card sensors
    info_sensors = tracking_config.info_card_sensors.all()
    for sensor in info_sensors:
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
    timeseries_sensors = tracking_config.time_series_sensors.all()
    for sensor in timeseries_sensors:
        if sensor.field_name not in fields:
            fields.append(sensor.field_name)
        if sensor.field_name in all_sensors:
            all_sensors[sensor.field_name]['groups'].append('timeseries')
        else:
            all_sensors[sensor.field_name] = {
                'sensor': sensor,
                'groups': ['timeseries']
            }
    
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
    
    try:
        response = requests.get(
            f"{config.base_api}/query",
            params={
                'db': config.db_name,
                'q': query,
            },
            auth=HTTPBasicAuth(config.api_username, config.api_password),
            timeout=30,
            verify=False
        )
        response.raise_for_status()
        result = response.json()
    except Exception as e:
        logger.error(f"InfluxDB query error: {e}")
        raise Exception(f"Failed to fetch data from InfluxDB: {e}")
    
    # Parse response
    points = []
    
    if result.get('results') and result['results'][0].get('series'):
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
                
                formatted_time = dt.strftime('%H:%M')
                formatted_date = dt.strftime('%d-%m-%Y')
                full_timestamp = f"{formatted_date} {formatted_time}"
                
                lat = row[lat_idx] if lat_idx >= 0 else None
                lng = row[lng_idx] if lng_idx >= 0 else None
                
                if lat is None or lng is None:
                    continue
                
                # Build data groups
                popup_data = {}
                info_data = {}
                timeseries_data = {}
                
                for field_name, sensor_info in all_sensors.items():
                    try:
                        sensor = sensor_info['sensor']
                        groups = sensor_info['groups']
                        
                        sensor_index = columns.index(field_name)
                        value = row[sensor_index]
                        
                        # Get display name and unit - use metadata_config
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
                
                points.append({
                    'point_index': point_index,
                    'is_start': False,
                    'is_end': False,
                    'time': formatted_time,
                    'date': formatted_date,
                    'timestamp': full_timestamp,
                    'lat': float(lat),
                    'lng': float(lng),
                    'popup_data': popup_data,
                    'info_data': info_data,
                    'timeseries_data': timeseries_data
                })
                
                point_index += 1
            
            except Exception:
                continue
    
    # Mark start and end points
    if points:
        points[0]['is_start'] = True
        points[-1]['is_end'] = True
    
    # Get current location (latest)
    current_location = points[-1] if points else None
    
    # Fetch latest info card data
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
    """Fetch latest values for info card display."""
    
    if not field_names:
        return {}
    
    # Get real InfluxDB measurement name and device column from metadata
    influx_measurement_id = device.metadata.get('influx_measurement_id', device.measurement_name) if device.metadata else device.measurement_name
    device_column = device.metadata.get('device_column', 'id') if device.metadata else 'id'
    
    field_select = ', '.join([f'last("{f}") AS "{f}"' for f in field_names])
    
    query = f'''
        SELECT {field_select}
        FROM "{influx_measurement_id}"
        WHERE "{device_column}" = '{device.device_id}'
        tz('Asia/Kolkata')
    '''
    
    try:
        response = requests.get(
            f"{config.base_api}/query",
            params={
                'db': config.db_name,
                'q': query,
            },
            auth=HTTPBasicAuth(config.api_username, config.api_password),
            timeout=15,
            verify=False
        )
        response.raise_for_status()
        result = response.json()
    except Exception:
        return {}
    
    data = {}
    if result.get('results') and result['results'][0].get('series'):
        series = result['results'][0]['series'][0]
        columns = series.get('columns', [])
        values = series.get('values', [[]])[0]
        
        for i, col in enumerate(columns):
            if col != 'time' and i < len(values):
                data[col] = values[i]
    
    return data