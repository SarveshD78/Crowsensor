# accounts/decorators.py - UPDATED FOR 3 ROLES ONLY

from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps


# =============================================================================
# HELPER FUNCTIONS (Internal use only)
# =============================================================================

def _check_tenant_subdomain(request):
    """Check if request is from tenant subdomain (not main domain)"""
    hostname = request.get_host().split(':')[0]
    parts = hostname.split('.')
    
    is_main_domain = (
        hostname in ['localhost', '127.0.0.1'] or 
        len(parts) == 1 or 
        parts[0] in ['www', '127']
    )
    
    return not is_main_domain  # True if on tenant subdomain


def _check_tenant_active(request):
    """Check if tenant is active"""
    return (
        hasattr(request, 'tenant') and 
        request.tenant is not None and 
        request.tenant.is_active
    )


def _get_redirect_for_role(user):
    """Get appropriate redirect URL based on user role"""
    if user.is_company_admin():
        return 'companyadmin:dashboard'
    elif user.is_department_admin():
        return 'departmentadmin:dashboard'
    elif user.is_user():  # ← Changed from is_operator()
        return 'userdashboard:user_home'  # ← Changed URL name
    else:
        return 'accounts:login'


# =============================================================================
# THE 3 ROLE-BASED DECORATORS (Removed sub_admin, operator)
# =============================================================================

def require_company_admin(view_func):
    """
    Company Admin ONLY (highest level).
    
    Allows: company_admin
    Blocks: department_admin, user
    
    Use for: Company-wide management, creating departments, creating dept admins
    
    Usage:
        @require_company_admin
        def dashboard_view(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # 1. Check authentication
        if not request.user.is_authenticated:
            messages.error(request, '🔒 Please login to continue.')
            return redirect('accounts:login')
        
        # 2. Check tenant subdomain
        if not _check_tenant_subdomain(request):
            messages.error(
                request, 
                '⛔ This page is only accessible from your company subdomain.'
            )
            return redirect('systemadmin:home')
        
        # 3. Check tenant is active
        if not _check_tenant_active(request):
            messages.error(
                request, 
                '⛔ Your company account has been deactivated. Contact support.'
            )
            from django.contrib.auth import logout
            logout(request)
            return redirect('accounts:login')
        
        # 4. Check role
        if not request.user.is_company_admin():
            messages.error(
                request, 
                '⛔ Access denied. Company Administrator privileges required.'
            )
            return redirect(_get_redirect_for_role(request.user))
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def require_department_admin(view_func):
    """
    Department Admin or higher.
    
    Allows: company_admin, department_admin
    Blocks: user
    
    Use for: Department management, creating users, assigning sensors
    
    Usage:
        @require_department_admin
        def dashboard_view(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # 1. Check authentication
        if not request.user.is_authenticated:
            messages.error(request, '🔒 Please login to continue.')
            return redirect('accounts:login')
        
        # 2. Check tenant subdomain
        if not _check_tenant_subdomain(request):
            messages.error(
                request, 
                '⛔ This page is only accessible from your company subdomain.'
            )
            return redirect('systemadmin:home')
        
        # 3. Check tenant is active
        if not _check_tenant_active(request):
            messages.error(
                request, 
                '⛔ Your company account has been deactivated. Contact support.'
            )
            from django.contrib.auth import logout
            logout(request)
            return redirect('accounts:login')
        
        # 4. Check role (department_admin OR company_admin)
        if not (request.user.is_department_admin() or request.user.is_company_admin()):
            messages.error(
                request, 
                '⛔ Access denied. Department Administrator privileges required.'
            )
            return redirect(_get_redirect_for_role(request.user))
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


# ✅ REMOVED require_sub_admin and require_operator decorators


def require_user(view_func):
    """
    Read-only User level (formerly operator).
    
    Allows: ALL roles (company_admin, department_admin, user)
    
    Use for: User dashboard, read-only views (3-4 graphs)
    
    Note: Users see limited data (read-only access)
    
    Usage:
        @require_user
        def user_home(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # 1. Check authentication
        if not request.user.is_authenticated:
            messages.error(request, '🔒 Please login to continue.')
            return redirect('accounts:login')
        
        # 2. Check tenant subdomain
        if not _check_tenant_subdomain(request):
            messages.error(
                request, 
                '⛔ This page is only accessible from your company subdomain.'
            )
            return redirect('systemadmin:home')
        
        # 3. Check tenant is active
        if not _check_tenant_active(request):
            messages.error(
                request, 
                '⛔ Your company account has been deactivated. Contact support.'
            )
            from django.contrib.auth import logout
            logout(request)
            return redirect('accounts:login')
        
        # 4. No role restriction - all roles allowed
        # Inside view, users see limited data (read-only)
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def require_login(view_func):
    """
    Any authenticated tenant user (all 3 roles).
    
    Allows: company_admin, department_admin, user (ALL)
    Blocks: Anonymous users
    
    Use for: Shared views like profile, logout, password change
    
    Usage:
        @require_login
        def profile_view(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # 1. Check authentication
        if not request.user.is_authenticated:
            messages.error(request, '🔒 Please login to continue.')
            return redirect('accounts:login')
        
        # 2. Check tenant subdomain
        if not _check_tenant_subdomain(request):
            messages.error(
                request, 
                '⛔ This page is only accessible from your company subdomain.'
            )
            return redirect('systemadmin:home')
        
        # 3. Check tenant is active
        if not _check_tenant_active(request):
            messages.error(
                request, 
                '⛔ Your company account has been deactivated. Contact support.'
            )
            from django.contrib.auth import logout
            logout(request)
            return redirect('accounts:login')
        
        # 4. No role check - ALL roles allowed
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


# =============================================================================
# DEPARTMENT-LEVEL ACCESS DECORATOR
# =============================================================================

def require_department_access(dept_id_param='department_id'):
    """
    Validates user has access to a specific department.
    
    MUST be used WITH @require_department_admin or @require_company_admin
    
    - Company admin: Always allowed (all departments)
    - Department admin: Only assigned departments
    
    Args:
        dept_id_param (str): Name of URL parameter or POST parameter containing department ID
    
    Usage:
        @require_department_admin
        @require_department_access(dept_id_param='department_id')
        def edit_department(request, department_id):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Company admin bypasses department check
            if request.user.is_company_admin():
                return view_func(request, *args, **kwargs)
            
            # Get department ID
            dept_id = kwargs.get(dept_id_param) or request.POST.get(dept_id_param)
            
            if not dept_id:
                messages.error(request, '⛔ Department ID is required.')
                return redirect('departmentadmin:dashboard')
            
            # Check if department admin has access
            if request.user.is_department_admin():
                from companyadmin.models import DepartmentMembership
                
                has_access = DepartmentMembership.objects.filter(
                    user=request.user,
                    department_id=dept_id,
                    is_active=True
                ).exists()
                
                if not has_access:
                    messages.error(
                        request, 
                        '⛔ You do not have permission to access this department.'
                    )
                    return redirect('departmentadmin:dashboard')
                
                return view_func(request, *args, **kwargs)
            
            # Other roles blocked
            messages.error(request, '⛔ Insufficient permissions.')
            return redirect(_get_redirect_for_role(request.user))
        
        return wrapper
    return decorator