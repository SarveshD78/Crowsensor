"""
departmentadmin/asset_map_func.py

Asset Map helper functions for Department Admin.
Fetches location tracking data from InfluxDB (ALL points, not bucketed).
Supports map popup, info card, and time series sensor groups.
"""

import logging
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)


# =============================================================================
# MAIN DATA FETCH FUNCTION
# =============================================================================

def fetch_asset_tracking_data_from_influx(device, asset_config, influx_config, time_range='now() - 1h'):
    """
    Fetch ALL location points for asset tracking device from InfluxDB.
    
    Returns every data point with ALL sensor groups (popup, info, timeseries).
    Points include index numbers for display (Point 0, Point 1, etc.).
    
    Args:
        device: Device model instance
        asset_config: AssetTrackingConfig instance with sensor selections
        influx_config: AssetConfig instance (InfluxDB connection)
        time_range: InfluxDB time range (default: 'now() - 1h')
    
    Returns:
        dict: {
            'success': True/False,
            'message': str,
            'data': {
                'points': [
                    {
                        'point_index': 0,
                        'is_start': True,
                        'is_end': False,
                        'time': '14:30',
                        'date': '23-12-2025',
                        'timestamp': '23-12-2025 14:30',
                        'lat': 18.5204,
                        'lng': 73.8567,
                        'popup_data': {...},
                        'info_data': {...},
                        'timeseries_data': {...}
                    },
                ],
                'total_points': 156,
                'start_point': {...},
                'end_point': {...},
                'time_range': 'now() - 1h'
            }
        }
    """
    try:
        # Get InfluxDB measurement details from device metadata
        influx_measurement_id = device.metadata.get('influx_measurement_id', device.measurement_name)
        device_column = device.metadata.get('device_column', 'id')
        
        logger.info("=" * 80)
        logger.info("FETCHING ASSET TRACKING DATA FROM INFLUXDB")
        logger.info("=" * 80)
        logger.info(f"Device: {device.display_name} (ID: {device.device_id})")
        logger.info(f"Measurement: {influx_measurement_id}")
        logger.info(f"Device Column: {device_column}")
        logger.info(f"Time Range: {time_range}")
        
        # Step 1: Build SELECT fields for ALL 3 sensor groups
        select_fields, all_sensors = _build_select_fields(asset_config)
        
        if not select_fields:
            return {
                'success': False,
                'message': 'Location sensors (lat/lng) not configured',
                'data': None
            }
        
        select_clause = ', '.join(select_fields)
        logger.info(f"Total unique sensors in query: {len(all_sensors)}")
        
        # Step 2: Build InfluxDB query (ORDER BY time ASC for polyline)
        query = f'''
        SELECT {select_clause}
        FROM "{influx_measurement_id}"
        WHERE time >= {time_range} 
          AND time <= now() 
          AND "{device_column}" = '{device.device_id}'
        ORDER BY time ASC
        tz('Asia/Kolkata')
        '''
        
        logger.debug(f"Query: {query}")
        
        # Step 3: Execute query
        base_url = f"{influx_config.base_api}/query"
        auth = HTTPBasicAuth(influx_config.api_username, influx_config.api_password)
        
        response = requests.get(
            base_url,
            params={'db': influx_config.db_name, 'q': query},
            auth=auth,
            verify=False,
            timeout=30
        )
        
        logger.debug(f"Response Status: {response.status_code}")
        
        if response.status_code != 200:
            logger.warning(f"InfluxDB returned error: {response.status_code}")
            return {
                'success': False,
                'message': f'InfluxDB error: {response.status_code}',
                'data': None
            }
        
        # Step 4: Parse response
        data = response.json()
        
        validation_result = _validate_influx_response(data)
        if not validation_result['valid']:
            return {
                'success': False,
                'message': validation_result['message'],
                'data': None
            }
        
        series = data['results'][0]['series'][0]
        columns = series['columns']
        values = series['values']
        
        logger.info(f"Data Points Received: {len(values)}")
        logger.debug(f"Columns: {columns}")
        
        # Step 5: Parse data points
        points, stats = _parse_location_points(columns, values, all_sensors)
        
        # Step 6: Mark start and end points
        if points:
            points[0]['is_start'] = True
            points[-1]['is_end'] = True
        
        # Log summary
        logger.info("=" * 80)
        logger.info(f"Successfully parsed {len(points)} location points (Point 0 to Point {len(points)-1})")
        
        if stats['skipped_null_locations'] > 0:
            logger.warning(f"Skipped {stats['skipped_null_locations']} points with null lat/lng")
        
        if stats['skipped_parse_errors'] > 0:
            logger.warning(f"Skipped {stats['skipped_parse_errors']} points due to parse errors")
        
        logger.info("=" * 80)
        
        return {
            'success': True,
            'message': 'Location data fetched successfully',
            'data': {
                'points': points,
                'total_points': len(points),
                'start_point': points[0] if points else None,
                'end_point': points[-1] if points else None,
                'time_range': time_range,
                'skipped_null_locations': stats['skipped_null_locations'],
                'skipped_parse_errors': stats['skipped_parse_errors']
            }
        }
    
    except Exception as e:
        logger.error(f"Error in fetch_asset_tracking_data_from_influx: {e}", exc_info=True)
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _build_select_fields(asset_config):
    """
    Build SELECT fields for all 3 sensor groups.
    
    Args:
        asset_config: AssetTrackingConfig instance
        
    Returns:
        tuple: (select_fields list, all_sensors dict)
    """
    select_fields = []
    all_sensors = {}  # Track which sensor belongs to which group
    
    # Add latitude & longitude (REQUIRED)
    lat_sensor = asset_config.latitude_sensor
    lng_sensor = asset_config.longitude_sensor
    
    if not lat_sensor or not lng_sensor:
        logger.warning("Location sensors not configured")
        return [], {}
    
    select_fields.append(f'"{lat_sensor.field_name}" as lat')
    select_fields.append(f'"{lng_sensor.field_name}" as lng')
    
    logger.info(f"Location sensors: {lat_sensor.field_name} / {lng_sensor.field_name}")
    
    # Helper to add sensors from a group
    def add_sensor_group(sensors, group_name):
        logger.info(f"GROUP - {group_name}: {sensors.count()} sensors")
        
        for sensor in sensors:
            # Add to SELECT if not already present
            existing_fields = [s.split(' as ')[0].strip('"') for s in select_fields]
            if sensor.field_name not in existing_fields:
                select_fields.append(f'"{sensor.field_name}"')
            
            # Track sensor groups
            if sensor.field_name in all_sensors:
                all_sensors[sensor.field_name]['groups'].append(group_name)
            else:
                all_sensors[sensor.field_name] = {
                    'sensor': sensor,
                    'groups': [group_name]
                }
            
            logger.debug(f"  - {sensor.field_name} ({sensor.display_name})")
    
    # GROUP 1: Map popup sensors
    add_sensor_group(asset_config.map_popup_sensors.all(), 'popup')
    
    # GROUP 2: Info card sensors
    add_sensor_group(asset_config.info_card_sensors.all(), 'info')
    
    # GROUP 3: Time series sensors
    add_sensor_group(asset_config.time_series_sensors.all(), 'timeseries')
    
    return select_fields, all_sensors


def _validate_influx_response(data):
    """
    Validate InfluxDB response structure.
    
    Args:
        data: Parsed JSON response from InfluxDB
        
    Returns:
        dict: {'valid': bool, 'message': str}
    """
    if 'results' not in data or not data['results']:
        logger.warning("No results in InfluxDB response")
        return {'valid': False, 'message': 'No results from InfluxDB'}
    
    if 'series' not in data['results'][0] or not data['results'][0]['series']:
        logger.warning("No location data found for this time range")
        return {'valid': False, 'message': 'No location data found for this time range'}
    
    return {'valid': True, 'message': 'OK'}


def _parse_location_points(columns, values, all_sensors):
    """
    Parse location points from InfluxDB response.
    
    Args:
        columns: List of column names
        values: List of value rows
        all_sensors: Dict mapping field names to sensor info
        
    Returns:
        tuple: (points list, stats dict)
    """
    points = []
    stats = {
        'skipped_null_locations': 0,
        'skipped_parse_errors': 0
    }
    
    point_index = 0
    
    for row in values:
        try:
            # Parse timestamp
            parsed_time = _parse_timestamp(row[0])
            if not parsed_time:
                stats['skipped_parse_errors'] += 1
                continue
            
            # Get lat/lng
            lat_index = columns.index('lat')
            lng_index = columns.index('lng')
            
            lat = row[lat_index]
            lng = row[lng_index]
            
            if lat is None or lng is None:
                stats['skipped_null_locations'] += 1
                continue
            
            # Build 3 separate data groups
            popup_data, info_data, timeseries_data = _extract_sensor_groups(
                columns, row, all_sensors
            )
            
            # Add point with index and flags
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
        
        except Exception as e:
            stats['skipped_parse_errors'] += 1
            if stats['skipped_parse_errors'] <= 3:
                logger.warning(f"Warning parsing point: {e}")
            continue
    
    return points, stats


def _parse_timestamp(timestamp_str):
    """
    Parse timestamp from InfluxDB format.
    
    Args:
        timestamp_str: Timestamp string from InfluxDB
        
    Returns:
        dict: {'time': 'HH:MM', 'date': 'DD-MM-YYYY', 'full': 'DD-MM-YYYY HH:MM'} or None
    """
    try:
        # Remove timezone offset
        if '+' in timestamp_str:
            timestamp_str_naive = timestamp_str.split('+')[0]
        elif timestamp_str.endswith('Z'):
            timestamp_str_naive = timestamp_str.replace('Z', '')
        else:
            timestamp_str_naive = timestamp_str
        
        # Truncate fractional seconds to 6 digits
        if '.' in timestamp_str_naive:
            parts = timestamp_str_naive.split('.')
            if len(parts) == 2:
                date_time_part = parts[0]
                fractional_part = parts[1][:6]
                timestamp_str_naive = f"{date_time_part}.{fractional_part}"
        
        # Parse datetime
        dt = None
        try:
            dt = datetime.strptime(timestamp_str_naive, '%Y-%m-%dT%H:%M:%S.%f')
        except ValueError:
            try:
                dt = datetime.strptime(timestamp_str_naive, '%Y-%m-%dT%H:%M:%S')
            except ValueError:
                return None
        
        return {
            'time': dt.strftime('%H:%M'),
            'date': dt.strftime('%d-%m-%Y'),
            'full': dt.strftime('%d-%m-%Y %H:%M')
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
            display_name, unit = _get_sensor_display_info(sensor)
            
            sensor_data = {
                'display_name': display_name,
                'value': value,
                'unit': unit
            }
            
            # Add to appropriate group(s)
            if 'popup' in groups:
                popup_data[field_name] = sensor_data
            if 'info' in groups:
                info_data[field_name] = sensor_data
            if 'timeseries' in groups:
                timeseries_data[field_name] = sensor_data
        
        except (ValueError, IndexError):
            continue
    
    return popup_data, info_data, timeseries_data


def _get_sensor_display_info(sensor):
    """
    Get display name and unit for a sensor.
    
    Args:
        sensor: Sensor model instance
        
    Returns:
        tuple: (display_name, unit)
    """
    if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
        display_name = sensor.metadata_config.display_name or sensor.display_name
        unit = sensor.metadata_config.unit or sensor.unit or ''
    else:
        display_name = sensor.display_name or sensor.field_name
        unit = sensor.unit or ''
    
    return display_name, unit