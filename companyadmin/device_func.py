# companyadmin/device_func.py
"""
Device Discovery and Management Helper Functions
All InfluxDB device/sensor discovery logic isolated here
"""

import sys
import json
import requests
from requests.auth import HTTPBasicAuth
from django.utils import timezone
from django.db import transaction


def debug_print(msg, level=0):
    """Helper to print debug messages with indentation"""
    indent = "   " * level
    print(f"{indent}{msg}", flush=True)
    sys.stdout.flush()


def analyze_device_sensors_from_influx(measurement, device_column, device_id, base_url, db_name, auth):
    """
    Query InfluxDB for specific device and detect which sensors have data (not all NULL)
    Returns list of sensor dictionaries with name, type, category
    """
    debug_print(f"\n{'='*100}", 0)
    debug_print(f"🔍 analyze_device_sensors_from_influx()", 0)
    debug_print(f"{'='*100}", 0)
    debug_print(f"measurement      = {measurement}", 1)
    debug_print(f"device_column    = {device_column}", 1)
    debug_print(f"device_id        = {device_id}", 1)
    
    try:
        # Build query
        device_query = f'SELECT * FROM "{measurement}" WHERE "{device_column}"=\'{device_id}\' ORDER BY time DESC LIMIT 1000'
        debug_print(f"Query: {device_query}", 1)
        
        # Send request
        response = requests.get(
            base_url,
            params={'db': db_name, 'q': device_query},
            auth=auth,
            verify=False,
            timeout=10
        )
        
        debug_print(f"Status Code: {response.status_code}", 1)
        
        if response.status_code != 200:
            debug_print(f"❌ Bad HTTP status", 1)
            return []
        
        # Parse JSON
        data = response.json()
        
        # Validate structure
        if 'results' not in data or not data['results']:
            debug_print(f"❌ No results", 1)
            return []
        
        if 'series' not in data['results'][0] or not data['results'][0]['series']:
            debug_print(f"❌ No series data", 1)
            return []
        
        # Extract columns and values
        series = data['results'][0]['series'][0]
        columns = series.get('columns', [])
        values = series.get('values', [])
        
        debug_print(f"Columns: {len(columns)}, Rows: {len(values)}", 1)
        
        if not values:
            debug_print(f"❌ No data rows", 1)
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
            
            # Determine field type
            field_type = 'unknown'
            if isinstance(sample_value, bool):
                field_type = 'boolean'
            elif isinstance(sample_value, int):
                field_type = 'integer'
            elif isinstance(sample_value, float):
                field_type = 'float'
            elif isinstance(sample_value, str):
                field_type = 'string'
            
            # Determine category
            col_lower = col_name.lower()
            
            if col_lower in ['slave', 'slaveid', 'slave_id']:
                category = 'slave'
            elif any(k in col_lower for k in ['device', 'deviceid', 'mac', 'ip', 'location', 'name', 'description']):
                category = 'info'
            elif field_type in ['integer', 'float', 'boolean']:
                category = 'sensor'
            else:
                category = 'info'
            
            device_sensors.append({
                'name': col_name,
                'type': field_type,
                'category': category,
                'sample_value': sample_value
            })
        
        debug_print(f"✅ Detected {len(device_sensors)} sensors", 1)
        debug_print(f"{'='*100}\n", 0)
        
        return device_sensors
    
    except Exception as e:
        debug_print(f"❌ EXCEPTION: {str(e)}", 0)
        import traceback
        traceback.print_exc()
        return []


def detect_column_type(column_name, sample_values):
    """
    Detect column type and category from name and sample values
    Returns dict with category, type, reason
    """
    col_lower = column_name.lower()
    
    # Time column
    if col_lower == 'time':
        return {'category': 'hidden', 'type': 'timestamp', 'reason': 'Time column'}
    
    # ID column (check if device or slave)
    if col_lower == 'id':
        unique_values = set(sample_values)
        if len(unique_values) > 1:
            return {'category': 'device', 'type': 'integer', 'reason': 'Multiple unique IDs'}
        else:
            return {'category': 'slave', 'type': 'integer', 'reason': 'Single ID'}
    
    # Slave identifier
    if col_lower in ['slave', 'slaveid', 'slave_id']:
        return {'category': 'slave', 'type': 'integer', 'reason': 'Slave identifier'}
    
    # Device info fields
    if any(k in col_lower for k in ['device', 'deviceid', 'mac', 'ip', 'location', 'name']):
        return {'category': 'info', 'type': 'string', 'reason': 'Device info'}
    
    # Analyze sample values
    if sample_values:
        valid_values = [v for v in sample_values if v is not None]
        if valid_values:
            first_value = valid_values[0]
            
            if isinstance(first_value, (int, float)):
                return {
                    'category': 'sensor',
                    'type': 'float' if isinstance(first_value, float) else 'integer',
                    'reason': 'Numeric sensor'
                }
            elif isinstance(first_value, bool):
                return {'category': 'sensor', 'type': 'boolean', 'reason': 'Boolean sensor'}
            elif isinstance(first_value, str):
                return {'category': 'info', 'type': 'string', 'reason': 'Text info'}
    
    return {'category': 'info', 'type': 'string', 'reason': 'Unknown'}


def fetch_measurements_from_influx(config):
    """
    Fetch all measurement names from InfluxDB
    Returns list of measurement names
    """
    try:
        base_url = f"{config.base_api}/query"
        auth = HTTPBasicAuth(config.api_username, config.api_password)
        
        query = 'SHOW MEASUREMENTS'
        response = requests.get(
            base_url,
            params={'db': config.db_name, 'q': query},
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
        return measurements
    
    except Exception as e:
        debug_print(f"Error fetching measurements: {e}", 0)
        return []


def fetch_device_ids_from_measurement(config, measurement, device_column):
    """
    Fetch all device IDs from a measurement
    Tries TAG query first, then FIELD query as fallback
    Returns sorted list of device IDs
    """
    try:
        base_url = f"{config.base_api}/query"
        auth = HTTPBasicAuth(config.api_username, config.api_password)
        
        device_ids = set()
        
        # Approach 1: TAG query
        try:
            tag_query = f'SHOW TAG VALUES FROM "{measurement}" WITH KEY = "{device_column}"'
            response = requests.get(
                base_url,
                params={'db': config.db_name, 'q': tag_query},
                auth=auth,
                verify=False,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'results' in data and data['results'] and 'series' in data['results'][0]:
                    if data['results'][0]['series']:
                        tag_values = [v[1] for v in data['results'][0]['series'][0]['values']]
                        device_ids.update(tag_values)
                        debug_print(f"TAG approach found {len(tag_values)} IDs", 1)
        except Exception as e:
            debug_print(f"TAG query failed: {e}", 1)
        
        # Approach 2: FIELD query (fallback)
        if not device_ids:
            try:
                field_query = f'SELECT DISTINCT("{device_column}") FROM "{measurement}" LIMIT 10000'
                response = requests.get(
                    base_url,
                    params={'db': config.db_name, 'q': field_query},
                    auth=auth,
                    verify=False,
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if 'results' in data and data['results'] and 'series' in data['results'][0]:
                        if data['results'][0]['series']:
                            field_values = [v[1] for v in data['results'][0]['series'][0]['values'] if len(v) > 1 and v[1] is not None]
                            device_ids.update([str(v) for v in field_values])
                            debug_print(f"FIELD approach found {len(field_values)} IDs", 1)
            except Exception as e:
                debug_print(f"FIELD query failed: {e}", 1)
        
        # Sort device IDs
        sorted_ids = sorted(list(device_ids), key=lambda x: int(x) if str(x).isdigit() else x)
        return sorted_ids
    
    except Exception as e:
        debug_print(f"Error fetching device IDs: {e}", 0)
        return []


def analyze_measurement_columns(config, measurement):
    """
    Analyze columns in a measurement to detect types
    Returns dict of column_name -> {category, type, reason, unique_count}
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
        
        return column_info
    
    except Exception as e:
        debug_print(f"Error analyzing columns: {e}", 0)
        return {}


def save_device_with_sensors(measurement, device_column, device_id, sensors, config):
    """
    Save device and its sensors to database
    Returns (device, created, sensors_created)
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
                updated = False
                if 'influx_measurement_id' not in device.metadata:
                    device.metadata['influx_measurement_id'] = measurement
                    updated = True
                
                if 'device_column' not in device.metadata:
                    device.metadata['device_column'] = device_column
                    updated = True
                
                if updated:
                    device.save()
            
            # Save sensors
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
                            'sample_value': str(sensor_info['sample_value']) if sensor_info['sample_value'] is not None else None
                        }
                    }
                )
                
                if sensor_created:
                    sensors_created += 1
            
            return device, created, sensors_created
    
    except Exception as e:
        debug_print(f"Error saving device: {e}", 0)
        raise