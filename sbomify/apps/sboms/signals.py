from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from sbomify.apps.core.services.transactions import run_on_commit
from sbomify.logging import getLogger

from .models import SBOM

logger = getLogger(__name__)


def _get_latest_release_ids_for_sbom(sbom_instance: SBOM) -> list[str]:
    """Return the auto-'latest' release ID for each product containing this SBOM's component.

    Called inside the on_commit callback of trigger_plugin_assessments. By that time,
    update_latest_release_on_sbom_created has already created the latest ReleaseArtifact
    rows. Returns an empty list if the component has no product membership.
    """
    from sbomify.apps.core.models import Component, Release, ReleaseArtifact

    try:
        component = Component.objects.get(id=sbom_instance.component_id)
    except Component.DoesNotExist:
        return []

    products = list(component.get_products())
    if not products:
        return []

    release_ids: list[str] = []
    for product in products:
        artifact = (
            ReleaseArtifact.objects.filter(sbom_id=sbom_instance.id, release__is_latest=True, release__product=product)
            .order_by("-created_at")
            .values_list("release_id", flat=True)
            .first()
        )
        if artifact is not None:
            release_ids.append(str(artifact))
        else:
            # Fallback for the rare case where the latest ReleaseArtifact wasn't created.
            latest = Release.get_or_create_latest_release(product)
            release_ids.append(str(latest.id))

    return release_ids


@receiver(post_save, sender="core.ReleaseArtifact")
def trigger_release_dependent_assessments(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Enqueue security plugin assessments when an SBOM is linked to a named release.

    Category B path (sbomify/sbomify#873, #881): customers tagging named releases via
    PRODUCT_RELEASE get per-release vulnerability scans on top of the rolling 'latest' scan
    that trigger_plugin_assessments already provides. Skips 'latest' (already covered by
    upload signal) and enforces a defense-in-depth cross-team check before enqueueing.
    """
    if not created:
        return
    if instance.sbom_id is None:
        return

    # Honor the suppression context used by bulk ReleaseArtifact operations.
    from sbomify.apps.core.models import Release, _suppress_collection_signals

    if _suppress_collection_signals.get(False):
        return

    release_info = Release.objects.filter(pk=instance.release_id).values_list("is_latest", "product__team_id").first()
    if release_info is None:
        logger.debug(
            "ReleaseArtifact %s has no reachable release/product/team, skipping plugin assessments",
            instance.pk,
        )
        return

    is_latest, team_id_value = release_info
    if is_latest:
        return

    # Defense-in-depth cross-team check. Loads the SBOM's component team via
    # a single values_list query and compares to the release's team. If the
    # chain is unreachable (missing component) or the teams differ, skip
    # with a log entry — we refuse to enqueue plugin work under a team that
    # doesn't own the SBOM.
    sbom_team_id_value = SBOM.objects.filter(pk=instance.sbom_id).values_list("component__team_id", flat=True).first()
    if sbom_team_id_value is None:
        logger.debug(
            "ReleaseArtifact %s references SBOM %s without a reachable component/team, skipping plugin assessments",
            instance.pk,
            instance.sbom_id,
        )
        return
    if sbom_team_id_value != team_id_value:
        logger.warning(
            "ReleaseArtifact %s links release team %s to SBOM %s owned by team %s; skipping plugin assessments",
            instance.pk,
            team_id_value,
            instance.sbom_id,
            sbom_team_id_value,
        )
        return

    team_id = str(team_id_value)

    from sbomify.apps.plugins.sdk.enums import RunReason
    from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom

    sbom_id = instance.sbom_id
    artifact_id = instance.pk
    release_id = str(instance.release_id)

    def _enqueue() -> None:
        try:
            enqueued = enqueue_assessments_for_sbom(
                sbom_id=sbom_id,
                team_id=team_id,
                run_reason=RunReason.ON_RELEASE_ASSOCIATION,
                # Only security plugins need per-release context. Compliance plugins are
                # deterministic on SBOM bytes and have already run on upload.
                only_categories={"security"},
                release_id=release_id,
            )
            if enqueued:
                logger.info(
                    "Enqueued %d release-dependent plugin assessments for SBOM %s (via ReleaseArtifact %s): %s",
                    len(enqueued),
                    sbom_id,
                    artifact_id,
                    enqueued,
                )
            else:
                logger.debug(
                    "No release-dependent plugins enqueued for SBOM %s (none enabled)",
                    sbom_id,
                )
        except Exception:
            logger.warning(
                "Failed to enqueue release-dependent plugin assessments for "
                "SBOM %s (message broker may be unavailable)",
                sbom_id,
                exc_info=True,
            )

    run_on_commit(_enqueue)


# License processing task has been removed - functionality moved to native model fields
# License processing is now handled directly during SBOM upload via ComponentLicense model


@receiver(post_save, sender=SBOM)
def trigger_plugin_assessments(sender: type[SBOM], instance: SBOM, created: bool, **kwargs: Any) -> None:
    """Trigger plugin assessments when a new SBOM is created.

    Two-path trigger model (sbomify/sbomify#873, #881):
      1. Compliance/attestation/license plugins run once per SBOM (deterministic on bytes).
      2. Security plugins (DT, OSV) run once per (sbom, product-latest-release) pair, so
         each product's DT/OSV project gets the rolling 'latest' scan updated.

    Category A customers (no PRODUCT_RELEASE) get only the 'latest' scan; Category B
    customers (named releases) get an additional per-named-release scan from
    trigger_release_dependent_assessments. Components without product membership get no
    security scans on upload — this is expected.

    Plugin access is controlled by:
    1. Team's enabled_plugins in TeamPluginSettings
    2. Plugin's global is_enabled flag in RegisteredPlugin
    3. Billing plan restrictions (enforced when enabling plugins)
    """
    if not created:
        return

    try:
        team = instance.component.team
    except AttributeError:
        logger.debug(f"SBOM {instance.id} has no component.team, skipping plugin assessments")
        return

    try:
        from sbomify.apps.plugins.sdk.enums import RunReason
        from sbomify.apps.plugins.tasks import enqueue_assessments_for_sbom

        logger.info(f"Triggering plugin assessments for SBOM {instance.id} (team: {team.key})")

        sbom_id = instance.id
        team_id = str(team.id)

        def _enqueue_assessments() -> None:
            try:
                # Compliance/attestation/license: once per SBOM, no release context.
                compliance_enqueued = enqueue_assessments_for_sbom(
                    sbom_id=sbom_id,
                    team_id=team_id,
                    run_reason=RunReason.ON_UPLOAD,
                    only_categories={"compliance", "attestation", "license"},
                )
                if compliance_enqueued:
                    logger.info(
                        f"Enqueued {len(compliance_enqueued)} compliance/attestation/license plugin "
                        f"assessments for SBOM {sbom_id}: {compliance_enqueued}"
                    )
                else:
                    logger.debug(f"No compliance/attestation/license plugin assessments enqueued for SBOM {sbom_id}")

                # Security plugins: once per (sbom, product-latest-release) pair.
                # Called inside on_commit so the latest ReleaseArtifact rows are already committed.
                latest_release_ids = _get_latest_release_ids_for_sbom(instance)
                if not latest_release_ids:
                    logger.debug(
                        f"SBOM {sbom_id} component is not linked to any product; "
                        "skipping security plugin assessments (no release context)"
                    )
                for latest_release_id in latest_release_ids:
                    security_enqueued = enqueue_assessments_for_sbom(
                        sbom_id=sbom_id,
                        team_id=team_id,
                        run_reason=RunReason.ON_UPLOAD,
                        only_categories={"security"},
                        release_id=latest_release_id,
                    )
                    if security_enqueued:
                        logger.info(
                            f"Enqueued {len(security_enqueued)} security plugin assessments for SBOM "
                            f"{sbom_id} (latest release {latest_release_id}): {security_enqueued}"
                        )
                    else:
                        logger.debug(
                            f"No security plugin assessments enqueued for SBOM {sbom_id} "
                            f"(latest release {latest_release_id})"
                        )

            except Exception:
                logger.warning(
                    f"Failed to enqueue plugin assessments for SBOM {sbom_id} (message broker may be unavailable)",
                    exc_info=True,
                )

        run_on_commit(_enqueue_assessments)

    except ImportError as e:
        logger.error(f"Failed to import plugin modules for SBOM {instance.id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error triggering plugin assessments for SBOM {instance.id}: {e}", exc_info=True)
