"""
Graph Helper Functions for Department Admin
Fetches time-series data from InfluxDB with bucketing
"""

import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
import pytz


# Time range to bucket interval mapping (30 data points)
INTERVAL_LOOKUP = {
    'now() - 1h': '2m',      # 1 hour / 30 = 2 min buckets
    'now() - 2h': '4m',      # 2 hours / 30 = 4 min buckets
    'now() - 3h': '6m',      # 3 hours / 30 = 6 min buckets
    'now() - 6h': '12m',     # 6 hours / 30 = 12 min buckets
    'now() - 12h': '24m',    # 12 hours / 30 = 24 min buckets
    'now() - 24h': '48m',    # 24 hours / 30 = 48 min buckets
    'now() - 2d': '96m',     # 2 days / 30 = 96 min buckets
    'now() - 7d': '336m',    # 7 days / 30 = 336 min buckets
    'now() - 30d': '1440m'   # 30 days / 30 = 1440 min (24h) buckets
}


def fetch_sensor_data_from_influx(device, sensors, config, time_range='now() - 24h'):
    """
    Fetch time-series data for multiple sensors from InfluxDB
    Returns bucketed data (30 points) for each sensor
    
    Args:
        device: Device model instance
        sensors: QuerySet of Sensor objects
        config: AssetConfig instance
        time_range: InfluxDB time range (e.g., 'now() - 24h')
    
    Returns:
        dict: {
            'success': True/False,
            'message': str,
            'data': {
                'timestamps': [...],  # List of timestamps (30 points)
                'sensors': [
                    {
                        'id': sensor.id,
                        'field_name': '40001',
                        'display_name': 'Temperature',
                        'unit': '°C',
                        'values': [...],  # 30 data points
                        'metadata': {...}  # upper_limit, lower_limit, etc.
                    },
                    ...
                ]
            }
        }
    """
    
    try:
        # Get real InfluxDB measurement name and device column from metadata
        influx_measurement_id = device.metadata.get('influx_measurement_id', device.measurement_name)
        device_column = device.metadata.get('device_column', 'id')
        
        # Get bucket interval for time range
        interval = INTERVAL_LOOKUP.get(time_range, '48m')
        
        print(f"\n{'='*80}")
        print(f"📊 FETCHING SENSOR DATA FROM INFLUXDB")
        print(f"{'='*80}")
        print(f"Device: {device.display_name} (ID: {device.device_id})")
        print(f"Measurement: {influx_measurement_id}")
        print(f"Device Column: {device_column}")
        print(f"Time Range: {time_range}")
        print(f"Interval: {interval}")
        print(f"Sensors: {sensors.count()}")
        
        # Build SELECT fields for all sensors
        select_fields = []
        for sensor in sensors:
            select_fields.append(f'mean("{sensor.field_name}") as sensor_{sensor.field_name}')
        
        select_clause = ', '.join(select_fields)
        
        # Build InfluxDB query
        query = f'''
        SELECT {select_clause}
        FROM "{influx_measurement_id}"
        WHERE time >= {time_range} 
          AND time <= now() 
          AND "{device_column}" = '{device.device_id}'
        GROUP BY time({interval}) fill(null)
        tz('Asia/Kolkata')
        '''
        
        print(f"\nQuery:\n{query}")
        
        # Execute query
        base_url = f"{config.base_api}/query"
        auth = HTTPBasicAuth(config.api_username, config.api_password)
        
        response = requests.get(
            base_url,
            params={'db': config.db_name, 'q': query},
            auth=auth,
            verify=False, 
            timeout=30
        )
        
        print(f"\nResponse Status: {response.status_code}")
        
        if response.status_code != 200:
            return {
                'success': False,
                'message': f'InfluxDB error: {response.status_code}',
                'data': None
            }
        
        # Parse response
        data = response.json()
        
        # Validate response structure
        if 'results' not in data or not data['results']:
            return {
                'success': False,
                'message': 'No results from InfluxDB',
                'data': None
            }
        
        if 'series' not in data['results'][0] or not data['results'][0]['series']:
            return {
                'success': False,
                'message': 'No data found for this time range',
                'data': None
            }
        
        # Extract data
        series = data['results'][0]['series'][0]
        columns = series['columns']  # ['time', 'sensor_40001', 'sensor_40002', ...]
        values = series['values']    # [[timestamp, val1, val2, ...], ...]
        
        print(f"\nData Points Received: {len(values)}")
        print(f"Columns: {columns}")
        
        # ✅ UPDATED: Parse timestamps (handle IST timezone format from InfluxDB)
        timestamps = []
        
        for row in values:
            timestamp_str = row[0]
            
            try:
                # InfluxDB returns: '2025-11-15T12:48:00+05:30' (already in IST)
                # We need to parse this and format it nicely
                
                # Remove timezone offset to get naive datetime
                # '2025-11-15T12:48:00+05:30' -> '2025-11-15T12:48:00'
                if '+' in timestamp_str:
                    timestamp_str_naive = timestamp_str.split('+')[0]
                elif timestamp_str.endswith('Z'):
                    timestamp_str_naive = timestamp_str.replace('Z', '')
                else:
                    timestamp_str_naive = timestamp_str
                
                # Parse the datetime
                dt = datetime.strptime(timestamp_str_naive, '%Y-%m-%dT%H:%M:%S')
                
                # Format for display (it's already in IST from InfluxDB)
                formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                timestamps.append(formatted_time)
                
            except Exception as e:
                print(f"⚠️  Warning: Could not parse timestamp '{row[0]}': {e}")
                # Use original timestamp if parsing fails
                timestamps.append(row[0])
        
        print(f"First timestamp: {timestamps[0] if timestamps else 'None'}")
        print(f"Last timestamp: {timestamps[-1] if timestamps else 'None'}")
        
        # Parse sensor data
        sensors_data = []
        
        for sensor in sensors:
            column_name = f'sensor_{sensor.field_name}'
            
            try:
                column_index = columns.index(column_name)
            except ValueError:
                # Sensor not in results
                print(f"⚠️  Warning: {column_name} not found in results")
                continue
            
            # Extract values for this sensor
            sensor_values = [row[column_index] for row in values]
            
            # Get metadata if exists
            metadata_dict = {}
            if hasattr(sensor, 'metadata_config'):
                metadata = sensor.metadata_config
                metadata_dict = {
                    'upper_limit': metadata.upper_limit,
                    'lower_limit': metadata.lower_limit,
                    'central_line': metadata.central_line,
                    'show_time_series': metadata.show_time_series,
                    'show_latest_value': metadata.show_latest_value,
                    'show_digital': metadata.show_digital,
                    'display_name': metadata.display_name or sensor.display_name,
                    'unit': metadata.unit or ''
                }
            else:
                metadata_dict = {
                    'upper_limit': None,
                    'lower_limit': None,
                    'central_line': None,
                    'show_time_series': False,
                    'show_latest_value': False,
                    'show_digital': False,
                    'display_name': sensor.display_name or sensor.field_name,
                    'unit': sensor.unit or ''
                }
            
            # Calculate latest value
            non_null_values = [v for v in sensor_values if v is not None]
            latest_value = non_null_values[-1] if non_null_values else None
            
            sensors_data.append({
                'id': sensor.id,
                'field_name': sensor.field_name,
                'display_name': metadata_dict['display_name'],
                'unit': metadata_dict['unit'],
                'values': sensor_values,
                'latest_value': latest_value,
                'metadata': metadata_dict
            })
        
        print(f"\n✅ Successfully fetched data for {len(sensors_data)} sensors")
        print(f"{'='*80}\n")
        
        return {
            'success': True,
            'message': 'Data fetched successfully',
            'data': {
                'timestamps': timestamps,
                'sensors': sensors_data,
                'time_range': time_range,
                'interval': interval
            }
        }
    
    except Exception as e:
        print(f"\n❌ Error fetching sensor data: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }