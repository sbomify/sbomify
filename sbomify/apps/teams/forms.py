from django import forms
from django.conf import settings
from django.forms import inlineformset_factory

from sbomify.apps.teams.models import ContactProfile, ContactProfileContact, Member, Team


class AddTeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name"]

    def save(self, *args, user=None, **kwargs):
        is_new = self.instance._state.adding
        super().save(*args, **kwargs)
        if is_new and user:
            is_default_team = not Member.objects.filter(user=user).exists()
            Member.objects.create(team=self.instance, user=user, is_default_team=is_default_team, role="owner")
        return self.instance


class UpdateTeamForm(forms.Form):
    key = forms.CharField(
        required=True,
        widget=forms.HiddenInput(),
    )


class DeleteTeamForm(forms.Form):
    key = forms.CharField(
        required=True,
        widget=forms.HiddenInput(),
    )


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


class OnboardingProductForm(forms.Form):
    """Form for creating a product during onboarding."""

    name = forms.CharField(
        label="Product Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "Enter product name",
                "autofocus": True,
            }
        ),
        help_text=(
            "A product is your top-level offering, which can be physical hardware, software, or a combination of both. "
            "For example, a smart device, an application suite, or an IoT platform."
        ),
    )


class OnboardingProjectForm(forms.Form):
    """Form for creating a project during onboarding."""

    name = forms.CharField(
        label="Project Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "Enter project name",
                "autofocus": True,
            }
        ),
        help_text=(
            "Projects are logical groupings within your product. For example, a smart device might have "
            "firmware, mobile app, and cloud backend projects."
        ),
    )


class OnboardingComponentForm(forms.Form):
    """Form for creating a component during onboarding."""

    name = forms.CharField(
        label="Component Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "Enter component name",
                "autofocus": True,
            }
        ),
        help_text=(
            "Components are the individual building blocks that make up your project. These can be libraries, "
            "microservices, firmware modules, or any other distinct piece of software."
        ),
    )


class DeleteMemberForm(forms.Form):
    member_id = forms.IntegerField(
        required=True,
        widget=forms.HiddenInput(),
    )


class DeleteInvitationForm(forms.Form):
    invitation_id = forms.IntegerField(
        required=True,
        widget=forms.HiddenInput(),
    )


class ContactProfileForm(forms.Form):
    profile_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput(),
    )


class ContactProfileModelForm(forms.ModelForm):
    website_urls_text = forms.CharField(
        label="Website URLs",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Enter one URL per line\nhttps://example.com\nhttps://example.org",
            }
        ),
        help_text="Enter one URL per line",
    )

    class Meta:
        model = ContactProfile
        fields = [
            "name",
            "company",
            "supplier_name",
            "vendor",
            "email",
            "phone",
            "address",
            "is_default",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Profile name"}),
            "company": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company name"}),
            "supplier_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Supplier name"}),
            "vendor": forms.TextInput(attrs={"class": "form-control", "placeholder": "Vendor name"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "contact@example.com"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+1 555 123 4567"}),
            "address": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "placeholder": "Street, City, Country"}
            ),
            "is_default": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.website_urls:
            self.fields["website_urls_text"].initial = "\n".join(self.instance.website_urls)

    def clean_website_urls_text(self):
        text = self.cleaned_data.get("website_urls_text")
        if not text:
            return []
        return [url.strip() for url in text.split("\n") if url.strip()]

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.website_urls = self.cleaned_data.get("website_urls_text", [])
        if commit:
            instance.save()
        return instance


class ContactProfileContactForm(forms.ModelForm):
    class Meta:
        model = ContactProfileContact
        fields = ["name", "email", "phone"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Contact name"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "email@example.com"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+1 555 123 4567"}),
        }


ContactProfileContactFormSet = inlineformset_factory(
    ContactProfile,
    ContactProfileContact,
    form=ContactProfileContactForm,
    extra=0,
    can_delete=False,
)


class VulnerabilitySettingsForm(forms.Form):
    vulnerability_provider = forms.ChoiceField(
        required=True,
        choices=[("osv", "OSV"), ("dependency_track", "Dependency Track")],
        widget=forms.RadioSelect(),
    )
    custom_dt_server_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )
