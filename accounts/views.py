# accounts/views.py - FIXED WITH SUBDOMAIN CHECK (NO TENANT DECORATOR ON LOGIN)

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from .decorators import require_login


def login_view(request):
    """
    Tenant user login view - PUBLIC page but MUST be on tenant subdomain
    Accessed via: subdomain.localhost:8000/accounts/login/
    
    CRITICAL: No decorator - this is a public page
    BUT: Manual subdomain check to block main domain
    
    Redirects based on role after successful login:
    - company_admin → companyadmin/dashboard/
    - department_admin → departmentadmin/dashboard/
    - user → userdashboard/user/ (formerly operator)
    """
    
    # STEP 1: Manual subdomain check (block main domain)
    hostname = request.get_host().split(':')[0]
    parts = hostname.split('.')
    
    is_main_domain = (
        hostname in ['localhost', '127.0.0.1'] or 
        len(parts) == 1 or 
        parts[0] in ['www', '127']
    )
    
    if is_main_domain:
        # Blocked: Trying to access tenant login from main domain
        messages.error(
            request, 
            '⛔ Please use your company-specific login link. '
            'If you don\'t have one, enter your company code on the home page.'
        )
        return redirect('systemadmin:home')
    
    # STEP 2: If already logged in, redirect to appropriate dashboard
    if request.user.is_authenticated:
        if request.user.is_company_admin():
            return redirect('companyadmin:dashboard')
        elif request.user.is_department_admin():
            return redirect('departmentadmin:dashboard')
        elif request.user.is_user():  # ← Changed from is_operator()
            return redirect('userdashboard:user_home')  # ← Changed URL name
    
    # STEP 3: Handle login form submission
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        
        if not username or not password:
            messages.error(request, '⛔ Please enter both username and password.')
            context = {'page_title': 'Login'}
            return render(request, 'accounts/login.html', context)
        
        # Authenticate user
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            # Check if user is active
            if not user.is_active:
                messages.error(
                    request, 
                    '⛔ Your account has been deactivated. Contact your administrator.'
                )
                context = {'page_title': 'Login'}
                return render(request, 'accounts/login.html', context)
            
            # Check if tenant is active
            if hasattr(request, 'tenant') and request.tenant:
                if not request.tenant.is_active:
                    messages.error(
                        request, 
                        '⛔ Your company account has been deactivated. Contact support.'
                    )
                    context = {'page_title': 'Login'}
                    return render(request, 'accounts/login.html', context)
            
            # Login successful
            login(request, user)
            messages.success(
                request, 
                f'✅ Welcome back, {user.get_full_name_or_username()}!'
            )
            
            # ✅ UPDATED: Role-based redirect (removed sub_admin, changed operator to user)
            if user.is_company_admin():
                return redirect('companyadmin:dashboard')
            elif user.is_department_admin():
                return redirect('departmentadmin:dashboard')
            elif user.is_user():  # ← Changed from is_operator()
                return redirect('userdashboard:user_home')  # ← Changed URL name
            else:
                # Fallback (shouldn't happen)
                messages.error(request, '⛔ Invalid user role.')
                logout(request)
                return redirect('accounts:login')
        
        else:
            # Authentication failed
            messages.error(request, '⛔ Invalid username or password.')
    
    # STEP 4: Show login form
    context = {
        'page_title': 'Login',
        'tenant': request.tenant if hasattr(request, 'tenant') else None
    }
    return render(request, 'accounts/login.html', context)


@require_login
def logout_view(request):
    """
    Logout tenant user
    Available to all roles
    
    Uses @require_login decorator (includes subdomain + tenant checks)
    """
    username = request.user.get_full_name_or_username()
    logout(request)
    messages.success(request, f'👋 Goodbye {username}! You have been logged out successfully.')
    return redirect('accounts:login')