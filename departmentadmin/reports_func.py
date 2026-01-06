# departmentadmin/reports_func.py - FIXED VERSION

import csv
import io
import time
import requests
from datetime import datetime, timedelta
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from companyadmin.models import Device, Sensor, AssetConfig
from .models import DailyDeviceReport


def generate_device_daily_report(device, report_date, department, generated_by, tenant):
    """
    Main function to generate daily device report
    """
    
    print(f"\n{'='*100}")
    print(f"🔄 GENERATING DAILY REPORT")
    print(f"📱 Device: {device.display_name}")
    print(f"📅 Date: {report_date}")
    print(f"🏢 Department: {department.name}")
    print(f"{'='*100}\n")
    
    # Calculate time range (full day in IST)
    start_datetime = datetime.combine(report_date, datetime.min.time())
    end_datetime = datetime.combine(report_date, datetime.max.time())
    
    print(f"⏰ Time range: {start_datetime} to {end_datetime}")
    
    # Get only actual sensor data, exclude metadata/info fields
    sensors = device.sensors.filter(
        is_active=True,
        category='sensor'
    ).select_related('metadata_config')
    
    total_sensors = sensors.count()
    print(f"📊 Total sensors: {total_sensors}")
    
    if total_sensors == 0:
        raise Exception("No active sensors found for this device")
    
    # ✅ FIXED: Categorize sensors using data_types JSONField
    trend_sensors = []
    latest_sensors = []
    digital_sensors = []
    
    for sensor in sensors:
        if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
            metadata = sensor.metadata_config
            data_types = metadata.data_types or []
            
            # Check data_types list for sensor type
            if 'digital' in data_types:
                digital_sensors.append(sensor)
            elif 'latest_value' in data_types:
                latest_sensors.append(sensor)
            elif 'trend' in data_types:
                trend_sensors.append(sensor)
            else:
                # Default to trend if no data_types set
                trend_sensors.append(sensor)
        else:
            # No metadata - default to trend
            trend_sensors.append(sensor)
    
    print(f"📈 Trend sensors: {len(trend_sensors)}")
    print(f"📍 Latest sensors: {len(latest_sensors)}")
    print(f"🔌 Digital sensors: {len(digital_sensors)}")
    
    # Get AssetConfig for InfluxDB queries
    asset_config = device.asset_config
    
    if not asset_config or not asset_config.is_connected:
        raise Exception("No active AssetConfig found - configure InfluxDB settings first")
    
    print(f"🔧 InfluxDB: {asset_config.db_name}")
    
    # Fetch ALL three types of sensor data
    trend_data = fetch_trend_sensor_data(
        device=device,
        sensors=trend_sensors,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        asset_config=asset_config
    )
    
    latest_data = fetch_latest_sensor_data(
        device=device,
        sensors=latest_sensors,
        asset_config=asset_config
    )
    
    # Fetch digital sensor analysis
    digital_data = fetch_digital_sensors_batch(
        device=device,
        sensors=digital_sensors,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        asset_config=asset_config
    )
    
    # Generate CSV with all three types
    csv_content = generate_csv_content(
        device=device,
        trend_sensors=trend_sensors,
        latest_sensors=latest_sensors,
        digital_sensors=digital_sensors,
        trend_data=trend_data,
        latest_data=latest_data,
        digital_data=digital_data,
        report_date=report_date,
        start_datetime=start_datetime,
        end_datetime=end_datetime
    )
    
    # Create filename
    filename = f"daily_report_{device.display_name}_{report_date.strftime('%Y%m%d')}.csv"
    filename = filename.replace(' ', '_').replace('/', '_')
    
    # Calculate statistics
    total_data_points = sum(item.get('data_points', 0) for item in trend_data.values())
    total_data_points += sum(item.get('data_points', 0) for item in digital_data.values())
    
    # Save to database
    with transaction.atomic():
        report = DailyDeviceReport.objects.create(
            tenant=tenant,
            department=department,
            device=device,
            report_date=report_date,
            total_sensors=total_sensors,
            trend_sensors_count=len(trend_sensors),
            latest_sensors_count=len(latest_sensors),
            data_points_analyzed=total_data_points,
            generated_by=generated_by
        )
        
        # Save CSV file
        csv_file = ContentFile(csv_content.encode('utf-8'))
        report.csv_file.save(filename, csv_file, save=True)
    
    print(f"\n✅ Report generated successfully!")
    print(f"📄 File: {filename}")
    print(f"💾 Size: {report.file_size_mb} MB")
    print(f"📊 Data points: {total_data_points}")
    print(f"{'='*100}\n")
    
    return report

def generate_custom_device_report(device, start_datetime, end_datetime, department, generated_by, tenant):
    """
    Generate custom date/time range report with statistical summary + raw data
    """
    
    print(f"\n{'='*100}")
    print(f"🔄 GENERATING CUSTOM REPORT")
    print(f"📱 Device: {device.display_name}")
    print(f"📅 Range: {start_datetime} to {end_datetime}")
    print(f"🏢 Department: {department.name}")
    print(f"{'='*100}\n")
    
    # Calculate duration
    duration = end_datetime - start_datetime
    duration_hours = duration.total_seconds() / 3600
    
    print(f"⏰ Duration: {duration_hours:.1f} hours ({duration.days} days)")
    
    # Get only actual sensor data, exclude metadata/info fields
    sensors = device.sensors.filter(
        is_active=True,
        category='sensor'
    ).select_related('metadata_config')
    
    total_sensors = sensors.count()
    print(f"📊 Total sensors: {total_sensors}")
    
    if total_sensors == 0:
        raise Exception("No active sensors found for this device")
    
    # ✅ FIXED: Categorize sensors using data_types JSONField
    trend_sensors = []
    latest_sensors = []
    digital_sensors = []
    
    for sensor in sensors:
        if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
            metadata = sensor.metadata_config
            data_types = metadata.data_types or []
            
            # Check data_types list for sensor type
            if 'digital' in data_types:
                digital_sensors.append(sensor)
            elif 'latest_value' in data_types:
                latest_sensors.append(sensor)
            elif 'trend' in data_types:
                trend_sensors.append(sensor)
            else:
                # Default to trend if no data_types set
                trend_sensors.append(sensor)
        else:
            # No metadata - default to trend
            trend_sensors.append(sensor)
    
    print(f"📈 Trend sensors: {len(trend_sensors)}")
    print(f"📍 Latest sensors: {len(latest_sensors)}")
    print(f"🔌 Digital sensors: {len(digital_sensors)}")
    
    # Get AssetConfig
    asset_config = device.asset_config
    
    if not asset_config or not asset_config.is_connected:
        raise Exception("No active AssetConfig found")
    
    print(f"🔧 InfluxDB: {asset_config.db_name}")
    
    # Fetch statistical data
    trend_data = fetch_trend_sensor_data(
        device=device,
        sensors=trend_sensors,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        asset_config=asset_config
    )
    
    latest_data = fetch_latest_sensor_data(
        device=device,
        sensors=latest_sensors,
        asset_config=asset_config
    )
    
    digital_data = fetch_digital_sensors_batch(
        device=device,
        sensors=digital_sensors,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        asset_config=asset_config
    )
    
    # Fetch ALL raw data points for time series
    print(f"\n{'='*100}")
    print(f"📥 FETCHING RAW DATA (ALL DATA POINTS)")
    print(f"{'='*100}\n")
    
    raw_data = fetch_raw_sensor_data(
        device=device,
        sensors=sensors,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        asset_config=asset_config
    )
    
    # Generate CSV with statistics + raw data
    csv_content = generate_custom_csv_content(
        device=device,
        trend_sensors=trend_sensors,
        latest_sensors=latest_sensors,
        digital_sensors=digital_sensors,
        trend_data=trend_data,
        latest_data=latest_data,
        digital_data=digital_data,
        raw_data=raw_data,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        duration_hours=duration_hours
    )
    
    # Create filename with date range
    start_str = start_datetime.strftime('%Y%m%d_%H%M')
    end_str = end_datetime.strftime('%Y%m%d_%H%M')
    filename = f"custom_report_{device.display_name}_{start_str}_to_{end_str}.csv"
    filename = filename.replace(' ', '_').replace('/', '_')
    
    # Calculate statistics
    total_data_points = sum(item.get('data_points', 0) for item in trend_data.values())
    total_data_points += sum(item.get('data_points', 0) for item in digital_data.values())
    total_raw_points = raw_data.get('total_points', 0)
    
    # Save to database
    with transaction.atomic():
        report = DailyDeviceReport.objects.create(
            tenant=tenant,
            department=department,
            device=device,
            report_date=start_datetime.date(),
            report_type='custom',  # ✅ FIXED: Set report type to custom
            total_sensors=total_sensors,
            trend_sensors_count=len(trend_sensors),
            latest_sensors_count=len(latest_sensors),
            data_points_analyzed=total_raw_points,
            generated_by=generated_by
        )
        
        # Save CSV file
        csv_file = ContentFile(csv_content.encode('utf-8'))
        report.csv_file.save(filename, csv_file, save=True)
    
    print(f"\n✅ Custom report generated successfully!")
    print(f"📄 File: {filename}")
    print(f"💾 Size: {report.file_size_mb} MB")
    print(f"📊 Statistical points: {total_data_points}")
    print(f"📊 Raw data points: {total_raw_points}")
    print(f"{'='*100}\n")
    
    return report
# =============================================================================
# HELPER FUNCTION FOR SENSOR CATEGORIZATION (REUSABLE)
# =============================================================================

def categorize_sensors_by_type(sensors):
    """
    Categorize sensors by their data_types metadata
    
    Args:
        sensors: QuerySet of Sensor instances with metadata_config
    
    Returns:
        tuple: (trend_sensors, latest_sensors, digital_sensors)
    """
    trend_sensors = []
    latest_sensors = []
    digital_sensors = []
    
    for sensor in sensors:
        if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
            metadata = sensor.metadata_config
            data_types = metadata.data_types or []
            
            # Check data_types list for sensor type
            if 'digital' in data_types:
                digital_sensors.append(sensor)
            elif 'latest_value' in data_types:
                latest_sensors.append(sensor)
            elif 'trend' in data_types:
                trend_sensors.append(sensor)
            else:
                # Default to trend if no data_types set
                trend_sensors.append(sensor)
        else:
            # No metadata - default to trend
            trend_sensors.append(sensor)
    
    return trend_sensors, latest_sensors, digital_sensors


# =============================================================================
# REST OF THE FUNCTIONS (UNCHANGED)
# =============================================================================

def fetch_trend_sensor_data(device, sensors, start_datetime, end_datetime, asset_config):
    """
    Fetch trend sensor data from InfluxDB and calculate statistics
    """
    
    print(f"\n📈 Fetching TREND sensor data from InfluxDB...")
    
    if not sensors:
        print(f"   ⚠️  No trend sensors to fetch")
        return {}
    
    result = {}
    
    # Get device metadata
    metadata = device.metadata or {}
    influx_measurement_id = metadata.get('influx_measurement_id') or device.measurement_name
    device_column = metadata.get('device_column', 'id')
    
    # Format datetime for InfluxDB (UTC)
    start_str = start_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_str = end_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    print(f"   📡 Measurement: {influx_measurement_id}")
    print(f"   🆔 Device Column: {device_column} = {device.device_id}")
    print(f"   ⏰ Range: {start_str} to {end_str}")
    
    # Query each sensor
    for sensor in sensors:
        print(f"\n   🔍 Fetching: {sensor.field_name}")
        
        try:
            # Build InfluxDB query for statistics
            query = f'''
SELECT 
    mean("{sensor.field_name}") AS "mean_value",
    max("{sensor.field_name}") AS "max_value",
    min("{sensor.field_name}") AS "min_value"
FROM "{influx_measurement_id}"
WHERE time >= '{start_str}' 
  AND time <= '{end_str}'
  AND "{device_column}" = '{device.device_id}'
tz('Asia/Kolkata')
'''
            
            # Execute query
            response = requests.get(
                f"{asset_config.base_api}/query",
                params={
                    'db': asset_config.db_name,
                    'q': query
                },
                auth=(asset_config.api_username, asset_config.api_password),
                timeout=30,
                verify=False
            )
            
            if response.status_code != 200:
                print(f"      ❌ HTTP {response.status_code}")
                result[sensor.id] = {
                    'mean': None,
                    'max': None,
                    'min': None,
                    'data_points': 0
                }
                continue
            
            data = response.json()
            
            # Parse statistics
            if (data.get('results') and 
                data['results'][0].get('series')):
                
                series = data['results'][0]['series'][0]
                values = series.get('values', [])
                
                if values and values[0]:
                    row = values[0]
                    mean_val = row[1] if len(row) > 1 else None
                    max_val = row[2] if len(row) > 2 else None
                    min_val = row[3] if len(row) > 3 else None
                    
                    result[sensor.id] = {
                        'mean': round(float(mean_val), 2) if mean_val is not None else None,
                        'max': round(float(max_val), 2) if max_val is not None else None,
                        'min': round(float(min_val), 2) if min_val is not None else None,
                        'data_points': len(values)
                    }
                    
                    print(f"      ✅ Mean: {result[sensor.id]['mean']}, Max: {result[sensor.id]['max']}, Min: {result[sensor.id]['min']}")
                else:
                    result[sensor.id] = {
                        'mean': None,
                        'max': None,
                        'min': None,
                        'data_points': 0
                    }
                    print(f"      ⚠️  No data")
            else:
                result[sensor.id] = {
                    'mean': None,
                    'max': None,
                    'min': None,
                    'data_points': 0
                }
                print(f"      ⚠️  No series data")
                
        except Exception as e:
            print(f"      ❌ Error: {e}")
            result[sensor.id] = {
                'mean': None,
                'max': None,
                'min': None,
                'data_points': 0
            }
    
    print(f"\n   ✅ Trend data fetch complete: {len(result)} sensors")
    return result


def fetch_latest_sensor_data(device, sensors, asset_config):
    """
    Fetch latest values for latest-type sensors
    """
    
    print(f"\n📍 Fetching LATEST sensor data from InfluxDB...")
    
    if not sensors:
        print(f"   ⚠️  No latest sensors to fetch")
        return {}
    
    result = {}
    
    # Get device metadata
    metadata = device.metadata or {}
    influx_measurement_id = metadata.get('influx_measurement_id') or device.measurement_name
    device_column = metadata.get('device_column', 'id')
    
    print(f"   📡 Measurement: {influx_measurement_id}")
    print(f"   🆔 Device Column: {device_column} = {device.device_id}")
    
    # Query each sensor
    for sensor in sensors:
        print(f"\n   🔍 Fetching: {sensor.field_name}")
        
        try:
            query = f'''
SELECT last("{sensor.field_name}") AS "latest_value"
FROM "{influx_measurement_id}"
WHERE "{device_column}" = '{device.device_id}'
tz('Asia/Kolkata')
'''
            
            response = requests.get(
                f"{asset_config.base_api}/query",
                params={
                    'db': asset_config.db_name,
                    'q': query
                },
                auth=(asset_config.api_username, asset_config.api_password),
                timeout=10,
                verify=False
            )
            
            if response.status_code != 200:
                print(f"      ❌ HTTP {response.status_code}")
                result[sensor.id] = {'value': None, 'timestamp': None}
                continue
            
            data = response.json()
            
            if (data.get('results') and 
                data['results'][0].get('series')):
                
                series = data['results'][0]['series'][0]
                values = series.get('values', [])
                
                if values and values[0]:
                    timestamp = values[0][0]
                    value = values[0][1]
                    
                    result[sensor.id] = {
                        'value': round(float(value), 2) if value is not None else None,
                        'timestamp': timestamp
                    }
                    
                    print(f"      ✅ Value: {result[sensor.id]['value']} @ {timestamp}")
                else:
                    result[sensor.id] = {'value': None, 'timestamp': None}
                    print(f"      ⚠️  No data")
            else:
                result[sensor.id] = {'value': None, 'timestamp': None}
                print(f"      ⚠️  No series data")
                
        except Exception as e:
            print(f"      ❌ Error: {e}")
            result[sensor.id] = {'value': None, 'timestamp': None}
    
    print(f"\n   ✅ Latest data fetch complete: {len(result)} sensors")
    return result


def fetch_digital_sensors_batch(device, sensors, start_datetime, end_datetime, asset_config):
    """
    Fetch and analyze digital sensors in batch
    """
    
    print(f"\n🔌 Fetching DIGITAL sensor data from InfluxDB...")
    
    if not sensors:
        print(f"   ⚠️  No digital sensors to fetch")
        return {}
    
    result = {}
    
    # Get device metadata
    metadata = device.metadata or {}
    influx_measurement_id = metadata.get('influx_measurement_id') or device.measurement_name
    device_column = metadata.get('device_column', 'id')
    
    print(f"   📡 Measurement: {influx_measurement_id}")
    print(f"   🆔 Device Column: {device_column} = {device.device_id}")
    
    # Process each digital sensor
    for sensor in sensors:
        analysis = fetch_digital_sensor_analysis(
            device=device,
            sensor=sensor,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            influx_measurement_id=influx_measurement_id,
            device_column=device_column,
            asset_config=asset_config
        )
        
        if analysis:
            result[sensor.id] = analysis
    
    print(f"\n   ✅ Digital data fetch complete: {len(result)} sensors")
    return result


def fetch_digital_sensor_analysis(device, sensor, start_datetime, end_datetime,
                                   influx_measurement_id, device_column, asset_config):
    """
    Fetch and analyze digital sensor data for 24-hour period
    """
    
    try:
        print(f"\n   🔍 Fetching: {sensor.field_name}")
        
        # Query to get ALL data points for the day
        query = f'''
SELECT "{sensor.field_name}"
FROM "{influx_measurement_id}"
WHERE time >= '{start_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")}'
  AND time <= '{end_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")}'
  AND "{device_column}" = '{device.device_id}'
ORDER BY time ASC
'''
        
        response = requests.get(
            f"{asset_config.base_api}/query",
            params={
                'db': asset_config.db_name,
                'q': query,
                'epoch': 'ms'
            },
            auth=(asset_config.api_username, asset_config.api_password),
            verify=False,
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"      ⚠️  Query failed: {response.status_code}")
            return None
        
        result = response.json()
        
        if not result.get('results') or not result['results'][0].get('series'):
            print(f"      ⚠️  No data found")
            return None
        
        series = result['results'][0]['series'][0]
        values = series.get('values', [])
        
        if not values:
            print(f"      ⚠️  No values")
            return None
        
        print(f"      📊 Analyzing {len(values)} data points...")
        
        # Analyze the digital data
        analysis = analyze_digital_sensor_data(values, start_datetime, end_datetime)
        
        print(f"      ✅ Uptime: {analysis['uptime_percentage']:.1f}%, ON: {analysis['total_on_hours']:.1f}h, Changes: {analysis['state_changes']}")
        
        return analysis
        
    except Exception as e:
        print(f"      ❌ Error: {e}")
        return None


def analyze_digital_sensor_data(values, start_datetime, end_datetime):
    """
    Analyze digital sensor data points to calculate statistics
    """
    
    # Convert to list of (timestamp, state) tuples
    data_points = []
    for row in values:
        timestamp_ms = row[0]
        value = row[1]
        
        # Convert value to boolean
        if isinstance(value, str):
            state = value.strip().lower() in ['1', 'true', 'on']
        else:
            state = bool(int(float(value))) if value is not None else False
        
        data_points.append((timestamp_ms, state))
    
    # Calculate time periods
    total_duration_ms = (end_datetime - start_datetime).total_seconds() * 1000
    total_on_ms = 0
    state_changes = 0
    
    # Track continuous periods
    on_periods = []
    off_periods = []
    current_on_start = None
    current_off_start = None
    prev_state = None
    
    # Iterate through data points
    for i, (timestamp_ms, state) in enumerate(data_points):
        # Detect state change
        if prev_state is not None and state != prev_state:
            state_changes += 1
            
            # End previous period
            if prev_state:  # Was ON
                if current_on_start is not None:
                    on_duration = timestamp_ms - current_on_start
                    on_periods.append(on_duration)
                    current_on_start = None
            else:  # Was OFF
                if current_off_start is not None:
                    off_duration = timestamp_ms - current_off_start
                    off_periods.append(off_duration)
                    current_off_start = None
        
        # Start new period
        if state and current_on_start is None:
            current_on_start = timestamp_ms
        elif not state and current_off_start is None:
            current_off_start = timestamp_ms
        
        # Calculate time to next point
        if i < len(data_points) - 1:
            next_timestamp = data_points[i + 1][0]
            duration_to_next = next_timestamp - timestamp_ms
        else:
            end_timestamp_ms = int(end_datetime.timestamp() * 1000)
            duration_to_next = end_timestamp_ms - timestamp_ms
        
        # Add to ON time if currently ON
        if state:
            total_on_ms += duration_to_next
        
        prev_state = state
    
    # Close any open periods
    end_timestamp_ms = int(end_datetime.timestamp() * 1000)
    if current_on_start is not None:
        on_periods.append(end_timestamp_ms - current_on_start)
    if current_off_start is not None:
        off_periods.append(end_timestamp_ms - current_off_start)
    
    # Calculate statistics
    total_off_ms = total_duration_ms - total_on_ms
    uptime_percentage = (total_on_ms / total_duration_ms * 100) if total_duration_ms > 0 else 0
    
    total_on_hours = total_on_ms / (1000 * 60 * 60)
    total_off_hours = total_off_ms / (1000 * 60 * 60)
    
    longest_on_minutes = max(on_periods) / (1000 * 60) if on_periods else 0
    longest_off_minutes = max(off_periods) / (1000 * 60) if off_periods else 0
    
    current_state = "ON" if data_points[-1][1] else "OFF" if data_points else "UNKNOWN"
    
    return {
        'uptime_percentage': uptime_percentage,
        'total_on_hours': total_on_hours,
        'total_off_hours': total_off_hours,
        'state_changes': state_changes,
        'current_state': current_state,
        'data_points': len(data_points),
        'longest_on_minutes': longest_on_minutes,
        'longest_off_minutes': longest_off_minutes
    }


def fetch_raw_sensor_data(device, sensors, start_datetime, end_datetime, asset_config):
    """
    Fetch ALL raw data points for all sensors in the time range
    """
    
    print(f"📥 Fetching raw data for {sensors.count()} sensors...")
    
    if sensors.count() == 0:
        print(f"   ⚠️  No sensors to fetch")
        return {'timestamps': [], 'data': {}, 'total_points': 0}
    
    # Get device metadata
    metadata = device.metadata or {}
    influx_measurement_id = metadata.get('influx_measurement_id') or device.measurement_name
    device_column = metadata.get('device_column', 'id')
    
    # Format datetime for InfluxDB (UTC)
    start_str = start_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_str = end_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    print(f"   📡 Measurement: {influx_measurement_id}")
    print(f"   🆔 Device Column: {device_column} = {device.device_id}")
    print(f"   ⏰ Range: {start_str} to {end_str}")
    
    # Build SELECT clause with all sensor field names
    sensor_fields = [sensor.field_name for sensor in sensors]
    select_clause = ', '.join(f'"{field}"' for field in sensor_fields)
    
    # Build InfluxDB query for ALL raw data points
    query = f'''
SELECT {select_clause}
FROM "{influx_measurement_id}"
WHERE time >= '{start_str}' 
  AND time <= '{end_str}'
  AND "{device_column}" = '{device.device_id}'
ORDER BY time ASC
tz('Asia/Kolkata')
'''
    
    print(f"\n   🔍 Executing raw data query...")
    
    try:
        # Execute query
        response = requests.get(
            f"{asset_config.base_api}/query",
            params={
                'db': asset_config.db_name,
                'q': query,
                'epoch': 'ms'
            },
            auth=(asset_config.api_username, asset_config.api_password),
            timeout=120,
            verify=False
        )
        
        if response.status_code != 200:
            print(f"   ❌ HTTP {response.status_code}")
            return {'timestamps': [], 'data': {}, 'total_points': 0}
        
        result = response.json()
        
        # Parse the response
        if not result.get('results') or not result['results'][0].get('series'):
            print(f"   ⚠️  No data found")
            return {'timestamps': [], 'data': {}, 'total_points': 0}
        
        series = result['results'][0]['series'][0]
        columns = series.get('columns', [])
        values = series.get('values', [])
        
        total_points = len(values)
        print(f"   ✅ Retrieved {total_points:,} data points")
        
        # Organize data by timestamp
        organized_data = organize_raw_data(columns, values, sensors)
        
        print(f"   ✅ Data organized: {len(organized_data['timestamps']):,} timestamps")
        
        return organized_data
        
    except Exception as e:
        print(f"   ❌ Error fetching raw data: {e}")
        import traceback
        traceback.print_exc()
        return {'timestamps': [], 'data': {}, 'total_points': 0}


def organize_raw_data(columns, values, sensors):
    """
    Organize raw InfluxDB data into structured format for CSV
    """
    
    # Create sensor lookup by field_name
    sensor_lookup = {sensor.field_name: sensor for sensor in sensors}
    
    # Initialize data structure
    timestamps = []
    sensor_data = {sensor.field_name: [] for sensor in sensors}
    
    # Time column is always first (index 0)
    time_index = 0
    
    # Create column index mapping
    column_indices = {}
    for idx, col_name in enumerate(columns):
        if col_name == 'time':
            continue
        if col_name in sensor_lookup:
            column_indices[col_name] = idx
    
    # Process each row
    for row in values:
        # Extract timestamp (convert from milliseconds to datetime)
        timestamp_ms = row[time_index]
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000.0)
        timestamps.append(timestamp)
        
        # Extract sensor values
        for field_name, col_idx in column_indices.items():
            value = row[col_idx] if col_idx < len(row) else None
            
            # Format value
            if value is not None:
                try:
                    formatted_value = round(float(value), 2)
                except (ValueError, TypeError):
                    formatted_value = str(value)
            else:
                formatted_value = None
            
            sensor_data[field_name].append(formatted_value)
    
    return {
        'timestamps': timestamps,
        'data': sensor_data,
        'total_points': len(timestamps),
        'sensor_names': list(sensor_lookup.keys())
    }


def generate_csv_content(device, trend_sensors, latest_sensors, digital_sensors,
                        trend_data, latest_data, digital_data,
                        report_date, start_datetime, end_datetime):
    """
    Generate CSV with ALL sensor types
    """
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # HEADER
    writer.writerow([f"Daily Device Report - {device.display_name}"])
    writer.writerow([f"Report Date: {report_date.strftime('%Y-%m-%d')}"])
    writer.writerow([f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}"])
    writer.writerow([f"Time Range: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')} to {end_datetime.strftime('%Y-%m-%d %H:%M:%S')} IST"])
    writer.writerow([])
    
    # SUMMARY
    writer.writerow(["="*100])
    writer.writerow(["SUMMARY"])
    writer.writerow(["="*100])
    writer.writerow(["Total Sensors", len(trend_sensors) + len(latest_sensors) + len(digital_sensors)])
    writer.writerow(["Trend Sensors (Time Series)", len(trend_sensors)])
    writer.writerow(["Latest Sensors (Gauges)", len(latest_sensors)])
    writer.writerow(["Digital Sensors (ON/OFF)", len(digital_sensors)])
    writer.writerow([])
    
    # TREND SENSORS
    if trend_sensors:
        writer.writerow(["="*100])
        writer.writerow(["TREND SENSORS - TIME SERIES ANALYSIS (24 Hours)"])
        writer.writerow(["="*100])
        writer.writerow(["Sensor Name", "Unit", "Mean", "Maximum", "Minimum", "Data Points"])
        writer.writerow(["-"*100])
        
        for sensor in trend_sensors:
            if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
                sensor_name = sensor.metadata_config.display_name or sensor.field_name
                unit = sensor.metadata_config.unit or ""
            else:
                sensor_name = sensor.field_name
                unit = ""
            
            stats = trend_data.get(sensor.id, {})
            
            writer.writerow([
                sensor_name,
                unit or "-",
                stats.get('mean') or "N/A",
                stats.get('max') or "N/A",
                stats.get('min') or "N/A",
                stats.get('data_points', 0)
            ])
        
        writer.writerow([])
    
    # LATEST SENSORS
    if latest_sensors:
        writer.writerow(["="*100])
        writer.writerow(["LATEST VALUE SENSORS - CURRENT STATUS"])
        writer.writerow(["="*100])
        writer.writerow(["Sensor Name", "Unit", "Latest Value", "Timestamp"])
        writer.writerow(["-"*100])
        
        for sensor in latest_sensors:
            if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
                sensor_name = sensor.metadata_config.display_name or sensor.field_name
                unit = sensor.metadata_config.unit or ""
            else:
                sensor_name = sensor.field_name
                unit = ""
            
            latest = latest_data.get(sensor.id, {})
            
            writer.writerow([
                sensor_name,
                unit or "-",
                latest.get('value') or "N/A",
                latest.get('timestamp') or "N/A"
            ])
        
        writer.writerow([])
    
    # DIGITAL SENSORS
    if digital_sensors:
        writer.writerow(["="*100])
        writer.writerow(["DIGITAL SENSORS - OPERATIONAL ANALYSIS (24 Hours)"])
        writer.writerow(["="*100])
        writer.writerow([
            "Sensor Name", 
            "Uptime %", 
            "ON Time (hours)", 
            "OFF Time (hours)", 
            "State Changes",
            "Current State",
            "Longest ON (min)",
            "Longest OFF (min)",
            "Data Points"
        ])
        writer.writerow(["-"*100])
        
        for sensor in digital_sensors:
            if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
                sensor_name = sensor.metadata_config.display_name or sensor.field_name
            else:
                sensor_name = sensor.field_name
            
            stats = digital_data.get(sensor.id, {})
            
            writer.writerow([
                sensor_name,
                f"{stats.get('uptime_percentage', 0):.1f}%" if stats else "N/A",
                f"{stats.get('total_on_hours', 0):.1f}" if stats else "N/A",
                f"{stats.get('total_off_hours', 0):.1f}" if stats else "N/A",
                stats.get('state_changes', 0) if stats else "N/A",
                stats.get('current_state', 'UNKNOWN') if stats else "N/A",
                f"{stats.get('longest_on_minutes', 0):.1f}" if stats else "N/A",
                f"{stats.get('longest_off_minutes', 0):.1f}" if stats else "N/A",
                stats.get('data_points', 0) if stats else "N/A"
            ])
        
        writer.writerow([])
    
    # FOOTER
    writer.writerow(["="*100])
    writer.writerow(["END OF REPORT"])
    writer.writerow(["="*100])
    
    return output.getvalue()


def generate_custom_csv_content(device, trend_sensors, latest_sensors, digital_sensors,
                                trend_data, latest_data, digital_data, raw_data,
                                start_datetime, end_datetime, duration_hours):
    """
    Generate CSV content for custom report with statistics + raw data
    """
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Calculate duration display
    duration_days = int(duration_hours / 24)
    remaining_hours = duration_hours % 24
    
    if duration_days > 0:
        duration_str = f"{duration_days} days {remaining_hours:.1f} hours"
    else:
        duration_str = f"{duration_hours:.1f} hours"
    
    # ===================================
    # HEADER SECTION
    # ===================================
    writer.writerow(["="*100])
    writer.writerow(["CUSTOM DEVICE REPORT"])
    writer.writerow(["="*100])
    writer.writerow([f"Device: {device.display_name}"])
    writer.writerow([f"Device ID: {device.device_id}"])
    writer.writerow([f"Time Range: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')} to {end_datetime.strftime('%Y-%m-%d %H:%M:%S')} IST"])
    writer.writerow([f"Duration: {duration_str}"])
    writer.writerow([f"Total Data Points: {raw_data.get('total_points', 0):,}"])
    writer.writerow([f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}"])
    writer.writerow([])
    
    # ===================================
    # SUMMARY SECTION
    # ===================================
    writer.writerow(["="*100])
    writer.writerow(["SUMMARY"])
    writer.writerow(["="*100])
    writer.writerow(["Total Sensors", len(trend_sensors) + len(latest_sensors) + len(digital_sensors)])
    writer.writerow(["Trend Sensors (Time Series)", len(trend_sensors)])
    writer.writerow(["Latest Sensors (Gauges)", len(latest_sensors)])
    writer.writerow(["Digital Sensors (ON/OFF)", len(digital_sensors)])
    writer.writerow([])
    
    # ===================================
    # TREND SENSORS SECTION
    # ===================================
    if trend_sensors:
        writer.writerow(["="*100])
        writer.writerow(["TREND SENSORS - STATISTICAL ANALYSIS"])
        writer.writerow(["="*100])
        writer.writerow(["Sensor Name", "Unit", "Mean", "Maximum", "Minimum", "Data Points"])
        writer.writerow(["-"*100])
        
        for sensor in trend_sensors:
            if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
                sensor_name = sensor.metadata_config.display_name or sensor.field_name
                unit = sensor.metadata_config.unit or ""
            else:
                sensor_name = sensor.field_name
                unit = ""
            
            stats = trend_data.get(sensor.id, {})
            
            writer.writerow([
                sensor_name,
                unit or "-",
                stats.get('mean') or "N/A",
                stats.get('max') or "N/A",
                stats.get('min') or "N/A",
                stats.get('data_points', 0)
            ])
        
        writer.writerow([])
    
    # ===================================
    # LATEST SENSORS SECTION
    # ===================================
    if latest_sensors:
        writer.writerow(["="*100])
        writer.writerow(["LATEST VALUE SENSORS - CURRENT STATUS"])
        writer.writerow(["="*100])
        writer.writerow(["Sensor Name", "Unit", "Latest Value", "Timestamp"])
        writer.writerow(["-"*100])
        
        for sensor in latest_sensors:
            if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
                sensor_name = sensor.metadata_config.display_name or sensor.field_name
                unit = sensor.metadata_config.unit or ""
            else:
                sensor_name = sensor.field_name
                unit = ""
            
            latest = latest_data.get(sensor.id, {})
            
            writer.writerow([
                sensor_name,
                unit or "-",
                latest.get('value') or "N/A",
                latest.get('timestamp') or "N/A"
            ])
        
        writer.writerow([])
    
    # ===================================
    # DIGITAL SENSORS SECTION
    # ===================================
    if digital_sensors:
        writer.writerow(["="*100])
        writer.writerow(["DIGITAL SENSORS - OPERATIONAL ANALYSIS"])
        writer.writerow(["="*100])
        writer.writerow([
            "Sensor Name", 
            "Uptime %", 
            "ON Time (hours)", 
            "OFF Time (hours)", 
            "State Changes",
            "Current State",
            "Longest ON (min)",
            "Longest OFF (min)",
            "Data Points"
        ])
        writer.writerow(["-"*100])
        
        for sensor in digital_sensors:
            if hasattr(sensor, 'metadata_config') and sensor.metadata_config:
                sensor_name = sensor.metadata_config.display_name or sensor.field_name
            else:
                sensor_name = sensor.field_name
            
            stats = digital_data.get(sensor.id, {})
            
            writer.writerow([
                sensor_name,
                f"{stats.get('uptime_percentage', 0):.1f}%" if stats else "N/A",
                f"{stats.get('total_on_hours', 0):.1f}" if stats else "N/A",
                f"{stats.get('total_off_hours', 0):.1f}" if stats else "N/A",
                stats.get('state_changes', 0) if stats else "N/A",
                stats.get('current_state', 'UNKNOWN') if stats else "N/A",
                f"{stats.get('longest_on_minutes', 0):.1f}" if stats else "N/A",
                f"{stats.get('longest_off_minutes', 0):.1f}" if stats else "N/A",
                stats.get('data_points', 0) if stats else "N/A"
            ])
        
        writer.writerow([])
    
    # ===================================
    # RAW DATA SECTION
    # ===================================
    if raw_data.get('total_points', 0) > 0:
        writer.writerow(["="*100])
        writer.writerow(["RAW DATA - TIME SERIES (ALL DATA POINTS)"])
        writer.writerow(["="*100])
        writer.writerow([f"Total Records: {raw_data['total_points']:,}"])
        writer.writerow([f"Time Range: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')} to {end_datetime.strftime('%Y-%m-%d %H:%M:%S')} IST"])
        writer.writerow([])
        
        # Build header row with timestamp + all sensor names
        timestamps = raw_data.get('timestamps', [])
        sensor_names = raw_data.get('sensor_names', [])
        data = raw_data.get('data', {})
        
        # Header row
        header = ['Timestamp'] + sensor_names
        writer.writerow(header)
        writer.writerow(["-"*100])
        
        # Data rows
        total_rows = len(timestamps)
        print(f"\n   📝 Writing {total_rows:,} raw data rows to CSV...")
        
        # Write in batches for progress indication
        batch_size = 1000
        for i in range(0, total_rows, batch_size):
            batch_end = min(i + batch_size, total_rows)
            
            for j in range(i, batch_end):
                timestamp = timestamps[j]
                row = [timestamp.strftime('%Y-%m-%d %H:%M:%S')]
                
                # Add sensor values for this timestamp
                for sensor_name in sensor_names:
                    value = data.get(sensor_name, [])[j] if j < len(data.get(sensor_name, [])) else None
                    row.append(value if value is not None else "")
                
                writer.writerow(row)
            
            # Progress indication
            if batch_end % 5000 == 0 or batch_end == total_rows:
                progress = (batch_end / total_rows) * 100
                print(f"      Progress: {batch_end:,}/{total_rows:,} rows ({progress:.1f}%)")
        
        print(f"   ✅ Raw data section complete!")
        writer.writerow([])
    else:
        writer.writerow(["="*100])
        writer.writerow(["RAW DATA - TIME SERIES"])
        writer.writerow(["="*100])
        writer.writerow(["⚠️  No raw data available for the selected time range"])
        writer.writerow([])
    
    # ===================================
    # FOOTER SECTION
    # ===================================
    writer.writerow(["="*100])
    writer.writerow(["END OF REPORT"])
    writer.writerow(["="*100])
    writer.writerow([f"Device: {device.display_name}"])
    writer.writerow([f"Report Type: Custom Date/Time Range Report"])
    writer.writerow([f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}"])
    writer.writerow(["="*100])
    
    return output.getvalue()