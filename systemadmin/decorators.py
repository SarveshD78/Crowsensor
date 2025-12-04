from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps

# TENANT: Decorator to protect system admin views using Django's built-in superuser

def system_admin_required(view_func):
    """
    Decorator to ensure only authenticated superusers can access the view
    Uses Django's built-in User model with is_superuser=True
    
    SECURITY: Also blocks access from tenant subdomains
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # STEP 1: Block tenant subdomains (but allow IP addresses)
        hostname = request.get_host().split(':')[0]
        parts = hostname.split('.')
        
        # Check if it's an IP address (4 numeric parts)
        is_ip_address = len(parts) == 4 and all(part.isdigit() for part in parts)
        
        # Check if we're on a subdomain (tenant context) - but NOT an IP
        is_subdomain = len(parts) > 1 and not is_ip_address and parts[0] not in ['www', 'localhost', '127']
        
        if is_subdomain:
            # BLOCKED: Tenant subdomain trying to access system admin
            print(f"🚫 BLOCKED: System admin access attempted from tenant subdomain: {hostname}")
            messages.error(request, 'System admin is not accessible from this domain.')
            return redirect('accounts:login')  # Redirect to tenant login
        
        # STEP 2: Check if user is authenticated
        if not request.user.is_authenticated:
            messages.error(request, 'Please login as System Administrator to access this page.')
            return redirect('systemadmin:system_login')
        
        # STEP 3: Check if user is superuser
        if not request.user.is_superuser:
            messages.error(request, 'Access denied. System Administrator privileges required.')
            return redirect('systemadmin:system_login')
        
        # User is authenticated superuser on main domain - allow access
        return view_func(request, *args, **kwargs)
    
    return wrapper


def main_domain_only(view_func):
    """
    Decorator to block access from tenant subdomains
    Use for public system admin pages (like login page)
    Allows access from IP addresses
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Get hostname
        hostname = request.get_host().split(':')[0]
        parts = hostname.split('.')
        
        # Check if it's an IP address (4 numeric parts like 164.52.207.221)
        is_ip_address = len(parts) == 4 and all(part.isdigit() for part in parts)
        
        # Check if we're on a subdomain (tenant context) - but NOT an IP
        is_subdomain = len(parts) > 1 and not is_ip_address and parts[0] not in ['www', 'localhost', '127']
        
        if is_subdomain:
            # BLOCKED: Tenant subdomain trying to access system admin
            print(f"🚫 BLOCKED: System admin access attempted from tenant subdomain: {hostname}")
            messages.error(request, 'System admin is not accessible from this domain.')
            return redirect('accounts:login')  # Redirect to tenant login
        
        # Allow access from main domain or IP address
        print(f"✅ ALLOWED: System admin access from: {hostname}")
        return view_func(request, *args, **kwargs)
    
    return wrapper