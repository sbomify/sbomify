"""The Dependency-Track plugin keeps its projects in the tree and in scope as SBOMs and releases change."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.base import RetryLaterError
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunStatus
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.vulnerability_scanning.clients import DependencyTrackAPIError
from sbomify.apps.vulnerability_scanning.models import (
    DependencyTrackCollection,
    DependencyTrackServer,
    SbomDependencyTrackProjectVersion,
)
from sbomify.apps.vulnerability_scanning.services.dt_scope import reconcile_component

CLIENT = "sbomify.apps.vulnerability_scanning.clients.DependencyTrackClient"
NEW_VERSION = "00000000-0000-0000-0000-0000000000aa"


@pytest.fixture
def env(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    product = Product.objects.create(name="router", team=team)
    component = Component.objects.create(name="kernel", team=team)
    product.components.add(component)
    server = DependencyTrackServer.objects.create(name="dt", url="https://dt.example.com", api_key="k")
    return team, product, component, server


def _sbom(component, name):
    return SBOM.objects.create(
        name=name,
        version=name,
        component=component,
        format="cyclonedx",
        format_version="1.6",
        sbom_filename=f"{name}.json",
    )


def _client() -> MagicMock:
    client = MagicMock()
    client.create_collection_project.side_effect = lambda name, version, **kw: {"uuid": str(uuid.uuid4())}
    client.find_project_by_name_version.return_value = {"uuid": NEW_VERSION}
    client.set_project_state.return_value = True
    return client


def _first_scan(plugin, sbom, server, client, tmp_path):
    path = tmp_path / "sbom.json"
    path.write_bytes(b'{"bomFormat":"CycloneDX","specVersion":"1.6"}')
    with (
        patch(CLIENT, return_value=client),
        patch.object(plugin, "_select_dt_server", return_value=server),
        patch.object(plugin, "_team_has_dt_enabled", return_value=True),
        pytest.raises(RetryLaterError),
    ):
        plugin.assess(sbom_id=sbom.id, sbom_path=path, context=None)


@pytest.mark.django_db
class TestUploadLandsInTheTree:
    def test_a_new_sbom_is_uploaded_under_its_component_and_marked_latest(self, env, tmp_path):
        team, _, component, server = env
        sbom = _sbom(component, "s1")
        client = _client()

        _first_scan(DependencyTrackPlugin(), sbom, server, client, tmp_path)

        collection = DependencyTrackCollection.objects.get(dt_server=server, component=component)
        upload = client.upload_sbom_with_project_creation.call_args.kwargs
        assert upload["parent_uuid"] == str(collection.dt_project_uuid)
        assert upload["is_latest"] is True
        row = SbomDependencyTrackProjectVersion.objects.get(sbom=sbom, dt_server=server)
        assert (row.dt_active, row.dt_is_latest, str(row.dt_parent_uuid)) == (
            True,
            True,
            str(collection.dt_project_uuid),
        )

    def test_the_version_it_replaces_is_retired(self, env, tmp_path):
        _, _, component, server = env
        old = _sbom(component, "old")
        old_row = SbomDependencyTrackProjectVersion.objects.create(
            sbom=old,
            dt_server=server,
            dt_project_version=str(old.id),
            dt_project_version_uuid=uuid.uuid4(),
            dt_active=True,
            dt_is_latest=True,
        )
        new = _sbom(component, "new")  # replaces old in the latest release
        client = _client()

        _first_scan(DependencyTrackPlugin(), new, server, client, tmp_path)

        states = {c.args[0]: c.kwargs for c in client.set_project_state.call_args_list}
        assert states[str(old_row.dt_project_version_uuid)]["active"] is False
        assert states[str(old_row.dt_project_version_uuid)]["is_latest"] is False

    def test_a_key_that_may_not_change_projects_still_gets_the_scan(self, env, tmp_path):
        _, _, component, server = env
        sbom = _sbom(component, "s1")
        client = _client()
        client.create_collection_project.side_effect = DependencyTrackAPIError("forbidden", status_code=403)

        _first_scan(DependencyTrackPlugin(), sbom, server, client, tmp_path)

        upload = client.upload_sbom_with_project_creation.call_args.kwargs
        assert upload.get("parent_uuid") is None
        assert SbomDependencyTrackProjectVersion.objects.filter(sbom=sbom).exists()


@pytest.mark.django_db
class TestReleaseChangesMoveTheScope:
    def test_shipping_an_old_sbom_in_a_release_brings_it_back(self, env):
        _, product, component, server = env
        old = _sbom(component, "old")
        _sbom(component, "new")
        old_row = SbomDependencyTrackProjectVersion.objects.create(
            sbom=old,
            dt_server=server,
            dt_project_version=str(old.id),
            dt_project_version_uuid=uuid.uuid4(),
            dt_active=False,
        )
        run = AssessmentRun.objects.create(
            sbom=old,
            plugin_name="dependency-track",
            plugin_version="1.1.0",
            plugin_config_hash="h",
            category=AssessmentCategory.SECURITY.value,
            run_reason="on_upload",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"total_findings": 0}},
        )
        release = Release.objects.create(product=product, name="11.5")
        ReleaseArtifact.objects.create(release=release, sbom=old)
        client = _client()

        with patch(CLIENT, return_value=client):
            DependencyTrackPlugin().sync_release_tags(sbom_id=str(old.id), run_id=str(run.id), release=release)

        states = {c.args[0]: c.kwargs for c in client.set_project_state.call_args_list}
        assert states[str(old_row.dt_project_version_uuid)]["active"] is True


class FakeDT(MagicMock):
    """Projects kept the way Dependency-Track 4.14 keeps them.

    ``isLatest`` is one per project name: setting it on a version clears it on
    the others. A tag write is a POST of the whole project, so a snapshot read
    before someone else's write puts that write back.
    """

    def __init__(self) -> None:
        super().__init__()
        self.projects: dict[str, dict] = {}
        self.stale: dict[str, dict] = {}

    def _get_child_mock(self, **kw):
        return MagicMock(**kw)

    def add(self, name: str, version: str, **fields) -> str:
        project_uuid = str(uuid.uuid4())
        self.projects[project_uuid] = {
            "name": name,
            "version": version,
            "active": True,
            "isLatest": False,
            "parent": None,
            "tags": [],
            **fields,
        }
        return project_uuid

    def _make_latest(self, project_uuid: str) -> None:
        name = self.projects[project_uuid]["name"]
        for other_uuid, other in self.projects.items():
            if other["name"] == name:
                other["isLatest"] = other_uuid == project_uuid

    def create_collection_project(self, name, version, **kw):
        return {"uuid": self.add(name, version, parent=kw.get("parent_uuid"))}

    def upload_sbom_with_project_creation(self, project_name, project_version, sbom_data, **kw):
        project_uuid = self.add(project_name, project_version, parent=kw.get("parent_uuid"))
        if kw.get("is_latest"):
            self._make_latest(project_uuid)
        return {"token": "t"}

    def find_project_by_name_version(self, name, version):
        return next(
            ({"uuid": u} for u, p in self.projects.items() if (p["name"], p["version"]) == (name, version)), None
        )

    def set_project_state(self, project_uuid, *, active=None, is_latest=None, parent_uuid=None):
        project = self.projects[project_uuid]
        before = {**project}
        if active is not None:
            project["active"] = active
        if parent_uuid is not None:
            project["parent"] = parent_uuid
        if is_latest:
            self._make_latest(project_uuid)
        elif is_latest is False:
            project["isLatest"] = False
        return project != before

    def set_project_tags(self, project_uuid, tag_names):
        read = self.stale.pop(project_uuid, None) or {**self.projects[project_uuid]}
        names = sorted(set(tag_names))
        if read["tags"] == names:
            return False
        self.projects[project_uuid] = {**read, "tags": names}
        return True


@pytest.mark.django_db
class TestOrderDoesNotBreakTheScope:
    def test_a_tag_write_from_a_stale_read_does_not_leave_a_retired_version_active(self, env):
        _, _, component, server = env
        old = _sbom(component, "old")
        new = _sbom(component, "new")
        dt = FakeDT()
        rows = {}
        for sbom in (old, new):
            project_uuid = dt.add(f"local-sbomify-{component.id}", str(sbom.id), tags=["12.0"])
            rows[sbom.name] = SbomDependencyTrackProjectVersion.objects.create(
                sbom=sbom, dt_server=server, dt_project_version=str(sbom.id), dt_project_version_uuid=project_uuid
            )
        old_uuid = str(rows["old"].dt_project_version_uuid)
        run = AssessmentRun.objects.create(
            sbom=old,
            plugin_name="dependency-track",
            plugin_version="1.1.0",
            plugin_config_hash="h",
            category=AssessmentCategory.SECURITY.value,
            run_reason="on_upload",
            status=RunStatus.COMPLETED.value,
            result={"summary": {"total_findings": 0}},
        )
        # The release 12.0 has just let go of the old SBOM. Its tag sync reads
        # the project while it is still active...
        read_while_active = {**dt.projects[old_uuid]}

        with patch(CLIENT, return_value=dt):
            reconcile_component(component, server)
            assert dt.projects[old_uuid]["active"] is False
            # ...and writes that read back after the reconcile retired it.
            dt.stale[old_uuid] = read_while_active
            DependencyTrackPlugin().sync_release_tags(sbom_id=str(old.id), run_id=str(run.id), release=None)

        assert dt.projects[old_uuid]["tags"] == []
        assert dt.projects[old_uuid]["active"] is False

    def test_an_older_sbom_scanned_after_a_newer_one_leaves_latest_on_the_newer(self, env, tmp_path):
        _, _, component, server = env
        older = _sbom(component, "older")
        newer = _sbom(component, "newer")
        dt = FakeDT()
        plugin = DependencyTrackPlugin()

        _first_scan(plugin, newer, server, dt, tmp_path)
        _first_scan(plugin, older, server, dt, tmp_path)

        by_version = {p["version"]: p for p in dt.projects.values()}
        assert by_version[str(newer.id)]["isLatest"] is True
        assert by_version[str(newer.id)]["active"] is True
        assert by_version[str(older.id)]["isLatest"] is False
        assert by_version[str(older.id)]["active"] is False
