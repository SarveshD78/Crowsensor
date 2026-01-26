"""
departmentadmin/models.py

Models for Department Admin functionality including alerts, reports, and device assignments.
"""

import os

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# =============================================================================
# SENSOR ALERT MODEL
# =============================================================================

class SensorAlert(models.Model):
    """
    Alert system for sensor threshold breaches.
    
    Cross-app FK to companyadmin.SensorMetadata.
    Tenant-scoped (exists in tenant schemas).
    """
    
    STATUS_CHOICES = [
        ('initial', 'Initial'),      # 0-60 minutes
        ('medium', 'Medium'),        # 60-90 minutes
        ('high', 'High'),            # 90+ minutes
        ('resolved', 'Resolved')
    ]
    
    BREACH_TYPE_CHOICES = [
        ('upper', 'Upper Limit Breach'),
        ('lower', 'Lower Limit Breach')
    ]
    
    sensor_metadata = models.ForeignKey(
        'companyadmin.SensorMetadata',
        on_delete=models.CASCADE,
        related_name='alerts',
        help_text="Link to sensor metadata with configured limits"
    )
    
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='initial',
        db_index=True
    )
    
    breach_type = models.CharField(
        max_length=10,
        choices=BREACH_TYPE_CHOICES,
        db_index=True
    )
    
    breach_value = models.FloatField(
        help_text="Sensor value that caused the breach"
    )
    
    limit_value = models.FloatField(
        help_text="The limit that was breached"
    )
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_checked_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    escalated_to_medium_at = models.DateTimeField(null=True, blank=True)
    escalated_to_high_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'departmentadmin_sensoralert'
        verbose_name = "Sensor Alert"
        verbose_name_plural = "Sensor Alerts"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sensor_metadata', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['breach_type', 'status']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['sensor_metadata'],
                condition=models.Q(status__in=['initial', 'medium', 'high']),
                name='unique_active_alert_per_sensor'
            )
        ]
    
    def __str__(self):
        device_name = self.sensor_metadata.sensor.device.display_name
        sensor_name = self.sensor_metadata.get_display_name()
        return f"{device_name}.{sensor_name} - {self.get_status_display()}"
    
    def __repr__(self):
        return f"<SensorAlert(id={self.id}, status={self.status}, breach={self.breach_type})>"
    
    @property
    def is_active(self):
        """Check if alert is still active."""
        return self.status in ['initial', 'medium', 'high']
    
    @property
    def duration_minutes(self):
        """Calculate alert duration in minutes."""
        end_time = self.resolved_at if self.resolved_at else timezone.now()
        return int((end_time - self.created_at).total_seconds() / 60)
    
    @property
    def can_escalate_to_medium(self):
        """Check if alert can escalate to medium (after 60 minutes)."""
        return self.status == 'initial' and self.duration_minutes >= 60
    
    @property
    def can_escalate_to_high(self):
        """Check if alert can escalate to high (after 90 minutes total)."""
        return self.status == 'medium' and self.duration_minutes >= 90
    
    def escalate(self):
        """Escalate alert to next level."""
        now = timezone.now()
        if self.status == 'initial':
            self.status = 'medium'
            self.escalated_to_medium_at = now
        elif self.status == 'medium':
            self.status = 'high'
            self.escalated_to_high_at = now
        self.save(update_fields=['status', 'escalated_to_medium_at', 'escalated_to_high_at'])
    
    def resolve(self):
        """Mark alert as resolved."""
        self.status = 'resolved'
        self.resolved_at = timezone.now()
        self.save(update_fields=['status', 'resolved_at'])
    
    def update_breach_value(self, new_value):
        """Update current breach value."""
        self.breach_value = new_value
        self.save(update_fields=['breach_value'])
    
    def clean(self):
        """Validate alert data."""
        super().clean()
        if not self.sensor_metadata.upper_limit and not self.sensor_metadata.lower_limit:
            raise ValidationError("Cannot create alert for sensor without configured limits")
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


# =============================================================================
# DAILY DEVICE REPORT MODEL
# =============================================================================

def report_upload_path(instance, filename):
    """Generate upload path for reports."""
    date_str = instance.report_date.strftime('%Y/%m/%d')
    return f'reports/{instance.tenant.schema_name}/{date_str}/{filename}'


class DailyDeviceReport(models.Model):
    """Model to store daily device reports with sensor statistics."""
    
    REPORT_TYPE_CHOICES = [
        ('daily', 'Daily Report'),
        ('custom', 'Custom Report'),
    ]
    
    tenant = models.ForeignKey(
        'systemadmin.Tenant',
        on_delete=models.CASCADE,
        related_name='daily_reports'
    )
    
    department = models.ForeignKey(
        'companyadmin.Department',
        on_delete=models.CASCADE,
        related_name='daily_reports'
    )
    
    device = models.ForeignKey(
        'companyadmin.Device',
        on_delete=models.CASCADE,
        related_name='daily_reports'
    )
    
    report_date = models.DateField(
        db_index=True,
        help_text="Date this report covers (usually yesterday)"
    )
    
    report_type = models.CharField(
        max_length=20,
        default='daily',
        choices=REPORT_TYPE_CHOICES,
        db_index=True,
        help_text="Type of report"
    )
    
    csv_file = models.FileField(
        upload_to=report_upload_path,
        help_text="Generated CSV file"
    )
    
    total_sensors = models.IntegerField(
        default=0,
        help_text="Number of sensors included"
    )
    
    trend_sensors_count = models.IntegerField(
        default=0,
        help_text="Number of trend/time-series sensors"
    )
    
    latest_sensors_count = models.IntegerField(
        default=0,
        help_text="Number of latest value sensors"
    )
    
    data_points_analyzed = models.IntegerField(
        default=0,
        help_text="Total data points analyzed from InfluxDB"
    )
    
    generation_time_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Time taken to generate report"
    )
    
    generated_by = models.ForeignKey(
        'companyadmin.DepartmentMembership',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_reports'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    generation_errors = models.TextField(
        blank=True,
        help_text="Any errors during generation"
    )
    
    class Meta:
        verbose_name = "Daily Device Report"
        verbose_name_plural = "Daily Device Reports"
        ordering = ['-report_date', '-created_at']
        unique_together = ['tenant', 'device', 'report_date', 'report_type']
        indexes = [
            models.Index(fields=['tenant', 'department', 'report_date']),
            models.Index(fields=['device', 'report_date']),
            models.Index(fields=['report_type']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.device.display_name} - {self.report_date}"
    
    def __repr__(self):
        return f"<DailyDeviceReport(id={self.id}, device={self.device_id}, date={self.report_date})>"
    
    @property
    def file_size_mb(self):
        """Get file size in MB."""
        if self.csv_file and os.path.exists(self.csv_file.path):
            size_bytes = os.path.getsize(self.csv_file.path)
            return round(size_bytes / (1024 * 1024), 2)
        return 0
    
    @property
    def filename(self):
        """Get just the filename."""
        if self.csv_file:
            return os.path.basename(self.csv_file.name)
        return None
    
    def get_download_url(self):
        """Get download URL."""
        if self.csv_file:
            return self.csv_file.url
        return None
    
    def delete_file(self):
        """Delete the CSV file."""
        if self.csv_file and os.path.exists(self.csv_file.path):
            os.remove(self.csv_file.path)
            self.csv_file = None
            self.save(update_fields=['csv_file'])
            return True
        return False


# =============================================================================
# DEVICE USER ASSIGNMENT MODEL
# =============================================================================

class DeviceUserAssignment(models.Model):
    """
    Tracks which users have access to which devices within a department.
    
    Department Admin assigns devices to users in their department.
    """
    
    device = models.ForeignKey(
        'companyadmin.Device',
        on_delete=models.CASCADE,
        related_name='user_assignments',
        help_text="Device being assigned"
    )
    
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='device_assignments',
        help_text="User receiving access to device"
    )
    
    department = models.ForeignKey(
        'companyadmin.Department',
        on_delete=models.CASCADE,
        related_name='device_user_assignments',
        help_text="Department context for this assignment"
    )
    
    assigned_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='device_assignments_made',
        help_text="Admin who made this assignment"
    )
    
    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        verbose_name = "Device User Assignment"
        verbose_name_plural = "Device User Assignments"
        ordering = ['-assigned_at']
        unique_together = ['device', 'user', 'department']
        indexes = [
            models.Index(fields=['device', 'is_active']),
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['department', 'is_active']),
        ]
    
    def __str__(self):
        user_name = self.user.get_full_name() or self.user.username
        return f"{self.device.display_name} → {user_name} ({self.department.name})"
    
    def __repr__(self):
        return f"<DeviceUserAssignment(device={self.device_id}, user={self.user_id})>"
    
    @classmethod
    def get_device_users(cls, device, department):
        """Get all active users assigned to a device in a department."""
        return cls.objects.filter(
            device=device,
            department=department,
            is_active=True
        ).select_related('user')
    
    @classmethod
    def get_user_devices(cls, user, department):
        """Get all active devices assigned to a user in a department."""
        return cls.objects.filter(
            user=user,
            department=department,
            is_active=True
        ).select_related('device')
    
    @classmethod
    def assign_device_to_users(cls, device, users, department, assigned_by):
        """
        Bulk assign a device to multiple users.
        
        Args:
            device: Device instance
            users: QuerySet or list of User instances
            department: Department instance
            assigned_by: User who made the assignment
            
        Returns:
            tuple: (created_count, already_assigned_count)
        """
        created = 0
        existing = 0
        
        for user in users:
            obj, was_created = cls.objects.get_or_create(
                device=device,
                user=user,
                department=department,
                defaults={
                    'assigned_by': assigned_by,
                    'is_active': True
                }
            )
            
            if was_created:
                created += 1
            else:
                if not obj.is_active:
                    obj.is_active = True
                    obj.assigned_by = assigned_by
                    obj.save()
                    created += 1
                else:
                    existing += 1
        
        return created, existing
    
    @classmethod
    def unassign_device_from_users(cls, device, users, department):
        """Bulk unassign (soft delete) device from multiple users."""
        return cls.objects.filter(
            device=device,
            user__in=users,
            department=department,
            is_active=True
        ).update(is_active=False)