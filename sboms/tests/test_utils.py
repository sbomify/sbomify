import json
from unittest.mock import patch

import pytest
from django.http import HttpRequest

from core.tests.fixtures import sample_user  # noqa: F401
from core.utils import number_to_random_token
from sboms.utils import ProjectSBOMBuilder, verify_item_access
from teams.fixtures import sample_team, sample_team_with_owner_member  # noqa: F401
from teams.models import Team

from .fixtures import (
    sample_access_token,  # noqa: F401
    sample_component,  # noqa: F401
    sample_project,  # noqa: F401
    sample_sbom,  # noqa: F401
)


@pytest.fixture
def mock_request(sample_user) -> HttpRequest:  # noqa: F811
    request = HttpRequest()
    request.user = sample_user
    request.session = {}
    return request


@pytest.fixture
def mock_request_with_teams(mock_request, sample_team) -> HttpRequest:  # noqa: F811
    team_key = number_to_random_token(sample_team.id)
    mock_request.session["user_teams"] = {team_key: {"role": "owner", "name": "test team"}}
    return mock_request


def test_verify_item_access_unauthenticated(mock_request):
    """Test access verification for unauthenticated user"""
    mock_request.user = type("AnonymousUser", (), {"is_authenticated": False})()
    team = Team(name="test")

    result = verify_item_access(mock_request, team, ["owner"])

    assert result is False


def test_verify_item_access_team_with_session(mock_request_with_teams, sample_team):  # noqa: F811
    """Test access verification for team using session data"""
    result = verify_item_access(mock_request_with_teams, sample_team, ["owner"])

    assert result is True


def test_verify_item_access_team_wrong_role(mock_request_with_teams, sample_team):  # noqa: F811
    """Test access verification fails with wrong role"""
    result = verify_item_access(mock_request_with_teams, sample_team, ["admin"])

    assert result is False


def test_verify_item_access_product(mock_request_with_teams, sample_product):
    """Test access verification for product"""
    result = verify_item_access(mock_request_with_teams, sample_product, ["owner"])

    assert result is True


def test_verify_item_access_project(mock_request_with_teams, sample_project):  # noqa: F811
    """Test access verification for project"""
    result = verify_item_access(mock_request_with_teams, sample_project, ["owner"])

    assert result is True


def test_verify_item_access_component(mock_request_with_teams, sample_component):  # noqa: F811
    """Test access verification for component"""
    result = verify_item_access(mock_request_with_teams, sample_component, ["owner"])

    assert result is True


def test_verify_item_access_sbom(mock_request_with_teams, sample_sbom):  # noqa: F811
    """Test access verification for SBOM"""
    result = verify_item_access(mock_request_with_teams, sample_sbom, ["owner"])

    assert result is True


@pytest.fixture
def mock_s3_client():
    with patch("sboms.utils.S3Client") as mock:
        instance = mock.return_value
        instance.get_sbom_data.return_value = json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "metadata": {"component": {"name": "test-component", "type": "library", "version": "1.0.0"}},
            }
        ).encode()
        yield instance


@pytest.mark.django_db
def test_project_sbom_builder(sample_project, mock_s3_client, tmp_path):  # noqa: F811
    """Test ProjectSBOMBuilder generates valid SBOM"""
    builder = ProjectSBOMBuilder()
    sbom = builder(sample_project, tmp_path)

    assert sbom.bomFormat == "CycloneDX"
    assert sbom.specVersion == "1.6"
    assert sbom.metadata.component.name == sample_project.name


@pytest.mark.django_db
def test_project_sbom_builder_no_components(sample_project, tmp_path):  # noqa: F811
    """Test ProjectSBOMBuilder with no components"""
    builder = ProjectSBOMBuilder()
    sbom = builder(sample_project, tmp_path)

    assert sbom.components is None


@pytest.mark.django_db
def test_project_sbom_builder_invalid_sbom_format(sample_project, mock_s3_client, tmp_path):  # noqa: F811
    """Test ProjectSBOMBuilder with invalid SBOM format"""
    mock_s3_client.get_sbom_data.return_value = json.dumps({"bomFormat": "Invalid", "specVersion": "1.6"}).encode()

    builder = ProjectSBOMBuilder()
    sbom = builder(sample_project, tmp_path)

    assert sbom.components is None
