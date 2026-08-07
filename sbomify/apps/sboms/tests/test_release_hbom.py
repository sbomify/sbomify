"""Merged release-level HBOM: one hardware BOM per release, built from the HBOM
artifacts pinned in the release's slots, gated like the SBOM/VEX/CBOM downloads."""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.sboms.hbom import build_release_hbom
from sbomify.apps.sboms.models import SBOM


def _release_with_components(team, *, is_public: bool):
    product = Product.objects.create(name="P", team=team, is_public=is_public)
    release = Release.objects.create(product=product, name="v1")
    c1 = Component.objects.create(name="c1", team=team)
    c2 = Component.objects.create(name="c2", team=team)
    return product, release, c1, c2


def _hbom_sbom(component, filename: str, version: str = "") -> SBOM:
    return SBOM.objects.create(
        name=f"hbom-{filename}",
        version=version,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename=filename,
        component=component,
        bom_type=SBOM.BomType.HBOM,
    )


def _doc(*refs: str, board: str | None = None, dependencies: list | None = None) -> bytes:
    document: dict = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [{"type": "device", "bom-ref": ref, "name": ref} for ref in refs],
    }
    if board is not None:
        document["metadata"] = {"component": {"type": "device", "bom-ref": board, "name": board}}
    if dependencies is not None:
        document["dependencies"] = dependencies
    return json.dumps(document).encode()


def _mock_s3(mocker, docs_by_filename: dict[str, bytes]):
    """Patch the reader method, never the S3Client class itself.

    Replacing the class rebinds the name in object_store, and any module that
    has not yet been imported binds the mock permanently when it is — teardown
    restores object_store but cannot reach the copy the importer kept. That is
    a leak into whichever test happens to import sboms.apis first, and it
    surfaces there as an unrelated upload failure.
    """
    return mocker.patch(
        "sbomify.apps.core.object_store.S3Client.get_sbom_data",
        side_effect=lambda filename: docs_by_filename[filename],
    )


@pytest.mark.django_db
def test_build_release_hbom_merges_slot_documents(sample_team_with_owner_member, mocker):
    team = sample_team_with_owner_member.team
    _product, release, c1, c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "c1.hbom.json"))
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c2, "c2.hbom.json"))
    _mock_s3(mocker, {"c1.hbom.json": _doc("part/a"), "c2.hbom.json": _doc("part/b")})

    merged = build_release_hbom(release)

    assert merged is not None
    assert {c["bom-ref"] for c in merged["components"]} == {"part/a", "part/b"}


@pytest.mark.django_db
def test_build_release_hbom_lifts_metadata_device(sample_team_with_owner_member, mocker):
    """The board an HBOM describes lives in metadata.component; the merged
    inventory must carry it, not just its parts."""
    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "board.hbom.json"))
    _mock_s3(mocker, {"board.hbom.json": _doc("part/a", board="board-1")})

    merged = build_release_hbom(release)

    assert {c["bom-ref"] for c in merged["components"]} == {"board-1", "part/a"}


@pytest.mark.django_db
def test_two_boards_reusing_a_ref_keep_both_parts(sample_team_with_owner_member, mocker):
    """bom-ref is scoped to its document, so the same string in two members names
    two different physical parts.

    Collapsing them loses a whole board from the release inventory, which is why
    the colliding member is re-keyed instead of dropped.
    """
    team = sample_team_with_owner_member.team
    _product, release, c1, c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "a.hbom.json"))
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c2, "b.hbom.json"))
    _mock_s3(
        mocker,
        {
            "a.hbom.json": _doc("shared-cap", "conn-a", dependencies=[{"ref": "shared-cap", "dependsOn": ["conn-a"]}]),
            "b.hbom.json": _doc("shared-cap", "conn-b", dependencies=[{"ref": "shared-cap", "dependsOn": ["conn-b"]}]),
        },
    )

    merged = build_release_hbom(release)
    refs = [c["bom-ref"] for c in merged["components"]]

    # Four parts went in and four come out; none was silently dropped.
    assert len(refs) == 4
    assert len(set(refs)) == 4, f"a ref repeats, so a consumer cannot tell the parts apart: {refs}"
    assert {"conn-a", "conn-b"} <= set(refs)
    # The first member keeps its refs, so a single-HBOM download is unchanged.
    assert "shared-cap" in refs


@pytest.mark.django_db
def test_a_rekeyed_ref_carries_its_edges_with_it(sample_team_with_owner_member, mocker):
    """Re-keying is only correct if the document's own edges follow. An edge left
    pointing at the original string would reparent one board's parts onto
    another's node, which is the same corruption by a different route."""
    team = sample_team_with_owner_member.team
    _product, release, c1, c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "a.hbom.json"))
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c2, "b.hbom.json"))
    _mock_s3(
        mocker,
        {
            "a.hbom.json": _doc("root", "conn-a", dependencies=[{"ref": "root", "dependsOn": ["conn-a"]}]),
            "b.hbom.json": _doc("root", "conn-b", dependencies=[{"ref": "root", "dependsOn": ["conn-b"]}]),
        },
    )

    merged = build_release_hbom(release)
    edges = {d["ref"]: set(d["dependsOn"]) for d in merged["dependencies"]}
    refs = {c["bom-ref"] for c in merged["components"]}

    # Two distinct roots, each owning only its own connector.
    assert len(edges) == 2, f"the two boards' roots collapsed into one node: {edges}"
    assert {frozenset(t) for t in edges.values()} == {frozenset({"conn-a"}), frozenset({"conn-b"})}
    # Every edge endpoint resolves to a component that is actually present.
    for ref, targets in edges.items():
        assert ref in refs, f"edge source {ref} names no component in the merged document"
        assert targets <= refs, f"edge from {ref} points outside the document: {targets - refs}"


@pytest.mark.django_db
def test_a_repeated_ref_inside_one_document_still_collapses(sample_team_with_owner_member, mocker):
    """A repeat within a single member is a malformed document, not a collision,
    and stays deduplicated."""
    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "a.hbom.json"))
    _mock_s3(mocker, {"a.hbom.json": _doc("dup", "dup", "other")})

    merged = build_release_hbom(release)
    refs = [c["bom-ref"] for c in merged["components"]]

    assert sorted(refs) == ["dup", "other"]


@pytest.mark.django_db
def test_build_release_hbom_uses_newest_per_component(sample_team_with_owner_member, mocker):
    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "old.hbom.json", version="1"))
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "new.hbom.json", version="2"))
    _mock_s3(mocker, {"old.hbom.json": _doc("rev-a"), "new.hbom.json": _doc("rev-b")})

    merged = build_release_hbom(release)

    assert {c["bom-ref"] for c in merged["components"]} == {"rev-b"}


@pytest.mark.django_db
def test_build_release_hbom_skips_malformed_and_missing(sample_team_with_owner_member, mocker):
    """Non-dict components are dropped rather than emitted into an invalid
    document, and a malformed dependsOn is coerced to its string targets."""
    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "a.hbom.json"))
    doc = json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"type": "device", "bom-ref": "good"}, "junk", None, 42],
            "dependencies": [
                {"ref": "good", "dependsOn": ["ok", {"nested": 1}, 42, None]},
                {"ref": "y", "dependsOn": "not-a-list"},
                {"ref": 99, "dependsOn": ["ignored"]},
            ],
        }
    ).encode()
    _mock_s3(mocker, {"a.hbom.json": doc})

    merged = build_release_hbom(release)

    assert {c["bom-ref"] for c in merged["components"]} == {"good"}
    assert {d["ref"]: d["dependsOn"] for d in merged["dependencies"]} == {"good": ["ok"], "y": []}


@pytest.mark.django_db
def test_build_release_hbom_skips_missing_s3_object(sample_team_with_owner_member, mocker):
    """A missing/unreadable HBOM object is skipped, not 500."""
    from botocore.exceptions import ClientError

    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "gone.hbom.json"))
    # Patch the method, not the class — see _mock_s3 for why replacing the class
    # leaks into whichever module imports it next.
    mocker.patch(
        "sbomify.apps.core.object_store.S3Client.get_sbom_data",
        side_effect=ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject"),
    )

    assert build_release_hbom(release) is None


@pytest.mark.django_db
def test_build_release_hbom_none_without_slot(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    _product, release, _c1, _c2 = _release_with_components(team, is_public=True)
    assert build_release_hbom(release) is None


@pytest.mark.django_db
def test_download_release_hbom_public_returns_attachment(sample_team_with_owner_member, mocker):
    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "c1.hbom.json"))
    _mock_s3(mocker, {"c1.hbom.json": _doc("part/a")})
    cache.clear()

    resp = Client().get(reverse("api-1:download_release_hbom", kwargs={"release_id": release.id}))

    assert resp.status_code == 200
    assert "attachment" in resp["Content-Disposition"]
    assert resp["Content-Disposition"].rstrip('"').endswith(".hbom.cdx.json")
    assert json.loads(resp.content)["specVersion"] == "1.6"


@pytest.mark.django_db
def test_download_release_hbom_404_when_absent(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    _product, release, _c1, _c2 = _release_with_components(team, is_public=True)
    cache.clear()

    resp = Client().get(reverse("api-1:download_release_hbom", kwargs={"release_id": release.id}))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "No HBOM available for this release"


@pytest.mark.django_db
def test_download_release_hbom_private_requires_auth(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    _product, release, _c1, _c2 = _release_with_components(team, is_public=False)
    resp = Client().get(reverse("api-1:download_release_hbom", kwargs={"release_id": release.id}))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_download_release_hbom_version_param(sample_team_with_owner_member, mocker):
    """1.7 is emitted natively (no hardware vocabulary differs between the two);
    anything else is rejected rather than echoed into specVersion."""
    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "c1.hbom.json"))
    _mock_s3(mocker, {"c1.hbom.json": _doc("part/a", board="board-1")})
    cache.clear()
    url = reverse("api-1:download_release_hbom", kwargs={"release_id": release.id})

    native = Client().get(url + "?version=1.7")
    assert native.status_code == 200
    assert json.loads(native.content)["specVersion"] == "1.7"

    assert Client().get(url + "?version=1.5").status_code == 400


@pytest.mark.django_db
def test_download_release_hbom_cache_key_tracks_slot_state(sample_team_with_owner_member, mocker):
    """Adding an HBOM to the release must not serve the previously cached merge."""
    team = sample_team_with_owner_member.team
    _product, release, c1, c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "c1.hbom.json"))
    _mock_s3(mocker, {"c1.hbom.json": _doc("part/a"), "c2.hbom.json": _doc("part/b")})
    cache.clear()
    url = reverse("api-1:download_release_hbom", kwargs={"release_id": release.id})

    first = Client().get(url)
    assert {c["bom-ref"] for c in json.loads(first.content)["components"]} == {"part/a"}

    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c2, "c2.hbom.json"))
    second = Client().get(url)

    assert {c["bom-ref"] for c in json.loads(second.content)["components"]} == {"part/a", "part/b"}


@pytest.mark.django_db
def test_download_release_hbom_fires_analytics_event(sample_team_with_owner_member, mocker):
    team = sample_team_with_owner_member.team
    product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "c1.hbom.json"))
    _mock_s3(mocker, {"c1.hbom.json": _doc("part/a")})
    cache.clear()
    capture = mocker.patch("sbomify.apps.core.posthog_service.capture")
    mocker.patch("sbomify.apps.core.posthog_service.is_enabled", return_value=True)

    Client().get(reverse("api-1:download_release_hbom", kwargs={"release_id": release.id}))

    fired = {call.args[1]: call.args[2] for call in capture.call_args_list}
    assert fired["release_hbom:downloaded"] == {"release_id": str(release.id), "product_id": str(product.id)}


@pytest.mark.django_db
def test_a_1_7_member_downlevels_to_a_valid_1_6_document(sample_team_with_owner_member, mocker):
    """Uploads accept 1.3 through 1.7, so a release can pin a 1.7 HBOM while the
    default download emits 1.6. 1.7 added Component fields that 1.6 forbids, and
    copying them through produced a file sbomify itself rejects on re-upload."""
    from sbomify.apps.sboms.schemas import validate_cyclonedx_sbom

    team = sample_team_with_owner_member.team
    _product, release, c1, _c2 = _release_with_components(team, is_public=True)
    ReleaseArtifact.objects.create(release=release, sbom=_hbom_sbom(c1, "a.hbom.json"))
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "components": [
            {"type": "device", "bom-ref": "part-1", "name": "STM32", "isExternal": True, "versionRange": "vers:x/1"}
        ],
    }
    _mock_s3(mocker, {"a.hbom.json": json.dumps(document).encode()})

    merged = build_release_hbom(release, spec_version="1.6")

    assert merged["specVersion"] == "1.6"
    assert "isExternal" not in merged["components"][0]
    assert "versionRange" not in merged["components"][0]
    # The real check: the document sbomify hands a customer must survive the
    # validator sbomify would apply to it.
    validated, detected = validate_cyclonedx_sbom(merged)
    assert detected == "1.6", validated

    kept = build_release_hbom(release, spec_version="1.7")
    assert kept["components"][0]["isExternal"] is True


@pytest.mark.django_db
def test_repinning_to_an_older_revision_is_not_served_from_cache(sample_team_with_owner_member, mocker):
    """Rolling a release back to an earlier revision must change what downloads.

    Replacing a pin is a delete plus a create, so the pin count is unchanged and
    the newest *upload* time still belongs to the artifact that was left alone.
    Keying on the upload time made a rollback invisible for the rest of the TTL,
    which is a release advertising hardware it no longer ships.
    """
    from sbomify.apps.core.utils import add_artifact_to_release

    team = sample_team_with_owner_member.team
    _product, release, c1, c2 = _release_with_components(team, is_public=True)
    old_revision = _hbom_sbom(c1, "old.hbom.json", version="rev-1")
    new_revision = _hbom_sbom(c1, "new.hbom.json", version="rev-2")
    untouched = _hbom_sbom(c2, "other.hbom.json", version="rev-1")
    _mock_s3(
        mocker,
        {
            "old.hbom.json": _doc("old-part"),
            "new.hbom.json": _doc("new-part"),
            "other.hbom.json": _doc("other-part"),
        },
    )
    add_artifact_to_release(release, untouched)
    add_artifact_to_release(release, new_revision)
    cache.clear()

    url = reverse("api-1:download_release_hbom", kwargs={"release_id": release.id})
    first = json.loads(Client().get(url).content)
    assert {c["bom-ref"] for c in first["components"]} == {"new-part", "other-part"}

    # Roll c1 back. Count stays 2 and the newest upload is still c2's.
    replaced = add_artifact_to_release(release, old_revision, allow_replacement=True)
    assert replaced["replaced"] is True, replaced
    second = json.loads(Client().get(url).content)

    assert {c["bom-ref"] for c in second["components"]} == {"old-part", "other-part"}
