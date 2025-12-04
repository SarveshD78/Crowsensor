# companyadmin/forms.py - CREATE THIS FILE

from django import forms
from .models import AssetConfig


class AssetConfigForm(forms.ModelForm):
    """
    Form for creating/editing InfluxDB configuration
    Company Admin uses this to configure external InfluxDB connection
    """
    
    # Override password field to use PasswordInput
    api_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter InfluxDB password'
        }),
        help_text='InfluxDB password for authentication',
        required=True
    )
    
    class Meta:
        model = AssetConfig
        fields = ['db_name', 'base_api', 'api_username', 'api_password', 'notes', 'is_active']
        widgets = {
            'db_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., production_iot',
                'autofocus': True
            }),
            'base_api': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., http://influxdb.company.com:8086'
            }),
            'api_username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter InfluxDB username'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional notes about this configuration...'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
        help_texts = {
            'db_name': 'InfluxDB database name',
            'base_api': 'Full API URL including protocol and port',
            'api_username': 'Username for InfluxDB authentication',
            'notes': 'Internal notes (optional)',
            'is_active': 'Only one active configuration allowed per company',
        }
    
    def clean_base_api(self):
        """Validate and normalize base API URL"""
        base_api = self.cleaned_data.get('base_api', '').strip()
        
        # Remove trailing slash
        if base_api.endswith('/'):
            base_api = base_api[:-1]
        
        # Validate it starts with http:// or https://
        if not base_api.startswith(('http://', 'https://')):
            raise forms.ValidationError(
                'Base API must start with http:// or https://'
            )
        
        return base_api
    
    def clean(self):
        """Additional validation"""
        cleaned_data = super().clean()
        
        # Check if another active config exists (only if this one is active)
        if cleaned_data.get('is_active'):
            existing = AssetConfig.objects.filter(is_active=True)
            
            # Exclude current instance if editing
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                raise forms.ValidationError(
                    'Only one active InfluxDB configuration allowed. '
                    'Please deactivate the existing configuration first.'
                )
        
        return cleaned_data


class AssetConfigEditForm(forms.ModelForm):
    """
    Form for editing EXISTING InfluxDB configuration
    Password field is optional (leave blank to keep existing)
    """
    
    api_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Leave blank to keep existing password'
        }),
        required=False,
        help_text='Leave blank to keep existing password'
    )
    
    class Meta:
        model = AssetConfig
        fields = ['db_name', 'base_api', 'api_username', 'api_password', 'notes', 'is_active']
        widgets = {
            'db_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., production_iot'
            }),
            'base_api': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., http://influxdb.company.com:8086'
            }),
            'api_username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter InfluxDB username'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional notes...'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
    
    def clean_base_api(self):
        """Validate and normalize base API URL"""
        base_api = self.cleaned_data.get('base_api', '').strip()
        
        if base_api.endswith('/'):
            base_api = base_api[:-1]
        
        if not base_api.startswith(('http://', 'https://')):
            raise forms.ValidationError(
                'Base API must start with http:// or https://'
            )
        
        return base_api
    
    def save(self, commit=True):
        """Override save to handle optional password"""
        instance = super().save(commit=False)
        
        # If password field is empty, keep the existing password
        if not self.cleaned_data.get('api_password'):
            # Get existing password from database
            if self.instance.pk:
                old_instance = AssetConfig.objects.get(pk=self.instance.pk)
                instance.api_password = old_instance.api_password
        
        if commit:
            instance.save()
        
        return instance