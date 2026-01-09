from django import forms
from django.conf import settings
from django.forms import inlineformset_factory

from sbomify.apps.teams.models import ContactEntity, ContactProfile, ContactProfileContact, Member, Team


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


class TeamBrandingForm(forms.Form):
    brand_color = forms.CharField(required=False)
    accent_color = forms.CharField(required=False)
    branding_enabled = forms.BooleanField(required=False)
    icon_pending_deletion = forms.BooleanField(required=False)
    logo_pending_deletion = forms.BooleanField(required=False)
    icon = forms.FileField(required=False)
    logo = forms.FileField(required=False)


class TeamGeneralSettingsForm(forms.Form):
    """Form for updating workspace general settings (name)."""

    name = forms.CharField(
        max_length=255,
        min_length=1,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter workspace name",
            }
        ),
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


class OnboardingCompanyForm(forms.Form):
    """Single-step onboarding form for SBOM identity setup."""

    company_name = forms.CharField(
        label="Company / Organization Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "e.g., Acme Corporation",
                "autofocus": True,
            }
        ),
    )
    contact_name = forms.CharField(
        label="Contact Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "e.g., Jane Smith",
            }
        ),
    )
    email = forms.EmailField(
        label="Contact Email",
        required=False,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "security@example.com",
            }
        ),
    )
    website = forms.URLField(
        label="Website",
        required=False,
        widget=forms.URLInput(
            attrs={
                "class": "form-control form-control-lg",
                "placeholder": "https://example.com",
            }
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
    """Form for ContactProfile - only contains profile-level fields."""

    class Meta:
        model = ContactProfile
        fields = ["name", "is_default"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Profile name"}),
            "is_default": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class ContactEntityModelForm(forms.ModelForm):
    """Form for ContactEntity - contains organization/company details."""

    website_urls_text = forms.CharField(
        label="Website URLs",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Enter one URL per line\nhttps://example.com",
            }
        ),
        help_text="Enter one URL per line",
    )

    class Meta:
        model = ContactEntity
        fields = [
            "name",
            "email",
            "phone",
            "address",
            "is_manufacturer",
            "is_supplier",
            "is_author",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Entity name"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "contact@example.com"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+1 555 123 4567"}),
            "address": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Street, City, Country"}
            ),
            "is_manufacturer": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_supplier": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_author": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk and self.instance.website_urls:
            self.fields["website_urls_text"].initial = "\n".join(self.instance.website_urls)

    def clean(self):
        cleaned_data = super().clean()
        is_manufacturer = cleaned_data.get("is_manufacturer")
        is_supplier = cleaned_data.get("is_supplier")
        is_author = cleaned_data.get("is_author")

        if not (is_manufacturer or is_supplier or is_author):
            raise forms.ValidationError("At least one role (Manufacturer, Supplier, or Author) must be selected.")

        return cleaned_data

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
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Contact name", "required": True}),
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "email@example.com", "required": True}
            ),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+1 555 123 4567"}),
        }


# Formset for contacts linked to an entity (3-level hierarchy)
ContactProfileContactFormSet = inlineformset_factory(
    ContactEntity,
    ContactProfileContact,
    form=ContactProfileContactForm,
    extra=0,
    can_delete=True,
)


# Formset for entities linked to a profile
ContactEntityFormSet = inlineformset_factory(
    ContactProfile,
    ContactEntity,
    form=ContactEntityModelForm,
    extra=0,
    can_delete=True,
)


class VulnerabilitySettingsForm(forms.Form):
    vulnerability_provider = forms.ChoiceField(
        required=True,
        choices=[("osv", "OSV"), ("dependency_track", "Dependency Track")],
    )
    custom_dt_server_id = forms.CharField(
        required=False,
    )
