"""
Django settings for crowsensor_project project.
Multi-tenant IoT Monitoring Platform
"""
import os
from pathlib import Path


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-temporary-key-change-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS','164.52.207.221,localhost,127.0.0.1,.localhost,*').split(',')

# Application definition
SHARED_APPS = [
    'django_tenants',  # Must come first
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.admin',
    
    # System-level apps (Public Schema)
    'systemadmin',  # Tenant management, system admin dashboard
      
]

TENANT_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.admin',
    
    # Tenant-specific apps (Isolated per tenant)
    'accounts',
    'companyadmin',      # Company admin features
    'departmentadmin',   # Department management
    'userdashboard',     # User dashboards
]

INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]

# Middleware
MIDDLEWARE = [
    'systemadmin.middleware.SystemAdminBypassMiddleware',  # Bypass tenant for /system/ routes
    'django_tenants.middleware.main.TenantMainMiddleware',  # Must be second
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'crowsensor_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'crowsensor_project.wsgi.application'

# Database - PostgreSQL with django-tenants
# Database - TEMPORARY HARDCODED (for debugging)
DATABASES = {
    'default': {
        'ENGINE': 'django_tenants.postgresql_backend',
        'NAME': 'crowsensor_db',
        'USER': 'crowsensor_user',
        'PASSWORD': 'Sisai@2025',  # ← HARDCODED (remove after testing)
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

DATABASE_ROUTERS = [
    'django_tenants.routers.TenantSyncRouter',
]

# Django-Tenants Configuration
TENANT_MODEL = 'systemadmin.Tenant'
TENANT_DOMAIN_MODEL = 'systemadmin.Domain'
PUBLIC_SCHEMA_NAME = os.getenv('PUBLIC_SCHEMA_NAME', 'public')
TENANT_CREATION_FAKES_MIGRATIONS = True
TENANT_BASE_SCHEMA = 'public'

# For development with localhost
TENANT_SUBFOLDER_PREFIX = ''
HAS_MULTI_TYPE_TENANTS = False

AUTHENTICATION_BACKENDS = [
    'accounts.backends.TenantBackend',  # Tenant user authentication
    'django.contrib.auth.backends.ModelBackend',  # System admin authentication
]

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'  # Indian Standard Time (IST)
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'debug.log',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
        'django_tenants': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}