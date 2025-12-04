from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Custom admin interface for User model
    Optimized for multi-tenant role-based system
    """
    
    # List Display
    list_display = [
        'username',
        'email',
        'get_full_name_display',
        'role_badge',
        'is_active',
        'is_staff',
        'date_joined',
    ]
    
    # ✅ UPDATED: List Filters (removed sub_admin, operator)
    list_filter = [
        'role',
        'is_active',
        'is_staff',
        'is_superuser',
        'date_joined',
    ]
    
    # Search Fields
    search_fields = [
        'username',
        'email',
        'first_name',
        'last_name',
        'phone',
    ]
    
    # Ordering
    ordering = ['-date_joined']
    
    # Filters on right sidebar
    date_hierarchy = 'date_joined'
    
    # Fields displayed when editing user
    fieldsets = (
        ('Authentication', {
            'fields': ('username', 'password')
        }),
        ('Personal Information', {
            'fields': ('first_name', 'last_name', 'email', 'phone', 'bio', 'avatar')
        }),
        ('Role & Permissions', {
            'fields': ('role', 'is_active', 'is_staff', 'is_superuser')
        }),
        ('Important Dates', {
            'fields': ('last_login', 'date_joined', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    # Fields displayed when adding new user
    add_fieldsets = (
        ('Authentication', {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2'),
        }),
        ('Personal Information', {
            'classes': ('wide',),
            'fields': ('first_name', 'last_name', 'email', 'phone'),
        }),
        ('Role & Permissions', {
            'classes': ('wide',),
            'fields': ('role', 'is_active', 'is_staff'),
        }),
    )
    
    # Read-only fields
    readonly_fields = ['created_at', 'updated_at', 'last_login', 'date_joined']
    
    # Custom Methods
    def get_full_name_display(self, obj):
        """Display full name or username"""
        full_name = obj.get_full_name()
        return full_name if full_name else '—'
    get_full_name_display.short_description = 'Full Name'
    
    def role_badge(self, obj):
        """Display role with colored badge"""
        # ✅ UPDATED: Removed sub_admin and operator colors
        colors = {
            'company_admin': '#0d6efd',      # Blue
            'department_admin': '#198754',   # Green
            'user': '#6c757d',               # Gray (formerly operator)
        }
        color = colors.get(obj.role, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: 600; font-size: 11px;">{}</span>',
            color,
            obj.get_role_display()
        )
    role_badge.short_description = 'Role'
    
    # ✅ UPDATED: Actions (removed sub_admin actions, changed operator to user)
    actions = ['activate_users', 'deactivate_users', 'make_company_admin', 'make_user']
    
    def activate_users(self, request, queryset):
        """Activate selected users"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} user(s) activated successfully.')
    activate_users.short_description = 'Activate selected users'
    
    def deactivate_users(self, request, queryset):
        """Deactivate selected users"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} user(s) deactivated successfully.')
    deactivate_users.short_description = 'Deactivate selected users'
    
    def make_company_admin(self, request, queryset):
        """Change role to Company Admin"""
        updated = queryset.update(role='company_admin')
        self.message_user(request, f'{updated} user(s) changed to Company Admin.')
    make_company_admin.short_description = 'Change role to Company Admin'
    
    def make_user(self, request, queryset):
        """Change role to User (read-only)"""
        updated = queryset.update(role='user')  # ← Changed from 'operator'
        self.message_user(request, f'{updated} user(s) changed to User.')
    make_user.short_description = 'Change role to User'  # ← Changed description