"""
Forms for billing-related functionality
"""

from django import forms


class EnterpriseContactForm(forms.Form):
    """Form for enterprise contact inquiries."""

    # Company Information
    company_name = forms.CharField(
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Your company name"}),
        label="Company Name",
    )

    # Contact Person Information
    first_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "John"}),
        label="First Name",
    )

    last_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Doe"}),
        label="Last Name",
    )

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "john.doe@company.com"}),
        label="Work Email",
    )

    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "+1 (555) 123-4567"}),
        label="Phone Number (Optional)",
    )

    job_title = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "CTO, Security Manager, etc."}),
        label="Job Title (Optional)",
    )

    # Company Details
    COMPANY_SIZE_CHOICES = [
        ("", "Select company size"),
        ("startup", "1-10 employees"),
        ("small", "11-50 employees"),
        ("medium", "51-200 employees"),
        ("large", "201-1000 employees"),
        ("enterprise", "1000+ employees"),
    ]

    company_size = forms.ChoiceField(
        choices=COMPANY_SIZE_CHOICES,
        required=True,
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Company Size",
    )

    industry = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Technology, Healthcare, Finance, etc."}),
        label="Industry (Optional)",
    )

    # Use Case Information
    USE_CASE_CHOICES = [
        ("", "Select primary use case"),
        ("compliance", "Compliance and Risk Management"),
        ("supply_chain", "Supply Chain Security"),
        ("vulnerability", "Vulnerability Management"),
        ("licensing", "License Compliance"),
        ("devops", "DevOps and CI/CD Integration"),
        ("audit", "Audit and Reporting"),
        ("other", "Other"),
    ]

    primary_use_case = forms.ChoiceField(
        choices=USE_CASE_CHOICES,
        required=True,
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Primary Use Case",
    )

    # Project Details
    timeline = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Immediate, 1-3 months, 6+ months"}),
        label="Implementation Timeline (Optional)",
    )

    # Additional Information
    message = forms.CharField(
        required=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Please describe your requirements, specific needs, or any questions you "
                "have about our Enterprise plan...",
            }
        ),
        label="Message",
    )

    # Consent
    newsletter_signup = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="I would like to receive product updates and security best practices via email",
    )

    def clean_email(self) -> str:
        """Validate email domain for enterprise inquiries."""
        email = self.cleaned_data.get("email", "")

        # List of common personal email domains to warn about
        personal_domains = [
            "gmail.com",
            "yahoo.com",
            "hotmail.com",
            "outlook.com",
            "aol.com",
            "icloud.com",
            "protonmail.com",
        ]

        if email:
            domain = email.split("@")[-1].lower()
            if domain in personal_domains:
                # Don't block it, but we could add a warning if needed
                pass

        return email

    def clean_company_name(self) -> str:
        """Clean and validate company name."""
        company_name = self.cleaned_data.get("company_name", "")
        return company_name.strip()

    def clean_message(self) -> str:
        """Validate message length and content."""
        message = self.cleaned_data.get("message", "")

        if len(message.strip()) < 10:
            raise forms.ValidationError("Please provide a more detailed message (at least 10 characters).")

        return message.strip()
