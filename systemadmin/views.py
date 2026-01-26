"""
systemadmin/views.py

System administration views for tenant management.
Handles system admin authentication, tenant CRUD, and dashboard.
"""

import logging
import random
import string
import traceback

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from django_tenants.utils import schema_context

from .decorators import main_domain_only, system_admin_required
from .forms import SystemAdminLoginForm, TenantCreationForm, TenantEditForm
from .models import Domain, Tenant

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _is_main_domain(hostname):
    """
    Check if hostname is the main domain (not a tenant subdomain).
    
    Args:
        hostname: Request hostname without port
        
    Returns:
        bool: True if main domain, False if tenant subdomain
    """
    parts = hostname.split('.')
    is_ip_address = len(parts) == 4 and all(part.isdigit() for part in parts)
    main_domains = ['e2e-75-221.ssdcloudindia.net', 'localhost', '127.0.0.1']
    return hostname in main_domains or is_ip_address


def _is_tenant_subdomain(hostname):
    """
    Check if hostname is a tenant subdomain.
    
    Args:
        hostname: Request hostname without port
        
    Returns:
        bool: True if tenant subdomain, False otherwise
    """
    parts = hostname.split('.')
    return len(parts) > 3 and not _is_main_domain(hostname)


def _generate_unique_code(company_name):
    """
    Generate unique subdomain code from company name + random digits.
    
    Example: "Acme Corporation" → "acmecorp1234"
    PostgreSQL schema names: lowercase, alphanumeric only, no hyphens.
    
    Args:
        company_name: Company name to generate code from
        
    Returns:
        str: Unique code suitable for subdomain and schema name
    """
    import time
    
    # Create base from company name (lowercase, alphanumeric only, max 8 chars)
    base = slugify(company_name).replace('-', '')[:8]
    
    if len(base) < 3:
        base = 'tenant'
    
    # Try up to 10 times to get a unique code
    for _ in range(10):
        random_digits = ''.join(random.choices(string.digits, k=4))
        code = f"{base}{random_digits}"
        
        if not Tenant.objects.filter(subdomain=code).exists() and \
           not Tenant.objects.filter(schema_name=code).exists():
            return code
    
    # Fallback: use timestamp
    timestamp = str(int(time.time()))[-4:]
    return f"{base}{timestamp}"


def _generate_secure_password(length=12):
    """
    Generate a secure random password.
    
    Includes uppercase, lowercase, digits, and special characters.
    
    Args:
        length: Password length (default 12)
        
    Returns:
        str: Secure random password
    """
    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    special = "!@#$%^&*"
    
    # Ensure at least one of each type
    password = [
        random.choice(uppercase),
        random.choice(lowercase),
        random.choice(digits),
        random.choice(special)
    ]
    
    # Fill remaining with random characters
    all_characters = uppercase + lowercase + digits + special
    password += [random.choice(all_characters) for _ in range(length - 4)]
    
    random.shuffle(password)
    return ''.join(password)


def _create_schema_if_not_exists(schema_name):
    """
    Create PostgreSQL schema if it doesn't exist.
    
    Args:
        schema_name: Name of schema to create
    """
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
    logger.info(f"Schema '{schema_name}' created/verified")


def _run_migrations_for_schema(schema_name):
    """
    Run migrations for a specific tenant schema.
    
    Args:
        schema_name: Name of schema to migrate
        
    Returns:
        bool: True if successful
        
    Raises:
        Exception: If migration fails
    """
    logger.info(f"Running migrations for schema: {schema_name}")
    
    call_command(
        'migrate_schemas',
        schema_name=schema_name,
        verbosity=0,
        interactive=False
    )
    
    logger.info(f"Migrations completed for schema: {schema_name}")
    return True


# =============================================================================
# PUBLIC VIEWS
# =============================================================================

def home(request):
    """
    Landing page with company code access portal.
    
    Behavior:
    - Main domain (localhost/IP) → Shows landing page with company code form
    - Subdomain (tenant.localhost) → Auto-redirect to tenant login
    - Logged in system admin → Redirect to dashboard
    """
    # Redirect logged-in system admin to dashboard
    if request.user.is_authenticated and getattr(request.user, 'is_superuser', False):
        logger.debug("System admin logged in, redirecting to dashboard")
        return redirect('systemadmin:system_dashboard')
    
    hostname = request.get_host().split(':')[0]
    
    # Subdomain detected - redirect to tenant login
    if _is_tenant_subdomain(hostname):
        logger.debug(f"Subdomain detected: {hostname} - redirecting to tenant login")
        return redirect('accounts:login')
    
    # Handle company code form submission
    if request.method == 'POST':
        return _handle_company_code_submission(request)
    
    # Show landing page
    context = {
        'page_title': 'Welcome to Crowsensor - IoT Monitoring Platform',
    }
    return render(request, 'systemadmin/landing.html', context)


def _handle_company_code_submission(request):
    """
    Handle company code form submission.
    
    Args:
        request: HTTP request with POST data
        
    Returns:
        HttpResponse: Redirect to tenant login or error page
    """
    company_code = request.POST.get('company_code', '').strip()
    
    logger.debug(f"Company code submitted: {company_code}")
    
    if not company_code or len(company_code) < 3:
        context = {
            'page_title': 'Welcome to Crowsensor',
            'error': 'Please enter a valid company code (minimum 3 characters).'
        }
        return render(request, 'systemadmin/landing.html', context)
    
    try:
        # Search by tenant_code OR subdomain (backward compatible)
        tenant = Tenant.objects.filter(
            Q(tenant_code__iexact=company_code) | Q(subdomain__iexact=company_code),
            is_active=True
        ).first()
        
        if not tenant:
            logger.debug(f"No tenant found with code: {company_code}")
            context = {
                'page_title': 'Welcome to Crowsensor',
                'error': 'Invalid company code. Please check and try again.'
            }
            return render(request, 'systemadmin/landing.html', context)
        
        logger.debug(f"Tenant found: {tenant.company_name}")
        
        # Get primary domain
        primary_domain = tenant.get_primary_domain()
        
        if not primary_domain or not primary_domain.is_active:
            logger.warning(f"No active primary domain for tenant: {tenant.company_name}")
            context = {
                'page_title': 'Welcome to Crowsensor',
                'error': 'Company domain is not configured. Please contact support.'
            }
            return render(request, 'systemadmin/landing.html', context)
        
        # Build redirect URL
        protocol = 'https' if request.is_secure() else 'http'
        hostname = request.get_host().split(':')[0]
        is_ip = len(hostname.split('.')) == 4 and all(p.isdigit() for p in hostname.split('.'))
        
        if is_ip:
            redirect_url = f"{protocol}://{primary_domain.domain}:8000/accounts/login/"
        else:
            port = ':8000' if 'localhost' in primary_domain.domain else ''
            redirect_url = f"{protocol}://{primary_domain.domain}{port}/accounts/login/"
        
        logger.info(f"Redirecting to tenant login: {redirect_url}")
        return redirect(redirect_url)
        
    except Exception as e:
        logger.error(f"Error processing company code: {e}", exc_info=True)
        context = {
            'page_title': 'Welcome to Crowsensor',
            'error': 'An error occurred. Please try again.'
        }
        return render(request, 'systemadmin/landing.html', context)


@main_domain_only
def system_login_view(request):
    """
    System Administrator login page.
    
    Uses Django's built-in authentication with is_superuser check.
    Only accessible from main domain.
    """
    # Redirect if already logged in as superuser
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect('systemadmin:system_dashboard')
    
    if request.method == 'POST':
        form = SystemAdminLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            
            user = authenticate(request, username=username, password=password)
            
            if user is not None:
                if user.is_superuser:
                    login(request, user)
                    messages.success(request, f'Welcome back, {user.username}!')
                    return redirect('systemadmin:system_dashboard')
                else:
                    messages.error(
                        request,
                        'Access denied. System Administrator privileges required.'
                    )
            else:
                messages.error(request, 'Invalid username or password.')
    else:
        form = SystemAdminLoginForm()
    
    context = {
        'form': form,
        'page_title': 'System Admin Login'
    }
    return render(request, 'systemadmin/system_login.html', context)


def system_logout_view(request):
    """Logout system administrator."""
    logout(request)
    messages.success(request, '👋 You have been logged out successfully.')
    return redirect('systemadmin:system_login')


# =============================================================================
# DASHBOARD VIEWS
# =============================================================================

@system_admin_required
def system_dashboard_view(request):
    """
    System Administrator Dashboard.
    
    Shows all tenants in card view with statistics.
    """
    tenants = Tenant.objects.exclude(
        schema_name='public'
    ).prefetch_related('domains')
    
    context = {
        'tenants': tenants,
        'total_tenants': tenants.count(),
        'active_tenants': tenants.filter(is_active=True).count(),
        'inactive_tenants': tenants.filter(is_active=False).count(),
        'page_title': 'System Dashboard',
        'admin_user': request.user,
    }
    return render(request, 'systemadmin/system_dashboard.html', context)


# =============================================================================
# TENANT CRUD VIEWS
# =============================================================================

@system_admin_required
def tenant_create_view(request):
    """
    Create new tenant with schema and company admin user.
    """
    if request.method == 'POST':
        form = TenantCreationForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    tenant = _create_tenant(form, request)
                    return redirect('systemadmin:tenant_detail', tenant_id=tenant.id)
            except Exception as e:
                logger.error(f"Error creating tenant: {e}", exc_info=True)
                messages.error(request, f'Error creating tenant: {str(e)}')
    else:
        form = TenantCreationForm()
    
    context = {
        'form': form,
        'page_title': 'Create New Tenant'
    }
    return render(request, 'systemadmin/tenant_create.html', context)


def _create_tenant(form, request):
    """
    Create tenant with all associated resources.
    
    Creates:
    - Tenant record
    - Domain record
    - PostgreSQL schema
    - Company admin user
    
    Args:
        form: Validated TenantCreationForm
        request: HTTP request for messages
        
    Returns:
        Tenant: Created tenant instance
    """
    company_name = form.cleaned_data['company_name']
    subdomain = form.cleaned_data['subdomain'].lower().strip()
    
    logger.info(f"Creating tenant: {company_name} ({subdomain})")
    
    # Generate credentials
    username_base = slugify(company_name).replace('-', '')[:8]
    if len(username_base) < 3:
        username_base = 'tenant'
    random_digits = ''.join(random.choices(string.digits, k=4))
    username = f"{username_base}{random_digits}"
    tenant_code = username
    
    password_base = slugify(company_name).replace('-', '')
    if len(password_base) > 15:
        password_base = password_base[:15]
    admin_password = f"{password_base}@Sisai@2025"
    
    # Create tenant record
    tenant = form.save(commit=False)
    tenant.subdomain = subdomain
    tenant.schema_name = subdomain
    tenant.tenant_code = tenant_code
    tenant.save()
    
    logger.info(f"Tenant record created (ID: {tenant.id})")
    
    # Create domain
    domain_name = f"{subdomain}.technologymatters.in"
    Domain.objects.create(
        tenant=tenant,
        domain=domain_name,
        is_primary=True,
        is_active=True
    )
    logger.info(f"Domain created: {domain_name}")
    
    # Create schema and run migrations
    _create_schema_if_not_exists(tenant.schema_name)
    _run_migrations_for_schema(tenant.schema_name)
    
    # Create company admin user
    admin_email = form.cleaned_data['admin_email']
    contact_person = form.cleaned_data.get('contact_person', '')
    
    with schema_context(tenant.schema_name):
        from accounts.models import User as TenantUser
        
        # Clean existing users
        existing_count = TenantUser.objects.count()
        if existing_count > 0:
            logger.debug(f"Cleaning {existing_count} existing user(s)")
            TenantUser.objects.all().delete()
        
        # Parse contact person name
        name_parts = contact_person.split() if contact_person else []
        first_name = name_parts[0] if name_parts else ''
        last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
        
        # Create company admin
        admin_user = TenantUser.objects.create_user(
            username=username,
            email=admin_email,
            password=admin_password,
            first_name=first_name,
            last_name=last_name,
            role='company_admin',
            is_active=True,
            is_superuser=False,
            is_staff=False
        )
        logger.info(f"Company admin created: {admin_user.username}")
    
    # Success message with credentials
    messages.success(
        request,
        f'🎉 Tenant "{tenant.company_name}" created successfully!\n\n'
        f'🎫 Tenant Access Code: {tenant_code}\n'
        f'🌐 Login URL: https://{subdomain}.technologymatters.in/accounts/login/\n'
        f'👤 Username: {username}\n'
        f'🔐 Password: {admin_password}\n\n'
        f'⚠️ Save these credentials - they cannot be viewed again!'
    )
    
    logger.info(f"Tenant setup complete: {company_name}")
    return tenant


@system_admin_required
def tenant_detail_view(request, tenant_id):
    """View tenant details with company admin info."""
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # Get company admin from tenant schema
    company_admin = None
    try:
        with schema_context(tenant.schema_name):
            from accounts.models import User as TenantUser
            company_admin = TenantUser.objects.filter(role='company_admin').first()
    except Exception as e:
        logger.warning(f"Could not fetch company admin for {tenant.schema_name}: {e}")
    
    context = {
        'tenant': tenant,
        'company_admin': company_admin,
        'page_title': f'Tenant: {tenant.company_name}'
    }
    return render(request, 'systemadmin/tenant_detail.html', context)


@system_admin_required
def tenant_edit_view(request, tenant_id):
    """Edit existing tenant."""
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    if request.method == 'POST':
        form = TenantEditForm(request.POST, instance=tenant)
        if form.is_valid():
            try:
                form.save()
                messages.success(
                    request,
                    f'✅ Tenant "{tenant.company_name}" updated successfully!'
                )
                return redirect('systemadmin:tenant_detail', tenant_id=tenant.id)
            except Exception as e:
                logger.error(f"Error updating tenant: {e}")
                messages.error(request, f'❌ Error updating tenant: {str(e)}')
    else:
        form = TenantEditForm(instance=tenant)
    
    context = {
        'form': form,
        'tenant': tenant,
        'page_title': f'Edit Tenant: {tenant.company_name}'
    }
    return render(request, 'systemadmin/tenant_edit.html', context)


@system_admin_required
def tenant_toggle_status(request, tenant_id):
    """Toggle tenant active/inactive status."""
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    if tenant.schema_name == 'public':
        messages.error(request, '❌ Cannot deactivate the public schema.')
        return redirect('systemadmin:system_dashboard')
    
    tenant.is_active = not tenant.is_active
    tenant.save()
    
    status = "activated" if tenant.is_active else "deactivated"
    icon = "✅" if tenant.is_active else "⚠️"
    messages.success(
        request,
        f'{icon} Tenant "{tenant.company_name}" {status} successfully!'
    )
    
    return redirect('systemadmin:tenant_detail', tenant_id=tenant.id)


@system_admin_required
def tenant_delete_view(request, tenant_id):
    """
    Permanently delete tenant, schema, and all associated data.
    
    Security:
    - POST request required
    - Company name confirmation required
    - Cannot delete 'public' schema
    - Terminates all active connections before schema drop
    """
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # Prevent deletion of public schema
    if tenant.schema_name == 'public':
        messages.error(request, '❌ Cannot delete the public schema!')
        return redirect('systemadmin:system_dashboard')
    
    # Only allow POST
    if request.method != 'POST':
        messages.error(request, '❌ Invalid request method')
        return redirect('systemadmin:tenant_detail', tenant_id=tenant_id)
    
    # Verify company name confirmation
    confirmed_name = request.POST.get('confirm_company_name', '').strip()
    if confirmed_name != tenant.company_name:
        messages.error(
            request,
            f'❌ Company name confirmation failed. Please type "{tenant.company_name}" exactly.'
        )
        return redirect('systemadmin:tenant_detail', tenant_id=tenant_id)
    
    # Store details for success message
    company_name = tenant.company_name
    schema_name = tenant.schema_name
    subdomain = tenant.subdomain
    
    try:
        with transaction.atomic():
            logger.info(f"Deleting tenant: {company_name}")
            
            # Drop schema if enabled
            if tenant.auto_drop_schema:
                _drop_tenant_schema(schema_name)
            else:
                logger.warning(f"Schema NOT dropped (auto_drop_schema=False): {schema_name}")
            
            # Delete domains
            domain_list = list(tenant.domains.values_list('domain', flat=True))
            domain_count = tenant.domains.count()
            tenant.domains.all().delete()
            logger.info(f"Deleted {domain_count} domain(s)")
            
            # Delete tenant record
            tenant.delete()
            logger.info(f"Tenant record deleted: {company_name}")
            
            messages.success(
                request,
                f'✅ Tenant "{company_name}" has been permanently deleted!\n\n'
                f'Details:\n'
                f'• Schema: {schema_name}\n'
                f'• Subdomain: {subdomain}\n'
                f'• Domains: {", ".join(domain_list)}'
            )
            
            return redirect('systemadmin:system_dashboard')
            
    except Exception as e:
        logger.error(f"Failed to delete tenant {company_name}: {e}", exc_info=True)
        messages.error(
            request,
            f'❌ Failed to delete tenant "{company_name}"!\n\n'
            f'Error: {str(e)}\n\n'
            f'Please check server logs for details.'
        )
        return redirect('systemadmin:tenant_detail', tenant_id=tenant_id)


def _drop_tenant_schema(schema_name):
    """
    Drop PostgreSQL schema with all data.
    
    Terminates active connections before dropping.
    
    Args:
        schema_name: Name of schema to drop
    """
    logger.info(f"Dropping schema: {schema_name}")
    
    with connection.cursor() as cursor:
        # Terminate active connections
        cursor.execute(f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = current_database()
              AND pg_stat_activity.pid <> pg_backend_pid()
              AND pg_stat_activity.query LIKE '%{schema_name}%';
        """)
        
        # Drop schema
        cursor.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
    
    logger.info(f"Schema dropped: {schema_name}")