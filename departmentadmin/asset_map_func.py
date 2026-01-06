"""
Asset Map Helper Functions for Department Admin
Fetches location tracking data from InfluxDB (ALL points, not bucketed)
FIXED: Now fetches ALL 3 sensor groups (popup, info, timeseries)
UPDATED: Added point indexing for display
"""

import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
import re


def fetch_asset_tracking_data_from_influx(device, asset_config, influx_config, time_range='now() - 1h'):
    """
    Fetch ALL location points for asset tracking device from InfluxDB
    Returns every data point with ALL sensor groups (popup, info, timeseries)
    
    UPDATED: Now includes point_index (0, 1, 2...) for each point
    
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
                        'point_index': 0,        # NEW: Point number
                        'is_start': True,        # NEW: Is first point
                        'is_end': False,         # NEW: Is last point
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
                'start_point': {...},    # NEW: First point reference
                'end_point': {...},      # NEW: Last point reference
                'time_range': 'now() - 1h'
            }
        }
    """
    
    try:
        # Get real InfluxDB measurement name and device column from metadata
        influx_measurement_id = device.metadata.get('influx_measurement_id', device.measurement_name)
        device_column = device.metadata.get('device_column', 'id')
        
        print(f"\n{'='*80}")
        print(f"🗺️  FETCHING ASSET TRACKING DATA FROM INFLUXDB")
        print(f"{'='*80}")
        print(f"Device: {device.display_name} (ID: {device.device_id})")
        print(f"Measurement: {influx_measurement_id}")
        print(f"Device Column: {device_column}")
        print(f"Time Range: {time_range}")
        
        # ✅ STEP 1: Build SELECT fields for ALL 3 sensor groups
        select_fields = []
        all_sensors = {}  # Track which sensor belongs to which group
        
        # Add latitude & longitude (REQUIRED)
        lat_sensor = asset_config.latitude_sensor
        lng_sensor = asset_config.longitude_sensor
        
        if not lat_sensor or not lng_sensor:
            print(f"❌ Location sensors not configured")
            return {
                'success': False,
                'message': 'Location sensors (lat/lng) not configured',
                'data': None
            }
        
        select_fields.append(f'"{lat_sensor.field_name}" as lat')
        select_fields.append(f'"{lng_sensor.field_name}" as lng')
        
        print(f"📍 Location sensors: {lat_sensor.field_name} / {lng_sensor.field_name}")
        
        # ✅ GROUP 1: Map popup sensors
        popup_sensors = asset_config.map_popup_sensors.all()
        print(f"\n📊 GROUP 1 - Map Popup Sensors: {popup_sensors.count()}")
        
        for sensor in popup_sensors:
            if sensor.field_name not in [s.split(' as ')[0].strip('"') for s in select_fields]:
                select_fields.append(f'"{sensor.field_name}"')
            all_sensors[sensor.field_name] = {
                'sensor': sensor,
                'groups': ['popup']
            }
            print(f"   ✅ {sensor.field_name} ({sensor.display_name})")
        
        # ✅ GROUP 2: Info card sensors
        info_sensors = asset_config.info_card_sensors.all()
        print(f"\n📊 GROUP 2 - Info Card Sensors: {info_sensors.count()}")
        
        for sensor in info_sensors:
            if sensor.field_name not in [s.split(' as ')[0].strip('"') for s in select_fields]:
                select_fields.append(f'"{sensor.field_name}"')
            
            if sensor.field_name in all_sensors:
                all_sensors[sensor.field_name]['groups'].append('info')
            else:
                all_sensors[sensor.field_name] = {
                    'sensor': sensor,
                    'groups': ['info']
                }
            print(f"   ✅ {sensor.field_name} ({sensor.display_name})")
        
        # ✅ GROUP 3: Time series sensors
        timeseries_sensors = asset_config.time_series_sensors.all()
        print(f"\n📊 GROUP 3 - Time Series Sensors: {timeseries_sensors.count()}")
        
        for sensor in timeseries_sensors:
            if sensor.field_name not in [s.split(' as ')[0].strip('"') for s in select_fields]:
                select_fields.append(f'"{sensor.field_name}"')
            
            if sensor.field_name in all_sensors:
                all_sensors[sensor.field_name]['groups'].append('timeseries')
            else:
                all_sensors[sensor.field_name] = {
                    'sensor': sensor,
                    'groups': ['timeseries']
                }
            print(f"   ✅ {sensor.field_name} ({sensor.display_name})")
        
        select_clause = ', '.join(select_fields)
        
        print(f"\n📝 Total unique sensors in query: {len(all_sensors)}")
        
        # ✅ STEP 2: Build InfluxDB query (WITH ORDER BY time ASC - CRITICAL FOR POLYLINE!)
        query = f'''
        SELECT {select_clause}
        FROM "{influx_measurement_id}"
        WHERE time >= {time_range} 
          AND time <= now() 
          AND "{device_column}" = '{device.device_id}'
        ORDER BY time ASC
        tz('Asia/Kolkata')
        '''
        
        print(f"\n📝 Query:\n{query}")
        
        # ✅ STEP 3: Execute query
        base_url = f"{influx_config.base_api}/query"
        auth = HTTPBasicAuth(influx_config.api_username, influx_config.api_password)
        
        response = requests.get(
            base_url,
            params={'db': influx_config.db_name, 'q': query},
            auth=auth,
            verify=False,
            timeout=30
        )
        
        print(f"\n📡 Response Status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ InfluxDB returned error: {response.status_code}")
            return {
                'success': False,
                'message': f'InfluxDB error: {response.status_code}',
                'data': None
            }
        
        # ✅ STEP 4: Parse response
        data = response.json()
        
        if 'results' not in data or not data['results']:
            print(f"❌ No results in InfluxDB response")
            return {
                'success': False,
                'message': 'No results from InfluxDB',
                'data': None
            }
        
        if 'series' not in data['results'][0] or not data['results'][0]['series']:
            print(f"⚠️  No location data found for this time range")
            return {
                'success': False,
                'message': 'No location data found for this time range',
                'data': None
            }
        
        series = data['results'][0]['series'][0]
        columns = series['columns']
        values = series['values']
        
        print(f"\n📊 Data Points Received: {len(values)}")
        print(f"📋 Columns: {columns}")
        
        # ✅ STEP 5: Parse data points and separate into 3 groups
        points = []
        skipped_null_locations = 0
        skipped_parse_errors = 0
        
        # UPDATED: Track point index (Point 0, Point 1, Point 2...)
        point_index = 0
        
        for row in values:
            try:
                # Parse timestamp
                timestamp_str = row[0]
                
                # Truncate fractional seconds to 6 digits
                if '+' in timestamp_str:
                    timestamp_str_naive = timestamp_str.split('+')[0]
                elif timestamp_str.endswith('Z'):
                    timestamp_str_naive = timestamp_str.replace('Z', '')
                else:
                    timestamp_str_naive = timestamp_str
                
                if '.' in timestamp_str_naive:
                    parts = timestamp_str_naive.split('.')
                    if len(parts) == 2:
                        date_time_part = parts[0]
                        fractional_part = parts[1][:6]
                        timestamp_str_naive = f"{date_time_part}.{fractional_part}"
                
                dt = None
                try:
                    dt = datetime.strptime(timestamp_str_naive, '%Y-%m-%dT%H:%M:%S.%f')
                except ValueError:
                    try:
                        dt = datetime.strptime(timestamp_str_naive, '%Y-%m-%dT%H:%M:%S')
                    except ValueError:
                        skipped_parse_errors += 1
                        continue
                
                formatted_time = dt.strftime('%H:%M')
                formatted_date = dt.strftime('%d-%m-%Y')
                full_timestamp = f"{formatted_date} {formatted_time}"
                
                # Get lat/lng
                lat_index = columns.index('lat')
                lng_index = columns.index('lng')
                
                lat = row[lat_index]
                lng = row[lng_index]
                
                if lat is None or lng is None:
                    skipped_null_locations += 1
                    continue
                
                # ✅ BUILD 3 SEPARATE DATA GROUPS
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
                        
                        # Add to appropriate group(s)
                        if 'popup' in groups:
                            popup_data[field_name] = sensor_data
                        if 'info' in groups:
                            info_data[field_name] = sensor_data
                        if 'timeseries' in groups:
                            timeseries_data[field_name] = sensor_data
                    
                    except (ValueError, IndexError):
                        continue
                
                # ✅ UPDATED: Add point with index and flags
                points.append({
                    'point_index': point_index,      # NEW: Point 0, 1, 2...
                    'is_start': False,               # Will be updated after loop
                    'is_end': False,                 # Will be updated after loop
                    'time': formatted_time,
                    'date': formatted_date,
                    'timestamp': full_timestamp,
                    'lat': float(lat),
                    'lng': float(lng),
                    'popup_data': popup_data,
                    'info_data': info_data,
                    'timeseries_data': timeseries_data
                })
                
                point_index += 1  # Increment for next point
            
            except Exception as e:
                skipped_parse_errors += 1
                if skipped_parse_errors <= 3:
                    print(f"⚠️  Warning parsing point: {e}")
                continue
        
        # ✅ UPDATED: Mark start and end points
        if points:
            points[0]['is_start'] = True
            points[-1]['is_end'] = True
        
        # ✅ STEP 6: Summary
        print(f"\n{'='*80}")
        print(f"✅ Successfully parsed {len(points)} location points (Point 0 to Point {len(points)-1})")
        print(f"   📍 Popup sensors: {len(popup_data) if points else 0}")
        print(f"   📊 Info sensors: {len(info_data) if points else 0}")
        print(f"   📈 Timeseries sensors: {len(timeseries_data) if points else 0}")
        
        if skipped_null_locations > 0:
            print(f"⚠️  Skipped {skipped_null_locations} points with null lat/lng")
        
        if skipped_parse_errors > 0:
            print(f"⚠️  Skipped {skipped_parse_errors} points due to parse errors")
        
        print(f"{'='*80}\n")
        
        return {
            'success': True,
            'message': 'Location data fetched successfully',
            'data': {
                'points': points,
                'total_points': len(points),
                'start_point': points[0] if points else None,     # NEW
                'end_point': points[-1] if points else None,      # NEW
                'time_range': time_range,
                'skipped_null_locations': skipped_null_locations,
                'skipped_parse_errors': skipped_parse_errors
            }
        }
    
    except Exception as e:
        print(f"\n❌ ERROR in fetch_asset_tracking_data_from_influx")
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }