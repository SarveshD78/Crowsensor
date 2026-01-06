# companyadmin/models.py - CLEAN VERSION FOR FRESH START

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from accounts.models import User


# =============================================================================
# DEPARTMENT MODEL (UNCHANGED)
# =============================================================================

class Department(models.Model):
    """Department/Workspace within tenant"""
    
    name = models.CharField(max_length=200, unique=True)
    department_type = models.CharField(max_length=100)
    plant_location = models.CharField(max_length=255)
    email = models.EmailField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'companyadmin_department'
        verbose_name = 'Department'
        verbose_name_plural = 'Departments'
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def deactivate(self):
        """Soft delete"""
        self.is_active = False
        self.save(update_fields=['is_active'])


# =============================================================================
# DEPARTMENT MEMBERSHIP MODEL (UNCHANGED)
# =============================================================================

class DepartmentMembership(models.Model):
    """Many-to-Many relationship between User and Department"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='department_memberships'
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name='user_memberships'
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'companyadmin_department_membership'
        unique_together = ['user', 'department']
        verbose_name = 'Department Membership'
        verbose_name_plural = 'Department Memberships'
    
    def __str__(self):
        return f"{self.user.username} → {self.department.name}"


# =============================================================================
# ✨ ASSET CONFIG MODEL - UPDATED FOR MULTIPLE CONFIGS
# =============================================================================

class AssetConfig(models.Model):
    """
    ✨ NEW: Supports multiple InfluxDB configurations per tenant
    Each config represents a different InfluxDB instance (Factory 1, Factory 2, etc.)
    """
    
    # ✨ NEW FIELD - Identifies this specific InfluxDB instance
    config_name = models.CharField(
        max_length=200,
        unique=True,
        help_text="Friendly name (e.g., 'Factory 1 - Mumbai', 'Building A - Pune')"
    )
    
    # InfluxDB connection details
    db_name = models.CharField(
        max_length=100,
        help_text="InfluxDB database name"
    )
    base_api = models.URLField(
        max_length=500,
        help_text="InfluxDB API URL (e.g., http://influxdb.example.com:8086)"
    )
    api_username = models.CharField(max_length=100)
    api_password = models.CharField(max_length=100)
    
    # Connection status
    is_connected = models.BooleanField(default=False)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    connection_error = models.TextField(blank=True)
    
    # ✨ MODIFIED - No longer enforces "only one active"
    is_active = models.BooleanField(default=True, db_index=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'asset_config'
        verbose_name = 'InfluxDB Configuration'
        verbose_name_plural = 'InfluxDB Configurations'
        ordering = ['config_name']  # ✨ Sort by name, not date
    
    def __str__(self):
        return f"{self.config_name} ({self.db_name})"
    
    # ✨ NEW CLASS METHODS
    @classmethod
    def get_active_configs(cls):
        """Get all active configurations"""
        return cls.objects.filter(is_active=True).order_by('config_name')
    
    @classmethod
    def get_default_config(cls):
        """Get first active config (backward compatibility)"""
        return cls.objects.filter(is_active=True).order_by('config_name').first()
    
    @classmethod
    def has_active_config(cls):
        """Check if ANY active config exists"""
        return cls.objects.filter(is_active=True).exists()
    
    @classmethod
    def has_multiple_configs(cls):
        """Check if tenant has multiple InfluxDB configs"""
        return cls.objects.filter(is_active=True).count() > 1
    
    # Instance methods
    def mark_connected(self):
        """Mark as successfully connected"""
        self.is_connected = True
        self.last_tested_at = timezone.now()
        self.connection_error = ''
        self.save(update_fields=['is_connected', 'last_tested_at', 'connection_error'])
    
    def mark_disconnected(self, error_message=''):
        """Mark as connection failed"""
        self.is_connected = False
        self.last_tested_at = timezone.now()
        self.connection_error = error_message
        self.save(update_fields=['is_connected', 'last_tested_at', 'connection_error'])
    
    def update_sync_time(self):
        """Update last sync timestamp"""
        self.last_sync_at = timezone.now()
        self.save(update_fields=['last_sync_at'])


# =============================================================================
# ✨ DEVICE MODEL - LINKED TO ASSETCONFIG
# =============================================================================

class Device(models.Model):
    """
    IoT Device discovered from InfluxDB
    ✨ NEW: Each device belongs to a specific AssetConfig (InfluxDB instance)
    """
    
    DEVICE_TYPE_CHOICES = [
        ('industrial_sensor', 'Industrial Sensor'),
        ('asset_tracking', 'Asset Tracking'),
    ]
    
    # ✨ NEW FIELD - Links device to specific InfluxDB config
    asset_config = models.ForeignKey(
        AssetConfig,
        on_delete=models.CASCADE,
        related_name='devices',
        help_text="Which InfluxDB instance this device came from"
    )
    
    # Device identification
    device_type = models.CharField(
        max_length=50,
        choices=DEVICE_TYPE_CHOICES,
        blank=True,
        null=True
    )
    device_id = models.CharField(max_length=100)
    display_name = models.CharField(max_length=200)
    measurement_name = models.CharField(max_length=200)
    
    # Relationships
    departments = models.ManyToManyField(
        Department,
        related_name='devices',
        blank=True
    )
    
    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'companyadmin_device'
        verbose_name = 'Device'
        verbose_name_plural = 'Devices'
        ordering = ['asset_config', 'measurement_name', 'device_id']
        # ✨ NEW: Uniqueness includes asset_config
        unique_together = [['asset_config', 'measurement_name', 'device_id']]
    
    def __str__(self):
        return f"{self.display_name} ({self.asset_config.config_name})"
    
    @property
    def sensor_count(self):
        """Total sensor fields"""
        return self.sensors.filter(is_active=True).count()
    
    @property
    def configured_sensor_count(self):
        """Sensors with metadata configured"""
        return self.sensors.filter(
            is_active=True,
            metadata_config__isnull=False
        ).count()
    
    @property
    def configuration_progress(self):
        """Percentage of sensors configured"""
        total = self.sensor_count
        if total == 0:
            return 0
        return round((self.configured_sensor_count / total) * 100, 1)
    
    # ✨ NEW HELPER
    def get_influxdb_config(self):
        """Get InfluxDB config for this device"""
        return self.asset_config


# =============================================================================
# SENSOR MODEL (UNCHANGED)
# =============================================================================

class Sensor(models.Model):
    """Individual sensor field from InfluxDB"""
    
    CATEGORY_CHOICES = [
        ('sensor', 'Sensor Data'),
        ('info', 'Device Info'),
        ('slave', 'Slave ID'),
    ]
    
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='sensors'
    )
    
    field_name = models.CharField(max_length=100)
    display_name = models.CharField(max_length=200)
    field_type = models.CharField(max_length=50)
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='sensor'
    )
    unit = models.CharField(max_length=50, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'companyadmin_sensor'
        verbose_name = 'Sensor'
        verbose_name_plural = 'Sensors'
        unique_together = [['device', 'field_name']]
        ordering = ['device', 'category', 'field_name']
    
    def __str__(self):
        return f"{self.device.display_name} - {self.field_name}"
    
    def get_influxdb_config(self):
        """Get InfluxDB config through device"""
        return self.device.asset_config


# =============================================================================
# SENSOR METADATA MODEL (UNCHANGED)
# =============================================================================

class SensorMetadata(models.Model):
    """User-configured metadata for sensors"""
    
    DATA_TYPE_CHOICES = [
        ('trend', 'Trend Chart'),
        ('latest_value', 'Latest Value'),
        ('digital', 'Digital Status'),
    ]
    
    DATA_NATURE_CHOICES = [
        ('spot', 'Spot Reading'),
        ('cumulative', 'Cumulative'),
        ('digital_io', 'Digital I/O'),
    ]
    
    sensor = models.OneToOneField(
        Sensor,
        on_delete=models.CASCADE,
        related_name='metadata_config'
    )
    
    display_name = models.CharField(max_length=100, blank=True)
    unit = models.CharField(max_length=50, blank=True, null=True)
    description = models.TextField(blank=True)
    
    lower_limit = models.FloatField(blank=True, null=True)
    center_line = models.FloatField(blank=True, null=True)
    upper_limit = models.FloatField(blank=True, null=True)
    
    data_types = models.JSONField(default=list)
    data_nature = models.CharField(
        max_length=20,
        choices=DATA_NATURE_CHOICES,
        default='spot'
    )
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'companyadmin_sensor_metadata'
        verbose_name = 'Sensor Metadata'
        verbose_name_plural = 'Sensor Metadata'
    
    def __str__(self):
        return f"Metadata: {self.sensor.field_name}"
    
    def clean(self):
        super().clean()
        if not self.data_types:
            raise ValidationError("At least one data type must be selected")
        if (self.lower_limit is not None and self.upper_limit is not None 
            and self.lower_limit >= self.upper_limit):
            raise ValidationError("Lower limit must be less than upper limit")


# =============================================================================
# ASSET TRACKING CONFIG MODEL (UNCHANGED)
# =============================================================================

class AssetTrackingConfig(models.Model):
    """Configuration for asset tracking devices"""
    
    device = models.OneToOneField(
        Device,
        on_delete=models.CASCADE,
        related_name='asset_tracking_config',
        limit_choices_to={'device_type': 'asset_tracking'}
    )
    
    latitude_sensor = models.ForeignKey(
        Sensor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lat_configs'
    )
    longitude_sensor = models.ForeignKey(
        Sensor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lng_configs'
    )
    
    map_popup_sensors = models.ManyToManyField(
        Sensor,
        related_name='map_popup_configs',
        blank=True
    )
    info_card_sensors = models.ManyToManyField(
        Sensor,
        related_name='info_card_configs',
        blank=True
    )
    time_series_sensors = models.ManyToManyField(
        Sensor,
        related_name='time_series_configs',
        blank=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'companyadmin_asset_tracking_config'
        verbose_name = 'Asset Tracking Configuration'
        verbose_name_plural = 'Asset Tracking Configurations'
    
    def __str__(self):
        return f"Tracking Config: {self.device.display_name}"
    
    @property
    def has_location_config(self):
        return self.latitude_sensor is not None and self.longitude_sensor is not None
    
    def clean(self):
        super().clean()
        if self.device.device_type != 'asset_tracking':
            raise ValidationError(
                "Asset tracking config can only be created for asset_tracking devices"
            )