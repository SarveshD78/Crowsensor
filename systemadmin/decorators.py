"""
systemadmin/decorators.py

Access control decorators for system admin routes.
Ensures only superusers can access system administration from main domain.
"""

import logging
from functools import wraps

from django.shortcuts import redirect
from django.contrib import messages

logger = logging.getLogger(__name__)


def _is_main_domain(hostname):
    """
    Check if hostname is the main domain (not a tenant subdomain).
    
    Args:
        hostname: Request hostname without port
        
    Returns:
        bool: True if main domain, False if tenant subdomain
    """
    parts = hostname.split('.')
    
    # Check if it's an IP address (4 numeric parts like 164.52.207.221)
    is_ip_address = len(parts) == 4 and all(part.isdigit() for part in parts)
    
    # Main domain conditions
    main_domains = ['e2e-75-221.ssdcloudindia.net', 'localhost', '127.0.0.1']
    is_main = hostname in main_domains or is_ip_address
    
    return is_main


def _is_tenant_subdomain(hostname):
    """
    Check if hostname is a tenant subdomain.
    
    Args:
        hostname: Request hostname without port
        
    Returns:
        bool: True if tenant subdomain, False otherwise
    """
    parts = hostname.split('.')
    
    # Subdomain: more than 3 parts AND not main domain
    return len(parts) > 3 and not _is_main_domain(hostname)


def system_admin_required(view_func):
    """
    Decorator to ensure only authenticated superusers can access the view.
    
    Security checks:
    1. Blocks access from tenant subdomains
    2. Requires authentication
    3. Requires is_superuser=True
    
    Usage:
        @system_admin_required
        def system_dashboard_view(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        hostname = request.get_host().split(':')[0]
        
        # Block tenant subdomains
        if _is_tenant_subdomain(hostname):
            logger.warning(f"System admin access blocked from subdomain: {hostname}")
            messages.error(request, 'System admin is not accessible from this domain.')
            return redirect('accounts:login')
        
        # Check authentication
        if not request.user.is_authenticated:
            messages.error(
                request,
                'Please login as System Administrator to access this page.'
            )
            return redirect('systemadmin:system_login')
        
        # Check superuser status
        if not request.user.is_superuser:
            messages.error(
                request,
                'Access denied. System Administrator privileges required.'
            )
            return redirect('systemadmin:system_login')
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def main_domain_only(view_func):
    """
    Decorator to block access from tenant subdomains.
    
    Use for public system admin pages (like login page).
    Allows access from main domain only.
    
    Usage:
        @main_domain_only
        def system_login_view(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        hostname = request.get_host().split(':')[0]
        
        # Block tenant subdomains
        if _is_tenant_subdomain(hostname):
            logger.warning(f"Main domain page access blocked from subdomain: {hostname}")
            messages.error(request, 'System admin is not accessible from this domain.')
            return redirect('accounts:login')
        
        logger.debug(f"Main domain access allowed from: {hostname}")
        return view_func(request, *args, **kwargs)
    
    return wrapper