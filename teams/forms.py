from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from .models import Team


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name"]


class InviteUserForm(forms.Form):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    role = forms.ChoiceField(
        required=True,
        choices=settings.TEAMS_SUPPORTED_ROLES,
        widget=forms.Select(attrs={"class": "form-control"}),
    )


# Getting Started Wizard Forms
class WizardPlanSelectionForm(forms.Form):
    """Form for selecting a billing plan in the getting started wizard."""

    PLAN_CHOICES = [
        ("community", "Community - Free forever"),
        ("business", "Business - $199/month"),
        ("enterprise", "Enterprise - Contact us"),
    ]

    plan = forms.ChoiceField(
        label="Choose Your Plan",
        choices=PLAN_CHOICES,
        initial="community",
        required=True,
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
        help_text=(
            "Start with Community and upgrade anytime. You can always change your plan later in your team settings."
        ),
    )


class WizardProductForm(forms.Form):
    """Form for creating a product in the getting started wizard."""

    name = forms.CharField(
        label="Product Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "Enter your product name",
                "autofocus": True,
            }
        ),
        help_text=(
            "A product is your top-level offering, which can be physical hardware, software, or a combination of both. "
            "For example, a smart device, an application suite, or an IoT platform."
        ),
    )

    description = forms.CharField(
        label="Description",
        max_length=500,
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "placeholder": "Briefly describe your product (optional)",
                "rows": 3,
            }
        ),
        help_text="A brief description of what your product does or provides.",
    )


class WizardProjectForm(forms.Form):
    """Form for creating a project in the getting started wizard."""

    name = forms.CharField(
        label="Project Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "Enter your project name",
                "autofocus": True,
            }
        ),
        help_text=(
            "Projects are logical groupings within your product. For example, a smart device might have "
            "firmware, mobile app, and cloud backend projects."
        ),
    )


class WizardComponentForm(forms.Form):
    """Form for creating a component in the getting started wizard."""

    name = forms.CharField(
        label="Component Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "Enter your component name",
                "autofocus": True,
            }
        ),
        help_text=(
            "Components are the individual building blocks that make up your project. These can be libraries, "
            "microservices, firmware modules, or any other distinct piece of software."
        ),
    )


class DependencyTrackServerForm(forms.Form):
    """Form for adding/editing custom Dependency Track servers."""

    name = forms.CharField(
        label="Server Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter a friendly name for this server",
            }
        ),
        help_text="A descriptive name to identify this server (e.g., 'Production DT', 'Staging Environment')",
    )

    url = forms.URLField(
        label="Server URL",
        max_length=500,
        required=True,
        widget=forms.URLInput(
            attrs={
                "class": "form-control",
                "placeholder": "https://dependencytrack.example.com",
            }
        ),
        help_text="The base URL of your Dependency Track server (e.g., https://dependencytrack.example.com)",
    )

    api_key = forms.CharField(
        label="API Key",
        max_length=255,
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter your DT API key",
            }
        ),
        help_text=(
            "Your Dependency Track API key with BOM_UPLOAD, VIEW_PORTFOLIO, "
            "VIEW_VULNERABILITY, and PROJECT_CREATION_UPLOAD permissions"
        ),
    )

    priority = forms.IntegerField(
        label="Priority",
        initial=100,
        min_value=1,
        max_value=1000,
        required=True,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "min": "1",
                "max": "1000",
            }
        ),
        help_text="Lower numbers = higher priority for load balancing (1-1000)",
    )

    max_concurrent_scans = forms.IntegerField(
        label="Max Concurrent Scans",
        initial=100,
        min_value=1,
        max_value=1000,
        required=True,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "min": "1",
                "max": "1000",
            }
        ),
        help_text="Maximum number of concurrent SBOM uploads/scans this server can handle",
    )

    def clean_url(self):
        """Validate and normalize the URL."""
        url = self.cleaned_data.get("url")
        if url:
            # Remove trailing slash for consistency
            url = url.rstrip("/")

            # Basic validation - ensure it's a proper HTTP/HTTPS URL
            if not url.startswith(("http://", "https://")):
                raise ValidationError("URL must start with http:// or https://")

        return url

    def clean_priority(self):
        """Validate priority value."""
        priority = self.cleaned_data.get("priority")
        if priority is not None and (priority < 1 or priority > 1000):
            raise ValidationError("Priority must be between 1 and 1000")
        return priority

    def clean_max_concurrent_scans(self):
        """Validate max concurrent scans value."""
        max_scans = self.cleaned_data.get("max_concurrent_scans")
        if max_scans is not None and (max_scans < 1 or max_scans > 1000):
            raise ValidationError("Max concurrent scans must be between 1 and 1000")
        return max_scans
