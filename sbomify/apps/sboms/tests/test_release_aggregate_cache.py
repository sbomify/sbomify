"""Tests for aggregated release/product SBOM caching + builder query cleanup (#998)."""

import json

import pytest

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.tests.s3_fixtures import s3_sboms_mock  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import team_with_business_plan  # noqa: F401
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.utils import get_release_sbom_package


def _make_member_sbom(team, s3_mock, name: str) -> SBOM:
    """Create a PUBLIC component + SBOM whose bytes live in the mocked S3."""
    component = Component.objects.create(
        name=f"{name}-comp",
        team=team,
        visibility=Component.Visibility.PUBLIC,
        component_type=Component.ComponentType.BOM,
    )
    body = json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {"component": {"name": name, "type": "library", "version": "1.0.0"}},
            "components": [],
        }
    ).encode()
    filename = f"{name}.json"
    s3_mock.uploaded_files[filename] = body
    return SBOM.objects.create(
        name=name, component=component, format="cyclonedx", version="1.0.0", sbom_filename=filename
    )


def _public_release(team, s3_mock, *, member_names=("alpha", "beta")) -> Release:
    product = Product.objects.create(name="CacheProd", team=team, is_public=True)
    release = Release.objects.create(product=product, name="v1.0.0")
    for nm in member_names:
        ReleaseArtifact.objects.create(release=release, sbom=_make_member_sbom(team, s3_mock, nm))
    return release


@pytest.mark.django_db
class TestAggregateCache:
    def test_cache_hit_serves_without_refetching_members(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        team = team_with_business_plan
        release = _public_release(team, s3_sboms_mock)
        member_files = {a.sbom.sbom_filename for a in release.artifacts.all()}

        # Cold build: members are fetched and a cache object is written.
        s3_sboms_mock.get_calls.clear()
        first = get_release_sbom_package(release, tmp_path, output_format="cyclonedx").read_bytes()
        assert member_files & set(s3_sboms_mock.get_calls), "cold build should fetch members"
        cache_keys = [k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/release/")]
        assert len(cache_keys) == 1

        # Warm build: served from cache — members are NOT re-fetched.
        s3_sboms_mock.get_calls.clear()
        second = get_release_sbom_package(release, tmp_path, output_format="cyclonedx").read_bytes()
        assert not (member_files & set(s3_sboms_mock.get_calls)), "warm build must not re-fetch members"
        assert cache_keys[0] in s3_sboms_mock.get_calls
        assert first == second

    def test_changed_artifact_set_busts_cache(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        team = team_with_business_plan
        release = _public_release(team, s3_sboms_mock)
        get_release_sbom_package(release, tmp_path, output_format="cyclonedx")  # cold build creates the cache
        keys_before = {k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/")}
        assert len(keys_before) == 1

        # Add a third member -> new artifact-set hash -> new cache key -> rebuild.
        ReleaseArtifact.objects.create(release=release, sbom=_make_member_sbom(team, s3_sboms_mock, "gamma"))
        s3_sboms_mock.get_calls.clear()
        rebuilt = get_release_sbom_package(release, tmp_path, output_format="cyclonedx").read_bytes()

        assert "gamma.json" in s3_sboms_mock.get_calls, "changed set must re-fetch members"
        # GC: the new fingerprint replaces the old; the orphaned key is reclaimed.
        keys_after = {k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/")}
        assert len(keys_after) == 1
        assert keys_after != keys_before
        assert b"gamma" in rebuilt

    def test_member_visibility_change_busts_cache(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        """A member flipping PUBLIC->PRIVATE drops out of a public aggregate, so
        the cache key MUST change — otherwise the stale doc would keep exposing a
        now-private member. (Visibility is part of the artifact-set hash.)
        """
        team = team_with_business_plan
        release = _public_release(team, s3_sboms_mock)
        first = get_release_sbom_package(release, tmp_path, output_format="cyclonedx").read_bytes()
        keys_before = {k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/")}
        assert len(keys_before) == 1

        member = release.artifacts.order_by("sbom__id").first().sbom
        member.component.visibility = Component.Visibility.PRIVATE
        member.component.save()

        rebuilt = get_release_sbom_package(release, tmp_path, output_format="cyclonedx").read_bytes()
        keys_after = {k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/")}
        assert keys_after != keys_before, "visibility change must produce a new cache key"
        # GC reclaims the orphaned key, so only the new one remains.
        assert len(keys_after) == 1
        # The now-private member is excluded from the rebuilt public aggregate.
        assert rebuilt != first

    def test_product_rename_busts_cache(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        """The aggregate embeds the product/release name, so a rename (same
        artifact set) must bust the cache and rebuild — not serve the old name.
        """
        team = team_with_business_plan
        release = _public_release(team, s3_sboms_mock)
        get_release_sbom_package(release, tmp_path, output_format="cyclonedx")
        keys_before = {k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/")}
        assert len(keys_before) == 1

        release.product.name = "Renamed Product"
        release.product.save()

        rebuilt = get_release_sbom_package(release, tmp_path, output_format="cyclonedx").read_bytes()
        keys_after = {k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/")}
        assert keys_after != keys_before, "a product rename must bust the cache"
        assert b"Renamed Product" in rebuilt

    def test_private_member_change_does_not_bust_cache(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        """A PRIVATE member never appears in a public aggregate, so changing it
        must NOT bust the public cache — only the included (public) members do.
        """
        team = team_with_business_plan
        release = _public_release(team, s3_sboms_mock)
        priv = _make_member_sbom(team, s3_sboms_mock, "secret")
        priv.component.visibility = Component.Visibility.PRIVATE
        priv.component.save()
        ReleaseArtifact.objects.create(release=release, sbom=priv)

        get_release_sbom_package(release, tmp_path, output_format="cyclonedx")  # cold build creates the cache
        keys_before = {k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/")}
        assert len(keys_before) == 1

        # Replace the PRIVATE member's content (new filename); the public aggregate is unchanged.
        s3_sboms_mock.uploaded_files["secret-v2.json"] = s3_sboms_mock.uploaded_files["secret.json"]
        priv.sbom_filename = "secret-v2.json"
        priv.save()

        s3_sboms_mock.get_calls.clear()
        get_release_sbom_package(release, tmp_path, output_format="cyclonedx")
        keys_after = {k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/")}
        assert keys_after == keys_before, "a private-member change must not bust the public cache"
        assert "alpha.json" not in s3_sboms_mock.get_calls, "should have been a cache hit"

    def test_private_product_is_not_cached(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        team = team_with_business_plan
        release = _public_release(team, s3_sboms_mock)
        release.product.is_public = False
        release.product.save()

        get_release_sbom_package(release, tmp_path, output_format="cyclonedx")
        get_release_sbom_package(release, tmp_path, output_format="cyclonedx")

        assert not [k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/")]

    def test_incomplete_build_is_not_cached(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        """If a member fetch fails (transient S3 error -> member skipped), the
        partial aggregate must NOT be cached — otherwise the incomplete document
        would be frozen under this artifact-set hash indefinitely.
        """
        team = team_with_business_plan
        release = _public_release(team, s3_sboms_mock)
        # Simulate a transient fetch failure: drop one member's bytes from S3.
        missing = release.artifacts.order_by("sbom__id").first().sbom
        s3_sboms_mock.uploaded_files.pop(missing.sbom_filename, None)

        get_release_sbom_package(release, tmp_path, output_format="cyclonedx")

        assert not [
            k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/")
        ], "an incomplete build (skipped member) must not be cached"

    def test_malicious_names_cannot_escape_target_folder(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        """Product/release names are user-controlled; the built file must stay a
        basename inside target_folder even if a name contains path separators.
        """
        team = team_with_business_plan
        release = _public_release(team, s3_sboms_mock)
        release.product.name = "../../evil"
        release.product.save()
        release.name = "../escape"
        release.save()

        path = get_release_sbom_package(release, tmp_path, output_format="cyclonedx")
        assert path.resolve().parent == tmp_path.resolve(), "build must not escape target_folder"

    def test_spdx_builder_no_redundant_per_artifact_sbom_get(
        self, tmp_path, team_with_business_plan, s3_sboms_mock, mocker  # noqa: F811
    ):
        team = team_with_business_plan
        release = _public_release(team, s3_sboms_mock, member_names=("one", "two", "three"))

        get_spy = mocker.patch.object(SBOM.objects, "get", wraps=SBOM.objects.get)
        get_release_sbom_package(release, tmp_path, output_format="spdx")
        # The builders use the select_related-loaded artifact.sbom, so they must
        # not issue a per-artifact SBOM.objects.get during aggregation.
        assert get_spy.call_count == 0

    def test_gc_preserves_other_formats(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        """GC scopes to the format+version prefix, so busting cyclonedx must not
        delete the still-valid spdx aggregate (or vice versa)."""
        team = team_with_business_plan
        release = _public_release(team, s3_sboms_mock)
        get_release_sbom_package(release, tmp_path, output_format="cyclonedx")
        get_release_sbom_package(release, tmp_path, output_format="spdx")
        spdx_before = {k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/") and "spdx-" in k}
        assert len(spdx_before) == 1

        # Change the artifact set and rebuild ONLY cyclonedx.
        ReleaseArtifact.objects.create(release=release, sbom=_make_member_sbom(team, s3_sboms_mock, "gamma"))
        get_release_sbom_package(release, tmp_path, output_format="cyclonedx")

        cdx_keys = {k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/") and "cyclonedx-" in k}
        spdx_after = {k for k in s3_sboms_mock.uploaded_files if k.startswith("aggregates/") and "spdx-" in k}
        assert len(cdx_keys) == 1, "stale cyclonedx fingerprint should be reclaimed"
        assert spdx_after == spdx_before, "the spdx aggregate must survive a cyclonedx bust"

    def test_gc_is_best_effort(
        self, tmp_path, team_with_business_plan, s3_sboms_mock, mocker  # noqa: F811
    ):
        """A delete failure during GC must never fail the download — the freshly
        built aggregate is still served."""
        team = team_with_business_plan
        release = _public_release(team, s3_sboms_mock)
        get_release_sbom_package(release, tmp_path, output_format="cyclonedx")  # cold build -> key K1

        ReleaseArtifact.objects.create(release=release, sbom=_make_member_sbom(team, s3_sboms_mock, "gamma"))
        mocker.patch.object(s3_sboms_mock, "delete_cached_aggregate", side_effect=Exception("boom"))

        rebuilt = get_release_sbom_package(release, tmp_path, output_format="cyclonedx").read_bytes()
        assert b"gamma" in rebuilt, "download must succeed even when GC delete fails"

    def test_parallel_member_fetch_includes_every_member(
        self, tmp_path, team_with_business_plan, s3_sboms_mock  # noqa: F811
    ):
        """Members are fetched concurrently; every one must land in the aggregate
        exactly once (the parallel prefetch must not drop or duplicate members)."""
        team = team_with_business_plan
        names = ("alpha", "beta", "gamma", "delta", "epsilon")
        release = _public_release(team, s3_sboms_mock, member_names=names)

        built = json.loads(get_release_sbom_package(release, tmp_path, output_format="cyclonedx").read_bytes())
        member_components = [c["name"] for c in built["components"]]
        assert sorted(member_components) == sorted(f"{release.name}/{n}" for n in names)
        assert len(member_components) == len(names), "no member dropped or duplicated by the parallel fetch"
