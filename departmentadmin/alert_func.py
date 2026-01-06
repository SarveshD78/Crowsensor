# departmentadmin/alert_func.py - FIXED VERSION WITH DEVICE-SPECIFIC INFLUXDB

from datetime import datetime
from django.db import connection
from django_tenants.utils import schema_context
from companyadmin.models import SensorMetadata, AssetConfig
from departmentadmin.models import SensorAlert
from django.db.models import Q
import requests
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def check_tenant_sensors_for_alerts(tenant_schema_name):
    """
    Main alert monitoring function for a SPECIFIC TENANT
    Runs every 30 seconds per tenant with FULL DEBUG OUTPUT
    
    ✅ FIXED: Uses device-specific InfluxDB config
    ✅ FIXED: Only monitors industrial_sensor devices (not asset_tracking)
    
    Args:
        tenant_schema_name (str): The tenant's schema name (e.g., 'sisaitech', 'tecktrol')
    """
    
    # Switch to tenant's schema
    with schema_context(tenant_schema_name):
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        print("\n" + "="*100)
        print(f"🔍 ALERT MONITORING CYCLE - TENANT: {tenant_schema_name.upper()}")
        print(f"🕐 Time: {current_time}")
        print("="*100)
        
        try:
            # ✅ REMOVED: No longer fetch global AssetConfig here
            # Each sensor will use its device's specific asset_config
            
            # STEP 1: Check if tenant has any active AssetConfig
            print(f"\n📋 STEP 1: Checking AssetConfig availability for tenant '{tenant_schema_name}'...")
            
            if not AssetConfig.has_active_config():
                print(f"   ❌ FAILED: No active AssetConfig found")
                print(f"   💡 Action: Configure InfluxDB settings in Company Admin")
                print("="*100 + "\n")
                return
            
            active_configs = AssetConfig.get_active_configs()
            print(f"   ✅ Found {active_configs.count()} active InfluxDB config(s):")
            for config in active_configs:
                print(f"      - {config.config_name} ({config.db_name})")
            
            # STEP 2: Get all sensors with limits configured (ONLY industrial_sensor devices)
            print(f"\n📋 STEP 2: Finding sensors with configured limits (industrial devices only)...")
            
            # ✅ FIXED: Filter by device_type='industrial_sensor'
            sensors_with_limits = SensorMetadata.objects.filter(
                Q(upper_limit__isnull=False) | Q(lower_limit__isnull=False),
                sensor__device__device_type='industrial_sensor',  # ✅ Only industrial devices
                sensor__device__is_active=True,                   # ✅ Only active devices
                sensor__is_active=True                            # ✅ Only active sensors
            ).select_related(
                'sensor__device__asset_config'  # ✅ Prefetch asset_config for efficiency
            )
            
            total_sensors = sensors_with_limits.count()
            print(f"   📊 Found {total_sensors} sensor(s) with limits on industrial devices")
            
            if total_sensors == 0:
                print(f"   ⚠️  No sensors have limits configured on industrial devices")
                print(f"   💡 Action: Set upper_limit or lower_limit in SensorMetadata")
                print("="*100 + "\n")
                return
            
            # List all sensors being monitored
            print(f"\n   📝 Sensors to monitor:")
            for idx, sensor_meta in enumerate(sensors_with_limits, 1):
                device = sensor_meta.sensor.device
                print(f"      {idx}. {sensor_meta.sensor.field_name}")
                print(f"         Device: {device.display_name} (ID: {device.device_id})")
                print(f"         InfluxDB: {device.asset_config.config_name}")  # ✅ Show which InfluxDB
                print(f"         Limits: Upper={sensor_meta.upper_limit}, Lower={sensor_meta.lower_limit}")
            
            # STEP 3: Check each sensor
            print(f"\n📋 STEP 3: Checking each sensor for breaches...")
            print("-"*100)
            
            # Stats tracking
            alerts_created = 0
            alerts_escalated = 0
            alerts_resolved = 0
            errors = 0
            checked_normal = 0
            no_data = 0
            
            # Check each sensor
            for sensor_idx, sensor_meta in enumerate(sensors_with_limits, 1):
                device = sensor_meta.sensor.device
                
                print(f"\n🔬 SENSOR {sensor_idx}/{total_sensors}: {sensor_meta.sensor.field_name}")
                print(f"   Device: {device.display_name}")
                print(f"   Device ID: {device.device_id}")
                print(f"   Measurement: {device.measurement_name}")
                print(f"   InfluxDB Config: {device.asset_config.config_name}")  # ✅ Show config
                
                try:
                    # ✅ FIXED: Pass device's specific asset_config
                    result = check_single_sensor(sensor_meta, tenant_schema_name)
                    
                    if result == 'created':
                        alerts_created += 1
                        print(f"   ✅ RESULT: New alert created")
                    elif result == 'escalated':
                        alerts_escalated += 1
                        print(f"   ⚠️  RESULT: Alert escalated")
                    elif result == 'resolved':
                        alerts_resolved += 1
                        print(f"   ✔️  RESULT: Alert resolved")
                    elif result == 'normal':
                        checked_normal += 1
                        print(f"   ✅ RESULT: Normal (no breach)")
                    elif result == 'no_data':
                        no_data += 1
                        print(f"   ⚠️  RESULT: No data from InfluxDB")
                    elif result == 'checked':
                        print(f"   ⏱️  RESULT: Alert exists, waiting for escalation")
                        
                except Exception as e:
                    errors += 1
                    print(f"   ❌ EXCEPTION: {e}")
                    import traceback
                    traceback.print_exc()
                
                print("-"*100)
            
            # STEP 4: Summary
            print(f"\n📊 CYCLE SUMMARY - TENANT: {tenant_schema_name.upper()}")
            print(f"   🟢 New Alerts Created:    {alerts_created}")
            print(f"   ⚠️  Alerts Escalated:      {alerts_escalated}")
            print(f"   ✅ Alerts Resolved:       {alerts_resolved}")
            print(f"   ✔️  Normal (No Breach):    {checked_normal}")
            print(f"   ⚠️  No Data:               {no_data}")
            print(f"   ❌ Errors:                {errors}")
            print("="*100 + "\n")
            
        except Exception as e:
            print(f"\n❌ CRITICAL ERROR in tenant '{tenant_schema_name}': {e}")
            import traceback
            traceback.print_exc()
            print("="*100 + "\n")


def check_single_sensor(sensor_meta, tenant_schema_name):
    """
    Check a single sensor for alert conditions with DETAILED DEBUG
    
    ✅ FIXED: Gets asset_config from the device itself
    
    Args:
        sensor_meta: SensorMetadata instance
        tenant_schema_name: Current tenant schema
    
    Returns:
        str: 'created', 'escalated', 'resolved', 'normal', 'checked', or 'no_data'
    """
    
    sensor = sensor_meta.sensor
    device = sensor.device
    
    # ✅ FIXED: Get asset_config from device (not global)
    asset_config = device.asset_config
    
    sensor_name = sensor.field_name
    device_id = device.device_id
    
    # STEP A: Display sensor limits
    print(f"\n   🎯 STEP A: Checking limits configuration")
    print(f"      Upper limit: {sensor_meta.upper_limit}")
    print(f"      Lower limit: {sensor_meta.lower_limit}")
    print(f"      InfluxDB: {asset_config.config_name} ({asset_config.db_name})")  # ✅ Show config
    
    # STEP B: Get current value from InfluxDB
    print(f"\n   📡 STEP B: Fetching current value from InfluxDB...")
    current_value = get_sensor_current_value(sensor_meta, asset_config)
    
    if current_value is None:
        print(f"      ❌ No data returned - cannot check for breach")
        return 'no_data'
    
    print(f"      ✅ Current value: {current_value}")
    
    # STEP C: Check for existing alert
    print(f"\n   🔍 STEP C: Checking for existing alerts...")
    existing_alert = SensorAlert.objects.filter(
        sensor_metadata=sensor_meta,
        status__in=['initial', 'medium', 'high']
    ).first()
    
    if existing_alert:
        print(f"      ⚠️  Existing alert found:")
        print(f"         ID: {existing_alert.id}")
        print(f"         Status: {existing_alert.status}")
        print(f"         Created: {existing_alert.created_at}")
        print(f"         Duration: {existing_alert.duration_minutes} minutes")
        print(f"         Breach type: {existing_alert.breach_type}")
        print(f"         Breach value: {existing_alert.breach_value}")
    else:
        print(f"      ✅ No existing active alert")
    
    # STEP D: Check if breach occurred
    print(f"\n   🚨 STEP D: Checking for breach conditions...")
    is_breach = False
    breach_type = None
    limit_value = None
    
    # Check upper limit breach
    if sensor_meta.upper_limit is not None:
        print(f"      Checking: {current_value} > {sensor_meta.upper_limit} (upper limit)?")
        if current_value > sensor_meta.upper_limit:
            is_breach = True
            breach_type = 'upper'
            limit_value = sensor_meta.upper_limit
            print(f"      🔴 YES! UPPER LIMIT BREACH DETECTED!")
            print(f"         Current: {current_value}")
            print(f"         Limit: {limit_value}")
            print(f"         Difference: +{current_value - limit_value:.2f}")
    
    # Check lower limit breach (only if no upper breach)
    if not is_breach and sensor_meta.lower_limit is not None:
        print(f"      Checking: {current_value} < {sensor_meta.lower_limit} (lower limit)?")
        if current_value < sensor_meta.lower_limit:
            is_breach = True
            breach_type = 'lower'
            limit_value = sensor_meta.lower_limit
            print(f"      🔴 YES! LOWER LIMIT BREACH DETECTED!")
            print(f"         Current: {current_value}")
            print(f"         Limit: {limit_value}")
            print(f"         Difference: -{limit_value - current_value:.2f}")
    
    if not is_breach:
        print(f"      ✅ NO BREACH - Value is within limits")
    
    # STEP E: Handle alert logic
    print(f"\n   ⚙️  STEP E: Executing alert logic...")
    
    if is_breach:
        print(f"      🚨 Breach detected - processing alert...")
        
        if existing_alert:
            print(f"      ℹ️  Alert already exists - checking for escalation...")
            
            # Check escalation conditions
            can_escalate_medium = existing_alert.can_escalate_to_medium
            can_escalate_high = existing_alert.can_escalate_to_high
            
            print(f"         Can escalate to medium? {can_escalate_medium}")
            print(f"         Can escalate to high? {can_escalate_high}")
            
            if can_escalate_medium or can_escalate_high:
                old_status = existing_alert.status
                existing_alert.escalate()
                new_status = existing_alert.status
                print(f"      ⚠️  ESCALATED: {old_status} → {new_status}")
                return 'escalated'
            else:
                # Update breach value but don't escalate yet
                existing_alert.update_breach_value(current_value)
                print(f"      ⏱️  Alert waiting for escalation time")
                print(f"         Current duration: {existing_alert.duration_minutes} minutes")
                print(f"         Next escalation: {60 if existing_alert.status == 'initial' else 90} minutes")
                return 'checked'
        else:
            print(f"      🟢 No existing alert - creating new alert...")
            
            try:
                alert = SensorAlert.objects.create(
                    sensor_metadata=sensor_meta,
                    status='initial',
                    breach_type=breach_type,
                    breach_value=current_value,
                    limit_value=limit_value
                )
                print(f"      ✅ NEW ALERT CREATED!")
                print(f"         Alert ID: {alert.id}")
                print(f"         Status: {alert.status}")
                print(f"         Breach type: {breach_type}")
                print(f"         Current value: {current_value}")
                print(f"         Limit value: {limit_value}")
                return 'created'
                
            except Exception as e:
                print(f"      ❌ FAILED TO CREATE ALERT: {e}")
                import traceback
                traceback.print_exc()
                return 'error'
    else:
        print(f"      ✅ No breach - checking for alert resolution...")
        
        if existing_alert:
            print(f"      ✅ Resolving existing alert (value returned to normal)")
            existing_alert.resolve()
            print(f"         Alert ID: {existing_alert.id} marked as RESOLVED")
            return 'resolved'
        else:
            print(f"      ✅ All normal - no action needed")
            return 'normal'


def get_sensor_current_value(sensor_meta, asset_config):
    """
    Get current sensor value from InfluxDB using MEAN over last 1 hour
    
    ✅ FIXED: Uses passed asset_config (device-specific)
    
    Args:
        sensor_meta: SensorMetadata instance
        asset_config: AssetConfig instance (device-specific)
    
    Returns:
        float: Mean sensor value over last 1 hour or None if error
    """
    
    try:
        sensor = sensor_meta.sensor
        device = sensor.device
        measurement = device.measurement_name
        
        # Get device_column from device metadata (like graphs do!)
        influx_measurement_id = device.metadata.get('influx_measurement_id', measurement)
        device_column = device.metadata.get('device_column', 'id')  # Default 'id', but usually 'deviceID'
        
        # Use 1 hour window with 2 minute intervals
        time_range = 'now() - 1h'
        interval = '2m'
        
        print(f"      📝 Query parameters:")
        print(f"         Config: {asset_config.config_name}")  # ✅ Show which config
        print(f"         Database: {asset_config.db_name}")
        print(f"         Measurement: {influx_measurement_id}")
        print(f"         Field: {sensor.field_name}")
        print(f"         Device ID: {device.device_id}")
        print(f"         Device Column: {device_column}")
        print(f"         Time Range: {time_range}")
        print(f"         Interval: {interval}")
        
        # Build InfluxDB query using MEAN aggregation
        query = f'''
SELECT mean("{sensor.field_name}") AS "current_value"
FROM "{influx_measurement_id}"
WHERE time >= {time_range} 
  AND time <= now() 
  AND "{device_column}" = '{device.device_id}'
GROUP BY time({interval}) fill(null)
tz('Asia/Kolkata')
'''
        
        print(f"      📡 Executing InfluxDB query...")
        print(f"         URL: {asset_config.base_api}/query")
        print(f"         WHERE {device_column} = '{device.device_id}'")
        print(f"         Aggregation: MEAN over 1 hour")
        
        # Execute query
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
        
        print(f"      📊 Response received:")
        print(f"         Status code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"         ❌ HTTP Error: {response.text}")
            return None
        
        data = response.json()
        
        # Check if we have results
        if not data.get('results'):
            print(f"         ❌ No 'results' in response")
            print(f"         Raw response: {data}")
            return None
        
        if not data['results'][0].get('series'):
            print(f"         ⚠️  No 'series' in results (no data points found)")
            print(f"         This means no data in last 1 hour for this device/sensor")
            return None
        
        series = data['results'][0]['series'][0]
        columns = series.get('columns', [])
        values = series.get('values', [])
        
        print(f"         ✅ Data found:")
        print(f"            Columns: {columns}")
        print(f"            Data points: {len(values)}")
        
        if not values:
            print(f"         ⚠️  No values returned")
            return None
        
        # Find last non-null mean value (most recent data point)
        last_value = None
        last_timestamp = None
        
        # Column index for "current_value" (mean result)
        try:
            value_index = columns.index('current_value')
        except ValueError:
            # Fallback: try index 1 (time is always 0)
            value_index = 1
        
        # Iterate in reverse to find most recent non-null value
        for row in reversed(values):
            if len(row) > value_index:
                value = row[value_index]
                if value is not None:
                    last_value = value
                    last_timestamp = row[0]  # time is always first column
                    break
        
        if last_value is None:
            print(f"         ⚠️  All mean values are NULL in the 1-hour range")
            return None
        
        print(f"            Latest timestamp: {last_timestamp}")
        print(f"            Latest mean value: {last_value}")
        
        fetched_value = float(last_value)
        print(f"      ✅ SUCCESS: Mean Value (1hr) = {fetched_value}")
        return fetched_value
        
    except Exception as e:
        print(f"      ❌ EXCEPTION occurred: {e}")
        import traceback
        traceback.print_exc()
        return None