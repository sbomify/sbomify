import os
import json
from dataclasses import dataclass
from typing import Generator, Any
from urllib.parse import urlencode
from random import randint
import string

from django.http import HttpResponse
from django.test import Client
from django.urls import reverse
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
import pytest
from pytest_mock.plugin import MockerFixture
from social_django.models import UserSocialAuth

from .fixtures import sample_user, guest_user  # noqa: F401
from access_tokens.models import AccessToken
from sboms.models import Product, Project, Component
from teams.models import Team, Member, get_team_name_for_user
from .utils import number_to_random_token, token_to_number, obj_extract, ExtractSpec, generate_id
from .object_store import S3Client


@pytest.mark.django_db
def test_homepage():
    client = Client()
    response: HttpResponse = client.get(reverse("core:home"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_dashboard_is_only_accessible_when_logged_in(sample_user: AbstractBaseUser):  # noqa: F811
    client = Client()
    response: HttpResponse = client.get(reverse("core:dashboard"))

    assert response.status_code == 302

    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    response: HttpResponse = client.get(reverse("core:dashboard"))

    assert response.status_code == 200


@pytest.mark.django_db
def test_access_token_creation(sample_user: AbstractBaseUser):  # noqa: F811
    client = Client()
    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    # Create token
    uri = reverse("core:settings")
    form_data = urlencode({"description": "Test Token"})
    response = client.post(uri, form_data, content_type="application/x-www-form-urlencoded")

    assert response.status_code == 200
    messages = list(get_messages(response.wsgi_request))
    assert any(m.message == "New access token created" for m in messages)

    # Verify token was created correctly
    access_tokens = AccessToken.objects.filter(user=sample_user).all()
    assert len(access_tokens) == 1
    assert access_tokens[0].user_id == sample_user.id
    assert access_tokens[0].description == "Test Token"


@pytest.mark.django_db
def test_access_token_deletion(sample_user: AbstractBaseUser):  # noqa: F811
    # Setup: Create a token first
    token = AccessToken.objects.create(
        user=sample_user,
        description="Test Token",
        encoded_token="test-token"
    )

    # Delete token
    client = Client()
    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    uri = reverse("core:delete_access_token", kwargs={"token_id": token.id})
    response = client.get(uri)

    assert response.status_code == 302
    messages = list(get_messages(response.wsgi_request))
    assert any(m.message == "Access token removed" for m in messages)

    # Verify token was deleted
    assert len(AccessToken.objects.filter(user=sample_user).all()) == 0


# This fixture resides here instead of fixtures.py to avoid circular imports across fixtures
# used in other apps.
@pytest.fixture
def sample_items(
    sample_user: AbstractBaseUser,  # noqa: F811
    guest_user: AbstractBaseUser,  # noqa: F811
) -> Generator[tuple[Team, Product, Project, Component], Any, None]:
    team = Team(name="Test Team")
    team.save()

    team.key = number_to_random_token(team.pk)
    team.save()

    owner_member = Member(user=sample_user, team=team, role="owner")
    owner_member.save()

    guest_member = Member(user=guest_user, team=team, role="guest")
    guest_member.save()

    product = Product(name="Test Product", team=team)
    product.save()

    project = Project(name="Test Project", team=team)
    project.save()

    component = Component(name="Test Component", team=team)
    component.save()

    yield team, product, project, component

    component.delete()
    project.delete()
    product.delete()
    guest_member.delete()
    owner_member.delete()
    team.delete()


@pytest.mark.django_db
def test_item_rename_api(
    sample_user: AbstractBaseUser,  # noqa: F811
    guest_user: AbstractBaseUser,  # noqa: F811
    sample_items,  # noqa: F811
):
    sample_team, sample_product, sample_project, sample_component = sample_items

    client = Client()

    unknown_uri = reverse(
        "api-1:rename_item",
        kwargs={"item_type": "unknown", "item_id": 7},
    )

    team_uri = reverse(
        "api-1:rename_item",
        kwargs={"item_type": "team", "item_id": sample_team.key},
    )

    product_uri = reverse(
        "api-1:rename_item",
        kwargs={"item_type": "product", "item_id": sample_product.id},
    )

    project_uri = reverse(
        "api-1:rename_item",
        kwargs={"item_type": "project", "item_id": sample_project.id},
    )

    component_uri = reverse(
        "api-1:rename_item",
        kwargs={"item_type": "component", "item_id": sample_component.id},
    )

    uris = [unknown_uri, team_uri, product_uri, project_uri, component_uri]

    # Verify unauhtorized access is denied
    for item_uri in uris:
        response: HttpResponse = client.patch(
            item_uri, json.dumps({"name": "New Name"}), content_type="application/json"
        )
        assert response.status_code == 401

    # Verify non-owners are not allowed to change the name
    assert client.login(username="guest", password="guest")  # nosec B106

    for item_idx, item_uri in enumerate(uris):
        response: HttpResponse = client.patch(
            item_uri, json.dumps({"name": "New Name"}), content_type="application/json"
        )

        if item_idx == 0:
            assert response.status_code == 400
        else:
            assert response.status_code == 403

    client.logout()

    # Verify owners can change the name
    assert client.login(
        username=os.environ["DJANGO_TEST_USER"], password=os.environ["DJANGO_TEST_PASSWORD"]
    )

    # Test for unknown type
    response: HttpResponse = client.patch(
        unknown_uri, json.dumps({"name": "Unknown"}), content_type="application/json"
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid item type"

    # Test for team
    response: HttpResponse = client.patch(
        team_uri, json.dumps({"name": "New Team Name"}), content_type="application/json"
    )
    assert response.status_code == 204
    assert Team.objects.get(id=sample_team.id).name == "New Team Name"

    # Test for product
    response: HttpResponse = client.patch(
        product_uri, json.dumps({"name": "New Product Name"}), content_type="application/json"
    )
    assert response.status_code == 204
    assert Product.objects.get(id=sample_product.id).name == "New Product Name"

    # Test for project
    response: HttpResponse = client.patch(
        project_uri, json.dumps({"name": "New Project Name"}), content_type="application/json"
    )
    assert response.status_code == 204
    assert Project.objects.get(id=sample_project.id).name == "New Project Name"

    # Test for component
    response: HttpResponse = client.patch(
        component_uri, json.dumps({"name": "New Component Name"}), content_type="application/json"
    )
    assert response.status_code == 204
    assert Component.objects.get(id=sample_component.id).name == "New Component Name"


def test_id_token_conversion():
    for _ in range(100):
        num = randint(0, 10000)
        tok = number_to_random_token(num)
        assert isinstance(tok, str)
        assert len(tok) > 6
        assert num == token_to_number(tok)


def test_generate_id():
    # Test length
    id1 = generate_id()
    assert len(id1) == 12, "ID should be exactly 12 characters"

    # Test starts with letter
    assert id1[0].isalpha(), "ID should start with a letter"

    # Test alphanumeric
    assert id1.isalnum(), "ID should only contain alphanumeric characters"

    # Test uniqueness
    ids = {generate_id() for _ in range(1000)}
    assert len(ids) == 1000, "Generated IDs should be unique"

    # Test character set
    allowed_chars = set(string.ascii_letters + string.digits)
    for id_str in ids:
        assert all(c in allowed_chars for c in id_str), "ID should only use allowed characters"
        assert id_str[0] in string.ascii_letters, "ID should start with a letter"


def test_object_store(mocker: MockerFixture):  # noqa: F811
    mocker.patch("boto3.resource")

    s3 = S3Client("MEDIA")
    patched_upload_data_as_file = mocker.patch("core.object_store.S3Client.upload_data_as_file")
    with pytest.raises(ValueError) as e:
        s3.upload_sbom(b"test")

    assert patched_upload_data_as_file.assert_not_called
    assert str(e.value) == "This method is only for SBOMS bucket"

    s3 = S3Client("SBOMS")
    patched_upload_data_as_file = mocker.patch("core.object_store.S3Client.upload_data_as_file")
    with pytest.raises(ValueError) as e:
        s3.upload_media("test", b"test")

    assert patched_upload_data_as_file.assert_not_called
    assert str(e.value) == "This method is only for MEDIA bucket"

    sbom_name = s3.upload_sbom(b"test")

    assert patched_upload_data_as_file.assert_called
    assert sbom_name == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08.json"


## Tests for obj_extract function

@dataclass
class DummyObject:
    name: str
    age: int
    address: 'Address'

@dataclass
class Address:
    street: str
    city: str


def test_obj_extract_basic_fields():
    """Test extracting basic fields"""
    obj = DummyObject(name="John", age=30, address=None)

    fields = [
        ExtractSpec(field="name"),
        ExtractSpec(field="age")
    ]

    result = obj_extract(obj, fields)

    assert result["name"] == "John"
    assert result["age"] == 30


def test_obj_extract_nested_fields():
    """Test extracting nested fields"""
    address = Address(street="123 Main St", city="Boston")
    obj = DummyObject(name="John", age=30, address=address)

    fields = [
        ExtractSpec(field="address.street"),
        ExtractSpec(field="address.city")
    ]

    result = obj_extract(obj, fields)

    assert result["address.street"] == "123 Main St"
    assert result["address.city"] == "Boston"


def test_obj_extract_with_missing_required():
    """Test error when required field is missing"""
    obj = DummyObject(name=None, age=30, address=None)

    fields = [
        ExtractSpec(field="name", required=True)
    ]

    try:
        obj_extract(obj, fields)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert str(e) == "Field 'name' is required."


def test_obj_extract_with_custom_error():
    """Test custom error message"""
    obj = DummyObject(name=None, age=30, address=None)

    fields = [
        ExtractSpec(field="name", required=True, error_message="Name is mandatory")
    ]

    try:
        obj_extract(obj, fields)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert str(e) == "Name is mandatory"


def test_obj_extract_with_default():
    """Test default value when field is missing"""
    obj = DummyObject(name=None, age=30, address=None)

    fields = [
        ExtractSpec(field="name", required=False, default="Unknown")
    ]

    result = obj_extract(obj, fields)

    assert result["name"] == "Unknown"


def test_obj_extract_missing_optional():
    """Test handling of missing optional field"""
    obj = DummyObject(name="John", age=30, address=None)

    fields = [
        ExtractSpec(field="address.street", required=False)
    ]

    result = obj_extract(obj, fields)

    assert "address.street" not in result


def test_obj_extract_with_rename():
    # Setup test object
    address = Address(street="123 Main St", city="Test City")
    sample = DummyObject(name="John", age=30, address=address)

    # Define extraction spec with rename
    fields = [
        ExtractSpec(field="name", rename_to="full_name"),
        ExtractSpec(field="address.city", rename_to="location")
    ]

    # Execute
    result = obj_extract(sample, fields)

    # Assert
    assert "full_name" in result
    assert "location" in result
    assert result["full_name"] == "John"
    assert result["location"] == "Test City"
    assert "name" not in result
    assert "city" not in result


def test_obj_extract_rename_with_default():
    # Setup test object with missing field
    address = Address(street="123 Main St", city=None)
    sample = DummyObject(name="John", age=30, address=address)

    # Define extraction spec with rename and default
    fields = [
        ExtractSpec(
            field="address.city",
            rename_to="location",
            required=False,
            default="Unknown City"
        )
    ]

    # Execute
    result = obj_extract(sample, fields)

    # Assert
    assert "location" in result
    assert result["location"] == "Unknown City"
    assert "city" not in result


def test_obj_extract_rename_with_error_message():
    # Setup test object with missing required field
    address = Address(street="123 Main St", city=None)
    sample = DummyObject(name="John", age=30, address=address)

    # Define extraction spec with rename and custom error
    fields = [
        ExtractSpec(
            field="address.city",
            rename_to="location",
            error_message="City is required"
        )
    ]

    # Assert error is raised with custom message
    try:
        obj_extract(sample, fields)
        assert False, "Expected ValueError"
    except ValueError as e:
        assert str(e) == "City is required"


@pytest.mark.django_db
class TestUser:
    def test_default_team_name(self, sample_user: AbstractBaseUser):  # noqa: F811
        """Test that a user gets 'My Team' when no other information is available"""
        sample_user.first_name = ""
        sample_user.save()

        assert get_team_name_for_user(sample_user) == "My Team"

    def test_team_name_with_first_name(self, sample_user: AbstractBaseUser):  # noqa: F811
        """Test that user's first name is used in team name when available"""
        sample_user.first_name = "John"
        sample_user.save()

        assert get_team_name_for_user(sample_user) == "John's Team"

    def test_team_name_with_company(self, sample_user: AbstractBaseUser):  # noqa: F811
        """Test that company name from Auth0 user_metadata is used when available"""
        sample_user.first_name = ""
        sample_user.save()

        social_auth = UserSocialAuth.objects.create(
            user=sample_user,
            provider="auth0",
            extra_data={
                "user_metadata": {
                    "company": "Acme Corp"
                }
            }
        )
        social_auth.save()

        assert get_team_name_for_user(sample_user) == "Acme Corp"

    def test_team_name_company_takes_precedence(self, sample_user: AbstractBaseUser):  # noqa: F811
        """Test that company name takes precedence over first name when both are available"""
        sample_user.first_name = "John"
        sample_user.save()

        social_auth = UserSocialAuth.objects.create(
            user=sample_user,
            provider="auth0",
            extra_data={
                "user_metadata": {
                    "company": "Acme Corp"
                }
            }
        )
        social_auth.save()

        assert get_team_name_for_user(sample_user) == "Acme Corp"
