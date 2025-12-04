from django.db import models
from django.core.validators import EmailValidator
from django.utils import timezone


class Department(models.Model):
    """
    Department model for company admin
    
    NO TENANT FK NEEDED - Schema context provides tenant isolation!
    Each tenant has its own database schema with its own department table.
    """
    
    # BASIC INFO
    name = models.CharField(
        max_length=200,
        unique=True,  # Unique within this tenant's schema
        help_text="Department name"
    )
    
    department_type = models.CharField(
        max_length=100,
        help_text="e.g., Manufacturing, Quality Control, Packaging"
    )
    
    plant_location = models.CharField(
        max_length=200,
        help_text="e.g., Building A, Floor 3, Zone 2"
    )
    
    # PRIMARY CONTACT
    email = models.EmailField(
        validators=[EmailValidator()],
        blank=True,
        null=True,
        help_text="Primary department email for notifications"
    )
    
    # STATUS
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this department is active"
    )
    
    # TIMESTAMPS
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'department'  # Will be in tenant schema, not public
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['name']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Department"
        verbose_name_plural = "Departments"
    
    def __str__(self):
        return self.name
    
    def get_admin_count(self):
        """Count department admins assigned to this department"""
        from accounts.models import User
        return self.users.filter(
            role='department_admin',
            is_active=True
        ).count() if hasattr(self, 'users') else 0
    
    def get_total_users(self):
        """Count all active users in this department"""
        return self.users.filter(is_active=True).count() if hasattr(self, 'users') else 0
    
    def deactivate(self):
        """Soft delete - deactivate department"""
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])
    
    def activate(self):
        """Reactivate department"""
        self.is_active = True
        self.save(update_fields=['is_active', 'updated_at'])


# Optional: Link users to departments (if needed)
class DepartmentMembership(models.Model):
    """
    Many-to-many relationship between Users and Departments
    Allows users to belong to multiple departments
    """
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='department_memberships'
    )
    
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name='user_memberships'
    )
    
    # Role within this specific department (optional)
    role_in_department = models.CharField(
        max_length=50,
        blank=True,
        help_text="Specific role in this department"
    )
    
    assigned_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'department_membership'
        unique_together = [['user', 'department']]
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['department', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.department.name}"
    



# companyadmin/models.py - SIMPLIFIED FOR HTTP REQUESTS

from django.db import models
from django.core.validators import URLValidator
from django.utils import timezone
from django.core.exceptions import ValidationError


class AssetConfig(models.Model):
    """
    InfluxDB Configuration - ONE per tenant
    Stores connection details for HTTP-based InfluxDB API calls
    
    Company Admin manages this configuration.
    NO tenant FK needed - schema isolation provides tenant scope.
    """
    
    # InfluxDB Connection Details (for HTTP requests)
    db_name = models.CharField(
        max_length=100,
        help_text="InfluxDB database name (e.g., 'production_iot')"
    )
    
    base_api = models.URLField(
        max_length=500,
        validators=[URLValidator()],
        help_text="InfluxDB API base URL (e.g., 'http://influxdb.company.com:8086')"
    )
    
    api_username = models.CharField(
        max_length=100,
        help_text="InfluxDB username for Basic Auth"
    )
    
    api_password = models.CharField(
        max_length=100,
        help_text="InfluxDB password for Basic Auth"
    )
    
    # Status & Metadata
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this configuration is active"
    )
    
    is_connected = models.BooleanField(
        default=False,
        help_text="Last connection test result"
    )
    
    last_tested_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When connection was last tested"
    )
    
    last_sync_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When data was last fetched from InfluxDB"
    )
    
    connection_error = models.TextField(
        blank=True,
        help_text="Last connection error message (if any)"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Metadata
    notes = models.TextField(
        blank=True,
        help_text="Internal notes about this configuration"
    )
    
    class Meta:
        db_table = 'asset_config'
        verbose_name = 'Asset Configuration'
        verbose_name_plural = 'Asset Configurations'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"InfluxDB: {self.db_name}"
    
    def clean(self):
        """Validate that only ONE active config exists per tenant"""
        if self.is_active:
            existing = AssetConfig.objects.filter(is_active=True)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            
            if existing.exists():
                raise ValidationError(
                    'Only one active InfluxDB configuration allowed per company. '
                    'Please deactivate the existing configuration first.'
                )
    
    def save(self, *args, **kwargs):
        """Override save to run validation"""
        self.clean()
        super().save(*args, **kwargs)
    
    def mark_connected(self):
        """Mark configuration as successfully connected"""
        self.is_connected = True
        self.last_tested_at = timezone.now()
        self.connection_error = ''
        self.save(update_fields=['is_connected', 'last_tested_at', 'connection_error', 'updated_at'])
    
    def mark_disconnected(self, error_message=''):
        """Mark configuration as failed to connect"""
        self.is_connected = False
        self.last_tested_at = timezone.now()
        self.connection_error = error_message
        self.save(update_fields=['is_connected', 'last_tested_at', 'connection_error', 'updated_at'])
    
    def mark_synced(self):
        """Mark configuration as successfully synced data"""
        self.last_sync_at = timezone.now()
        self.save(update_fields=['last_sync_at', 'updated_at'])
    
    def get_masked_password(self):
        """Return masked password for display"""
        if not self.api_password:
            return ''
        return '*' * len(self.api_password)
    
    def get_connection_status_display(self):
        """Human-readable connection status"""
        if not self.last_tested_at:
            return 'Not Tested'
        return 'Connected' if self.is_connected else 'Connection Failed'
    
    def get_connection_status_color(self):
        """Bootstrap color class for status badge"""
        if not self.last_tested_at:
            return 'secondary'
        return 'success' if self.is_connected else 'danger'
    
    @classmethod
    def get_active_config(cls):
        """Get the active configuration (should be only one)"""
        return cls.objects.filter(is_active=True).first()
    
    @classmethod
    def has_active_config(cls):
        """Check if an active configuration exists"""
        return cls.objects.filter(is_active=True).exists()



# companyadmin/models.py - ADD THESE NEW MODELS

from django.db import models
from django.utils import timezone


class Device(models.Model):
    """
    IoT Device discovered from InfluxDB
    Links to a measurement and can be assigned to departments
    """
    
    # Basic Info
    device_id = models.CharField(
        max_length=100,
        help_text="Device ID from InfluxDB (e.g., '1', '2', 'PUMP_01')"
    )
    
    display_name = models.CharField(
        max_length=200,
        help_text="Human-readable name for the device (e.g., 'Chiller Unit 1')"
    )
    
    measurement_name = models.CharField(
        max_length=200,
        help_text="InfluxDB measurement name this device belongs to"
    )
    
    # Department Assignment (Many-to-Many)
    departments = models.ManyToManyField(
        'Department',
        related_name='devices',
        blank=True,
        help_text="Departments that can access this device"
    )
    
    # Metadata (JSON field for flexible data storage)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional device information (location, type, etc.)"
    )
    
    # Status & Timestamps
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'companyadmin_device'
        verbose_name = 'Device'
        verbose_name_plural = 'Devices'
        ordering = ['measurement_name', 'device_id']
        unique_together = [['measurement_name', 'device_id']]
    
    def __str__(self):
        return f"{self.display_name} ({self.measurement_name}/{self.device_id})"
    
    @property
    def sensor_count(self):
        """Get number of sensors for this device"""
        return self.sensors.count()

class Sensor(models.Model):
    """
    Sensor field for a Device
    Represents a data point/field in InfluxDB
    """
    
    FIELD_TYPE_CHOICES = [
        ('float', 'Float'),
        ('integer', 'Integer'),
        ('boolean', 'Boolean'),
        ('string', 'String'),
        ('unknown', 'Unknown'),
    ]
    
    SENSOR_CATEGORY_CHOICES = [
        ('sensor', 'Sensor Data'),
        ('info', 'Information'),
        ('slave', 'Slave ID'),
    ]
    
    # Relationship
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='sensors',
        help_text="Device this sensor belongs to"
    )
    
    # Sensor Info
    field_name = models.CharField(
        max_length=200,
        help_text="Field name in InfluxDB (e.g., 'temperature', 'pressure')"
    )
    
    display_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Human-readable name (defaults to field_name if blank)"
    )
    
    field_type = models.CharField(
        max_length=20,
        choices=FIELD_TYPE_CHOICES,
        default='unknown',
        help_text="Data type of this sensor field"
    )
    
    category = models.CharField(
        max_length=20,
        choices=SENSOR_CATEGORY_CHOICES,
        default='sensor',
        help_text="Is this a sensor or just info?"
    )
    
    # Optional Settings
    unit = models.CharField(
        max_length=50,
        blank=True,
        help_text="Unit of measurement (e.g., '°C', 'PSI', '%')"
    )
    
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional sensor information (sample_value, etc.)"
    )
    
    # Status & Timestamps
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'companyadmin_sensor'
        verbose_name = 'Sensor'
        verbose_name_plural = 'Sensors'
        ordering = ['device', 'field_name']
        unique_together = [['device', 'field_name']]
    
    def __str__(self):
        display = self.display_name or self.field_name
        return f"{self.device.display_name} - {display}"
    
    def save(self, *args, **kwargs):
        # Auto-set display_name if blank
        if not self.display_name:
            self.display_name = self.field_name
        super().save(*args, **kwargs)
    
    # ✅ NEW HELPER METHODS
    def get_or_create_metadata(self):
        """
        Get or create metadata for this sensor
        Returns: SensorMetadata instance
        """
        metadata, created = SensorMetadata.objects.get_or_create(
            sensor=self,
            defaults={
                'display_name': self.display_name,
                'unit': self.unit,  # Copy existing unit if any
                'show_time_series': True,
                'show_latest_value': False,
                'show_digital': self.field_type == 'boolean'  # Auto-enable for boolean sensors
            }
        )
        return metadata
    
    def has_metadata(self):
        """Check if sensor has metadata configured"""
        return hasattr(self, 'metadata_config')
    
    @property
    def sensor_count(self):
        """Total sensor count for this device"""
        return self.device.sensors.count()


class SensorMetadata(models.Model):
    """
    User-configurable metadata for sensors to control graph visualization
    This is separate from the Sensor model to keep InfluxDB-discovered data 
    separate from user configuration
    """
    sensor = models.OneToOneField(
        Sensor, 
        on_delete=models.CASCADE, 
        related_name='metadata_config',  # Changed from 'metadata' to avoid conflict
        help_text="Link to the sensor"
    )
    
    # Display Configuration
    display_name = models.CharField(
        max_length=255, 
        blank=True,
        help_text="User-friendly display name (e.g., 'Compressor Temperature')"
    )
    unit = models.CharField(
        max_length=50, 
        blank=True,
        help_text="Unit of measurement (e.g., °C, kWh, bar, %, RPM)"
    )
    
    # Thresholds/Limits for visualization
    upper_limit = models.FloatField(
        null=True, 
        blank=True,
        help_text="Upper threshold for alerts/visualization"
    )
    lower_limit = models.FloatField(
        null=True, 
        blank=True,
        help_text="Lower threshold for alerts/visualization"
    )
    central_line = models.FloatField(
        null=True, 
        blank=True,
        help_text="Target/setpoint value (central line on graph)"
    )
    
    # Graph Type Flags (multiple can be True)
    show_time_series = models.BooleanField(
        default=True,
        help_text="Show time series line chart"
    )
    show_latest_value = models.BooleanField(
        default=False,
        help_text="Show latest value as big number card"
    )
    show_digital = models.BooleanField(
        default=False,
        help_text="Show as digital display (ON/OFF for boolean sensors)"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'companyadmin_sensor_metadata'
        verbose_name = "Sensor Metadata"
        verbose_name_plural = "Sensor Metadata"
        ordering = ['sensor__field_name']
    
    def __str__(self):
        return f"Metadata: {self.sensor.field_name}"
    
    def get_display_name(self):
        """Return display_name if set, otherwise return sensor field_name"""
        return self.display_name if self.display_name else self.sensor.field_name
    
    def get_graph_types_list(self):
        """Return list of enabled graph types"""
        types = []
        if self.show_time_series:
            types.append('Time Series')
        if self.show_latest_value:
            types.append('Latest Value')
        if self.show_digital:
            types.append('Digital')
        return types