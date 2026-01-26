"""
tests.py

Comprehensive Test Suite for Crowsensor Multi-Tenant IoT Monitoring Platform.

This file contains 55 tests covering all apps.
Uses manual schema context for tenant-aware testing (compatible with custom Tenant.save()).

Run tests with:
    python manage.py test tests --verbosity=2
"""

import logging
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.db import connection

# Disable logging during tests
logging.disable(logging.CRITICAL)


# =============================================================================
# UNIT TESTS - NO DATABASE REQUIRED (Tests 1-15)
# =============================================================================

class UnitTests(TestCase):
    """
    Unit tests that don't require database access.
    Tests helper functions, utilities, and pure logic.
    """
    
    def test_01_interval_lookup_exists(self):
        """Test 1: INTERVAL_LOOKUP dictionary exists and has values."""
        from userdashboard.graph_helpers import INTERVAL_LOOKUP
        
        self.assertIsInstance(INTERVAL_LOOKUP, dict)
        self.assertGreater(len(INTERVAL_LOOKUP), 0)
    
    def test_02_interval_lookup_time_ranges(self):
        """Test 2: INTERVAL_LOOKUP has expected time ranges."""
        from userdashboard.graph_helpers import INTERVAL_LOOKUP
        
        expected_ranges = ['now() - 1h', 'now() - 24h', 'now() - 7d']
        for time_range in expected_ranges:
            self.assertIn(time_range, INTERVAL_LOOKUP)
    
    def test_03_interval_lookup_values_are_strings(self):
        """Test 3: INTERVAL_LOOKUP values are valid interval strings."""
        from userdashboard.graph_helpers import INTERVAL_LOOKUP
        
        for key, value in INTERVAL_LOOKUP.items():
            self.assertIsInstance(value, str)
            self.assertTrue(
                value.endswith('s') or value.endswith('m') or 
                value.endswith('h') or value.endswith('d'),
                f"Invalid interval format: {value}"
            )
    
    def test_04_departmentadmin_interval_lookup(self):
        """Test 4: DepartmentAdmin has INTERVAL_LOOKUP."""
        from departmentadmin.graph_func import INTERVAL_LOOKUP
        
        self.assertIn('now() - 24h', INTERVAL_LOOKUP)
        self.assertEqual(INTERVAL_LOOKUP['now() - 24h'], '48m')
    
    def test_05_parse_timestamp_helper(self):
        """Test 5: Timestamp parsing helper works correctly."""
        from userdashboard.graph_helpers import _parse_timestamp
        
        result = _parse_timestamp('2025-01-26T10:30:00+05:30')
        self.assertIn('2025-01-26', result)
        self.assertIn('10:30', result)
    
    def test_06_parse_timestamp_with_z(self):
        """Test 6: Timestamp parsing handles Z suffix."""
        from userdashboard.graph_helpers import _parse_timestamp
        
        result = _parse_timestamp('2025-01-26T10:30:00Z')
        self.assertIn('2025-01-26', result)
    
    def test_07_parse_timestamp_with_fractional_seconds(self):
        """Test 7: Timestamp parsing handles fractional seconds."""
        from userdashboard.graph_helpers import _parse_timestamp
        
        result = _parse_timestamp('2025-01-26T10:30:00.123456+05:30')
        self.assertIsNotNone(result)
    
    def test_08_check_for_breach_upper_limit(self):
        """Test 8: _check_for_breach detects upper limit breach."""
        from departmentadmin.alert_func import _check_for_breach
        
        class MockMetadata:
            upper_limit = 80.0
            lower_limit = 20.0
        
        result = _check_for_breach(MockMetadata(), 85.0)
        self.assertTrue(result['is_breach'])
        self.assertEqual(result['breach_type'], 'upper')
    
    def test_09_check_for_breach_lower_limit(self):
        """Test 9: _check_for_breach detects lower limit breach."""
        from departmentadmin.alert_func import _check_for_breach
        
        class MockMetadata:
            upper_limit = 80.0
            lower_limit = 20.0
        
        result = _check_for_breach(MockMetadata(), 15.0)
        self.assertTrue(result['is_breach'])
        self.assertEqual(result['breach_type'], 'lower')
    
    def test_10_check_for_breach_no_breach(self):
        """Test 10: _check_for_breach returns no breach for normal value."""
        from departmentadmin.alert_func import _check_for_breach
        
        class MockMetadata:
            upper_limit = 80.0
            lower_limit = 20.0
        
        result = _check_for_breach(MockMetadata(), 50.0)
        self.assertFalse(result['is_breach'])
        self.assertIsNone(result['breach_type'])
    
    def test_11_check_for_breach_at_upper_limit(self):
        """Test 11: Value exactly at upper limit is NOT a breach."""
        from departmentadmin.alert_func import _check_for_breach
        
        class MockMetadata:
            upper_limit = 80.0
            lower_limit = 20.0
        
        result = _check_for_breach(MockMetadata(), 80.0)
        self.assertFalse(result['is_breach'])
    
    def test_12_check_for_breach_at_lower_limit(self):
        """Test 12: Value exactly at lower limit is NOT a breach."""
        from departmentadmin.alert_func import _check_for_breach
        
        class MockMetadata:
            upper_limit = 80.0
            lower_limit = 20.0
        
        result = _check_for_breach(MockMetadata(), 20.0)
        self.assertFalse(result['is_breach'])
    
    def test_13_check_for_breach_none_upper_limit(self):
        """Test 13: No breach when upper_limit is None."""
        from departmentadmin.alert_func import _check_for_breach
        
        class MockMetadata:
            upper_limit = None
            lower_limit = 20.0
        
        result = _check_for_breach(MockMetadata(), 100.0)
        self.assertFalse(result['is_breach'])
    
    def test_14_check_for_breach_none_lower_limit(self):
        """Test 14: No breach when lower_limit is None."""
        from departmentadmin.alert_func import _check_for_breach
        
        class MockMetadata:
            upper_limit = 80.0
            lower_limit = None
        
        result = _check_for_breach(MockMetadata(), 0.0)
        self.assertFalse(result['is_breach'])
    
    def test_15_update_stats_helper(self):
        """Test 15: _update_stats helper updates correctly."""
        from departmentadmin.alert_func import _update_stats
        
        stats = {
            'alerts_created': 0,
            'alerts_escalated': 0,
            'alerts_resolved': 0,
            'checked_normal': 0,
            'no_data': 0,
            'errors': 0
        }
        
        _update_stats(stats, 'created')
        self.assertEqual(stats['alerts_created'], 1)
        
        _update_stats(stats, 'escalated')
        self.assertEqual(stats['alerts_escalated'], 1)
        
        _update_stats(stats, 'resolved')
        self.assertEqual(stats['alerts_resolved'], 1)


# =============================================================================
# MULTI-TENANT DATABASE TESTS - Using existing tenant schema
# =============================================================================

class TenantSchemaTestCase(TransactionTestCase):
    """
    Base class for tests that need tenant database access.
    Uses an existing tenant schema for testing.
    """
    
    # Set this to your test tenant's schema name
    # You can create a test tenant in your DB or use an existing one
    TENANT_SCHEMA = None  # Will be set dynamically
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Try to find an existing tenant to use for tests
        from django_tenants.utils import get_tenant_model
        Tenant = get_tenant_model()
        
        # Get first available tenant (excluding public)
        try:
            tenant = Tenant.objects.exclude(schema_name='public').first()
            if tenant:
                cls.TENANT_SCHEMA = tenant.schema_name
            else:
                cls.TENANT_SCHEMA = None
        except Exception:
            cls.TENANT_SCHEMA = None
    
    def setUp(self):
        super().setUp()
        if self.TENANT_SCHEMA:
            from django_tenants.utils import schema_context
            self._schema_context = schema_context(self.TENANT_SCHEMA)
            self._schema_context.__enter__()
    
    def tearDown(self):
        if self.TENANT_SCHEMA and hasattr(self, '_schema_context'):
            self._schema_context.__exit__(None, None, None)
        super().tearDown()
    
    def skipIfNoTenant(self):
        """Skip test if no tenant schema is available."""
        if not self.TENANT_SCHEMA:
            self.skipTest("No tenant schema available for testing")


# =============================================================================
# ACCOUNTS MODEL TESTS (Tests 16-25)
# =============================================================================

class AccountsModelTests(TenantSchemaTestCase):
    """Test cases for accounts.models.User within tenant schema."""
    
    def test_16_create_user_with_valid_data(self):
        """Test 16: Create user with valid data."""
        self.skipIfNoTenant()
        from accounts.models import User
        
        user = User.objects.create_user(
            username='testuser16',
            email='test16@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            role='user'
        )
        
        self.assertEqual(user.username, 'testuser16')
        self.assertEqual(user.email, 'test16@example.com')
        self.assertEqual(user.role, 'user')
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password('TestPass123!'))
        
        # Cleanup
        user.delete()
    
    def test_17_create_user_without_username_raises_error(self):
        """Test 17: Creating user without username raises ValueError."""
        self.skipIfNoTenant()
        from accounts.models import User
        
        with self.assertRaises(ValueError):
            User.objects.create_user(
                username='',
                email='test17@example.com',
                password='TestPass123!'
            )
    
    def test_18_create_user_without_email_raises_error(self):
        """Test 18: Creating user without email raises ValueError."""
        self.skipIfNoTenant()
        from accounts.models import User
        
        with self.assertRaises(ValueError):
            User.objects.create_user(
                username='testuser18',
                email='',
                password='TestPass123!'
            )
    
    def test_19_user_role_choices(self):
        """Test 19: User role field accepts valid choices."""
        self.skipIfNoTenant()
        from accounts.models import User
        
        valid_roles = ['company_admin', 'department_admin', 'sub_admin', 'user']
        created_users = []
        
        for i, role in enumerate(valid_roles):
            user = User.objects.create_user(
                username=f'user_role_{role}_{i}',
                email=f'role_{role}_{i}@example.com',
                password='TestPass123!',
                role=role
            )
            self.assertEqual(user.role, role)
            created_users.append(user)
        
        # Cleanup
        for user in created_users:
            user.delete()
    
    def test_20_user_get_full_name_or_username(self):
        """Test 20: get_full_name_or_username returns correct value."""
        self.skipIfNoTenant()
        from accounts.models import User
        
        user_with_name = User.objects.create_user(
            username='withname20',
            email='withname20@example.com',
            password='TestPass123!',
            first_name='John',
            last_name='Doe'
        )
        self.assertEqual(user_with_name.get_full_name_or_username(), 'John Doe')
        
        user_without_name = User.objects.create_user(
            username='noname20',
            email='noname20@example.com',
            password='TestPass123!'
        )
        self.assertEqual(user_without_name.get_full_name_or_username(), 'noname20')
        
        # Cleanup
        user_with_name.delete()
        user_without_name.delete()
    
    def test_21_user_str_representation(self):
        """Test 21: User __str__ returns username."""
        self.skipIfNoTenant()
        from accounts.models import User
        
        user = User.objects.create_user(
            username='strtest21',
            email='str21@example.com',
            password='TestPass123!'
        )
        self.assertEqual(str(user), 'strtest21')
        user.delete()
    
    def test_22_user_is_company_admin_property(self):
        """Test 22: is_company_admin property works correctly."""
        self.skipIfNoTenant()
        from accounts.models import User
        
        admin = User.objects.create_user(
            username='admin22',
            email='admin22@example.com',
            password='TestPass123!',
            role='company_admin'
        )
        
        regular = User.objects.create_user(
            username='regular22',
            email='regular22@example.com',
            password='TestPass123!',
            role='user'
        )
        
        self.assertTrue(admin.is_company_admin)
        self.assertFalse(regular.is_company_admin)
        
        admin.delete()
        regular.delete()
    
    def test_23_user_is_department_admin_property(self):
        """Test 23: is_department_admin property works correctly."""
        self.skipIfNoTenant()
        from accounts.models import User
        
        dept_admin = User.objects.create_user(
            username='deptadmin23',
            email='deptadmin23@example.com',
            password='TestPass123!',
            role='department_admin'
        )
        
        self.assertTrue(dept_admin.is_department_admin)
        dept_admin.delete()
    
    def test_24_user_created_at_auto_set(self):
        """Test 24: created_at is automatically set."""
        self.skipIfNoTenant()
        from accounts.models import User
        
        user = User.objects.create_user(
            username='timetest24',
            email='time24@example.com',
            password='TestPass123!'
        )
        
        self.assertIsNotNone(user.created_at)
        self.assertLessEqual(user.created_at, timezone.now())
        user.delete()
    
    def test_25_user_email_normalization(self):
        """Test 25: Email domain is normalized to lowercase."""
        self.skipIfNoTenant()
        from accounts.models import User
        
        user = User.objects.create_user(
            username='emailtest25',
            email='TEST@EXAMPLE.COM',
            password='TestPass123!'
        )
        
        # Domain should be lowercase
        self.assertEqual(user.email, 'TEST@example.com')
        user.delete()


# =============================================================================
# COMPANYADMIN MODEL TESTS (Tests 26-35)
# =============================================================================

class CompanyAdminModelTests(TenantSchemaTestCase):
    """Test cases for companyadmin.models within tenant schema."""
    
    def test_26_create_department(self):
        """Test 26: Create Department model."""
        self.skipIfNoTenant()
        from companyadmin.models import Department
        
        dept = Department.objects.create(
            name='Engineering26',
            description='Engineering Department',
            is_active=True
        )
        
        self.assertEqual(dept.name, 'Engineering26')
        self.assertTrue(dept.is_active)
        self.assertEqual(str(dept), 'Engineering26')
        dept.delete()
    
    def test_27_create_department_membership(self):
        """Test 27: Create DepartmentMembership."""
        self.skipIfNoTenant()
        from accounts.models import User
        from companyadmin.models import Department, DepartmentMembership
        
        user = User.objects.create_user(
            username='memberuser27',
            email='member27@example.com',
            password='TestPass123!',
            role='user'
        )
        
        dept = Department.objects.create(name='Sales27')
        
        membership = DepartmentMembership.objects.create(
            user=user,
            department=dept,
            is_active=True
        )
        
        self.assertEqual(membership.user, user)
        self.assertEqual(membership.department, dept)
        self.assertTrue(membership.is_active)
        
        membership.delete()
        dept.delete()
        user.delete()
    
    def test_28_create_asset_config(self):
        """Test 28: Create AssetConfig (InfluxDB config)."""
        self.skipIfNoTenant()
        from companyadmin.models import AssetConfig
        
        config = AssetConfig.objects.create(
            config_name='Test InfluxDB 28',
            base_api='http://localhost:8086',
            db_name='test_db_28',
            api_username='admin',
            api_password='password123',
            is_active=True
        )
        
        self.assertEqual(config.config_name, 'Test InfluxDB 28')
        self.assertTrue(config.is_active)
        config.delete()
    
    def test_29_create_device(self):
        """Test 29: Create Device model."""
        self.skipIfNoTenant()
        from companyadmin.models import Device
        
        device = Device.objects.create(
            device_id='CHILLER_029',
            display_name='Main Chiller 29',
            measurement_name='chiller_data29',
            device_type='industrial_sensor',
            is_active=True
        )
        
        self.assertEqual(device.device_id, 'CHILLER_029')
        self.assertEqual(device.display_name, 'Main Chiller 29')
        self.assertEqual(device.device_type, 'industrial_sensor')
        device.delete()
    
    def test_30_device_str_representation(self):
        """Test 30: Device __str__ returns display name."""
        self.skipIfNoTenant()
        from companyadmin.models import Device
        
        device = Device.objects.create(
            device_id='DEV_030',
            display_name='Test Device 30',
            measurement_name='test_measurement30',
            device_type='industrial_sensor'
        )
        
        self.assertEqual(str(device), 'Test Device 30')
        device.delete()
    
    def test_31_create_sensor(self):
        """Test 31: Create Sensor model."""
        self.skipIfNoTenant()
        from companyadmin.models import Device, Sensor
        
        device = Device.objects.create(
            device_id='DEV_031',
            display_name='Sensor Device 31',
            measurement_name='sensor_data31',
            device_type='industrial_sensor'
        )
        
        sensor = Sensor.objects.create(
            device=device,
            field_name='temperature31',
            display_name='Temperature 31',
            field_type='float',
            category='sensor',
            unit='°C',
            is_active=True
        )
        
        self.assertEqual(sensor.field_name, 'temperature31')
        self.assertEqual(sensor.display_name, 'Temperature 31')
        self.assertEqual(sensor.unit, '°C')
        
        sensor.delete()
        device.delete()
    
    def test_32_create_sensor_metadata(self):
        """Test 32: Create SensorMetadata with limits."""
        self.skipIfNoTenant()
        from companyadmin.models import Device, Sensor, SensorMetadata
        
        device = Device.objects.create(
            device_id='DEV_032',
            display_name='Metadata Device 32',
            measurement_name='meta_data32',
            device_type='industrial_sensor'
        )
        
        sensor = Sensor.objects.create(
            device=device,
            field_name='pressure32',
            display_name='Pressure 32',
            field_type='float',
            category='sensor'
        )
        
        metadata = SensorMetadata.objects.create(
            sensor=sensor,
            display_name='System Pressure 32',
            unit='PSI',
            upper_limit=100.0,
            lower_limit=10.0,
            center_line=55.0,
            data_types=['trend', 'latest_value']
        )
        
        self.assertEqual(metadata.upper_limit, 100.0)
        self.assertEqual(metadata.lower_limit, 10.0)
        self.assertIn('trend', metadata.data_types)
        
        metadata.delete()
        sensor.delete()
        device.delete()
    
    def test_33_department_assign_devices(self):
        """Test 33: Assign devices to department."""
        self.skipIfNoTenant()
        from companyadmin.models import Department, Device
        
        dept = Department.objects.create(name='Operations33')
        
        device1 = Device.objects.create(
            device_id='DEV_033_1',
            display_name='Device 33-1',
            measurement_name='data33_1',
            device_type='industrial_sensor'
        )
        
        device2 = Device.objects.create(
            device_id='DEV_033_2',
            display_name='Device 33-2',
            measurement_name='data33_2',
            device_type='industrial_sensor'
        )
        
        dept.devices.add(device1, device2)
        
        self.assertEqual(dept.devices.count(), 2)
        self.assertIn(device1, dept.devices.all())
        
        dept.devices.clear()
        device1.delete()
        device2.delete()
        dept.delete()
    
    def test_34_device_metadata_json_field(self):
        """Test 34: Device metadata JSON field stores correctly."""
        self.skipIfNoTenant()
        from companyadmin.models import Device
        
        metadata = {
            'influx_measurement_id': 'custom_measurement34',
            'device_column': 'device_id',
            'auto_discovered': True
        }
        
        device = Device.objects.create(
            device_id='META_034',
            display_name='Device with Metadata 34',
            measurement_name='meta_data34',
            device_type='industrial_sensor',
            metadata=metadata
        )
        
        device.refresh_from_db()
        
        self.assertEqual(device.metadata['influx_measurement_id'], 'custom_measurement34')
        self.assertTrue(device.metadata['auto_discovered'])
        device.delete()
    
    def test_35_device_type_choices(self):
        """Test 35: Device type field accepts valid choices."""
        self.skipIfNoTenant()
        from companyadmin.models import Device
        
        device1 = Device.objects.create(
            device_id='DEV_035_1',
            display_name='Industrial Device',
            measurement_name='ind_data',
            device_type='industrial_sensor'
        )
        
        device2 = Device.objects.create(
            device_id='DEV_035_2',
            display_name='Asset Device',
            measurement_name='asset_data',
            device_type='asset_tracking'
        )
        
        self.assertEqual(device1.device_type, 'industrial_sensor')
        self.assertEqual(device2.device_type, 'asset_tracking')
        
        device1.delete()
        device2.delete()


# =============================================================================
# DEPARTMENTADMIN MODEL TESTS (Tests 36-45)
# =============================================================================

class DepartmentAdminModelTests(TenantSchemaTestCase):
    """Test cases for departmentadmin.models within tenant schema."""
    
    def _create_test_data(self):
        """Create test data and return cleanup function."""
        from accounts.models import User
        from companyadmin.models import Department, Device, Sensor, SensorMetadata
        
        user = User.objects.create_user(
            username='deptadmin_test',
            email='dept_test@example.com',
            password='TestPass123!',
            role='department_admin'
        )
        
        department = Department.objects.create(name='Test Dept')
        
        device = Device.objects.create(
            device_id='ALERT_DEV_TEST',
            display_name='Alert Test Device',
            measurement_name='alert_data_test',
            device_type='industrial_sensor'
        )
        
        sensor = Sensor.objects.create(
            device=device,
            field_name='temperature_test',
            display_name='Temperature Test',
            field_type='float',
            category='sensor'
        )
        
        sensor_metadata = SensorMetadata.objects.create(
            sensor=sensor,
            display_name='Temp Sensor Test',
            unit='°C',
            upper_limit=80.0,
            lower_limit=20.0
        )
        
        return user, department, device, sensor, sensor_metadata
    
    def _cleanup(self, *objects):
        """Delete test objects."""
        for obj in reversed(objects):
            try:
                obj.delete()
            except Exception:
                pass
    
    def test_36_create_sensor_alert(self):
        """Test 36: Create SensorAlert model."""
        self.skipIfNoTenant()
        from departmentadmin.models import SensorAlert
        
        user, dept, device, sensor, metadata = self._create_test_data()
        
        alert = SensorAlert.objects.create(
            sensor_metadata=metadata,
            status='initial',
            breach_type='upper',
            breach_value=85.0,
            limit_value=80.0
        )
        
        self.assertEqual(alert.status, 'initial')
        self.assertEqual(alert.breach_type, 'upper')
        self.assertEqual(alert.breach_value, 85.0)
        
        alert.delete()
        self._cleanup(metadata, sensor, device, dept, user)
    
    def test_37_sensor_alert_is_active_property(self):
        """Test 37: SensorAlert is_active property."""
        self.skipIfNoTenant()
        from departmentadmin.models import SensorAlert
        
        user, dept, device, sensor, metadata = self._create_test_data()
        
        active_alert = SensorAlert.objects.create(
            sensor_metadata=metadata,
            status='medium',
            breach_type='upper',
            breach_value=85.0,
            limit_value=80.0
        )
        
        self.assertTrue(active_alert.is_active)
        
        active_alert.delete()
        self._cleanup(metadata, sensor, device, dept, user)
    
    def test_38_sensor_alert_resolved_not_active(self):
        """Test 38: Resolved SensorAlert is not active."""
        self.skipIfNoTenant()
        from departmentadmin.models import SensorAlert
        
        user, dept, device, sensor, metadata = self._create_test_data()
        
        resolved_alert = SensorAlert.objects.create(
            sensor_metadata=metadata,
            status='resolved',
            breach_type='lower',
            breach_value=15.0,
            limit_value=20.0
        )
        
        self.assertFalse(resolved_alert.is_active)
        
        resolved_alert.delete()
        self._cleanup(metadata, sensor, device, dept, user)
    
    def test_39_sensor_alert_duration_minutes(self):
        """Test 39: SensorAlert duration_minutes property."""
        self.skipIfNoTenant()
        from departmentadmin.models import SensorAlert
        
        user, dept, device, sensor, metadata = self._create_test_data()
        
        alert = SensorAlert.objects.create(
            sensor_metadata=metadata,
            status='initial',
            breach_type='upper',
            breach_value=85.0,
            limit_value=80.0
        )
        
        self.assertGreaterEqual(alert.duration_minutes, 0)
        self.assertLess(alert.duration_minutes, 1)
        
        alert.delete()
        self._cleanup(metadata, sensor, device, dept, user)
    
    def test_40_sensor_alert_resolve(self):
        """Test 40: SensorAlert resolve() method."""
        self.skipIfNoTenant()
        from departmentadmin.models import SensorAlert
        
        user, dept, device, sensor, metadata = self._create_test_data()
        
        alert = SensorAlert.objects.create(
            sensor_metadata=metadata,
            status='high',
            breach_type='upper',
            breach_value=85.0,
            limit_value=80.0
        )
        
        alert.resolve()
        
        self.assertEqual(alert.status, 'resolved')
        self.assertIsNotNone(alert.resolved_at)
        
        alert.delete()
        self._cleanup(metadata, sensor, device, dept, user)
    
    def test_41_create_device_user_assignment(self):
        """Test 41: Create DeviceUserAssignment."""
        self.skipIfNoTenant()
        from departmentadmin.models import DeviceUserAssignment
        
        user, dept, device, sensor, metadata = self._create_test_data()
        
        assignment = DeviceUserAssignment.objects.create(
            device=device,
            user=user,
            department=dept,
            assigned_by=user,
            is_active=True
        )
        
        self.assertEqual(assignment.device, device)
        self.assertEqual(assignment.user, user)
        self.assertTrue(assignment.is_active)
        
        assignment.delete()
        self._cleanup(metadata, sensor, device, dept, user)
    
    def test_42_device_user_assignment_get_device_users(self):
        """Test 42: DeviceUserAssignment.get_device_users() class method."""
        self.skipIfNoTenant()
        from accounts.models import User
        from departmentadmin.models import DeviceUserAssignment
        
        user, dept, device, sensor, metadata = self._create_test_data()
        
        user2 = User.objects.create_user(
            username='user42_2',
            email='user42_2@example.com',
            password='TestPass123!',
            role='user'
        )
        
        assignment1 = DeviceUserAssignment.objects.create(
            device=device,
            user=user,
            department=dept,
            assigned_by=user,
            is_active=True
        )
        
        assignment2 = DeviceUserAssignment.objects.create(
            device=device,
            user=user2,
            department=dept,
            assigned_by=user,
            is_active=True
        )
        
        users = DeviceUserAssignment.get_device_users(device, dept)
        
        self.assertEqual(users.count(), 2)
        
        assignment1.delete()
        assignment2.delete()
        user2.delete()
        self._cleanup(metadata, sensor, device, dept, user)
    
    def test_43_device_user_assignment_bulk_assign(self):
        """Test 43: DeviceUserAssignment.assign_device_to_users() bulk operation."""
        self.skipIfNoTenant()
        from accounts.models import User
        from departmentadmin.models import DeviceUserAssignment
        
        user, dept, device, sensor, metadata = self._create_test_data()
        
        users = []
        for i in range(3):
            u = User.objects.create_user(
                username=f'bulkuser43_{i}',
                email=f'bulk43_{i}@example.com',
                password='TestPass123!',
                role='user'
            )
            users.append(u)
        
        created, updated = DeviceUserAssignment.assign_device_to_users(
            device=device,
            users=users,
            department=dept,
            assigned_by=user
        )
        
        self.assertEqual(created, 3)
        
        # Cleanup
        DeviceUserAssignment.objects.filter(device=device).delete()
        for u in users:
            u.delete()
        self._cleanup(metadata, sensor, device, dept, user)
    
    def test_44_device_user_assignment_bulk_unassign(self):
        """Test 44: DeviceUserAssignment.unassign_device_from_users() bulk operation."""
        self.skipIfNoTenant()
        from accounts.models import User
        from departmentadmin.models import DeviceUserAssignment
        
        user, dept, device, sensor, metadata = self._create_test_data()
        
        user2 = User.objects.create_user(
            username='unassignuser44',
            email='unassign44@example.com',
            password='TestPass123!',
            role='user'
        )
        
        assignment = DeviceUserAssignment.objects.create(
            device=device,
            user=user2,
            department=dept,
            assigned_by=user,
            is_active=True
        )
        
        removed = DeviceUserAssignment.unassign_device_from_users(
            device=device,
            users=[user2],
            department=dept
        )
        
        self.assertEqual(removed, 1)
        
        assignment.refresh_from_db()
        self.assertFalse(assignment.is_active)
        
        assignment.delete()
        user2.delete()
        self._cleanup(metadata, sensor, device, dept, user)
    
    def test_45_sensor_alert_update_breach_value(self):
        """Test 45: SensorAlert.update_breach_value() method."""
        self.skipIfNoTenant()
        from departmentadmin.models import SensorAlert
        
        user, dept, device, sensor, metadata = self._create_test_data()
        
        alert = SensorAlert.objects.create(
            sensor_metadata=metadata,
            status='initial',
            breach_type='upper',
            breach_value=85.0,
            limit_value=80.0
        )
        
        alert.update_breach_value(90.0)
        alert.refresh_from_db()
        
        self.assertEqual(alert.breach_value, 90.0)
        
        alert.delete()
        self._cleanup(metadata, sensor, device, dept, user)


# =============================================================================
# USERDASHBOARD TESTS (Tests 46-51)
# =============================================================================

class UserDashboardTests(TenantSchemaTestCase):
    """Test cases for userdashboard views and helpers within tenant schema."""
    
    def _create_test_data(self):
        """Create test data for dashboard tests."""
        from accounts.models import User
        from companyadmin.models import Department, DepartmentMembership, Device
        from departmentadmin.models import DeviceUserAssignment
        
        user = User.objects.create_user(
            username='dashuser_test',
            email='dash_test@example.com',
            password='TestPass123!',
            role='user'
        )
        
        department = Department.objects.create(name='User Dept Test')
        
        membership = DepartmentMembership.objects.create(
            user=user,
            department=department,
            is_active=True
        )
        
        device = Device.objects.create(
            device_id='DASH_DEV_TEST',
            display_name='Dashboard Device Test',
            measurement_name='dash_data_test',
            device_type='industrial_sensor'
        )
        
        department.devices.add(device)
        
        assignment = DeviceUserAssignment.objects.create(
            device=device,
            user=user,
            department=department,
            assigned_by=user,
            is_active=True
        )
        
        return user, department, membership, device, assignment
    
    def _cleanup(self, user, department, membership, device, assignment):
        """Clean up test data."""
        try:
            assignment.delete()
        except Exception:
            pass
        try:
            department.devices.clear()
        except Exception:
            pass
        try:
            membership.delete()
        except Exception:
            pass
        try:
            device.delete()
        except Exception:
            pass
        try:
            department.delete()
        except Exception:
            pass
        try:
            user.delete()
        except Exception:
            pass
    
    def test_46_get_user_device_assignment_exists(self):
        """Test 46: get_user_device_assignment returns assignment when exists."""
        self.skipIfNoTenant()
        from userdashboard.views import get_user_device_assignment
        
        user, dept, membership, device, assignment = self._create_test_data()
        
        result = get_user_device_assignment(user, device.id)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.device, device)
        
        self._cleanup(user, dept, membership, device, assignment)
    
    def test_47_get_user_device_assignment_not_exists(self):
        """Test 47: get_user_device_assignment returns None when not exists."""
        self.skipIfNoTenant()
        from userdashboard.views import get_user_device_assignment
        
        user, dept, membership, device, assignment = self._create_test_data()
        
        result = get_user_device_assignment(user, 99999)
        
        self.assertIsNone(result)
        
        self._cleanup(user, dept, membership, device, assignment)
    
    def test_48_get_user_departments(self):
        """Test 48: get_user_departments returns correct departments."""
        self.skipIfNoTenant()
        from userdashboard.views import get_user_departments
        
        user, dept, membership, device, assignment = self._create_test_data()
        
        result = get_user_departments(user)
        
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first().department, dept)
        
        self._cleanup(user, dept, membership, device, assignment)
    
    def test_49_get_user_assigned_device_ids(self):
        """Test 49: get_user_assigned_device_ids returns correct IDs."""
        self.skipIfNoTenant()
        from userdashboard.views import get_user_assigned_device_ids
        
        user, dept, membership, device, assignment = self._create_test_data()
        
        result = get_user_assigned_device_ids(user, [dept.id])
        
        self.assertEqual(len(result), 1)
        self.assertIn(device.id, result)
        
        self._cleanup(user, dept, membership, device, assignment)
    
    def test_50_user_without_assignments_gets_empty_list(self):
        """Test 50: User without assignments gets empty device list."""
        self.skipIfNoTenant()
        from accounts.models import User
        from userdashboard.views import get_user_assigned_device_ids
        
        user, dept, membership, device, assignment = self._create_test_data()
        
        new_user = User.objects.create_user(
            username='noaccess50',
            email='noaccess50@example.com',
            password='TestPass123!',
            role='user'
        )
        
        result = get_user_assigned_device_ids(new_user, [dept.id])
        
        self.assertEqual(len(result), 0)
        
        new_user.delete()
        self._cleanup(user, dept, membership, device, assignment)
    
    def test_51_inactive_assignment_not_returned(self):
        """Test 51: Inactive assignment is not returned."""
        self.skipIfNoTenant()
        from userdashboard.views import get_user_device_assignment
        
        user, dept, membership, device, assignment = self._create_test_data()
        
        assignment.is_active = False
        assignment.save()
        
        result = get_user_device_assignment(user, device.id)
        
        self.assertIsNone(result)
        
        self._cleanup(user, dept, membership, device, assignment)


# =============================================================================
# MOCKED INFLUXDB TESTS (Tests 52-55)
# =============================================================================

class MockedInfluxDBTests(TenantSchemaTestCase):
    """Tests with mocked InfluxDB responses."""
    
    def _create_test_data(self):
        """Create test data for InfluxDB tests."""
        from companyadmin.models import AssetConfig, Device, Sensor
        
        config = AssetConfig.objects.create(
            config_name='Test InfluxDB Mock',
            base_api='http://localhost:8086',
            db_name='test_db_mock',
            api_username='admin',
            api_password='password',
            is_active=True
        )
        
        device = Device.objects.create(
            device_id='MOCK_DEV',
            display_name='Mock Device',
            measurement_name='mock_data',
            device_type='industrial_sensor',
            asset_config=config,
            metadata={
                'influx_measurement_id': 'custom_measurement',
                'device_column': 'device_id'
            }
        )
        
        sensor = Sensor.objects.create(
            device=device,
            field_name='temperature_mock',
            display_name='Temperature Mock',
            field_type='float',
            category='sensor',
            is_active=True
        )
        
        return config, device, sensor
    
    def _cleanup(self, config, device, sensor):
        """Clean up test data."""
        try:
            sensor.delete()
        except Exception:
            pass
        try:
            device.delete()
        except Exception:
            pass
        try:
            config.delete()
        except Exception:
            pass
    
    def test_52_get_influxdb_config_for_user_returns_device_config(self):
        """Test 52: get_influxdb_config_for_user returns device's config."""
        self.skipIfNoTenant()
        from userdashboard.graph_helpers import get_influxdb_config_for_user
        
        config, device, sensor = self._create_test_data()
        
        result = get_influxdb_config_for_user(device)
        
        self.assertEqual(result, config)
        
        self._cleanup(config, device, sensor)
    
    @patch('userdashboard.graph_helpers.requests.get')
    def test_53_fetch_sensor_data_handles_empty_response(self, mock_get):
        """Test 53: fetch_sensor_data_for_user handles empty InfluxDB response."""
        self.skipIfNoTenant()
        from userdashboard.graph_helpers import fetch_sensor_data_for_user
        
        config, device, sensor = self._create_test_data()
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'results': [{}]}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        result = fetch_sensor_data_for_user(device, 'now() - 1h')
        
        self.assertEqual(result['timestamps'], [])
        self.assertEqual(len(result['sensors']), 1)
        
        self._cleanup(config, device, sensor)
    
    @patch('userdashboard.graph_helpers.requests.get')
    def test_54_fetch_sensor_data_with_valid_data(self, mock_get):
        """Test 54: fetch_sensor_data_for_user parses valid data correctly."""
        self.skipIfNoTenant()
        from userdashboard.graph_helpers import fetch_sensor_data_for_user
        
        config, device, sensor = self._create_test_data()
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'results': [{
                'series': [{
                    'columns': ['time', 'temperature_mock'],
                    'values': [
                        ['2025-01-26T10:00:00Z', 25.5],
                        ['2025-01-26T10:02:00Z', 26.0],
                    ]
                }]
            }]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        result = fetch_sensor_data_for_user(device, 'now() - 1h')
        
        self.assertEqual(len(result['timestamps']), 2)
        self.assertEqual(len(result['sensors']), 1)
        self.assertEqual(result['sensors'][0]['field_name'], 'temperature_mock')
        
        self._cleanup(config, device, sensor)
    
    @patch('userdashboard.graph_helpers.requests.get')
    def test_55_fetch_sensor_data_handles_connection_error(self, mock_get):
        """Test 55: fetch_sensor_data_for_user handles connection errors."""
        self.skipIfNoTenant()
        from userdashboard.graph_helpers import fetch_sensor_data_for_user
        import requests
        
        config, device, sensor = self._create_test_data()
        
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
        
        with self.assertRaises(Exception) as context:
            fetch_sensor_data_for_user(device, 'now() - 1h')
        
        self.assertIn('Failed to fetch data', str(context.exception))
        
        self._cleanup(config, device, sensor)


# =============================================================================
# RUN TESTS SUMMARY
# =============================================================================

"""
Run all tests:
    python manage.py test tests --verbosity=2

Run only unit tests (no database needed):
    python manage.py test tests.UnitTests --verbosity=2

Run specific model tests:
    python manage.py test tests.AccountsModelTests --verbosity=2
    python manage.py test tests.CompanyAdminModelTests --verbosity=2
    python manage.py test tests.DepartmentAdminModelTests --verbosity=2
    python manage.py test tests.UserDashboardTests --verbosity=2
    python manage.py test tests.MockedInfluxDBTests --verbosity=2

IMPORTANT:
- Tests 1-15 (UnitTests) run without database and should always pass
- Tests 16-55 require an existing tenant in your database
- If no tenant exists, these tests will be skipped
- Create a test tenant first: Tenant.objects.create(schema_name='test_tenant', name='Test')
"""