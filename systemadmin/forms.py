from django import forms
from .models import Tenant

class SystemAdminLoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter username',
            'autofocus': True
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter password'
        })
    )

class TenantCreationForm(forms.ModelForm):
    # NEW: Manual subdomain entry
    subdomain = forms.CharField(
        max_length=63,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'acmecorp (lowercase, no spaces)',
            'pattern': '[a-z0-9]+',
            'title': 'Only lowercase letters and numbers allowed'
        }),
        help_text='Subdomain for tenant (e.g., "acmecorp" becomes acmecorp.localhost)'
    )
    
    admin_email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'admin@company.com'
        })
    )
    
    class Meta:
        model = Tenant
        fields = ['company_name', 'subdomain', 'admin_email', 'contact_person', 'contact_email', 'contact_phone', 'notes', 'is_active']
        widgets = {
            'company_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Acme Corporation'
            }),
            'contact_person': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'John Doe'
            }),
            'contact_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'billing@company.com'
            }),
            'contact_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+1234567890'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Internal notes...'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }
    
    def clean_subdomain(self):
        """Validate subdomain is unique and lowercase"""
        subdomain = self.cleaned_data.get('subdomain', '').lower().strip()
        
        # Check if subdomain already exists
        if Tenant.objects.filter(subdomain=subdomain).exists():
            raise forms.ValidationError(f'Subdomain "{subdomain}" is already taken.')
        
        # Check if schema_name already exists
        if Tenant.objects.filter(schema_name=subdomain).exists():
            raise forms.ValidationError(f'Schema name "{subdomain}" is already taken.')
        
        # Validate format (only lowercase letters and numbers)
        if not subdomain.isalnum():
            raise forms.ValidationError('Subdomain must contain only lowercase letters and numbers.')
        
        if not subdomain.islower():
            raise forms.ValidationError('Subdomain must be lowercase.')
        
        if len(subdomain) < 3:
            raise forms.ValidationError('Subdomain must be at least 3 characters long.')
        
        return subdomain

class TenantEditForm(forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ['company_name', 'contact_person', 'contact_email', 'contact_phone', 'notes', 'is_active']
        widgets = {
            'company_name': forms.TextInput(attrs={
                'class': 'form-control'
            }),
            'contact_person': forms.TextInput(attrs={
                'class': 'form-control'
            }),
            'contact_email': forms.EmailInput(attrs={
                'class': 'form-control'
            }),
            'contact_phone': forms.TextInput(attrs={
                'class': 'form-control'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }