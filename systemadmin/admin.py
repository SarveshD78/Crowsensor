from django.contrib import admin
from .models import Tenant, Domain


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'subdomain', 'schema_name', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['company_name', 'subdomain', 'contact_email']
    readonly_fields = ['schema_name', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Company Information', {
            'fields': ('company_name', 'subdomain', 'schema_name')
        }),
        ('Contact Details', {
            'fields': ('contact_person', 'contact_email', 'contact_phone')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Metadata', {
            'fields': ('notes', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ['domain', 'tenant', 'is_primary', 'is_active', 'created_at']
    list_filter = ['is_primary', 'is_active', 'created_at']
    search_fields = ['domain', 'tenant__company_name']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Domain Information', {
            'fields': ('tenant', 'domain', 'is_primary', 'is_active')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )