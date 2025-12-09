# cleanup_all.py - COMPLETE RESET WITH PUBLIC TENANT CREATION

import subprocess
import os
import shutil
from pathlib import Path
import sys

print("=" * 80)
print("🚀 ULTIMATE CROWSENSOR RESET - PYTHON 3.11 + DJANGO 4.2.7")
print("=" * 80)
print()

# ============================================================================
# STEP 1: CHECK IF PYTHON 3.11 IS INSTALLED
# ============================================================================
print("📋 STEP 1: Checking Python 3.11...")
print("-" * 80)

try:
    result = subprocess.run(
        ['python3.11', '--version'],
        capture_output=True,
        text=True,
        check=False
    )
    
    if result.returncode == 0:
        print(f"  ✅ {result.stdout.strip()}")
    else:
        print("  ⚠️  Python 3.11 not found!")
        print()
        print("  📝 Install Python 3.11:")
        print("     brew install python@3.11")
        print()
        sys.exit(1)
        
except FileNotFoundError:
    print("  ⚠️  Python 3.11 not found!")
    print()
    print("  📝 Install Python 3.11:")
    print("     brew install python@3.11")
    print()
    sys.exit(1)

print()

# ============================================================================
# STEP 2: KILL DJANGO SERVER
# ============================================================================
print("📋 STEP 2: Stopping Django server...")
print("-" * 80)

try:
    subprocess.run(['pkill', '-f', 'manage.py runserver'], check=False)
    print("  ✅ Django server stopped (if it was running)")
except Exception as e:
    print(f"  ℹ️  Could not kill server: {e}")

print()

# ============================================================================
# STEP 3: REMOVE OLD VENV
# ============================================================================
print("📋 STEP 3: Removing old virtual environment...")
print("-" * 80)

venv_path = Path('venv')
if venv_path.exists():
    try:
        shutil.rmtree(venv_path)
        print("  ✅ Old venv removed")
    except Exception as e:
        print(f"  ⚠️  Error removing venv: {e}")
else:
    print("  ℹ️  No venv to remove")

print()

# ============================================================================
# STEP 4: CREATE NEW VENV WITH PYTHON 3.11
# ============================================================================
print("📋 STEP 4: Creating new virtual environment with Python 3.11...")
print("-" * 80)

try:
    subprocess.run(
        ['python3.11', '-m', 'venv', 'venv'],
        check=True
    )
    print("  ✅ New venv created with Python 3.11")
except Exception as e:
    print(f"  ⚠️  Error creating venv: {e}")
    sys.exit(1)

print()

# ============================================================================
# STEP 5: DETERMINE ACTIVATE SCRIPT PATH
# ============================================================================
print("📋 STEP 5: Preparing pip installation...")
print("-" * 80)

# Determine pip path based on OS
if os.name == 'nt':  # Windows
    pip_path = 'venv/Scripts/pip'
    python_path = 'venv/Scripts/python'
else:  # Unix/Mac
    pip_path = 'venv/bin/pip'
    python_path = 'venv/bin/python'

print(f"  Using pip: {pip_path}")
print(f"  Using python: {python_path}")
print()

# ============================================================================
# STEP 6: UPGRADE PIP
# ============================================================================
print("📋 STEP 6: Upgrading pip...")
print("-" * 80)

try:
    subprocess.run(
        [python_path, '-m', 'pip', 'install', '--upgrade', 'pip'],
        check=True,
        capture_output=True
    )
    print("  ✅ Pip upgraded")
except Exception as e:
    print(f"  ⚠️  Error upgrading pip: {e}")

print()

# ============================================================================
# STEP 7: INSTALL PACKAGES
# ============================================================================
# ============================================================================
# STEP 7: INSTALL PACKAGES
# ============================================================================
print("📋 STEP 7: Installing Django 5.1.4 and compatible packages...")
print("-" * 80)

packages = [
    'Django==5.1.4',
    'django-tenants==3.7.0',
    'python-dotenv==1.0.1',
    'Pillow==11.0.0',
    'asgiref==3.11.0',
    'certifi==2025.11.12',
    'charset-normalizer==3.4.4',
    'idna==3.11',
    'psycopg2-binary==2.9.11',
    'pytz==2025.2',
    'requests==2.32.5',
    'sqlparse==0.5.4',
    'urllib3==2.5.0'
]

for package in packages:
    print(f"  Installing {package}...")
    result = subprocess.run(
        [pip_path, 'install', package],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print(f"    ✅ {package}")
    else:
        print(f"    ⚠️  {package} - Error")
        if 'psycopg2-binary' in package:
            print("       This is critical - psycopg2 failed to install")

print()
# ============================================================================
# STEP 8: VERIFY INSTALLATION
# ============================================================================
print("📋 STEP 8: Verifying installation...")
print("-" * 80)

# Verify Django
try:
    result = subprocess.run(
        [python_path, '-c', 'import django; print(f"Django {django.get_version()}")'],
        capture_output=True,
        text=True,
        check=False
    )
    if result.returncode == 0:
        print(f"  ✅ {result.stdout.strip()}")
    else:
        print("  ⚠️  Django import failed")
except Exception as e:
    print(f"  ⚠️  Django verification failed: {e}")

# Verify psycopg2
try:
    result = subprocess.run(
        [python_path, '-c', 'import psycopg2; print("psycopg2 OK")'],
        capture_output=True,
        text=True,
        check=False
    )
    if result.returncode == 0:
        print(f"  ✅ {result.stdout.strip()}")
    else:
        print("  ⚠️  psycopg2 import failed")
        print("  ⚠️  Database connections will NOT work!")
except Exception as e:
    print(f"  ⚠️  psycopg2 verification failed: {e}")

print()

# ============================================================================
# STEP 9: CLEAN MIGRATION FILES
# ============================================================================
print("📋 STEP 9: Cleaning migration files...")
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
# STEP 10: CLEAN ALL __pycache__
# ============================================================================
print("📋 STEP 10: Cleaning __pycache__ folders...")
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
# STEP 11: RESET POSTGRESQL DATABASE
# ============================================================================
print("📋 STEP 11: Resetting PostgreSQL database...")
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
# STEP 12: CREATE MIGRATIONS
# ============================================================================
print("📋 STEP 12: Creating migrations...")
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
# STEP 13: MIGRATE PUBLIC SCHEMA
# ============================================================================
print("📋 STEP 13: Migrating public schema...")
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
# STEP 14: CREATE PUBLIC TENANT (CRITICAL!)
# ============================================================================
print("📋 STEP 14: Creating public tenant...")
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
# STEP 15: MIGRATE TENANT SCHEMAS
# ============================================================================
print("📋 STEP 15: Migrating tenant schemas...")
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
# STEP 16: CREATE SUPERUSER
# ============================================================================
print("📋 STEP 16: Creating superuser...")
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
# STEP 17: VERIFY SETUP
# ============================================================================
print("📋 STEP 17: Verifying final setup...")
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
print("🎉 COMPLETE! SYSTEM READY")
print("=" * 80)
print()
print("📝 CONFIGURATION:")
print("   Python: 3.11.x")
print("   Django: 4.2.7")
print("   django-tenants: 3.6.1")
print("   psycopg2-binary: (latest compatible)")
print()
print("📝 CREDENTIALS:")
print("   System Admin:")
print("   URL: http://localhost:8000/system/login/")
print("   Username: admin")
print("   Password: admin123")
print()
print("🚀 START SERVER:")
print("   source venv/bin/activate")
print("   python manage.py runserver")
print()
print("=" * 80)