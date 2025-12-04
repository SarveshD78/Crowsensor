"""
URL Configuration for Crowsensor Multi-Tenant SaaS
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Specific paths FIRST
    path('company/', include('companyadmin.urls')),
    path('department/', include('departmentadmin.urls')),
    path('dashboard/', include('userdashboard.urls')),
    path('accounts/', include('accounts.urls')),
    
    # System admin at root - MUST BE LAST
    path('', include('systemadmin.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)