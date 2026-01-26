"""
accounts/backends.py

Custom authentication backend for multi-tenant system.
Authenticates users within their tenant schema context.
"""

import logging

from django.contrib.auth.backends import BaseBackend
from django.db import connection

# Logger for authentication debugging
logger = logging.getLogger(__name__)


class TenantBackend(BaseBackend):
    """
    Custom authentication backend for tenant users.
    
    Authenticates users within their tenant schema. This backend is skipped
    for public schema requests (system admin uses Django's ModelBackend).
    
    Flow:
        1. Check if request has tenant context
        2. Skip if public schema (system admin login)
        3. Authenticate user within tenant schema
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate user within tenant schema.
        
        Args:
            request: HTTP request object with tenant context
            username: Username to authenticate
            password: Password to verify
            **kwargs: Additional authentication parameters
            
        Returns:
            User instance if authentication successful, None otherwise
        """
        # Skip if no tenant context
        if not hasattr(request, 'tenant') or request.tenant is None:
            return None
        
        # Skip if public schema (system admin uses ModelBackend)
        if connection.schema_name == 'public':
            return None
        
        logger.debug(f"Authenticating user: {username} in schema: {connection.schema_name}")
        
        # Import here to use tenant's User model
        from accounts.models import User
        
        try:
            user = User.objects.get(username=username)
            
            if user.check_password(password):
                logger.debug(f"Authentication successful for: {username}")
                return user
            else:
                logger.debug(f"Invalid password for: {username}")
                return None
                
        except User.DoesNotExist:
            logger.debug(f"User not found: {username}")
            return None
    
    def get_user(self, user_id):
        """
        Retrieve user by ID within tenant schema.
        
        Required by Django authentication framework.
        
        Args:
            user_id: Primary key of user
            
        Returns:
            User instance if found, None otherwise
        """
        # Skip if public schema
        if connection.schema_name == 'public':
            return None
        
        from accounts.models import User
        
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None