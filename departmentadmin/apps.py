"""
departmentadmin/apps.py

Django app configuration with tenant-specific alert monitoring initialization.
"""

import atexit
import logging
import sys

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class DepartmentadminConfig(AppConfig):
    """Department Administration app configuration."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'departmentadmin'
    verbose_name = 'Department Administration'

    def ready(self):
        """
        Initialize tenant-specific alert monitoring schedulers.
        
        Each tenant gets its own 30-second alert monitoring cycle.
        """
        # Skip during migrations and other management commands
        skip_commands = ['migrate', 'makemigrations', 'createsuperuser', 'collectstatic']
        if any(cmd in sys.argv for cmd in skip_commands):
            logger.debug(f"Skipping alert monitoring during {sys.argv[1]}")
            return
        
        # Only start schedulers when running the actual server
        if 'runserver' not in sys.argv and 'gunicorn' not in sys.argv[0]:
            return
        
        self._initialize_alert_monitoring()
    
    def _initialize_alert_monitoring(self):
        """Initialize the background alert monitoring system."""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from django_tenants.utils import get_tenant_model, get_public_schema_name
            
            from departmentadmin.alert_func import check_tenant_sensors_for_alerts
            
            logger.info("Initializing tenant-specific alert monitoring system...")
            
            # Get all active tenants
            TenantModel = get_tenant_model()
            public_schema = get_public_schema_name()
            
            tenants = TenantModel.objects.exclude(
                schema_name=public_schema
            ).filter(is_active=True)
            
            tenant_count = tenants.count()
            
            if tenant_count == 0:
                logger.warning("No active tenants found - alert monitoring not started")
                return
            
            logger.info(f"Found {tenant_count} active tenant(s)")
            
            # Create one scheduler for all tenants
            scheduler = BackgroundScheduler(timezone='Asia/Kolkata')
            
            # Add a job for each tenant
            for tenant in tenants:
                job_id = f'alert_monitoring_{tenant.schema_name}'
                
                scheduler.add_job(
                    check_tenant_sensors_for_alerts,
                    'interval',
                    seconds=30,
                    args=[tenant.schema_name],
                    id=job_id,
                    max_instances=1,
                    replace_existing=True,
                    coalesce=True,
                    misfire_grace_time=60
                )
                
                logger.info(f"Scheduled alerts for tenant: {tenant.schema_name}")
            
            # Start the scheduler
            scheduler.start()
            
            logger.info("=" * 80)
            logger.info("ALERT MONITORING SYSTEM STARTED")
            logger.info("=" * 80)
            logger.info(f"Monitoring {tenant_count} tenant(s)")
            logger.info("Checking sensors every 30 seconds per tenant")
            logger.info("Escalation timeline: Initial (0-60m), Medium (60-90m), High (90+m)")
            logger.info("=" * 80)
            
            # Register graceful shutdown
            def shutdown_scheduler():
                logger.info("Shutting down alert monitoring system...")
                scheduler.shutdown(wait=False)
                logger.info("Alert monitoring stopped")
            
            atexit.register(shutdown_scheduler)
            
        except ImportError as e:
            logger.error(f"Import error: {e}")
            logger.error("Please install: pip install apscheduler django-tenants")
            logger.error("Alert monitoring will not start.")
            
        except Exception as e:
            logger.error(f"Error starting alert monitoring: {e}", exc_info=True)