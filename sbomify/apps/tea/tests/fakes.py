"""A fake TEA 1.0 server for one component, as the TeaClient calls a check makes see it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from libtea.exceptions import TeaNotFoundError
from libtea.models import CLE, Artifact, Collection, Component, Release


def artifact(uuid: str, version: int = 1, sha: str = "a") -> dict[str, Any]:
    return {
        "uuid": uuid,
        "name": f"{uuid}.cdx.json",
        "type": "BOM",
        "version": version,
        "createdDate": "2025-01-01T00:00:00Z",
        "formats": [
            {
                "mediaType": "application/vnd.cyclonedx+json",
                "url": f"https://cdn.example.com/{uuid}/{version}",
                "checksums": [{"algType": "SHA-256", "algValue": sha * 64}],
            }
        ],
    }


class FakeServer:
    """What one remote TEA server publishes for one component, mutable between checks."""

    def __init__(self, component_uuid: str) -> None:
        self.component_uuid = component_uuid
        self.releases: dict[str, dict[str, Any]] = {}
        self.collections: dict[str, list[dict[str, Any]]] = {}
        self.collection_versions: dict[str, int] = {}
        self.cles: dict[str, list[dict[str, Any]]] = {}
        self.gone: set[tuple[str, int]] = set()
        self.failure: Exception | None = None

    def publish(self, release_uuid: str, version: str, days_ago: int, artifacts: list[dict[str, Any]]) -> None:
        when = (datetime(2026, 1, 1, tzinfo=UTC) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
        self.releases[release_uuid] = {
            "uuid": release_uuid,
            "component": self.component_uuid,
            "version": version,
            "createdDate": when,
            "releaseDate": when,
        }
        self.collections[release_uuid] = artifacts
        self.collection_versions[release_uuid] = self.collection_versions.get(release_uuid, 0) + 1

    # The TeaClient calls a check makes.
    def __enter__(self) -> FakeServer:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def _maybe_fail(self) -> None:
        if self.failure is not None:
            raise self.failure

    def get_component(self, uuid: str) -> Component:
        self._maybe_fail()
        if uuid != self.component_uuid:
            raise TeaNotFoundError("no such component")
        return Component.model_validate({"uuid": uuid, "name": "remote lib", "identifiers": []})

    def get_component_releases(self, uuid: str) -> list[Release]:
        return [Release.model_validate(r) for r in self.releases.values()]

    def get_component_release_collection_latest(self, uuid: str) -> Collection:
        if uuid not in self.collections:
            raise TeaNotFoundError("no collection")
        return Collection.model_validate(
            {
                "uuid": uuid,
                "version": self.collection_versions[uuid],
                "createdDate": "2025-01-01T00:00:00Z",
                "belongsTo": "COMPONENT_RELEASE",
                "updateReason": {"type": "ARTIFACT_UPDATED"},
                "artifacts": self.collections[uuid],
            }
        )

    def get_component_release_cle(self, uuid: str) -> CLE:
        if uuid not in self.cles:
            raise TeaNotFoundError("no lifecycle")
        return CLE.model_validate({"events": self.cles[uuid]})

    def get_artifact_version(self, uuid: str, version: int) -> Artifact:
        if (uuid, version) in self.gone:
            raise TeaNotFoundError("gone")
        for listed in self.collections.values():
            for published in listed:
                if published["uuid"] == uuid and published["version"] == version:
                    return Artifact.model_validate(published)
        return Artifact.model_validate(artifact(uuid, version))
