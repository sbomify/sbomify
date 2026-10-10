"""
Onboarding email services.
"""

from __future__ import annotations

import smtplib
from collections.abc import Callable
from contextlib import suppress
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import Error, IntegrityError, InterfaceError, OperationalError
from django.db.models import F, Q, QuerySet
from django.template import TemplateDoesNotExist, TemplateSyntaxError
from django.utils import timezone

from sbomify.logging import getLogger

from ..models import OnboardingEmail, OnboardingStatus
from ..utils import get_email_context, render_email_templates

logger = getLogger(__name__)

# Template, subject and eligibility check for each drip email.
DRIP_EMAILS: dict[str, tuple[str, str, Callable[[OnboardingStatus], bool]]] = {
    OnboardingEmail.EmailType.QUICK_START: (
        "quick_start",
        "Your quick start guide - sbomify",
        lambda status: status.should_receive_quick_start(),
    ),
    OnboardingEmail.EmailType.FIRST_COMPONENT: (
        "first_component",
        "Ready to create your first component? - sbomify",
        lambda status: status.should_receive_component_reminder(days_threshold=3),
    ),
    OnboardingEmail.EmailType.FIRST_SBOM: (
        "first_sbom",
        "Time to upload your first SBOM - sbomify",
        lambda status: status.should_receive_sbom_reminder(days_threshold=7),
    ),
    OnboardingEmail.EmailType.COLLABORATION: (
        "collaboration",
        "Invite your team to sbomify",
        lambda status: status.should_receive_collaboration(),
    ),
}


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


#: Database failures that are the connection rather than the query: a restart,
#: a failover, a connection the pooler closed under us. The ORM is reached all
#: over a send — the eligibility check, the context build, every record write —
#: so these arrive from places no single ``try`` here covers.
TRANSIENT_DB_ERRORS = (OperationalError, InterfaceError)


def is_retryable_failure(exc: BaseException) -> bool:
    """Whether a failure out of this module deserves another attempt.

    The sending tasks ask this to decide how loudly to report, so it has to
    cover what the send paths classify *and* what simply escapes them. A
    ``TransientEmailError`` has already been judged; a bare database transport
    error has not, because it comes from an ORM call rather than from the
    mailer, and wrapping every one of those at its call site would be a lot of
    ``try`` for one bit of information.
    """
    return isinstance(exc, (TransientEmailError, *TRANSIENT_DB_ERRORS))


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
        # per recipient. smtplib raises this only when the message reached none
        # of them, so a retry cannot duplicate anything — and a mixed 450/550
        # set is exactly when it is worth making: the 550 address refuses again
        # and the 450 address may accept. Requiring every code to be temporary
        # would drop the recipients that were only asked to wait.
        refusals = (exc.recipients or {}).values()
        return any(_is_temporary_smtp_code(code) for code, _ in refusals)
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


def _outcome_unknown(exc: BaseException) -> bool:
    """Whether a send that failed this way may still have been delivered.

    Only asked once the connection is open and the handoff is stamped. A server
    that answers with a code has said no, so nothing was accepted and another
    attempt cannot duplicate it. A connection that drops or times out mid
    conversation says nothing: the server may already have queued the message
    when the transport went, and a retry would send a second copy.
    """
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return True
    return isinstance(exc, OSError) and not isinstance(exc, smtplib.SMTPException)


def _close_quietly(connection: Any) -> None:
    """Close the mail connection without letting the close decide the outcome.

    QUIT can fail after the server has taken the message, and that is not a
    failed send.
    """
    with suppress(smtplib.SMTPException, OSError):
        connection.close()


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

    A row that was handed to the mailer is never abandoned, however old it is.
    Its worker died after SMTP may have accepted the message, so reclaiming it
    would re-send something the recipient already has; an unresolved
    handoff is settled by :func:`_settle_unknown_outcome` instead, once it is
    old enough that nothing is coming back for it.
    """
    return (
        record.status == OnboardingEmail.EmailStatus.PENDING
        and not record.handoff_unresolved
        and timezone.now() - record.created_at > ABANDONED_PENDING_AFTER
    )


#: How long a handoff may go unresolved before nobody is coming back for it.
#:
#: The sending actors declare ``time_limit=60000`` -- one minute -- so a send
#: still unresolved a quarter of an hour later is not in flight. Generous on
#: purpose: inside this window the right answer is "another worker has it", and
#: guessing early would settle a message that is seconds from being sent
#: properly, which is the one way this mechanism could lose the mail it exists
#: to protect.
HANDOFF_SETTLES_AFTER = timedelta(minutes=15)


#: How many times a write recording a send's outcome is attempted.
#:
#: The write that records what SMTP did is the one write that must not be lost:
#: a row left stamped and pending is eventually settled as sent, so a failure
#: nobody could record becomes a success nobody can see. A dropped connection
#: is the common case and it clears on the next attempt once Django is made to
#: open a fresh one.
OUTCOME_WRITE_ATTEMPTS = 3


def _persist_outcome(write: Callable[[], None], description: str) -> bool:
    """Record a send's outcome, surviving a connection that went away.

    Returns whether it landed. A caller that gets ``False`` has a row still
    stamped and pending, which the stale-handoff path will settle later -- so
    this failing is logged at error, because it is the step that turns a known
    outcome into an unknown one.

    ``connection.close()`` between attempts because a Django connection that
    has seen ``OperationalError`` stays broken; the next query opens a new one
    only if the old is closed first.
    """
    from django.db import connection

    for attempt in range(1, OUTCOME_WRITE_ATTEMPTS + 1):
        try:
            write()
            return True
        except TRANSIENT_DB_ERRORS as e:
            if attempt == OUTCOME_WRITE_ATTEMPTS:
                logger.error(
                    "Could not record %s after %d attempts; the row stays pending and will be "
                    "settled as unresolved: %s",
                    description,
                    attempt,
                    e,
                )
                return False
            logger.warning(
                "The write recording %s failed on attempt %d of %d; retrying: %s",
                description,
                attempt,
                OUTCOME_WRITE_ATTEMPTS,
                e,
            )
            # Only outside a transaction. A connection that has seen
            # OperationalError stays broken until it is closed, and the sends
            # run in autocommit so closing is the recovery. Inside an atomic
            # block it would abort the transaction instead, which is a worse
            # outcome than the one being recovered from.
            if not connection.in_atomic_block:
                try:
                    connection.close()
                except Error:  # Django drops the connection even when closing fails; the next attempt reconnects
                    pass
    return False


def _handoff_is_stale(record: OnboardingEmail) -> bool:
    """Whether a handoff has gone unresolved long enough to be nobody's.

    A stamped row inside the window is a live send in another worker, not an
    orphan. The pre-send window -- stamp written, SMTP not yet called -- lives
    inside it too, so a crash there is not settled on the next pass either; it
    waits for the lease like any other unresolved handoff.
    """
    if not record.handoff_unresolved or record.handed_to_mailer_at is None:
        return False
    return timezone.now() - record.handed_to_mailer_at > HANDOFF_SETTLES_AFTER


def _settle_unknown_outcome(record: OnboardingEmail) -> None:
    """Resolve a row that was handed to the mailer and never finished.

    Only ever called for a handoff past ``HANDOFF_SETTLES_AFTER``, so the send
    it belonged to is not in flight and nothing else is coming to finish it.

    Recorded as sent, because that is the only reading that cannot make things
    worse. The message was given to SMTP; whether it was accepted is no longer
    knowable from here, and the two mistakes are not equal. Calling it failed
    re-sends a message the recipient may already have, every pass, for as long
    as they stay eligible. Calling it sent risks one welcome that never
    arrived, for a user whose signup coincided with the database going away
    between the handoff and the next statement.

    Logged at error because it is a real loss of certainty, and rare enough
    that a human should see each one.
    """
    logger.error(
        "Email %s for user %s was handed to the mailer at %s and never resolved; "
        "recording it as sent rather than risking a duplicate",
        record.email_type,
        record.user_id,
        record.handed_to_mailer_at,
    )
    record.mark_sent()


def _is_refused_address(exc: BaseException) -> bool:
    """Whether the server refused this recipient for good.

    Narrower than "permanent" on purpose. A 552 over-size, a 535 bad
    credential and a refused *sender* are all terminal for the attempt, but
    they are faults on our side: fix the template or the relay config and the
    next batch pass delivers. Marking those undeliverable would strand every
    user behind one misconfiguration, and nothing would clear it.

    A 5xx against the recipient is the one that says the address will not exist
    on the next attempt either, so it is the only one worth remembering.

    Every code 5xx, which is the exact complement of
    :func:`_is_transient_send_error`'s any-4xx rule, so a refusal lands in one
    branch or the other and never both.

    An earlier version of this asked for *any* 5xx. That overlapped the
    transient rule on a mixed 450/550 set and won, so a recipient the server
    had only asked us to wait for was recorded as permanently undeliverable.
    These messages carry a single recipient, where any and all agree -- but
    the overlap was real, and the retry is the right answer when the two
    disagree: smtplib raises ``SMTPRecipientsRefused`` only when no recipient
    accepted, so another attempt cannot duplicate a delivery.
    """
    if not isinstance(exc, smtplib.SMTPRecipientsRefused):
        return False
    refusals = [code for code, _ in (exc.recipients or {}).values()]
    return bool(refusals) and all(isinstance(code, int) and 500 <= code < 600 for code in refusals)


def _render_or_report(template_name: str, context: dict[str, Any], user_id: Any) -> tuple[str, str] | None:
    """Render a message, or report a broken template and answer ``None``.

    Rendering sits outside the send block, so without this a missing or broken
    template left the service as an ordinary exception, and the task re-raised
    it into dramatiq's retry budget. Three more attempts run the same template
    against the same context and fail the same way: a template is not a
    transport, and no amount of waiting repairs one.

    Only the two failures that say *the template itself is wrong* are caught.
    Rendering also touches things that break for a while and then stop — a
    loader reading from disk, a tag that queries — and swallowing those would
    acknowledge the message and spend none of the retry budget this exists to
    protect. Anything else leaves here and reaches the actor, which is what
    gets another attempt.
    """
    try:
        return render_email_templates(template_name, context)
    except (TemplateDoesNotExist, TemplateSyntaxError) as e:
        logger.error("Failed to render %s email for user %s: %s", template_name, user_id, e, exc_info=True)
        return None
    except (OSError, *TRANSIENT_DB_ERRORS) as e:
        # Classified here rather than left to the task: the answer to "is this
        # worth retrying" belongs on the exception, so one place decides it.
        # Letting these reach the actor unlabelled retried them, but wrote an
        # error-level line — and so a Sentry issue — on every attempt, which is
        # the reporting this change exists to stop.
        logger.warning("Transient failure rendering %s email for user %s: %s", template_name, user_id, e)
        raise TransientEmailError(f"{template_name} template for user {user_id}") from e


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
            True if the email was sent or had already been sent, False if it
            failed for a reason another attempt cannot fix: a refused address,
            a template that will not render, a recipient we must not mail.

        Raises:
            TransientEmailError: the attempt failed for a reason that may not
                recur, so the caller's retry budget should be spent on it. A
                caller that reads every failure as ``False`` will acknowledge
                the message and drop the email instead; the sending actors
                deliberately let this one out.
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
        if existing and existing.handoff_unresolved:
            if not _handoff_is_stale(existing):
                # Another worker is mid-send. Not ours to settle or to repeat.
                logger.info("Welcome email for user %s is already in flight, leaving it", user.id)
                return False
            _settle_unknown_outcome(existing)
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

        connection = get_connection(fail_silently=False)
        handed_over = False
        try:
            email = EmailMultiAlternatives(
                subject=email_record.subject,
                body=plain_text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
                reply_to=["hello@sbomify.com"],
                connection=connection,
                # Welcome opens the sequence, so it carries the opt-out too. It
                # is not suppressed by one (nobody can unsubscribe before their
                # first email), but bulk-sender rules look at the header, not at
                # our reasoning about which message is transactional.
                headers=_unsubscribe_headers(context.get("unsubscribe_url")),
            )
            email.attach_alternative(html_content, "text/html")
            # Connected before the stamp: a mail host that cannot be reached
            # fails here, before anything is handed over, and stays a retry.
            connection.open()
            # Stamped before the handoff, not after: everything past this line
            # may fail to record what SMTP did with the message, and a row that
            # says nothing is one a later pass will send again.
            email_record.mark_handed_to_mailer()
            handed_over = True
            email.send(fail_silently=False)
        except Exception as e:
            if handed_over and _outcome_unknown(e):
                # The server may have taken the message before the connection
                # went. A recorded failure would have the retry send it again,
                # so the row stays handed over for the stale-handoff path.
                logger.warning(
                    "%s email to user %s may have been delivered before the connection failed (%s); "
                    "leaving it for the stale-handoff path",
                    email_record.email_type,
                    user.id,
                    type(e).__name__,
                )
                return False
            if _is_refused_address(e):
                # Bound out of the lambda: ``except ... as e`` unbinds ``e``
                # at the end of the block, and the write may run after that.
                refusal = f"Address refused: {type(e).__name__}"
                if not _persist_outcome(
                    lambda: email_record.mark_undeliverable(user.email, refusal),
                    f"a refused address for user {user.id}",
                ):
                    # The refusal is known and unrecorded. Returning here would
                    # acknowledge the message and leave a stamped row for the
                    # stale-handoff path to settle as sent, so a known refusal
                    # would read as a delivery. Raise instead: the retry runs
                    # while the database may still come back.
                    raise TransientEmailError(f"recording a refusal for user {user.id}") from e
                logger.error("Welcome email address refused for user %s: %s", user.id, e)
                return False
            failure = f"SMTP send failure: {type(e).__name__}"
            if not _persist_outcome(
                lambda: email_record.mark_failed(failure),
                f"a failed send for user {user.id}",
            ):
                # See above: an unrecorded failure must not be acknowledged.
                raise TransientEmailError(f"recording a failed send for user {user.id}") from e
            # The database errors as well as the SMTP ones. The handoff stamp
            # is written inside this try, so a connection that goes away there
            # arrives here looking like a send failure; recording it as one
            # drops the email, because the task acknowledges a ``False`` return
            # and nothing retries it.
            if _is_transient_send_error(e) or isinstance(e, TRANSIENT_DB_ERRORS):
                logger.warning("Transient failure sending welcome email to user %s: %s", user.id, e)
                raise TransientEmailError(f"welcome email to user {user.id}") from e
            logger.error("Failed to send welcome email to user %s: %s", user.id, e, exc_info=True)
            return False
        finally:
            _close_quietly(connection)

        # Past the send, so nothing below may rewrite the record to FAILED: a
        # delivered email recorded as failed makes the recovery sweep send a
        # second copy instead of letting _reconcile_welcome_flag repair the
        # flag. If the bookkeeping itself fails, the row is already SENT and
        # the next attempt reconciles.
        # The flag only once the row says sent. Setting it against a row still
        # pending would leave the two disagreeing, and the flag is what the
        # recovery sweep reads: it would stop looking while the row said the
        # outcome was never recorded. If the record write landed and this one
        # does not, the next pass repairs it through _reconcile_welcome_flag.
        if _persist_outcome(email_record.mark_sent, f"a successful send for user {user.id}"):
            if not _persist_outcome(onboarding_status.mark_welcome_email_sent, f"the welcome flag for user {user.id}"):
                # The row says sent and the flag does not, and only the sweep's
                # seven-day window would ever look again. Raise: the retry finds
                # the SENT row and repairs the flag without sending again.
                raise TransientEmailError(f"recording the welcome flag for user {user.id}")
        logger.info("Welcome email sent successfully to user %s", user.id)
        return True

    @staticmethod
    def _send_onboarding_email(
        user: Any, email_type: str, template_name: str, subject: str, eligible_check: Any = None
    ) -> bool:
        """
        Generic helper to send an onboarding sequence email.

        Checks deduplication, eligibility, and handles record creation/failure tracking.

        Returns and raises as :meth:`send_welcome_email` does: ``False`` for a
        failure another attempt cannot fix, ``TransientEmailError`` for one it
        might.
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
        if existing and existing.handoff_unresolved:
            if not _handoff_is_stale(existing):
                logger.info("%s email for user %s is already in flight, leaving it", email_type, user.id)
                return False
            _settle_unknown_outcome(existing)
        if existing and existing.status == OnboardingEmail.EmailStatus.SENT:
            logger.info("%s email already sent to user %s", email_type, user.id)
            return True

        # Check eligibility if a check function is provided
        if eligible_check is not None:
            try:
                is_eligible = eligible_check()
            except TRANSIENT_DB_ERRORS:
                # The whole transport, not just OperationalError: an
                # InterfaceError is the same connection going away, and the
                # broad handler below would have read it as "not eligible" and
                # dropped the mail.
                raise
            except Exception as e:
                logger.error("%s eligibility check failed for user %s: %s", email_type, user.id, e, exc_info=True)
                return False
            if not is_eligible:
                logger.info("%s email not eligible for user %s", email_type, user.id)
                return False

        # Settled before rendering, as on the welcome path: an address the
        # server has refused should not cost a context build and a template
        # render on every direct retry.
        #
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

        context = get_email_context(user)
        rendered = _render_or_report(template_name, context, user.id)
        if rendered is None:
            return False
        html_content, plain_text_content = rendered

        try:
            email_record = OnboardingEmail.create_email(user=user, email_type=email_type, subject=subject)
        except IntegrityError:
            # Concurrent worker — verify actual status before returning
            concurrent = OnboardingEmail.objects.filter(user=user, email_type=email_type).first()
            if concurrent and concurrent.status == OnboardingEmail.EmailStatus.SENT:
                return True
            logger.warning("%s email being processed by another worker for user %s", email_type, user.id)
            return False

        connection = get_connection(fail_silently=False)
        handed_over = False
        try:
            email = EmailMultiAlternatives(
                subject=email_record.subject,
                body=plain_text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
                reply_to=["hello@sbomify.com"],
                connection=connection,
                headers=_unsubscribe_headers(context.get("unsubscribe_url")),
            )
            email.attach_alternative(html_content, "text/html")
            # Connected before the stamp: a mail host that cannot be reached
            # fails here, before anything is handed over, and stays a retry.
            connection.open()
            # Stamped before the handoff, not after: everything past this line
            # may fail to record what SMTP did with the message, and a row that
            # says nothing is one a later pass will send again.
            email_record.mark_handed_to_mailer()
            handed_over = True
            email.send(fail_silently=False)
        except Exception as e:
            if handed_over and _outcome_unknown(e):
                # See the welcome path: possibly delivered, so not repeated.
                logger.warning(
                    "%s email to user %s may have been delivered before the connection failed (%s); "
                    "leaving it for the stale-handoff path",
                    email_record.email_type,
                    user.id,
                    type(e).__name__,
                )
                return False
            if _is_refused_address(e):
                # Bound out of the lambda: ``except ... as e`` unbinds ``e``
                # at the end of the block, and the write may run after that.
                refusal = f"Address refused: {type(e).__name__}"
                if not _persist_outcome(
                    lambda: email_record.mark_undeliverable(user.email, refusal),
                    f"a refused address for user {user.id}",
                ):
                    # The refusal is known and unrecorded. Returning here would
                    # acknowledge the message and leave a stamped row for the
                    # stale-handoff path to settle as sent, so a known refusal
                    # would read as a delivery. Raise instead: the retry runs
                    # while the database may still come back.
                    raise TransientEmailError(f"recording a refusal for user {user.id}") from e
                logger.error("%s email address refused for user %s: %s", email_type, user.id, e)
                return False
            failure = f"SMTP send failure: {type(e).__name__}"
            if not _persist_outcome(
                lambda: email_record.mark_failed(failure),
                f"a failed send for user {user.id}",
            ):
                # See above: an unrecorded failure must not be acknowledged.
                raise TransientEmailError(f"recording a failed send for user {user.id}") from e
            # See the welcome path: a database error while stamping the handoff
            # is not a send failure, and recording it as one drops the email.
            if _is_transient_send_error(e) or isinstance(e, TRANSIENT_DB_ERRORS):
                logger.warning("Transient failure sending %s email to user %s: %s", email_type, user.id, e)
                raise TransientEmailError(f"{email_type} email to user {user.id}") from e
            logger.error("Failed to send %s email to user %s: %s", email_type, user.id, e, exc_info=True)
            return False
        finally:
            _close_quietly(connection)

        # See the welcome path: the record must not go back to FAILED once the
        # message has left.
        _persist_outcome(email_record.mark_sent, f"a successful send for user {user.id}")
        logger.info("%s email sent successfully to user %s", email_type, user.id)
        return True

    @staticmethod
    def send_drip_email(user: Any, email_type: str) -> bool:
        """Send one drip email: quick start, first component, first SBOM or collaboration."""
        template_name, subject, is_due = DRIP_EMAILS[email_type]
        status = OnboardingStatus.objects.filter(user=user).first()
        return OnboardingEmailService._send_onboarding_email(
            user,
            email_type=email_type,
            template_name=template_name,
            subject=subject,
            eligible_check=lambda: status is not None and is_due(status),
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
