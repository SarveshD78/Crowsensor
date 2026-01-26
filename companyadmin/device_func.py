"""
companyadmin/device_func.py

Device Discovery and Management Helper Functions.
All InfluxDB device/sensor discovery logic isolated here.
"""

import logging

import requests
from requests.auth import HTTPBasicAuth

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# =============================================================================
# SENSOR ANALYSIS
# =============================================================================

def analyze_device_sensors_from_influx(measurement, device_column, device_id, base_url, db_name, auth):
    """
    Query InfluxDB for specific device and detect which sensors have data.
    
    Args:
        measurement: InfluxDB measurement name
        device_column: Column name containing device identifier
        device_id: Specific device ID to analyze
        base_url: InfluxDB query API URL
        db_name: Database name
        auth: HTTPBasicAuth object
        
    Returns:
        list: Sensor dictionaries with name, type, category, sample_value
    """
    logger.debug(f"Analyzing sensors for {measurement}/{device_column}={device_id}")
    
    try:
        # Build query
        device_query = (
            f'SELECT * FROM "{measurement}" '
            f'WHERE "{device_column}"=\'{device_id}\' '
            f'ORDER BY time DESC LIMIT 1000'
        )
        
        # Send request
        response = requests.get(
            base_url,
            params={'db': db_name, 'q': device_query},
            auth=auth,
            verify=False,
            timeout=10
        )
        
        if response.status_code != 200:
            logger.warning(f"Bad HTTP status: {response.status_code}")
            return []
        
        # Parse JSON
        data = response.json()
        
        # Validate structure
        if 'results' not in data or not data['results']:
            logger.debug("No results in response")
            return []
        
        if 'series' not in data['results'][0] or not data['results'][0]['series']:
            logger.debug("No series data in response")
            return []
        
        # Extract columns and values
        series = data['results'][0]['series'][0]
        columns = series.get('columns', [])
        values = series.get('values', [])
        
        logger.debug(f"Found {len(columns)} columns, {len(values)} rows")
        
        if not values:
            logger.debug("No data rows")
            return []
        
        # Analyze each column
        skip_columns = ['time', device_column]
        device_sensors = []
        
        for i, col_name in enumerate(columns):
            if col_name in skip_columns:
                continue
            
            # Get all values for this column
            column_values = [row[i] if i < len(row) else None for row in values]
            non_null_values = [v for v in column_values if v is not None]
            
            # Skip if all NULL
            if not non_null_values:
                continue
            
            # Get sample value and detect type
            sample_value = non_null_values[0]
            field_type = _detect_field_type(sample_value)
            category = _detect_category(col_name, field_type)
            
            device_sensors.append({
                'name': col_name,
                'type': field_type,
                'category': category,
                'sample_value': sample_value
            })
        
        logger.debug(f"Detected {len(device_sensors)} sensors")
        return device_sensors
    
    except Exception as e:
        logger.error(f"Error analyzing sensors: {e}", exc_info=True)
        return []


def _detect_field_type(value):
    """
    Detect field type from sample value.
    
    Args:
        value: Sample value from InfluxDB
        
    Returns:
        str: Field type (boolean, integer, float, string, unknown)
    """
    if isinstance(value, bool):
        return 'boolean'
    elif isinstance(value, int):
        return 'integer'
    elif isinstance(value, float):
        return 'float'
    elif isinstance(value, str):
        return 'string'
    return 'unknown'


def _detect_category(col_name, field_type):
    """
    Detect sensor category from column name and type.
    
    Args:
        col_name: Column name
        field_type: Detected field type
        
    Returns:
        str: Category (slave, info, sensor)
    """
    col_lower = col_name.lower()
    
    # Slave identifier
    if col_lower in ['slave', 'slaveid', 'slave_id']:
        return 'slave'
    
    # Device info fields
    info_keywords = ['device', 'deviceid', 'mac', 'ip', 'location', 'name', 'description']
    if any(keyword in col_lower for keyword in info_keywords):
        return 'info'
    
    # Numeric fields are sensors
    if field_type in ['integer', 'float', 'boolean']:
        return 'sensor'
    
    return 'info'


# =============================================================================
# COLUMN TYPE DETECTION
# =============================================================================

def detect_column_type(column_name, sample_values):
    """
    Detect column type and category from name and sample values.
    
    Args:
        column_name: Name of the column
        sample_values: List of sample values
        
    Returns:
        dict: Contains category, type, reason
    """
    col_lower = column_name.lower()
    
    # Time column
    if col_lower == 'time':
        return {'category': 'hidden', 'type': 'timestamp', 'reason': 'Time column'}
    
    # ID column
    if col_lower == 'id':
        unique_values = set(sample_values)
        if len(unique_values) > 1:
            return {'category': 'device', 'type': 'integer', 'reason': 'Multiple unique IDs'}
        return {'category': 'slave', 'type': 'integer', 'reason': 'Single ID'}
    
    # Slave identifier
    if col_lower in ['slave', 'slaveid', 'slave_id']:
        return {'category': 'slave', 'type': 'integer', 'reason': 'Slave identifier'}
    
    # Device info fields
    info_keywords = ['device', 'deviceid', 'mac', 'ip', 'location', 'name']
    if any(keyword in col_lower for keyword in info_keywords):
        return {'category': 'info', 'type': 'string', 'reason': 'Device info'}
    
    # Analyze sample values
    if sample_values:
        valid_values = [v for v in sample_values if v is not None]
        if valid_values:
            first_value = valid_values[0]
            
            if isinstance(first_value, (int, float)):
                value_type = 'float' if isinstance(first_value, float) else 'integer'
                return {'category': 'sensor', 'type': value_type, 'reason': 'Numeric sensor'}
            elif isinstance(first_value, bool):
                return {'category': 'sensor', 'type': 'boolean', 'reason': 'Boolean sensor'}
            elif isinstance(first_value, str):
                return {'category': 'info', 'type': 'string', 'reason': 'Text info'}
    
    return {'category': 'info', 'type': 'string', 'reason': 'Unknown'}


# =============================================================================
# INFLUXDB QUERIES
# =============================================================================

def fetch_measurements_from_influx(config):
    """
    Fetch all measurement names from InfluxDB.
    
    Args:
        config: AssetConfig instance with connection details
        
    Returns:
        list: Measurement names
    """
    try:
        base_url = f"{config.base_api}/query"
        auth = HTTPBasicAuth(config.api_username, config.api_password)
        
        response = requests.get(
            base_url,
            params={'db': config.db_name, 'q': 'SHOW MEASUREMENTS'},
            auth=auth,
            verify=False,
            timeout=10
        )
        
        if response.status_code != 200:
            raise Exception(f"InfluxDB returned status {response.status_code}")
        
        data = response.json()
        
        if 'results' not in data or not data['results']:
            return []
        
        if 'series' not in data['results'][0] or not data['results'][0]['series']:
            return []
        
        measurements = [row[0] for row in data['results'][0]['series'][0]['values']]
        logger.debug(f"Found {len(measurements)} measurements")
        return measurements
    
    except Exception as e:
        logger.error(f"Error fetching measurements: {e}")
        return []


def fetch_device_ids_from_measurement(config, measurement, device_column):
    """
    Fetch all device IDs from a measurement.
    
    Tries TAG query first, then FIELD query as fallback.
    
    Args:
        config: AssetConfig instance
        measurement: Measurement name
        device_column: Column containing device IDs
        
    Returns:
        list: Sorted device IDs
    """
    try:
        base_url = f"{config.base_api}/query"
        auth = HTTPBasicAuth(config.api_username, config.api_password)
        device_ids = set()
        
        # Approach 1: TAG query
        device_ids = _fetch_device_ids_via_tag(base_url, config.db_name, auth, measurement, device_column)
        
        # Approach 2: FIELD query (fallback)
        if not device_ids:
            device_ids = _fetch_device_ids_via_field(base_url, config.db_name, auth, measurement, device_column)
        
        # Sort device IDs
        sorted_ids = sorted(
            list(device_ids),
            key=lambda x: int(x) if str(x).isdigit() else x
        )
        
        logger.debug(f"Found {len(sorted_ids)} device IDs for {measurement}")
        return sorted_ids
    
    except Exception as e:
        logger.error(f"Error fetching device IDs: {e}")
        return []


def _fetch_device_ids_via_tag(base_url, db_name, auth, measurement, device_column):
    """Fetch device IDs using TAG query."""
    try:
        tag_query = f'SHOW TAG VALUES FROM "{measurement}" WITH KEY = "{device_column}"'
        response = requests.get(
            base_url,
            params={'db': db_name, 'q': tag_query},
            auth=auth,
            verify=False,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'results' in data and data['results']:
                if 'series' in data['results'][0] and data['results'][0]['series']:
                    tag_values = [v[1] for v in data['results'][0]['series'][0]['values']]
                    logger.debug(f"TAG approach found {len(tag_values)} IDs")
                    return set(tag_values)
    except Exception as e:
        logger.debug(f"TAG query failed: {e}")
    
    return set()


def _fetch_device_ids_via_field(base_url, db_name, auth, measurement, device_column):
    """Fetch device IDs using FIELD query (fallback)."""
    try:
        field_query = f'SELECT DISTINCT("{device_column}") FROM "{measurement}" LIMIT 10000'
        response = requests.get(
            base_url,
            params={'db': db_name, 'q': field_query},
            auth=auth,
            verify=False,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'results' in data and data['results']:
                if 'series' in data['results'][0] and data['results'][0]['series']:
                    values = data['results'][0]['series'][0]['values']
                    field_values = [
                        str(v[1]) for v in values
                        if len(v) > 1 and v[1] is not None
                    ]
                    logger.debug(f"FIELD approach found {len(field_values)} IDs")
                    return set(field_values)
    except Exception as e:
        logger.debug(f"FIELD query failed: {e}")
    
    return set()


def analyze_measurement_columns(config, measurement):
    """
    Analyze columns in a measurement to detect types.
    
    Args:
        config: AssetConfig instance
        measurement: Measurement name
        
    Returns:
        dict: column_name -> {category, type, reason, unique_count}
    """
    try:
        base_url = f"{config.base_api}/query"
        auth = HTTPBasicAuth(config.api_username, config.api_password)
        
        sample_query = f'SELECT * FROM "{measurement}" LIMIT 100'
        response = requests.get(
            base_url,
            params={'db': config.db_name, 'q': sample_query},
            auth=auth,
            verify=False,
            timeout=30
        )
        
        if response.status_code != 200:
            return {}
        
        data = response.json()
        
        if 'results' not in data or not data['results']:
            return {}
        
        if 'series' not in data['results'][0] or not data['results'][0]['series']:
            return {}
        
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
        
        logger.debug(f"Analyzed {len(column_info)} columns for {measurement}")
        return column_info
    
    except Exception as e:
        logger.error(f"Error analyzing columns: {e}")
        return {}


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def save_device_with_sensors(measurement, device_column, device_id, sensors, config):
    """
    Save device and its sensors to database.
    
    Args:
        measurement: InfluxDB measurement name
        device_column: Column containing device ID
        device_id: Device identifier
        sensors: List of sensor dictionaries
        config: AssetConfig instance
        
    Returns:
        tuple: (device, created, sensors_created)
    """
    from companyadmin.models import Device, Sensor
    
    try:
        with transaction.atomic():
            # Create or get device
            device, created = Device.objects.get_or_create(
                asset_config=config,
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
            
            # Update metadata if device exists
            if not created:
                _update_device_metadata(device, measurement, device_column)
            
            # Save sensors
            sensors_created = _save_sensors_for_device(device, sensors)
            
            logger.info(
                f"{'Created' if created else 'Updated'} device {device_id} "
                f"with {sensors_created} new sensors"
            )
            
            return device, created, sensors_created
    
    except Exception as e:
        logger.error(f"Error saving device: {e}", exc_info=True)
        raise


def _update_device_metadata(device, measurement, device_column):
    """Update device metadata if missing fields."""
    updated = False
    
    if 'influx_measurement_id' not in device.metadata:
        device.metadata['influx_measurement_id'] = measurement
        updated = True
    
    if 'device_column' not in device.metadata:
        device.metadata['device_column'] = device_column
        updated = True
    
    if updated:
        device.save()


def _save_sensors_for_device(device, sensors):
    """
    Save sensors for a device.
    
    Args:
        device: Device instance
        sensors: List of sensor dictionaries
        
    Returns:
        int: Number of sensors created
    """
    from companyadmin.models import Sensor
    
    sensors_created = 0
    
    for sensor_info in sensors:
        sensor, sensor_created = Sensor.objects.get_or_create(
            device=device,
            field_name=sensor_info['name'],
            defaults={
                'display_name': sensor_info['name'].replace('_', ' ').title(),
                'field_type': sensor_info['type'],
                'category': sensor_info['category'],
                'is_active': True,
                'metadata': {
                    'sample_value': str(sensor_info['sample_value'])
                    if sensor_info['sample_value'] is not None else None
                }
            }
        )
        
        if sensor_created:
            sensors_created += 1
    
    return sensors_created