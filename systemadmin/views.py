from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User  # ← Django's built-in User for System Admin
from django.db import transaction, connection
from django.utils.text import slugify
from django.core.management import call_command
from django_tenants.utils import schema_context
import random
import string
import traceback
from .models import Tenant, Domain
from .forms import SystemAdminLoginForm, TenantCreationForm, TenantEditForm
from .decorators import main_domain_only, system_admin_required
# TENANT: System Admin views - Production Ready with Toast Notifications


from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Q
from .models import Tenant, Domain

from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Q
from .models import Tenant, Domain

def home(request):
    """
    Landing page with company code access portal
    - Main domain (localhost/IP) → Shows landing page with company code form
    - Subdomain (tenant.localhost) → Auto-redirect to tenant login
    """
    
    # STEP 1: Check if system admin is already logged in
    if request.user.is_authenticated and hasattr(request.user, 'is_superuser') and request.user.is_superuser:
        print("🔄 System admin logged in, redirecting to dashboard")
        return redirect('systemadmin:system_dashboard')
    
    # STEP 2: Check if we're on a tenant subdomain
    hostname = request.get_host().split(':')[0]
    parts = hostname.split('.')
    
    print(f"🔍 DEBUG home() - hostname: {hostname}, parts: {parts}")
    
    # Check if it's an IP address (has 4 numeric parts like 164.52.207.221)
    is_ip_address = len(parts) == 4 and all(part.isdigit() for part in parts)
    is_main_domain = hostname in ['e2e-75-221.ssdcloudindia.net', 'localhost', '127.0.0.1'] or is_ip_address
    
    # Subdomain detection: more than 1 part, NOT an IP address, NOT www/localhost/127
    is_subdomain = len(parts) > 3 and not is_main_domain
    
    if is_subdomain:
        # We're on a tenant subdomain - redirect immediately to tenant login
        print(f"🔄 Subdomain detected: {parts[0]} - Redirecting to /accounts/login/")
        return redirect('accounts:login')
    
    # STEP 3: We're on MAIN domain (localhost or IP) - handle company code form
    print(f"🏠 Main domain detected - Showing landing page")
    
    if request.method == 'POST':
        company_code = request.POST.get('company_code', '').strip()
        
        print("=" * 80)
        print(f"🔍 DEBUG: Received company_code: '{company_code}'")
        
        if not company_code or len(company_code) < 3:
            print("❌ Company code too short")
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
                print(f"❌ DEBUG: No tenant found with code: '{company_code}'")
                print("=" * 80)
                context = {
                    'page_title': 'Welcome to Crowsensor',
                    'error': 'Invalid company code. Please check and try again.'
                }
                return render(request, 'systemadmin/landing.html', context)
            
            print(f"✅ DEBUG: Tenant found!")
            print(f"   Company: {tenant.company_name}")
            print(f"   Tenant Code: {tenant.tenant_code if hasattr(tenant, 'tenant_code') else 'N/A'}")
            print(f"   Subdomain: {tenant.subdomain}")
            
            # Get primary domain
            primary_domain = tenant.get_primary_domain()
            
            if not primary_domain or not primary_domain.is_active:
                print("❌ DEBUG: No active primary domain")
                print("=" * 80)
                context = {
                    'page_title': 'Welcome to Crowsensor',
                    'error': 'Company domain is not configured. Please contact support.'
                }
                return render(request, 'systemadmin/landing.html', context)
            
            # Redirect to tenant login
            protocol = 'https' if request.is_secure() else 'http'
            
            # Use IP with port for IP-based domains, otherwise use the domain as-is
            if is_ip_address:
                redirect_url = f"{protocol}://{primary_domain.domain}:8000/accounts/login/"
            else:
                port = ':8000' if 'localhost' in primary_domain.domain else ''
                redirect_url = f"{protocol}://{primary_domain.domain}{port}/accounts/login/"
            
            print(f"🚀 DEBUG: Redirecting to: {redirect_url}")
            print("=" * 80)
            
            return redirect(redirect_url)
            
        except Exception as e:
            print(f"❌ DEBUG: Error: {str(e)}")
            import traceback
            print(traceback.format_exc())
            print("=" * 80)
            
            context = {
                'page_title': 'Welcome to Crowsensor',
                'error': 'An error occurred. Please try again.'
            }
            return render(request, 'systemadmin/landing.html', context)
    
    # STEP 4: Show landing page (GET request on main domain)
    print(f"✅ Rendering landing page for: {request.get_host()}")
    
    context = {
        'page_title': 'Welcome to Crowsensor - IoT Monitoring Platform',
    }
    return render(request, 'systemadmin/landing.html', context)


@main_domain_only
def system_login_view(request):
    """
    System Administrator login page
    Uses Django's built-in authentication with is_superuser check
    """
    # If already logged in as superuser, redirect to dashboard
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect('systemadmin:system_dashboard')
    
    if request.method == 'POST':
        form = SystemAdminLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            
            # Authenticate user
            user = authenticate(request, username=username, password=password)
            
            if user is not None:
                # Check if user is superuser
                if user.is_superuser:
                    # Login the user
                    login(request, user)
                    messages.success(request, f'Welcome back, {user.username}!')
                    return redirect('systemadmin:system_dashboard')
                else:
                    messages.error(request, 'Access denied. System Administrator privileges required.')
            else:
                messages.error(request, 'Invalid username or password.')
    else:
        form = SystemAdminLoginForm()
    
    context = {
        'form': form,
        'page_title': 'System Admin Login'
    }
    return render(request, 'systemadmin/system_login.html', context)


def generate_unique_code(company_name):
    """
    Generate unique subdomain code from company name + random digits
    Example: "Acme Corporation" → "acmecorp1234"
    PostgreSQL schema names: lowercase, alphanumeric only, no hyphens
    """
    # Create base from company name (lowercase, alphanumeric only, max 8 chars)
    base = slugify(company_name).replace('-', '')[:8]  # Remove hyphens for PostgreSQL
    
    # If base is empty or too short, use default
    if len(base) < 3:
        base = 'tenant'
    
    # Keep trying until we get a unique code
    max_attempts = 10
    for _ in range(max_attempts):
        # Add 4 random digits
        random_digits = ''.join(random.choices(string.digits, k=4))
        code = f"{base}{random_digits}"
        
        # Check if unique (subdomain and schema_name)
        if not Tenant.objects.filter(subdomain=code).exists() and \
           not Tenant.objects.filter(schema_name=code).exists():
            return code
    
    # Fallback: use timestamp if still not unique
    import time
    timestamp = str(int(time.time()))[-4:]
    return f"{base}{timestamp}"


def generate_secure_password(length=12):
    """
    Generate a secure random password
    Includes uppercase, lowercase, digits, and special characters
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
    
    # Shuffle to make it random
    random.shuffle(password)
    return ''.join(password)


def create_schema_if_not_exists(schema_name):
    """
    Create PostgreSQL schema if it doesn't exist
    """
    with connection.cursor() as cursor:
        cursor.execute(
            f"CREATE SCHEMA IF NOT EXISTS {schema_name}"
        )
        print(f"✅ Schema '{schema_name}' created/verified")


def run_migrations_for_schema(schema_name):
    """
    Run migrations for a specific tenant schema
    """
    try:
        print(f"🔄 Running migrations for schema: {schema_name}")
        call_command(
            'migrate_schemas',
            schema_name=schema_name,
            verbosity=0,
            interactive=False
        )
        print(f"✅ Migrations completed for schema: {schema_name}")
        return True
    except Exception as e:
        print(f"❌ Migration error for {schema_name}: {str(e)}")
        raise


@system_admin_required
def system_dashboard_view(request):
    """
    System Administrator Dashboard
    Shows all tenants in card view
    """
    # Get all tenants (exclude 'public' schema)
    tenants = Tenant.objects.exclude(schema_name='public').prefetch_related('domains')
    
    # Calculate statistics
    total_tenants = tenants.count()
    active_tenants = tenants.filter(is_active=True).count()
    inactive_tenants = tenants.filter(is_active=False).count()
    
    context = {
        'tenants': tenants,
        'total_tenants': total_tenants,
        'active_tenants': active_tenants,
        'inactive_tenants': inactive_tenants,
        'page_title': 'System Dashboard',
        'admin_user': request.user,
    }
    return render(request, 'systemadmin/system_dashboard.html', context)

@system_admin_required
def tenant_create_view(request):
    """
    Create new tenant - Dedicated page
    """
    if request.method == 'POST':
        form = TenantCreationForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    company_name = form.cleaned_data['company_name']
                    subdomain = form.cleaned_data['subdomain'].lower().strip()
                    
                    print(f"\n🏢 Creating tenant: {company_name}")
                    print(f"📝 Using subdomain: {subdomain}")
                    
                    # Generate username (existing logic - unchanged)
                    username_base = slugify(company_name).replace('-', '')[:8]
                    if len(username_base) < 3:
                        username_base = 'tenant'
                    random_digits = ''.join(random.choices(string.digits, k=4))
                    username = f"{username_base}{random_digits}"
                    
                    # 🆕 NEW: Store the same value as tenant_code
                    tenant_code = username
                    
                    password_base = slugify(company_name).replace('-', '')
                    if len(password_base) > 15:
                        password_base = password_base[:15]
                    admin_password = f"{password_base}@Sisai@2025"
                    
                    print(f"👤 Generated username: {username}")
                    print(f"🎫 Tenant code: {tenant_code}")  # 🆕 NEW LOG
                    print(f"🔐 Generated password: {admin_password}")
                    
                    tenant = form.save(commit=False)
                    tenant.subdomain = subdomain
                    tenant.schema_name = subdomain
                    tenant.tenant_code = tenant_code  # 🆕 NEW: Store tenant code
                    tenant.save()
                    print(f"✅ Tenant record created (ID: {tenant.id})")
                    
                    domain_name = f"{subdomain}.technologymatters.in"
                    #domain_name = f"{subdomain}.localhost"
                    Domain.objects.create(
                        tenant=tenant,
                        domain=domain_name,
                        is_primary=True,
                        is_active=True
                    )
                    print(f"✅ Domain created: {domain_name}")
                    
                    create_schema_if_not_exists(tenant.schema_name)
                    run_migrations_for_schema(tenant.schema_name)
                    
                    admin_email = form.cleaned_data['admin_email']
                    
                    # Import tenant User model inside schema context
                    with schema_context(tenant.schema_name):
                        from accounts.models import User as TenantUser
                        
                        # Check and clean any existing users
                        existing_count = TenantUser.objects.all().count()
                        if existing_count > 0:
                            print(f"🗑️  Cleaning {existing_count} existing user(s)...")
                            TenantUser.objects.all().delete()
                        
                        # Create the company admin
                        admin_user = TenantUser.objects.create_user(
                            username=username,
                            email=admin_email,
                            password=admin_password,
                            first_name=form.cleaned_data.get('contact_person', '').split()[0] if form.cleaned_data.get('contact_person') else '',
                            last_name=' '.join(form.cleaned_data.get('contact_person', '').split()[1:]) if form.cleaned_data.get('contact_person') else '',
                            role='company_admin',
                            is_active=True,
                            is_superuser=False,
                            is_staff=False
                        )
                        print(f"✅ Company admin created: {admin_user.username}")
                        print(f"✅ Final user count in {tenant.schema_name}: {TenantUser.objects.count()}")
                    
                    # 🆕 UPDATED: Show tenant code in success message
                    messages.success(
                        request,
                        f'🎉 Tenant "{tenant.company_name}" created successfully!\n\n'
                        f'🎫 Tenant Access Code: {tenant_code}\n'
                        f'🌐 Login URL: https://{subdomain}.e2e-76-221.ssdcloudindia.net/company/login/\n'
                        f'👤 Username: {username}\n'
                        f'🔐 Password: {admin_password}\n\n'
                        f'⚠️ Save these credentials - they cannot be viewed again!'
                    )
                    print(f"✅ Tenant setup complete!\n")
                    
                    return redirect('systemadmin:tenant_detail', tenant_id=tenant.id)
                    
            except Exception as e:
                error_msg = f'Error creating tenant: {str(e)}'
                messages.error(request, error_msg)
                print(f"\n❌ {error_msg}")
                print(traceback.format_exc())
    else:
        form = TenantCreationForm()
    
    context = {
        'form': form,
        'page_title': 'Create New Tenant'
    }
    return render(request, 'systemadmin/tenant_create.html', context)

@system_admin_required
def tenant_detail_view(request, tenant_id):
    """
    View tenant details with company admin info
    """
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # Get company admin user from tenant schema
    company_admin = None
    with schema_context(tenant.schema_name):
        from accounts.models import User as TenantUser
        try:
            company_admin = TenantUser.objects.filter(role='company_admin').first()
        except:
            pass
    
    context = {
        'tenant': tenant,
        'company_admin': company_admin,
        'page_title': f'Tenant: {tenant.company_name}'
    }
    return render(request, 'systemadmin/tenant_detail.html', context)


@system_admin_required
def tenant_edit_view(request, tenant_id):
    """
    Edit existing tenant
    """
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    if request.method == 'POST':
        form = TenantEditForm(request.POST, instance=tenant)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, f'✅ Tenant "{tenant.company_name}" updated successfully!')
                return redirect('systemadmin:tenant_detail', tenant_id=tenant.id)
            except Exception as e:
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
    """
    Toggle tenant active/inactive status
    """
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # Prevent deactivating public schema
    if tenant.schema_name == 'public':
        messages.error(request, '❌ Cannot deactivate the public schema.')
        return redirect('systemadmin:system_dashboard')
    
    tenant.is_active = not tenant.is_active
    tenant.save()
    
    status = "activated" if tenant.is_active else "deactivated"
    icon = "✅" if tenant.is_active else "⚠️"
    messages.success(request, f'{icon} Tenant "{tenant.company_name}" {status} successfully!')
    
    return redirect('systemadmin:tenant_detail', tenant_id=tenant.id)


def system_logout_view(request):
    """
    Logout system administrator
    """
    logout(request)
    messages.success(request, '👋 You have been logged out successfully.')
    return redirect('systemadmin:system_login')