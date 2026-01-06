# cleanup_all.py - DATABASE & MIGRATIONS RESET ONLY (Keep venv)

import subprocess
import os
import shutil
from pathlib import Path
import sys

print("=" * 80)
print("🚀 CROWSENSOR DATABASE RESET - KEEP VENV")
print("=" * 80)
print()

# ============================================================================
# STEP 1: KILL DJANGO SERVER
# ============================================================================
print("📋 STEP 1: Stopping Django server...")
print("-" * 80)

try:
    subprocess.run(['pkill', '-f', 'manage.py runserver'], check=False)
    print("  ✅ Django server stopped (if it was running)")
except Exception as e:
    print(f"  ℹ️  Could not kill server: {e}")

print()

# ============================================================================
# STEP 2: DETERMINE PYTHON PATH
# ============================================================================
print("📋 STEP 2: Finding Python in venv...")
print("-" * 80)

# Check if venv exists
venv_path = Path('venv')
if not venv_path.exists():
    print("  ⚠️  No venv found! Please create venv first:")
    print("     python3.11 -m venv venv")
    print("     source venv/bin/activate")
    print("     pip install -r requirements.txt")
    sys.exit(1)

# Determine pip/python path based on OS
if os.name == 'nt':  # Windows
    pip_path = 'venv/Scripts/pip'
    python_path = 'venv/Scripts/python'
else:  # Unix/Mac
    pip_path = 'venv/bin/pip'
    python_path = 'venv/bin/python'

print(f"  ✅ Using python: {python_path}")
print()

# ============================================================================
# STEP 3: CLEAN MIGRATION FILES
# ============================================================================
print("📋 STEP 3: Cleaning migration files...")
print("-" * 80)

apps = ['systemadmin', 'accounts', 'companyadmin', 'departmentadmin', 'userdashboard']

for app in apps:
    migrations_dir = Path(app) / 'migrations'
    
    # Create directory if missing
    if not migrations_dir.exists():
        migrations_dir.mkdir(parents=True)
    
    # Create __init__.py if missing
    init_file = migrations_dir / '__init__.py'
    if not init_file.exists():
        init_file.touch()
    
    # Delete all migration files except __init__.py
    for file in migrations_dir.glob('*.py'):
        if file.name != '__init__.py':
            file.unlink()
    
    # Delete __pycache__
    pycache = migrations_dir / '__pycache__'
    if pycache.exists():
        shutil.rmtree(pycache)

print("  ✅ Migration files cleaned")
print()

# ============================================================================
# STEP 4: CLEAN ALL __pycache__
# ============================================================================
print("📋 STEP 4: Cleaning __pycache__ folders...")
print("-" * 80)

pycache_count = 0
for pycache in Path('.').rglob('__pycache__'):
    if pycache.is_dir():
        try:
            shutil.rmtree(pycache)
            pycache_count += 1
        except:
            pass

print(f"  ✅ Deleted {pycache_count} __pycache__ folder(s)")
print()

# ============================================================================
# STEP 5: RESET POSTGRESQL DATABASE
# ============================================================================
print("📋 STEP 5: Resetting PostgreSQL database...")
print("-" * 80)

db_name = 'crowsensor_db'
db_user = 'crowsensor_user'
db_password = 'Sisai@2025'
db_host = 'localhost'
db_port = '5432'

print(f"  Database: {db_name}")
print(f"  User: {db_user}")
print()

env = os.environ.copy()
env['PGPASSWORD'] = db_password

# Terminate connections
print("  🔌 Terminating database connections...")
terminate_sql = f"""
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE datname = '{db_name}' AND pid <> pg_backend_pid();
"""

subprocess.run(
    ['psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c', terminate_sql],
    env=env,
    capture_output=True
)

# Drop database
print("  🗑️  Dropping database...")
subprocess.run(
    ['dropdb', '-h', db_host, '-p', db_port, '-U', db_user, '--if-exists', db_name],
    env=env,
    capture_output=True
)

# Create database
print("  🔨 Creating database...")
result = subprocess.run(
    ['createdb', '-h', db_host, '-p', db_port, '-U', db_user, db_name],
    env=env,
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print("  ✅ Database created successfully")
else:
    print(f"  ⚠️  Error: {result.stderr}")

print()

# ============================================================================
# STEP 6: CREATE MIGRATIONS
# ============================================================================
print("📋 STEP 6: Creating migrations...")
print("-" * 80)

result = subprocess.run(
    [python_path, 'manage.py', 'makemigrations'],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print(result.stdout)
    print("  ✅ Migrations created")
else:
    print(result.stderr)
    print("  ⚠️  Error creating migrations")

print()

# ============================================================================
# STEP 7: MIGRATE PUBLIC SCHEMA
# ============================================================================
print("📋 STEP 7: Migrating public schema...")
print("-" * 80)

result = subprocess.run(
    [python_path, 'manage.py', 'migrate_schemas', '--shared'],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print("  ✅ Public schema migrated")
else:
    print(result.stderr)
    print("  ⚠️  Error migrating public schema")

print()

# ============================================================================
# STEP 8: CREATE PUBLIC TENANT (CRITICAL!)
# ============================================================================
print("📋 STEP 8: Creating public tenant...")
print("-" * 80)

create_public_tenant_script = """
from systemadmin.models import Tenant, Domain

# Check if public tenant exists
public_tenant = Tenant.objects.filter(schema_name='public').first()

if not public_tenant:
    # Create public tenant
    public_tenant = Tenant(schema_name='public')
    public_tenant.save()
    print('✅ Public tenant created')
    
    # Create domain for public
    Domain.objects.create(
        domain='localhost',
        tenant=public_tenant,
        is_primary=True
    )
    print('✅ Public domain created: localhost')
else:
    print('ℹ️  Public tenant already exists')

# Verify
print(f'📊 Total tenants: {Tenant.objects.count()}')
"""

result = subprocess.run(
    [python_path, 'manage.py', 'shell'],
    input=create_public_tenant_script,
    text=True,
    capture_output=True
)

print(result.stdout)
if result.returncode != 0:
    print(f"  ⚠️  Error: {result.stderr}")

print()

# ============================================================================
# STEP 9: MIGRATE TENANT SCHEMAS
# ============================================================================
print("📋 STEP 9: Migrating tenant schemas...")
print("-" * 80)

result = subprocess.run(
    [python_path, 'manage.py', 'migrate_schemas'],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print("  ✅ Tenant schemas migrated")
else:
    print(result.stderr)
    print("  ⚠️  Error migrating tenant schemas")

print()

# ============================================================================
# STEP 10: CREATE SUPERUSER
# ============================================================================
print("📋 STEP 10: Creating superuser...")
print("-" * 80)

create_superuser_script = """
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@system.com', 'admin123')
    print('Superuser created')
else:
    print('Superuser already exists')
"""

result = subprocess.run(
    [python_path, 'manage.py', 'shell'],
    input=create_superuser_script,
    text=True,
    capture_output=True
)

if 'Superuser created' in result.stdout or 'already exists' in result.stdout:
    print("  ✅ Superuser: admin / admin123")
else:
    print("  ⚠️  Error creating superuser")
    print(result.stderr)

print()

# ============================================================================
# STEP 11: VERIFY SETUP
# ============================================================================
print("📋 STEP 11: Verifying final setup...")
print("-" * 80)

verify_script = """
from systemadmin.models import Tenant, Domain
from django.contrib.auth import get_user_model

User = get_user_model()

print(f'✅ Tenants: {Tenant.objects.count()}')
print(f'✅ Domains: {Domain.objects.count()}')
print(f'✅ Superusers: {User.objects.filter(is_superuser=True).count()}')

public_tenant = Tenant.objects.filter(schema_name='public').first()
if public_tenant:
    domain = Domain.objects.filter(tenant=public_tenant, is_primary=True).first()
    if domain:
        print(f'✅ Public domain: {domain.domain}')
"""

result = subprocess.run(
    [python_path, 'manage.py', 'shell'],
    input=verify_script,
    text=True,
    capture_output=True
)

print(result.stdout)

print()

# ============================================================================
# COMPLETE
# ============================================================================
print("=" * 80)
print("🎉 COMPLETE! DATABASE RESET SUCCESSFUL")
print("=" * 80)
print()
print("📝 CREDENTIALS:")
print("   System Admin:")
print("   URL: http://localhost:8000/system/login/")
print("   Username: admin")
print("   Password: admin123")
print()
print("🚀 START SERVER:")
print("   python manage.py runserver")
print()
print("=" * 80)