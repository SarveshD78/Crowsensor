"""
departmentadmin/alert_func.py

Alert monitoring functions for tenant-specific sensor threshold checking.
Uses device-specific InfluxDB configurations for querying sensor data.
"""

import logging

import requests
import urllib3
from django_tenants.utils import schema_context

from companyadmin.models import AssetConfig, SensorMetadata
from departmentadmin.models import SensorAlert
from django.db.models import Q

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


# =============================================================================
# MAIN ALERT MONITORING FUNCTION
# =============================================================================

def check_tenant_sensors_for_alerts(tenant_schema_name):
    """
    Main alert monitoring function for a specific tenant.
    
    Runs every 30 seconds per tenant. Uses device-specific InfluxDB config
    and only monitors industrial_sensor devices (not asset_tracking).
    
    Args:
        tenant_schema_name: The tenant's schema name (e.g., 'sisaitech', 'tecktrol')
    """
    with schema_context(tenant_schema_name):
        logger.info("=" * 100)
        logger.info(f"ALERT MONITORING CYCLE - TENANT: {tenant_schema_name.upper()}")
        logger.info("=" * 100)
        
        try:
            # Step 1: Check if tenant has any active AssetConfig
            logger.debug(f"Checking AssetConfig availability for tenant '{tenant_schema_name}'")
            
            if not AssetConfig.has_active_config():
                logger.warning("No active AssetConfig found - skipping alert check")
                return
            
            active_configs = AssetConfig.get_active_configs()
            logger.info(f"Found {active_configs.count()} active InfluxDB config(s)")
            
            # Step 2: Get all sensors with limits configured (industrial devices only)
            logger.debug("Finding sensors with configured limits (industrial devices only)")
            
            sensors_with_limits = SensorMetadata.objects.filter(
                Q(upper_limit__isnull=False) | Q(lower_limit__isnull=False),
                sensor__device__device_type='industrial_sensor',
                sensor__device__is_active=True,
                sensor__is_active=True
            ).select_related('sensor__device__asset_config')
            
            total_sensors = sensors_with_limits.count()
            logger.info(f"Found {total_sensors} sensor(s) with limits on industrial devices")
            
            if total_sensors == 0:
                logger.debug("No sensors have limits configured on industrial devices")
                return
            
            # Step 3: Check each sensor
            logger.debug("Checking each sensor for breaches")
            
            stats = {
                'alerts_created': 0,
                'alerts_escalated': 0,
                'alerts_resolved': 0,
                'checked_normal': 0,
                'no_data': 0,
                'errors': 0
            }
            
            for sensor_idx, sensor_meta in enumerate(sensors_with_limits, 1):
                device = sensor_meta.sensor.device
                logger.debug(
                    f"Sensor {sensor_idx}/{total_sensors}: {sensor_meta.sensor.field_name} "
                    f"on {device.display_name}"
                )
                
                try:
                    result = check_single_sensor(sensor_meta, tenant_schema_name)
                    _update_stats(stats, result)
                    
                except Exception as e:
                    stats['errors'] += 1
                    logger.error(f"Error checking sensor {sensor_meta.sensor.field_name}: {e}", exc_info=True)
            
            # Step 4: Log summary
            logger.info(f"CYCLE SUMMARY - TENANT: {tenant_schema_name.upper()}")
            logger.info(f"  New Alerts Created: {stats['alerts_created']}")
            logger.info(f"  Alerts Escalated: {stats['alerts_escalated']}")
            logger.info(f"  Alerts Resolved: {stats['alerts_resolved']}")
            logger.info(f"  Normal (No Breach): {stats['checked_normal']}")
            logger.info(f"  No Data: {stats['no_data']}")
            logger.info(f"  Errors: {stats['errors']}")
            logger.info("=" * 100)
            
        except Exception as e:
            logger.error(f"Critical error in tenant '{tenant_schema_name}': {e}", exc_info=True)


def _update_stats(stats, result):
    """Update statistics dictionary based on check result."""
    if result == 'created':
        stats['alerts_created'] += 1
    elif result == 'escalated':
        stats['alerts_escalated'] += 1
    elif result == 'resolved':
        stats['alerts_resolved'] += 1
    elif result == 'normal':
        stats['checked_normal'] += 1
    elif result == 'no_data':
        stats['no_data'] += 1


# =============================================================================
# SINGLE SENSOR CHECK
# =============================================================================

def check_single_sensor(sensor_meta, tenant_schema_name):
    """
    Check a single sensor for alert conditions.
    
    Gets asset_config from the device itself (device-specific InfluxDB).
    
    Args:
        sensor_meta: SensorMetadata instance
        tenant_schema_name: Current tenant schema
    
    Returns:
        str: 'created', 'escalated', 'resolved', 'normal', 'checked', or 'no_data'
    """
    sensor = sensor_meta.sensor
    device = sensor.device
    asset_config = device.asset_config
    
    logger.debug(f"Checking limits - Upper: {sensor_meta.upper_limit}, Lower: {sensor_meta.lower_limit}")
    logger.debug(f"Using InfluxDB config: {asset_config.config_name}")
    
    # Get current value from InfluxDB
    current_value = get_sensor_current_value(sensor_meta, asset_config)
    
    if current_value is None:
        logger.debug("No data returned from InfluxDB")
        return 'no_data'
    
    logger.debug(f"Current value: {current_value}")
    
    # Check for existing alert
    existing_alert = SensorAlert.objects.filter(
        sensor_metadata=sensor_meta,
        status__in=['initial', 'medium', 'high']
    ).first()
    
    if existing_alert:
        logger.debug(
            f"Existing alert found - ID: {existing_alert.id}, Status: {existing_alert.status}, "
            f"Duration: {existing_alert.duration_minutes} minutes"
        )
    
    # Check if breach occurred
    breach_info = _check_for_breach(sensor_meta, current_value)
    
    # Handle alert logic
    return _handle_alert_logic(
        sensor_meta, existing_alert, breach_info, current_value
    )


def _check_for_breach(sensor_meta, current_value):
    """
    Check if current value breaches any limit.
    
    Args:
        sensor_meta: SensorMetadata instance
        current_value: Current sensor value
        
    Returns:
        dict: {'is_breach': bool, 'breach_type': str or None, 'limit_value': float or None}
    """
    # Check upper limit breach
    if sensor_meta.upper_limit is not None:
        if current_value > sensor_meta.upper_limit:
            logger.debug(
                f"UPPER LIMIT BREACH: {current_value} > {sensor_meta.upper_limit} "
                f"(+{current_value - sensor_meta.upper_limit:.2f})"
            )
            return {
                'is_breach': True,
                'breach_type': 'upper',
                'limit_value': sensor_meta.upper_limit
            }
    
    # Check lower limit breach
    if sensor_meta.lower_limit is not None:
        if current_value < sensor_meta.lower_limit:
            logger.debug(
                f"LOWER LIMIT BREACH: {current_value} < {sensor_meta.lower_limit} "
                f"(-{sensor_meta.lower_limit - current_value:.2f})"
            )
            return {
                'is_breach': True,
                'breach_type': 'lower',
                'limit_value': sensor_meta.lower_limit
            }
    
    logger.debug("No breach - value is within limits")
    return {'is_breach': False, 'breach_type': None, 'limit_value': None}


def _handle_alert_logic(sensor_meta, existing_alert, breach_info, current_value):
    """
    Handle alert creation, escalation, or resolution.
    
    Args:
        sensor_meta: SensorMetadata instance
        existing_alert: Existing SensorAlert or None
        breach_info: Dict with breach details
        current_value: Current sensor value
        
    Returns:
        str: Result code ('created', 'escalated', 'resolved', 'normal', 'checked')
    """
    if breach_info['is_breach']:
        if existing_alert:
            # Check escalation conditions
            if existing_alert.can_escalate_to_medium or existing_alert.can_escalate_to_high:
                old_status = existing_alert.status
                existing_alert.escalate()
                logger.info(f"Alert escalated: {old_status} → {existing_alert.status}")
                return 'escalated'
            else:
                # Update breach value but don't escalate yet
                existing_alert.update_breach_value(current_value)
                logger.debug(
                    f"Alert waiting for escalation - Duration: {existing_alert.duration_minutes}m, "
                    f"Next at: {60 if existing_alert.status == 'initial' else 90}m"
                )
                return 'checked'
        else:
            # Create new alert
            try:
                alert = SensorAlert.objects.create(
                    sensor_metadata=sensor_meta,
                    status='initial',
                    breach_type=breach_info['breach_type'],
                    breach_value=current_value,
                    limit_value=breach_info['limit_value']
                )
                logger.info(
                    f"New alert created - ID: {alert.id}, Type: {breach_info['breach_type']}, "
                    f"Value: {current_value}, Limit: {breach_info['limit_value']}"
                )
                return 'created'
            except Exception as e:
                logger.error(f"Failed to create alert: {e}", exc_info=True)
                return 'error'
    else:
        # No breach
        if existing_alert:
            existing_alert.resolve()
            logger.info(f"Alert resolved - ID: {existing_alert.id} (value returned to normal)")
            return 'resolved'
        else:
            return 'normal'


# =============================================================================
# INFLUXDB DATA RETRIEVAL
# =============================================================================

def get_sensor_current_value(sensor_meta, asset_config):
    """
    Get current sensor value from InfluxDB using MEAN over last 1 hour.
    
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
        
        # Get device_column from device metadata
        influx_measurement_id = device.metadata.get('influx_measurement_id', measurement)
        device_column = device.metadata.get('device_column', 'id')
        
        # Query parameters
        time_range = 'now() - 1h'
        interval = '2m'
        
        logger.debug(
            f"Query params - Config: {asset_config.config_name}, DB: {asset_config.db_name}, "
            f"Measurement: {influx_measurement_id}, Field: {sensor.field_name}, "
            f"Device: {device.device_id}, Column: {device_column}"
        )
        
        # Build InfluxDB query
        query = f'''
SELECT mean("{sensor.field_name}") AS "current_value"
FROM "{influx_measurement_id}"
WHERE time >= {time_range} 
  AND time <= now() 
  AND "{device_column}" = '{device.device_id}'
GROUP BY time({interval}) fill(null)
tz('Asia/Kolkata')
'''
        
        # Execute query
        response = requests.get(
            f"{asset_config.base_api}/query",
            params={'db': asset_config.db_name, 'q': query},
            auth=(asset_config.api_username, asset_config.api_password),
            timeout=10,
            verify=False
        )
        
        logger.debug(f"InfluxDB response status: {response.status_code}")
        
        if response.status_code != 200:
            logger.warning(f"InfluxDB HTTP error: {response.status_code}")
            return None
        
        data = response.json()
        
        # Validate response structure
        if not data.get('results'):
            logger.debug("No 'results' in response")
            return None
        
        if not data['results'][0].get('series'):
            logger.debug("No 'series' in results (no data points found)")
            return None
        
        series = data['results'][0]['series'][0]
        columns = series.get('columns', [])
        values = series.get('values', [])
        
        logger.debug(f"Data found - Columns: {columns}, Points: {len(values)}")
        
        if not values:
            return None
        
        # Find last non-null mean value
        return _extract_latest_value(columns, values)
        
    except Exception as e:
        logger.error(f"Error fetching sensor value: {e}", exc_info=True)
        return None


def _extract_latest_value(columns, values):
    """
    Extract the most recent non-null value from InfluxDB results.
    
    Args:
        columns: List of column names
        values: List of value rows
        
    Returns:
        float: Latest non-null value or None
    """
    try:
        value_index = columns.index('current_value')
    except ValueError:
        value_index = 1  # Fallback: time is always 0
    
    # Iterate in reverse to find most recent non-null value
    for row in reversed(values):
        if len(row) > value_index:
            value = row[value_index]
            if value is not None:
                logger.debug(f"Latest value: {value} at {row[0]}")
                return float(value)
    
    logger.debug("All mean values are NULL in the 1-hour range")
    return None