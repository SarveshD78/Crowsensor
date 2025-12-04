from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from .managers import UserManager


class User(AbstractUser):
    """
    Custom user model for multi-tenant system
    
    Each user exists within a tenant's schema (automatic isolation).
    No tenant ForeignKey needed - schema context determines tenant ownership.
    
    Supports role-based access control (RBAC):
    - company_admin: Full access to company data
    - department_admin: Manage assigned departments
    - user: Read-only access (formerly operator)
    """
    
    # ✅ UPDATED ROLE_CHOICES - Removed sub_admin, renamed operator to user
    ROLE_CHOICES = [
        ('company_admin', 'Company Admin'),
        ('department_admin', 'Department Admin'),
        ('user', 'User'),  # ← Changed from 'operator'
    ]
    
    # Core Fields
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='user',  # ← Changed default from 'operator'
        db_index=True,
        help_text='User role determines access level within the tenant'
    )
    
    phone = models.CharField(
        max_length=20,
        blank=True,
        help_text='Contact phone number'
    )
    
    # Timestamps
    created_at = models.DateTimeField(
        default=timezone.now,
        help_text='When user account was created'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text='Last time user data was modified'
    )
    
    # Profile Fields
    avatar = models.ImageField(
        upload_to='avatars/',
        blank=True,
        null=True,
        help_text='User profile picture'
    )
    bio = models.TextField(
        blank=True,
        max_length=500,
        help_text='Short bio or description'
    )
    
    # FIX: Add related_name to avoid clash with Django's User
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name='tenant_user_set',
        related_query_name='tenant_user',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='tenant_user_set',
        related_query_name='tenant_user',
    )
    
    # Custom Manager
    objects = UserManager()
    
    class Meta:
        db_table = 'user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['role'], name='idx_user_role'),
            models.Index(fields=['email'], name='idx_user_email'),
            models.Index(fields=['is_active'], name='idx_user_active'),
            models.Index(fields=['created_at'], name='idx_user_created'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['username'],
                name='unique_username_per_tenant'
            ),
            models.UniqueConstraint(
                fields=['email'],
                condition=models.Q(email__isnull=False) & ~models.Q(email=''),
                name='unique_email_per_tenant'
            ),
        ]
    
    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
    
    def __repr__(self):
        return f"<User: {self.username} - {self.role}>"
    
    # ==========================================
    # ROLE CHECK METHODS
    # ==========================================
    
    def is_company_admin(self):
        """Check if user is company administrator"""
        return self.role == 'company_admin'
    
    def is_department_admin(self):
        """Check if user is department administrator"""
        return self.role == 'department_admin'
    
    # ✅ REMOVED is_sub_admin() method
    
    def is_user(self):
        """Check if user is read-only user (formerly operator)"""
        return self.role == 'user'
    
    # ✅ KEPT for backward compatibility during migration
    def is_operator(self):
        """DEPRECATED: Use is_user() instead. Kept for backward compatibility."""
        return self.role == 'user'
    
    # ==========================================
    # PERMISSION CHECK METHODS
    # ==========================================
    
    def can_manage_company(self):
        """Check if user can manage entire company settings"""
        return self.role == 'company_admin'
    
    def can_manage_users(self):
        """Check if user can create/edit/delete other users"""
        return self.role in ['company_admin', 'department_admin']
    
    def can_manage_departments(self):
        """Check if user can create/edit/delete departments"""
        return self.role == 'company_admin'
    
    def can_edit_settings(self):
        """Check if user can modify system settings"""
        return self.role in ['company_admin', 'department_admin']
    
    def can_view_reports(self):
        """Check if user can view reports"""
        return True
    
    def can_export_data(self):
        """Check if user can export data"""
        return self.role in ['company_admin', 'department_admin']  # ← Removed sub_admin
    
    def can_manage_assets(self):
        """Check if user can manage IoT assets/devices"""
        return self.role in ['company_admin', 'department_admin']  # ← Removed sub_admin
    
    def can_configure_alerts(self):
        """Check if user can configure alert thresholds"""
        return self.role in ['company_admin', 'department_admin']  # ← Removed sub_admin
    
    def is_read_only(self):
        """Check if user has read-only access"""
        return self.role == 'user'  # ← Changed from 'operator'
    
    # ==========================================
    # UTILITY METHODS
    # ==========================================
    
    def get_full_name_or_username(self):
        """Get full name if available, otherwise return username"""
        full_name = self.get_full_name().strip()
        return full_name if full_name else self.username
    
    def get_display_name(self):
        """Get best available name for display"""
        if self.first_name:
            return self.first_name
        full_name = self.get_full_name().strip()
        return full_name if full_name else self.username
    
    def get_initials(self):
        """Get user initials for avatar display"""
        if self.first_name and self.last_name:
            return f"{self.first_name[0]}{self.last_name[0]}".upper()
        elif self.first_name:
            return self.first_name[0].upper()
        else:
            return self.username[0].upper()
    
    def get_role_color(self):
        """Get color code for role badge display"""
        role_colors = {
            'company_admin': 'primary',
            'department_admin': 'success',
            'user': 'secondary',  # ← Changed from 'operator'
        }
        return role_colors.get(self.role, 'secondary')
    
    def get_role_icon(self):
        """Get FontAwesome icon for role"""
        role_icons = {
            'company_admin': 'fa-crown',
            'department_admin': 'fa-user-tie',
            'user': 'fa-user',  # ← Changed from 'operator'
        }
        return role_icons.get(self.role, 'fa-user')
    
    def has_profile_picture(self):
        """Check if user has uploaded a profile picture"""
        return bool(self.avatar and hasattr(self.avatar, 'url'))
    
    def get_avatar_url(self):
        """Get avatar URL or return default placeholder"""
        if self.has_profile_picture():
            return self.avatar.url
        return None
    
    def is_newly_created(self):
        """Check if user account was created recently"""
        from datetime import timedelta
        return (timezone.now() - self.created_at) < timedelta(days=7)
    
    def get_account_age_days(self):
        """Get number of days since account creation"""
        return (timezone.now() - self.created_at).days
    
    def save(self, *args, **kwargs):
        """Override save to ensure data integrity"""
        if self.email:
            self.email = self.email.lower().strip()
        self.username = self.username.strip()
        super().save(*args, **kwargs)