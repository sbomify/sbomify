"""
Onboarding email services.
"""

from __future__ import annotations

import smtplib
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, OperationalError
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from sbomify.logging import getLogger

from ..models import OnboardingEmail, OnboardingStatus
from ..utils import get_email_context, render_email_templates

logger = getLogger(__name__)


class TransientEmailError(Exception):
    """A send that failed for a reason another attempt could survive.

    The sending tasks are dramatiq actors declaring ``max_retries=3``, and
    that budget only exists if something raises. Reporting a failed send as a
    ``False`` return — which is what every path here used to do — spends it on
    nothing: the actor sees a clean return, the message is acknowledged, and a
    welcome email lost to a thirty-second mail outage is lost for good,
    because nothing schedules another attempt.

    Carrying the classification on the exception rather than re-deriving it in
    the task keeps one answer to "is this worth retrying" instead of two that
    can drift.
    """


def _is_temporary_smtp_code(code: object) -> bool:
    """Whether an SMTP reply code is a 4xx, which means "not now" rather than "no".

    RFC 5321 splits refusals by leading digit: 4yz is a transient negative
    reply the sender is invited to try again, 5yz is permanent. A greylisting
    server answering 450, or a box over quota answering 452, refuses the
    recipient exactly as a nonexistent address does — the code is the only
    thing that tells them apart.
    """
    return isinstance(code, int) and 400 <= code < 500


def _is_transient_send_error(exc: BaseException) -> bool:
    """Whether another attempt at this send could plausibly succeed.

    Refusals are read by their reply code rather than by their class. An
    ``SMTPRecipientsRefused`` is not intrinsically permanent: smtplib raises
    the same class for a greylisted 450 and for a 550 that will never be
    anything else, so treating the class as terminal drops a message the
    server explicitly asked us to send again.
    """
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        # The one response error that carries no ``smtp_code``: the codes are
        # per recipient. One recipient here, but the rule generalises — a retry
        # sends the whole message again, so it only helps if nothing was
        # permanently refused.
        refusals = (exc.recipients or {}).values()
        return bool(refusals) and all(_is_temporary_smtp_code(code) for code, _ in refusals)
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        # The server does not speak something we asked for. It will not have
        # learned it by the next attempt, and it carries no code to read.
        return False
    if isinstance(exc, smtplib.SMTPResponseException):
        # Everything the server answered, classified alike: refused senders,
        # a 552 over quota, a 535 bad credential, a 421 shutting the channel.
        # The code is the whole of the difference between them, so reading the
        # class instead would burn the retry budget on a 5xx that will not move
        # and drop the 4xx that would have gone through.
        return _is_temporary_smtp_code(exc.smtp_code)
    # What is left never reached a server that answered: a dropped connection
    # (SMTPServerDisconnected), a DNS failure, a timeout, an unroutable host.
    #
    # SMTPException is named alongside OSError rather than left to inherit from
    # it. It does subclass OSError, so the tuple is not two rules — but that
    # relationship surprises most readers, and a check that looks like it
    # misses every smtplib error is worth one redundant name.
    return isinstance(exc, (smtplib.SMTPException, OSError))


#: After this, a ``PENDING`` row is assumed to belong to nobody. The sending
#: actors declare ``time_limit=60000`` — one minute — so a row still pending an
#: hour later is not being worked on: the worker died between ``create_email``
#: and the send. Generous on purpose, because the cost of guessing early is two
#: copies of one email and the cost of guessing late is an hour's delay.
ABANDONED_PENDING_AFTER = timedelta(hours=1)


def _reconcile_welcome_flag(onboarding_status: OnboardingStatus, user: Any) -> None:
    """Catch ``welcome_email_sent`` up to a row that is already ``SENT``.

    The send writes the row and then the flag, so a worker dying between the
    two leaves a delivered email recorded as not sent. That is not cosmetic:
    the recovery sweep keys on the flag and would re-queue the user every day,
    and ``should_receive_quick_start`` and its siblings gate on it, so the whole
    drip stays blocked behind an email that did go out.

    Nothing else closes the window. Whoever next asks to send this email is the
    only code that sees both facts at once.
    """
    if onboarding_status.welcome_email_sent:
        return
    logger.info("Welcome email was sent for user %s but the status flag was not; repairing", user.id)
    onboarding_status.mark_welcome_email_sent()


def refused_at_current_address() -> Q:
    """Rows whose ``UNDELIVERABLE`` still applies to the user's address now.

    The ORM half of :meth:`OnboardingEmail.suppresses`, for the queries that
    decide what to queue. Keeping the blank case here as well is what stops the
    two disagreeing: a row from before ``attempted_address`` existed suppresses
    in both.
    """
    return Q(status=OnboardingEmail.EmailStatus.UNDELIVERABLE) & (
        Q(attempted_address="") | Q(attempted_address=F("user__email"))
    )


def _is_abandoned(record: OnboardingEmail) -> bool:
    """Whether a ``PENDING`` row is a leftover rather than a live attempt.

    Without this the row is permanent: the unique constraint makes every later
    attempt raise ``IntegrityError``, the handler reads that as a concurrent
    worker and answers ``False``, and the recovery sweep can never get the
    signup back. Nothing else clears it, because nothing else knows the worker
    that created it is gone.
    """
    return (
        record.status == OnboardingEmail.EmailStatus.PENDING
        and timezone.now() - record.created_at > ABANDONED_PENDING_AFTER
    )


def _is_refused_address(exc: BaseException) -> bool:
    """Whether the server refused this recipient for good.

    Narrower than "permanent" on purpose. A 552 over-size, a 535 bad
    credential and a refused *sender* are all terminal for the attempt, but
    they are faults on our side: fix the template or the relay config and the
    next batch pass delivers. Marking those undeliverable would strand every
    user behind one misconfiguration, and nothing would clear it.

    A 5xx against the recipient is the one that says the address will not exist
    on the next attempt either, so it is the only one worth remembering.
    """
    if not isinstance(exc, smtplib.SMTPRecipientsRefused):
        return False
    refusals = (exc.recipients or {}).values()
    return bool(refusals) and all(isinstance(code, int) and 500 <= code < 600 for code, _ in refusals)


def _render_or_report(template_name: str, context: dict[str, Any], user_id: Any) -> tuple[str, str] | None:
    """Render a message, or report the failure and answer ``None``.

    Rendering sits outside the send block, so without this a missing or broken
    template left the service as an ordinary exception, and the task re-raised
    it into dramatiq's retry budget. Three more attempts run the same template
    against the same context and fail the same way: a template is not a
    transport, and no amount of waiting repairs one.
    """
    try:
        return render_email_templates(template_name, context)
    except Exception as e:
        logger.error("Failed to render %s email for user %s: %s", template_name, user_id, e, exc_info=True)
        return None


def _is_mailable(user: Any) -> bool:
    """Return False for recipients that must never be handed to the mailer.

    Synthetic OIDC bot identities, and accounts that are deactivated or
    soft-deleted. This is the last gate before ``EmailMultiAlternatives``,
    deliberately duplicating the check in ``onboarding.signals`` so a bot
    reaching any send path — a backfill, an admin action, a future sender —
    still can't produce a message.

    The liveness pair is the one used everywhere else an account has to be
    live (``core/services/account_deletion.py``, ``access_tokens/utils.py``).
    It belongs here rather than in each caller's query: a send queued before a
    deletion runs after it, so the check has to be at the send, not at the
    point something decided to send.
    """
    from sbomify.apps.oidc.services import is_synthetic_bot_user

    if is_synthetic_bot_user(user):
        logger.debug("Suppressing onboarding email for synthetic bot user %s", user.id)
        return False
    if not user.is_active or user.deleted_at is not None:
        logger.info("Suppressing onboarding email for closed account %s", user.id)
        return False
    if not (getattr(user, "email", "") or "").strip():
        # Not a no-op: ``to=[""]`` is a one-element recipient list, so the send
        # reports success, the row is marked SENT and ``welcome_email_sent`` is
        # set — retiring the user from the recovery sweep for an email that was
        # never delivered anywhere. Refusing keeps them eligible until a profile
        # sync supplies an address.
        logger.info("Deferring onboarding email for user %s: no address yet", user.id)
        return False
    return True


def _unsubscribe_headers(unsubscribe_url: str | None) -> dict[str, str]:
    """List-Unsubscribe headers for a drip message.

    Gmail and Yahoo require these on bulk mail, and they are what puts the
    native "Unsubscribe" control next to the sender name. The One-Click header
    tells the client to POST rather than follow the link, which is also why the
    view treats GET as an offer and POST as the action.
    """
    if not unsubscribe_url:
        return {}
    return {
        "List-Unsubscribe": f"<{unsubscribe_url}>, <mailto:hello@sbomify.com?subject=unsubscribe>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


class OnboardingEmailService:
    """Service for sending onboarding emails."""

    @staticmethod
    def send_welcome_email(user: Any) -> bool:
        """
        Send welcome email to a new user.

        Args:
            user: User instance

        Returns:
            True if email was sent successfully, False otherwise
        """
        if not _is_mailable(user):
            return False

        # Check if welcome email already sent
        onboarding_status, _ = OnboardingStatus.objects.get_or_create(user=user)
        if onboarding_status.welcome_email_sent:
            logger.info("Welcome email already sent to user %s", user.id)
            return True

        # Every reason not to send is settled before anything is rendered. The
        # ordering is load-bearing for the first of them: a row already SENT
        # with the flag unset is the crash window ``_reconcile_welcome_flag``
        # exists to close, and rendering first meant a broken template returned
        # before the repair, leaving the sweep re-queueing a delivered email
        # and the drip blocked behind it.
        existing = OnboardingEmail.objects.filter(user=user, email_type=OnboardingEmail.EmailType.WELCOME).first()
        if existing and existing.status == OnboardingEmail.EmailStatus.SENT:
            logger.info("Welcome email record already sent for user %s", user.id)
            _reconcile_welcome_flag(onboarding_status, user)
            return True
        # An undeliverable row is kept and honoured. The FAILED row below is
        # deleted so the next pass can try again, which is what a batch
        # re-queue is for; doing that to a refused address would re-send to a
        # mailbox that does not exist, every day, for as long as the user
        # exists.
        if existing and existing.suppresses(user.email):
            logger.info("Welcome email address previously refused for user %s, not retrying", user.id)
            return False
        if existing and (
            existing.status
            in (
                OnboardingEmail.EmailStatus.FAILED,
                OnboardingEmail.EmailStatus.UNDELIVERABLE,
            )
            or _is_abandoned(existing)
        ):
            # UNDELIVERABLE only reaches here when the address has changed
            # since; the guard above kept the row when it still applies.
            existing.delete()

        context = get_email_context(user)
        rendered = _render_or_report("welcome", context, user.id)
        if rendered is None:
            return False
        html_content, plain_text_content = rendered

        try:
            email_record = OnboardingEmail.create_email(
                user=user,
                email_type=OnboardingEmail.EmailType.WELCOME,
                subject="Welcome to sbomify - Let's Get Started!",
            )
        except IntegrityError:
            concurrent = OnboardingEmail.objects.filter(user=user, email_type=OnboardingEmail.EmailType.WELCOME).first()
            if concurrent and concurrent.status == OnboardingEmail.EmailStatus.SENT:
                _reconcile_welcome_flag(onboarding_status, user)
                return True
            logger.warning("Welcome email being processed by another worker for user %s", user.id)
            return False

        try:
            email = EmailMultiAlternatives(
                subject=email_record.subject,
                body=plain_text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
                reply_to=["hello@sbomify.com"],
                # Welcome opens the sequence, so it carries the opt-out too. It
                # is not suppressed by one (nobody can unsubscribe before their
                # first email), but bulk-sender rules look at the header, not at
                # our reasoning about which message is transactional.
                headers=_unsubscribe_headers(context.get("unsubscribe_url")),
            )
            email.attach_alternative(html_content, "text/html")
            email.send(fail_silently=False)
            email_record.mark_sent()
            onboarding_status.mark_welcome_email_sent()
            logger.info("Welcome email sent successfully to user %s", user.id)
            return True
        except Exception as e:
            if _is_refused_address(e):
                email_record.mark_undeliverable(user.email, f"Address refused: {type(e).__name__}")
                logger.error("Welcome email address refused for user %s: %s", user.id, e)
                return False
            email_record.mark_failed(f"SMTP send failure: {type(e).__name__}")
            if _is_transient_send_error(e):
                logger.warning("Transient failure sending welcome email to user %s: %s", user.id, e)
                raise TransientEmailError(f"welcome email to user {user.id}") from e
            logger.error("Failed to send welcome email to user %s: %s", user.id, e, exc_info=True)
            return False

    @staticmethod
    def _send_onboarding_email(
        user: Any, email_type: str, template_name: str, subject: str, eligible_check: Any = None
    ) -> bool:
        """
        Generic helper to send an onboarding sequence email.

        Checks deduplication, eligibility, and handles record creation/failure tracking.
        """
        if not _is_mailable(user):
            return False

        # The opt-out is checked here as well as in the eligibility helpers, so
        # a backfill or an admin action cannot route around it the way the bot
        # guard above cannot be routed around either.
        status_for_optout = OnboardingStatus.objects.filter(user=user).first()
        if status_for_optout is not None and status_for_optout.drip_unsubscribed:
            logger.info("%s email suppressed: user %s unsubscribed", email_type, user.id)
            return False

        # Dedup check — only skip if successfully sent
        existing = OnboardingEmail.objects.filter(user=user, email_type=email_type).first()
        if existing and existing.status == OnboardingEmail.EmailStatus.SENT:
            logger.info("%s email already sent to user %s", email_type, user.id)
            return True

        # Check eligibility if a check function is provided
        if eligible_check is not None:
            try:
                is_eligible = eligible_check()
            except OperationalError:
                raise
            except Exception as e:
                logger.error("%s eligibility check failed for user %s: %s", email_type, user.id, e, exc_info=True)
                return False
            if not is_eligible:
                logger.info("%s email not eligible for user %s", email_type, user.id)
                return False

        context = get_email_context(user)
        rendered = _render_or_report(template_name, context, user.id)
        if rendered is None:
            return False
        html_content, plain_text_content = rendered

        # A refused address is remembered; a failed one is deleted so the next
        # pass can create a fresh record and try again.
        if existing and existing.suppresses(user.email):
            logger.info("%s email address previously refused for user %s, not retrying", email_type, user.id)
            return False
        if existing and (
            existing.status
            in (
                OnboardingEmail.EmailStatus.FAILED,
                OnboardingEmail.EmailStatus.UNDELIVERABLE,
            )
            or _is_abandoned(existing)
        ):
            # UNDELIVERABLE only reaches here when the address has changed
            # since; the guard above kept the row when it still applies.
            existing.delete()

        try:
            email_record = OnboardingEmail.create_email(user=user, email_type=email_type, subject=subject)
        except IntegrityError:
            # Concurrent worker — verify actual status before returning
            concurrent = OnboardingEmail.objects.filter(user=user, email_type=email_type).first()
            if concurrent and concurrent.status == OnboardingEmail.EmailStatus.SENT:
                return True
            logger.warning("%s email being processed by another worker for user %s", email_type, user.id)
            return False

        try:
            email = EmailMultiAlternatives(
                subject=email_record.subject,
                body=plain_text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
                reply_to=["hello@sbomify.com"],
                headers=_unsubscribe_headers(context.get("unsubscribe_url")),
            )
            email.attach_alternative(html_content, "text/html")
            email.send(fail_silently=False)
            email_record.mark_sent()
            logger.info("%s email sent successfully to user %s", email_type, user.id)
            return True
        except Exception as e:
            if _is_refused_address(e):
                email_record.mark_undeliverable(user.email, f"Address refused: {type(e).__name__}")
                logger.error("%s email address refused for user %s: %s", email_type, user.id, e)
                return False
            email_record.mark_failed(f"SMTP send failure: {type(e).__name__}")
            if _is_transient_send_error(e):
                logger.warning("Transient failure sending %s email to user %s: %s", email_type, user.id, e)
                raise TransientEmailError(f"{email_type} email to user {user.id}") from e
            logger.error("Failed to send %s email to user %s: %s", email_type, user.id, e, exc_info=True)
            return False

    @staticmethod
    def send_quick_start_email(user: Any) -> bool:
        """Send quick start guide email (day 1)."""
        status = OnboardingStatus.objects.filter(user=user).first()
        return OnboardingEmailService._send_onboarding_email(
            user,
            email_type=OnboardingEmail.EmailType.QUICK_START,
            template_name="quick_start",
            subject="Your quick start guide - sbomify",
            eligible_check=lambda: status is not None and status.should_receive_quick_start(),
        )

    @staticmethod
    def send_first_component_email(user: Any) -> bool:
        """Send first component reminder email (day 3, no component created)."""
        status = OnboardingStatus.objects.filter(user=user).first()
        return OnboardingEmailService._send_onboarding_email(
            user,
            email_type=OnboardingEmail.EmailType.FIRST_COMPONENT,
            template_name="first_component",
            subject="Ready to create your first component? - sbomify",
            eligible_check=lambda: status is not None and status.should_receive_component_reminder(days_threshold=3),
        )

    @staticmethod
    def send_first_sbom_email(user: Any) -> bool:
        """Send first SBOM upload reminder email (day 7, component exists but no SBOM)."""
        status = OnboardingStatus.objects.filter(user=user).first()
        return OnboardingEmailService._send_onboarding_email(
            user,
            email_type=OnboardingEmail.EmailType.FIRST_SBOM,
            template_name="first_sbom",
            subject="Time to upload your first SBOM - sbomify",
            eligible_check=lambda: status is not None and status.should_receive_sbom_reminder(days_threshold=7),
        )

    @staticmethod
    def send_collaboration_email(user: Any) -> bool:
        """Send collaboration/invite email (day 10, solo workspace)."""
        status = OnboardingStatus.objects.filter(user=user).first()
        return OnboardingEmailService._send_onboarding_email(
            user,
            email_type=OnboardingEmail.EmailType.COLLABORATION,
            template_name="collaboration",
            subject="Invite your team to sbomify",
            eligible_check=lambda: status is not None and status.should_receive_collaboration(),
        )

    @staticmethod
    def get_users_for_onboarding_sequence() -> dict[str, QuerySet[Any]]:
        """
        Get users eligible for each onboarding sequence email.

        Returns:
            Dict mapping email_type to list of eligible User objects
        """
        from django.contrib.auth import get_user_model

        from sbomify.apps.teams.models import Member

        User = get_user_model()
        results: dict[str, list[Any]] = {
            OnboardingEmail.EmailType.QUICK_START: [],
            OnboardingEmail.EmailType.FIRST_COMPONENT: [],
            OnboardingEmail.EmailType.FIRST_SBOM: [],
            OnboardingEmail.EmailType.COLLABORATION: [],
        }

        # Get all primary workspace owners with their onboarding status
        primary_owners = Member.objects.filter(
            role="owner",
            is_default_team=True,
        ).select_related("user", "team")

        sequence_types = [
            OnboardingEmail.EmailType.QUICK_START,
            OnboardingEmail.EmailType.FIRST_COMPONENT,
            OnboardingEmail.EmailType.FIRST_SBOM,
            OnboardingEmail.EmailType.COLLABORATION,
        ]
        # Emails that need no further attempt: sent, or refused by an address
        # the user still has. The send path checks the second one too, but only
        # after a task has been queued, its eligibility recomputed and its
        # template rendered — daily, for an address that is not going to start
        # working. Excluding it here is what makes that state stop costing
        # anything.
        settled_emails = set(
            OnboardingEmail.objects.filter(email_type__in=sequence_types)
            .filter(Q(status=OnboardingEmail.EmailStatus.SENT) | refused_at_current_address())
            .values_list("user_id", "email_type")
        )

        backfilled_status = 0
        skipped_errors = 0
        for member in primary_owners:
            try:
                # Synthetic OIDC bot identities have no row because the creation
                # signal refuses to make one — that absence is the intended
                # state, not a gap, and is a plausible source of the skipped
                # count in the first place. Backfilling them would resurrect a
                # row an operator deleted, on every run, and list a bot among
                # onboarding users. Checked with the same helper signals.py and
                # _is_mailable use, so the three cannot drift.
                if not _is_mailable(member.user):
                    continue

                # The row is created by a signal on user creation, so a human
                # primary owner without one predates that signal or was made by
                # a path that bypassed it. Every other call site in this app
                # reaches for it with get_or_create; this one used a bare get
                # and counted the miss, so those owners were stepped over on
                # every run and the count never converged or said who.
                #
                # Backdated to the account rather than to now. created_at is
                # what days_since_signup and the drip anchor are computed from,
                # so a fresh row would show "0 days since signup" on the admin
                # screen for someone who joined years ago, and would restart the
                # drip at day 0 if welcome_email_sent were ever set.
                status, created = OnboardingStatus.objects.get_or_create(user=member.user)
                if created:
                    joined = getattr(member.user, "date_joined", None)
                    if joined:
                        # Assigned and saved rather than update()+refresh: that
                        # was two round trips per backfilled row for a value
                        # already in hand. auto_now_add only fills the field on
                        # insert, so an explicit save on an existing row keeps
                        # what is assigned here.
                        status.created_at = joined
                        status.save(update_fields=["created_at"])
                    backfilled_status += 1

                user_id = member.user.id

                # Quick Start (day 1)
                if (
                    user_id,
                    OnboardingEmail.EmailType.QUICK_START,
                ) not in settled_emails and status.should_receive_quick_start(days_threshold=1):
                    results[OnboardingEmail.EmailType.QUICK_START].append(user_id)

                # First Component (day 3, no component)
                if (
                    user_id,
                    OnboardingEmail.EmailType.FIRST_COMPONENT,
                ) not in settled_emails and status.should_receive_component_reminder(days_threshold=3):
                    results[OnboardingEmail.EmailType.FIRST_COMPONENT].append(user_id)

                # First SBOM (day 7, component but no SBOM)
                if (
                    user_id,
                    OnboardingEmail.EmailType.FIRST_SBOM,
                ) not in settled_emails and status.should_receive_sbom_reminder(days_threshold=7):
                    results[OnboardingEmail.EmailType.FIRST_SBOM].append(user_id)

                # Collaboration (day 10, solo workspace)
                if (
                    user_id,
                    OnboardingEmail.EmailType.COLLABORATION,
                ) not in settled_emails and status.should_receive_collaboration(days_threshold=10):
                    results[OnboardingEmail.EmailType.COLLABORATION].append(user_id)
            except Exception as e:
                skipped_errors += 1
                logger.error("Error processing onboarding sequence for user %s: %s", member.user.id, e, exc_info=True)

        if backfilled_status:
            # Info, not warning: the gap is now closed by the time this is
            # written, and the count converges to zero instead of being
            # restated every day.
            logger.info(
                "Backfilled OnboardingStatus for %d primary owners during sequence processing",
                backfilled_status,
            )
        if skipped_errors:
            logger.error(
                "Failed to process %d primary owners during sequence processing",
                skipped_errors,
            )

        # Convert IDs to User querysets
        return {email_type: User.objects.filter(id__in=user_ids) for email_type, user_ids in results.items()}
