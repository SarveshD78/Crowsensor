# departmentadmin/apps.py

import sys
from django.apps import AppConfig


class DepartmentadminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'departmentadmin'
    verbose_name = 'Department Administration'

    def ready(self):
        """
        Initialize tenant-specific alert monitoring schedulers
        Each tenant gets its own 30-second alert monitoring cycle
        """
        
        # Skip during migrations and other management commands
        if any(cmd in sys.argv for cmd in ['migrate', 'makemigrations', 'createsuperuser', 'collectstatic']):
            print(f"⏭️  Skipping alert monitoring during {sys.argv[1]}")
            return
        
        # Only start schedulers when running the actual server
        if 'runserver' not in sys.argv and 'gunicorn' not in sys.argv[0]:
            return
        
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from django_tenants.utils import get_tenant_model, get_public_schema_name
            from departmentadmin.alert_func import check_tenant_sensors_for_alerts
            import atexit
            
            print("\n🔄 Initializing tenant-specific alert monitoring system...")
            
            # Get all active tenants
            TenantModel = get_tenant_model()
            public_schema = get_public_schema_name()
            
            # Get all tenants except public schema
            tenants = TenantModel.objects.exclude(schema_name=public_schema).filter(is_active=True)
            
            tenant_count = tenants.count()
            
            if tenant_count == 0:
                print("⚠️  No active tenants found - alert monitoring not started")
                return
            
            print(f"📊 Found {tenant_count} active tenant(s)")
            
            # Create one scheduler for all tenants
            scheduler = BackgroundScheduler(timezone='Asia/Kolkata')
            
            # Add a job for each tenant
            for tenant in tenants:
                job_id = f'alert_monitoring_{tenant.schema_name}'
                
                scheduler.add_job(
                    check_tenant_sensors_for_alerts,
                    'interval',
                    seconds=30,
                    args=[tenant.schema_name],  # Pass tenant schema name
                    id=job_id,
                    max_instances=1,
                    replace_existing=True,
                    coalesce=True,
                    misfire_grace_time=60
                )
                
                print(f"   ✅ Scheduled alerts for tenant: {tenant.schema_name}")
            
            # Start the scheduler
            scheduler.start()
            
            print("\n" + "="*80)
            print("✅ ALERT MONITORING SYSTEM STARTED")
            print("="*80)
            print(f"📊 Monitoring {tenant_count} tenant(s)")
            print(f"⏰ Checking sensors every 30 seconds per tenant")
            print(f"🔄 Escalation timeline:")
            print(f"   - Initial: 0-60 minutes")
            print(f"   - Medium: 60-90 minutes")
            print(f"   - High: 90+ minutes")
            print("="*80 + "\n")
            
            # Graceful shutdown
            def shutdown_scheduler():
                print("\n🛑 Shutting down alert monitoring system...")
                scheduler.shutdown(wait=False)
                print("✅ Alert monitoring stopped\n")
            
            atexit.register(shutdown_scheduler)
            
        except ImportError as e:
            print(f"\n❌ IMPORT ERROR: {e}")
            print("Please install: pip install apscheduler django-tenants")
            print("Alert monitoring will not start.\n")
            
        except Exception as e:
            print(f"\n❌ ERROR starting alert monitoring: {e}")
            import traceback
            traceback.print_exc()
            print()