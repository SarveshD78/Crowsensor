# userdashboard/urls.py

from django.urls import path
from . import views

app_name = 'userdashboard'

urlpatterns = [
    # Dashboard
    path('user/', views.user_home_view, name='user_home'),
    
    # Authentication
    path('logout/', views.logout_view, name='logout'),
]
