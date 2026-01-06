from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from companyadmin.models import DepartmentMembership
def get_current_department(request):
    """
    🌍 GLOBAL HELPER: Get current active department for user
    
    Returns tuple: (department, all_memberships, show_switcher)
    
    Usage in views:
        dept, all_depts, show_switcher = get_current_department(request)
    
    Logic:
    1. Get all user's department memberships
    2. Check session for selected_department_id
    3. If valid, return that department
    4. If invalid/missing, return first department and store in session
    5. Return None if user has no departments
    """
    
    # Get all active memberships for this user
    memberships = DepartmentMembership.objects.filter(
        user=request.user,
        is_active=True,
        department__is_active=True
    ).select_related('department').order_by('department__name')
    
    if not memberships.exists():
        return None, [], False
    
    # Get selected department from session
    selected_dept_id = request.session.get('selected_department_id')
    
    current_dept = None
    
    if selected_dept_id:
        # Try to find the selected department in user's memberships
        try:
            dept_membership = memberships.get(department_id=selected_dept_id)
            current_dept = dept_membership.department
        except DepartmentMembership.DoesNotExist:
            # Invalid selection - clear session
            request.session.pop('selected_department_id', None)
            request.session.pop('selected_department_name', None)
    
    # If no valid selection, use first department
    if not current_dept:
        first_membership = memberships.first()
        current_dept = first_membership.department
        # Store in session
        request.session['selected_department_id'] = current_dept.id
        request.session['selected_department_name'] = current_dept.name
    
    # Prepare return data
    all_departments = [m.department for m in memberships]
    show_switcher = len(all_departments) > 1
    
    return current_dept, all_departments, show_switcher


def get_department_or_redirect(request, redirect_url='departmentadmin:dashboard'):
    """
    🌍 GLOBAL HELPER: Get department or redirect with error message
    
    Usage in views:
        dept, all_depts, show_switcher = get_department_or_redirect(request)
        if not dept:
            return dept  # This will be the redirect response
    
    Returns:
    - If user has departments: (department, all_departments, show_switcher)
    - If user has NO departments: redirect response
    """
    
    dept, all_depts, show_switcher = get_current_department(request)
    
    if not dept:
        messages.error(request, '⛔ You are not assigned to any department.')
        return redirect(redirect_url), None, None
    
    return dept, all_depts, show_switcher

