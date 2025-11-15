from django import forms
from django.conf import settings

from sbomify.apps.teams.models import Member, Team


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
