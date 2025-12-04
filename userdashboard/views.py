# userdashboard/views.py - USER DASHBOARD (READ-ONLY)

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import logout
from accounts.decorators import require_user
from companyadmin.models import DepartmentMembership


# =============================================================================
# AUTHENTICATION
# =============================================================================

@require_user
def logout_view(request):
    """Logout user"""
    username = request.user.get_full_name_or_username()
    logout(request)
    messages.success(request, f'👋 Goodbye {username}! You have been logged out successfully.')
    return redirect('accounts:login')


# =============================================================================
# DASHBOARD
# =============================================================================

@require_user
def user_home_view(request):
    """
    User Dashboard (Read-Only)
    Shows departments assigned to this user
    No management capabilities - view only
    """
    
    # Get user's assigned departments
    user_departments = DepartmentMembership.objects.filter(
        user=request.user,
        is_active=True
    ).select_related('department').filter(
        department__is_active=True
    )
    
    # Stats
    total_departments = user_departments.count()
    
    context = {
        'user_departments': user_departments,
        'total_departments': total_departments,
        'user_role': request.user.get_role_display(),
        'page_title': 'User Dashboard',
    }
    
    return render(request, 'userdashboard/dashboard.html', context)
