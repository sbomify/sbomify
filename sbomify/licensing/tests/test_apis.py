import pytest
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
def test_get_licenses():
    client = Client()
    uri = reverse("api-1:list_licenses")
    response = client.get(uri)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 520
    origins = {d["origin"] for d in data}
    assert "SPDX" in origins and "Custom" in origins


@pytest.mark.django_db
def test_validate_expression_success():
    client = Client()
    uri = reverse("api-1:validate_license_expression")
    resp = client.post(
        uri,
        {"expression": "Apache-2.0 WITH Commons-Clause OR MIT"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["unknown_tokens"] == []


@pytest.mark.django_db
def test_validate_expression_unknown():
    client = Client()
    uri = reverse("api-1:validate_license_expression")
    resp = client.post(
        uri,
        {"expression": "FooBar-1.0"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert "FooBar-1.0" in resp.json()["unknown_tokens"]


@pytest.mark.django_db
def test_validate_expression_error():
    client = Client()
    uri = reverse("api-1:validate_license_expression")
    resp = client.post(
        uri,
        {"expression": "Apache-2.0 AND ("},
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "error" in resp.json()
