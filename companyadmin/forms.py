# companyadmin/forms.py - UPDATED FOR MULTIPLE INFLUXDB + NEW SENSORMETADATA

from django import forms
from .models import AssetConfig, SensorMetadata


# =============================================================================
# ✨ INFLUXDB CONFIGURATION FORMS - UPDATED FOR MULTIPLE CONFIGS
# =============================================================================

class AssetConfigForm(forms.ModelForm):
    """
    ✨ NEW: Form for creating InfluxDB configuration with config_name
    Supports multiple InfluxDB instances per tenant
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
        fields = [
            'config_name',      # ✨ NEW FIELD
            'db_name', 
            'base_api', 
            'api_username', 
            'api_password', 
            'notes', 
            'is_active'
        ]
        widgets = {
            'config_name': forms.TextInput(attrs={  # ✨ NEW
                'class': 'form-control',
                'placeholder': 'e.g., Factory 1 - Mumbai, Building A - Pune',
                'autofocus': True
            }),
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
                'placeholder': 'Optional notes about this InfluxDB instance...'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
        help_texts = {
            'config_name': 'Friendly name to identify this InfluxDB instance',  # ✨ NEW
            'db_name': 'InfluxDB database name',
            'base_api': 'Full API URL including protocol and port',
            'api_username': 'Username for InfluxDB authentication',
            'notes': 'Internal notes (optional)',
            'is_active': 'Multiple active configurations are allowed',  # ✨ CHANGED
        }
    
    def clean_config_name(self):
        """✨ NEW: Validate config_name is unique"""
        config_name = self.cleaned_data.get('config_name', '').strip()
        
        if not config_name:
            raise forms.ValidationError('Configuration name is required')
        
        # Check for duplicate config_name (case-insensitive)
        existing = AssetConfig.objects.filter(config_name__iexact=config_name)
        
        # Exclude current instance if editing
        if self.instance and self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        
        if existing.exists():
            raise forms.ValidationError(
                f'Configuration name "{config_name}" already exists. Please use a different name.'
            )
        
        return config_name
    
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


class AssetConfigEditForm(forms.ModelForm):
    """
    ✨ UPDATED: Form for editing EXISTING InfluxDB configuration
    Password field is optional (leave blank to keep existing)
    Includes config_name field
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
        fields = [
            'config_name',      # ✨ NEW FIELD
            'db_name', 
            'base_api', 
            'api_username', 
            'api_password', 
            'notes', 
            'is_active'
        ]
        widgets = {
            'config_name': forms.TextInput(attrs={  # ✨ NEW
                'class': 'form-control',
                'placeholder': 'e.g., Factory 1 - Mumbai'
            }),
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
    
    def clean_config_name(self):
        """✨ NEW: Validate config_name is unique"""
        config_name = self.cleaned_data.get('config_name', '').strip()
        
        if not config_name:
            raise forms.ValidationError('Configuration name is required')
        
        # Check for duplicate (excluding current instance)
        existing = AssetConfig.objects.filter(config_name__iexact=config_name)
        
        if self.instance and self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        
        if existing.exists():
            raise forms.ValidationError(
                f'Configuration name "{config_name}" already exists.'
            )
        
        return config_name
    
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
            if self.instance.pk:
                old_instance = AssetConfig.objects.get(pk=self.instance.pk)
                instance.api_password = old_instance.api_password
        
        if commit:
            instance.save()
        
        return instance


# =============================================================================
# ✅ SENSOR METADATA FORM - CORRECTED FOR NEW MODEL STRUCTURE
# =============================================================================

class SensorMetadataForm(forms.ModelForm):
    """
    ✅ FIXED: Form for Sensor Metadata Configuration
    Matches NEW model structure with data_types (JSONField) and center_line
    """
    
    # ✅ Use MultipleChoiceField for data_types
    data_types = forms.MultipleChoiceField(
        choices=SensorMetadata.DATA_TYPE_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=True,
        label="Display Types",
        help_text="Select how this sensor should be displayed"
    )
    
    class Meta:
        model = SensorMetadata
        fields = [
            'display_name',
            'unit',
            'description',
            'data_types',       # ✅ JSONField (list)
            'data_nature',
            'lower_limit',
            'center_line',      # ✅ Correct spelling (not central_line)
            'upper_limit',
            'notes'
        ]
        widgets = {
            'display_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter display name (e.g., Compressor Temperature)'
            }),
            'unit': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., °C, kW, bar, PSI, %'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Brief description of this sensor'
            }),
            'data_nature': forms.Select(attrs={
                'class': 'form-select'
            }),
            'lower_limit': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Lower limit (optional)'
            }),
            'center_line': forms.NumberInput(attrs={  # ✅ Correct field name
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Target/setpoint value (optional)'
            }),
            'upper_limit': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Upper limit (optional)'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Additional notes (optional)'
            }),
        }
        help_texts = {
            'display_name': 'User-friendly name for this sensor',
            'unit': 'Unit of measurement',
            'description': 'What this sensor measures',
            'data_types': 'How to display this sensor (can select multiple)',
            'data_nature': 'Type of reading',
            'lower_limit': 'Lower threshold for visualization/alerts',
            'center_line': 'Target or setpoint value',
            'upper_limit': 'Upper threshold for visualization/alerts',
            'notes': 'Additional information',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # ✅ Set initial value for data_types if editing existing metadata
        if self.instance and self.instance.pk and self.instance.data_types:
            self.initial['data_types'] = self.instance.data_types
    
    def clean(self):
        """Form-level validation"""
        cleaned_data = super().clean()
        
        # ✅ Validate: At least one data type must be selected
        data_types = cleaned_data.get('data_types', [])
        
        if not data_types:
            raise forms.ValidationError(
                'At least one display type must be selected'
            )
        
        # ✅ Validate: Lower limit must be less than upper limit
        lower_limit = cleaned_data.get('lower_limit')
        upper_limit = cleaned_data.get('upper_limit')
        
        if lower_limit is not None and upper_limit is not None:
            if lower_limit >= upper_limit:
                raise forms.ValidationError(
                    'Lower limit must be less than upper limit'
                )
        
        return cleaned_data
    
    def save(self, commit=True):
        """✅ Convert data_types to list before saving"""
        instance = super().save(commit=False)
        
        # Convert data_types from form field to list for JSONField
        if 'data_types' in self.cleaned_data:
            instance.data_types = list(self.cleaned_data['data_types'])
        
        if commit:
            instance.save()
        
        return instance