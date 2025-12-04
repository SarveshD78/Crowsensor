from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps

def system_admin_required(view_func):
    """
    Decorator to ensure only authenticated superusers can access the view
    Uses Django's built-in User model with is_superuser=True
    
    SECURITY: Also blocks access from tenant subdomains
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # STEP 1: Block tenant subdomains (but allow main domain)
        hostname = request.get_host().split(':')[0]
        parts = hostname.split('.')
        
        # Check if it's an IP address (4 numeric parts)
        is_ip_address = len(parts) == 4 and all(part.isdigit() for part in parts)
        
        # Check if this is the main domain
        is_main_domain = hostname in ['e2e-75-221.ssdcloudindia.net', 'localhost', '127.0.0.1'] or is_ip_address
        
        # Subdomain detection: more than 3 parts AND not main domain
        is_subdomain = len(parts) > 3 and not is_main_domain
        
        if is_subdomain:
            # BLOCKED: Tenant subdomain trying to access system admin
            print(f"🚫 BLOCKED: System admin access attempted from tenant subdomain: {hostname}")
            messages.error(request, 'System admin is not accessible from this domain.')
            return redirect('accounts:login')
        
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
    Allows access from main domain
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Get hostname
        hostname = request.get_host().split(':')[0]
        parts = hostname.split('.')
        
        # Check if it's an IP address (4 numeric parts)
        is_ip_address = len(parts) == 4 and all(part.isdigit() for part in parts)
        
        # Check if this is the main domain
        is_main_domain = hostname in ['e2e-75-221.ssdcloudindia.net', 'localhost', '127.0.0.1'] or is_ip_address
        
        # Subdomain detection: more than 3 parts AND not main domain
        is_subdomain = len(parts) > 3 and not is_main_domain
        
        if is_subdomain:
            # BLOCKED: Tenant subdomain trying to access system admin
            print(f"🚫 BLOCKED: System admin access attempted from tenant subdomain: {hostname}")
            messages.error(request, 'System admin is not accessible from this domain.')
            return redirect('accounts:login')
        
        # Allow access from main domain
        print(f"✅ ALLOWED: System admin access from: {hostname}")
        return view_func(request, *args, **kwargs)
    
    return wrapper