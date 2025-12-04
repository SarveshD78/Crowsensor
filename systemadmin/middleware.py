from django.utils.deprecation import MiddlewareMixin

class SystemAdminBypassMiddleware(MiddlewareMixin):
    """
    Bypass tenant resolution for system admin URLs and static files.
    
    This middleware MUST be placed BEFORE TenantMainMiddleware in settings.
    It allows system admin routes (/system/) to work without requiring a tenant subdomain.
    
    Why needed:
    - System admin login at localhost:8000/system/login/ has no subdomain
    - TenantMainMiddleware would fail trying to find a tenant
    - This middleware marks these paths to skip tenant resolution
    """
    
    def process_request(self, request):
        """
        Check if the request path should bypass tenant resolution
        """
        path = request.path_info
        
        # URLs that don't require tenant resolution
        bypass_paths = [
            '/system/',   # System admin routes (login, dashboard, tenant management)
            '/admin/',    # Django admin panel
            '/static/',   # Static files (CSS, JS, images)
            '/media/',    # Uploaded media files
        ]
        
        # Check if current path should bypass tenant middleware
        for bypass_path in bypass_paths:
            if path.startswith(bypass_path):
                # Mark this request as not needing tenant
                request.tenant = None
                request.urlconf = None
                
                # Optional: Add debug flag
                request.bypass_tenant = True
                
                break
        
        # Continue to next middleware
        return None