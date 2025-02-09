import os
from urllib.parse import urlencode

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse

from access_tokens.models import AccessToken


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

    uri = reverse("core:settings")
    form_data = urlencode({"description": "Test Token"})
    response = client.post(uri, form_data, content_type="application/x-www-form-urlencoded")
    assert response.status_code == 200
    messages = list(get_messages(response.wsgi_request))
    assert any(m.message == "New access token created" for m in messages)
    access_tokens = AccessToken.objects.filter(user=sample_user).all()
    assert len(access_tokens) == 1
