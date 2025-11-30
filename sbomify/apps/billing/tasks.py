import logging
from smtplib import SMTPException

import dramatiq
from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

logger = logging.getLogger(__name__)


@dramatiq.actor(queue_name="default", max_retries=3)
def send_enterprise_inquiry_email(
    form_data: dict,
    user_email: str | None = None,
    user_name: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
    is_public: bool = False,
):
    """
    Send enterprise inquiry emails asynchronously.
    """
    try:
        company_name = form_data.get("company_name")

        # Construct subject
        if is_public:
            subject = f"Enterprise Inquiry from {company_name} (Public Form)"
        else:
            subject = f"Enterprise Inquiry from {company_name}"

        # Construct message content
        # We reconstruct the logic from the view here
        company_size = form_data.get("company_size_display", "N/A")
        industry = form_data.get("industry") or "Not specified"

        first_name = form_data.get("first_name")
        last_name = form_data.get("last_name")
        email = form_data.get("email")
        phone = form_data.get("phone") or "Not provided"
        job_title = form_data.get("job_title") or "Not specified"

        primary_use_case = form_data.get("primary_use_case_display", "N/A")
        timeline = form_data.get("timeline") or "Not specified"
        message = form_data.get("message")
        newsletter_signup = "Yes" if form_data.get("newsletter_signup") else "No"

        submitted_at = timezone.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        message_content = f"""
New Enterprise Plan Inquiry{" (Public Form)" if is_public else ""}

Company Information:
- Company Name: {company_name}
- Company Size: {company_size}
- Industry: {industry}

Contact Information:
- Name: {first_name} {last_name}
- Email: {email}
- Phone: {phone}
- Job Title: {job_title}

Project Details:
- Primary Use Case: {primary_use_case}
- Timeline: {timeline}

Message:
{message}

Newsletter Signup: {newsletter_signup}

"""
        if is_public:
            message_content += f"""
Submitted from: Public Enterprise Contact Form
Submitted at: {submitted_at}
Source IP: {source_ip or "Unknown"}
User Agent: {user_agent or "Unknown"}
"""
        else:
            message_content += f"""
Submitted by user: {user_email} ({user_name})
Submitted at: {submitted_at}
"""

        # Send email to sales team
        sales_email = EmailMessage(
            subject=subject,
            body=message_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[settings.ENTERPRISE_SALES_EMAIL],
            reply_to=[settings.ENTERPRISE_SALES_EMAIL],
        )
        sales_email.send(fail_silently=False)

        # Send confirmation email to the user
        confirmation_subject = "Thank you for your Enterprise inquiry"

        # Build confirmation message with proper line length
        greeting = f"Dear {first_name},"

        if is_public:
            intro = (
                "Thank you for your interest in sbomify Enterprise! "
                "We've received your inquiry and our sales team will reach out to you within 1-2 business days."
            )
            body = (
                f"Our team will review your requirements and discuss how sbomify "
                f"Enterprise can meet {company_name}'s specific needs."
            )
        else:
            intro = (
                "Thank you for your interest in sbomify Enterprise. "
                "We have received your inquiry and will get back to you within 1-2 business days."
            )
            body = (
                f"Our sales team will review your requirements and reach out to discuss how sbomify "
                f"Enterprise can meet {company_name}'s specific needs."
            )

        confirmation_message = f"""{greeting}

{intro}

{body}

Best regards,
The sbomify Team

---
You can reply to this email and we'll receive your message at {settings.ENTERPRISE_SALES_EMAIL}
"""

        confirmation_email = EmailMessage(
            subject=confirmation_subject,
            body=confirmation_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
            reply_to=[settings.ENTERPRISE_SALES_EMAIL],
        )
        confirmation_email.send(fail_silently=True)

        logger.info(f"Successfully processed enterprise inquiry from {email} for {company_name}")

    except (SMTPException, ConnectionError, TimeoutError, OSError) as e:
        # Transient network/SMTP errors - let Dramatiq retry
        logger.warning(f"Transient error sending enterprise inquiry email: {e}")
        raise
    except Exception as e:
        # Permanent errors (e.g., invalid email format, configuration issues)
        # Log and don't retry to avoid infinite loops
        logger.error(f"Permanent error processing enterprise inquiry email: {e}", exc_info=True)
