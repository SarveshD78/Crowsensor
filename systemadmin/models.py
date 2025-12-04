from django.db import models
from django.utils import timezone


class Tenant(models.Model):
    """
    Tenant/Company - Each customer company in the multi-tenant system
    """
    company_name = models.CharField(max_length=255, unique=True)
    subdomain = models.CharField(max_length=63, unique=True, 
                                  help_text="Used for subdomain routing (e.g., acme.yourdomain.com)")
    schema_name = models.CharField(max_length=63, unique=True,
                                    help_text="Database schema name (auto-generated from subdomain)")
    
    # 🆕 NEW FIELD - Optional, won't break existing data
    tenant_code = models.CharField(
        max_length=20, 
        unique=True, 
        blank=True,  # ✅ Safe: Allows existing records to be null
        null=True,   # ✅ Safe: Allows null in database
        help_text="Unique tenant access code (e.g., lime0026) - used for login portal"
    )
    
    auto_drop_schema = models.BooleanField(
        default=False,
        help_text="Automatically drop schema when tenant is deleted"
    )
    auto_create_schema = models.BooleanField(
        default=True,
        help_text="Automatically create schema when tenant is created"
    )
    
    contact_person = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    notes = models.TextField(blank=True, help_text="Internal notes about this tenant")

    class Meta:
        db_table = 'tenant'
        verbose_name = 'Tenant'
        verbose_name_plural = 'Tenants'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.company_name} ({self.subdomain})"

    def get_primary_domain(self):
        """Get primary domain for this tenant"""
        return self.domains.filter(is_primary=True).first()

    def get_user_count(self):
        """Get total users in this tenant's schema"""
        from accounts.models import User
        from django_tenants.utils import schema_context
        try:
            with schema_context(self.schema_name):
                return User.objects.count()
        except:
            return 0

    def get_last_login(self):
        """Get most recent user login timestamp"""
        from accounts.models import User
        from django_tenants.utils import schema_context
        try:
            with schema_context(self.schema_name):
                last_user = User.objects.filter(last_login__isnull=False).order_by('-last_login').first()
                return last_user.last_login if last_user else None
        except:
            return None

    def save(self, *args, **kwargs):
        """Auto-generate schema_name from subdomain if not provided"""
        if not self.schema_name:
            self.schema_name = self.subdomain.lower().replace('-', '_')
        super().save(*args, **kwargs)



class Domain(models.Model):
    """
    Domain names associated with tenants
    Supports multiple domains per tenant (primary + aliases)
    """
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='domains')
    domain = models.CharField(max_length=255, unique=True,
                              help_text="Full domain (e.g., acme.yourdomain.com)")
    is_primary = models.BooleanField(default=False,
                                     help_text="Primary domain for this tenant")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'domain'
        verbose_name = 'Domain'
        verbose_name_plural = 'Domains'
        ordering = ['-is_primary', 'domain']

    def __str__(self):
        primary = " (Primary)" if self.is_primary else ""
        return f"{self.domain}{primary}"

    def save(self, *args, **kwargs):
        """Ensure only one primary domain per tenant"""
        if self.is_primary:
            # Set all other domains for this tenant to non-primary
            Domain.objects.filter(tenant=self.tenant, is_primary=True).update(is_primary=False)
        super().save(*args, **kwargs)