import logging
from smtplib import SMTPException

import dramatiq
from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from .config import is_billing_enabled

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


@dramatiq.actor(queue_name="billing", max_retries=1, time_limit=600000)  # 10 minutes
def check_stale_trials_task():
    """
    Check for stale trial subscriptions and sync them with Stripe.

    This task acts as a safety net for missed webhooks by:
    1. Finding teams with trials that appear expired (trial_end in past)
    2. Fetching actual subscription status from Stripe
    3. Updating local database to match Stripe's state

    This is a defensive measure - normally trial expiration is handled by
    Stripe webhooks, but this catches cases where webhooks were missed.
    """
    from sbomify.apps.billing.stripe_client import StripeClient, StripeError
    from sbomify.apps.teams.models import Team

    if not is_billing_enabled():
        logger.info("Billing is not enabled, skipping stale trials check")
        return

    stripe_client = StripeClient()
    now_timestamp = int(timezone.now().timestamp())

    # Find teams with stale trials
    teams_with_subscriptions = Team.objects.exclude(billing_plan_limits__isnull=True).filter(
        billing_plan_limits__has_key="stripe_subscription_id"
    )

    stale_teams = []
    for team in teams_with_subscriptions:
        limits = team.billing_plan_limits or {}
        # Check if it looks like a trial that should have ended
        if limits.get("is_trial") or limits.get("subscription_status") == "trialing":
            trial_end = limits.get("trial_end")
            if trial_end and trial_end < now_timestamp:
                stale_teams.append(team)

    if not stale_teams:
        logger.info("No stale trials found")
        return

    logger.info(f"Found {len(stale_teams)} teams with potentially stale trials")

    synced_count = 0
    error_count = 0

    for team in stale_teams:
        subscription_id = team.billing_plan_limits.get("stripe_subscription_id")
        if not subscription_id:
            continue

        try:
            # Fetch actual subscription from Stripe
            subscription = stripe_client.get_subscription(subscription_id)

            # Get Stripe's actual state
            stripe_status = subscription.status
            stripe_is_trial = stripe_status == "trialing"

            # Get current local state
            local_status = team.billing_plan_limits.get("subscription_status")
            local_is_trial = team.billing_plan_limits.get("is_trial", False)

            # Check if update needed
            if local_status != stripe_status or local_is_trial != stripe_is_trial:
                team.billing_plan_limits["subscription_status"] = stripe_status
                team.billing_plan_limits["is_trial"] = stripe_is_trial
                team.billing_plan_limits["last_updated"] = timezone.now().isoformat()
                team.billing_plan_limits["last_synced_from_stripe"] = timezone.now().isoformat()

                if not stripe_is_trial:
                    team.billing_plan_limits["trial_days_remaining"] = 0

                team.save()

                logger.info(
                    f"Synced stale trial for team {team.key}: "
                    f"status {local_status} -> {stripe_status}, "
                    f"is_trial {local_is_trial} -> {stripe_is_trial}"
                )
                synced_count += 1

        except StripeError as e:
            logger.error(f"Failed to sync team {team.key}: {e}")
            error_count += 1
        except Exception as e:
            logger.exception(f"Unexpected error syncing team {team.key}: {e}")
            error_count += 1

    logger.info(f"Stale trials check complete: synced={synced_count}, errors={error_count}")
