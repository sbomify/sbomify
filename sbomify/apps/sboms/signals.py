from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from sbomify.apps.core.services.transactions import run_on_commit
from sbomify.logging import getLogger

from .models import SBOM

logger = getLogger(__name__)


def _get_latest_release_ids_for_sbom(sbom_instance: SBOM) -> list[str]:
    """Return the auto-'latest' release ID for each product that contains this SBOM's component.

    This function is called from inside the on_commit callback of trigger_plugin_assessments.
    By that time, update_latest_release_on_sbom_created (registered in core/signals.py, which
    runs first because core precedes sboms in INSTALLED_APPS) has already created the
    ReleaseArtifact rows linking this SBOM to each product's 'latest' release.

    Design rationale (sbomify/sbomify#873, #881):
      Category A customers ("one thing, always current") never set PRODUCT_RELEASE and rely
      exclusively on the rolling 'latest' release for continuous DT/OSV scans. This function
      produces the release IDs for those scans.

      Category B customers ("multiple supported versions in parallel") also benefit: they get
      a 'latest' scan here, plus a separate per-named-release scan from the ReleaseArtifact
      signal handler (trigger_release_dependent_assessments).

    Returns an empty list if the component isn't linked to any product (no product membership
    = no 'latest' release context). Security plugins will not run for such SBOMs until the
    component is added to a project/product. This is documented expected behaviour.
    """
    from sbomify.apps.core.models import Component, Release, ReleaseArtifact

    try:
        component = Component.objects.get(id=sbom_instance.component_id)
    except Component.DoesNotExist:
        return []

    products = list(component.get_products())
    if not products:
        return []

    # By the time this runs (inside on_commit), update_latest_release_on_sbom_created
    # has already executed synchronously (it is not deferred). The ReleaseArtifact rows
    # linking this SBOM to each product's latest release should already be committed.
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
            # Fallback: get-or-create the latest release for this product. This covers the
            # rare case where update_latest_release_on_sbom_created was suppressed or the
            # component wasn't yet linked to the product at creation time.
            latest = Release.get_or_create_latest_release(product)
            release_ids.append(str(latest.id))

    return release_ids


@receiver(post_save, sender="core.ReleaseArtifact")
def trigger_release_dependent_assessments(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    """Enqueue security plugin assessments when an SBOM is linked to a named release.

    This is the Category B path (sbomify/sbomify#873, #881): customers who tag named
    releases (via PRODUCT_RELEASE in the CI action) get per-release vulnerability scans
    on top of the rolling 'latest' scan that trigger_plugin_assessments already provides.

    Category B examples: LTS branches (Django 4.2/5.x, Node LTS), CalVer with rolling
    support windows, medical device firmware (FDA — every shipped version tracked for years),
    EU CRA-regulated products (24h vulnerability reporting, 5+ year tracking per version).

    Fires only for newly-created ReleaseArtifact rows that:
    - link an SBOM (not a document)
    - belong to a named release (not the auto-maintained "latest" release)
    - are not being created under a _suppress_collection_signals context

    The "latest" release is skipped because trigger_plugin_assessments already scans
    against 'latest' on every SBOM upload. Firing here too for 'latest' would cause DT
    to run twice on upload without adding value.

    Defense-in-depth: before enqueueing, the handler verifies that the SBOM's component
    team matches the release's product team. The add_artifact_to_release utility enforces
    this at the API path, but direct ORM creation (admin actions, migrations, data fixups)
    can bypass that check. A mismatched link silently returns here rather than enqueueing
    plugin tasks under the wrong team.
    """
    if not created:
        return
    if instance.sbom_id is None:
        return

    # Honor the same suppression context used by sibling ReleaseArtifact handlers
    # (e.g., during bulk refresh_latest_artifacts). The is_latest guard below
    # covers the latest-release use case; this guard covers any future bulk
    # operations that may touch non-latest releases.
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

    Implements the two-path trigger model for sbomify's customer base
    (sbomify/sbomify#873, #881):

      Category A ("one thing, always current"): continuous deployment, trunk-based dev
        with feature flags (TrunkVer 2024), SemVer projects with no maintenance branches.
        These customers never set PRODUCT_RELEASE in the CI action. They need a rolling
        'latest' scan on every upload. This handler provides that.

      Category B ("multiple supported versions in parallel"): LTS branches, CalVer, FDA
        medical device firmware, EU CRA-regulated products. These customers tag releases
        via PRODUCT_RELEASE and need independent scan history per supported version. They
        get a 'latest' scan here PLUS a per-named-release scan from
        trigger_release_dependent_assessments when the ReleaseArtifact is created.

    The handler makes TWO calls to enqueue_assessments_for_sbom per SBOM upload:

      1. Compliance/attestation/license plugins: run once per SBOM regardless of release
         context. Results are deterministic on SBOM bytes — running them again per release
         would produce identical output. One call, no release_id.

      2. Security plugins (vulnerability scanners): run once per (sbom, product-latest-release)
         pair, so each product's DT/OSV project gets the rolling 'latest' scan updated.
         For Category A customers, this is the only scan they ever get. For Category B
         customers, an additional scan fires from trigger_release_dependent_assessments
         when the named-release ReleaseArtifact is created.

    EU CRA's 24-hour vulnerability reporting requirement (in force Sept 2026) means more
    scans is better than fewer. The additional scan cost for Category B customers
    (latest + named release) is acceptable; we keep the model simple and do not add
    deferred-check optimizations.

    Edge case: if a component is not linked to any product, no 'latest' release context
    exists and security plugins won't fire on upload. The SBOM must be associated with a
    product (via project membership) before security scanning can run. This is documented
    expected behaviour, not a bug.

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
                # --- Path 1: Compliance/attestation/license plugins ---
                # Run once per SBOM. Results are deterministic on SBOM bytes; release
                # context is irrelevant for these plugins.
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

                # --- Path 2: Security plugins ---
                # Run once per (sbom, product-latest-release) pair. Each product the component
                # belongs to gets its own 'latest' DT/OSV project scan.
                #
                # _get_latest_release_ids_for_sbom is called here (inside on_commit) rather than
                # at signal-fire time because update_latest_release_on_sbom_created (core/signals.py)
                # runs synchronously first — by the time this callback executes the ReleaseArtifact
                # rows already exist in the committed transaction.
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
