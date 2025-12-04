from django.contrib.auth.backends import BaseBackend
from django.db import connection


class TenantBackend(BaseBackend):
    """
    Custom authentication backend for tenant users
    Authenticates users within their tenant schema
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        # Skip if no tenant or if in public schema (system admin login)
        if not hasattr(request, 'tenant') or request.tenant is None:
            return None
        
        # Skip if public schema (system admin uses ModelBackend)
        if connection.schema_name == 'public':
            return None
        
        print(f"🔍 TenantBackend called for: {username}")
        
        # Import here to use tenant's User model
        from accounts.models import User
        
        try:
            user = User.objects.get(username=username)
            print(f"🔍 Found user: {user.username}")
            
            if user.check_password(password):
                print(f"🔍 Password correct!")
                return user
            else:
                print(f"🔍 Password incorrect!")
                return None
                
        except User.DoesNotExist:
            print(f"🔍 User not found in schema: {connection.schema_name}")
            return None
    
    def get_user(self, user_id):
        """Required method"""
        # Skip if in public schema
        if connection.schema_name == 'public':
            return None
            
        from accounts.models import User
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None