import json

import pytest
from django.test import TestCase
from django.urls import reverse

from sbomify.apps.core.forms import TogglePublicStatusForm
from sbomify.apps.core.tests.fixtures import sample_user
from sbomify.apps.core.tests.shared_fixtures import AuthenticationTestCase
from sbomify.apps.sboms.tests.fixtures import (
    sample_component,
    sample_product,
    sample_project,
)


class TogglePublicStatusFormTest(TestCase):
    def test_toggle_public_status_form__when_is_public_true__should_be_valid(self) -> None:
        form = TogglePublicStatusForm({"is_public": True})
        self.assertTrue(form.is_valid())
        self.assertTrue(form.cleaned_data["is_public"])

    def test_toggle_public_status_form__when_is_public_false__should_be_valid(self) -> None:
        form = TogglePublicStatusForm({"is_public": False})
        self.assertTrue(form.is_valid())
        self.assertFalse(form.cleaned_data["is_public"])

    def test_toggle_public_status_form__when_no_is_public__should_be_valid(self) -> None:
        form = TogglePublicStatusForm({})
        self.assertTrue(form.is_valid())
        self.assertFalse(form.cleaned_data["is_public"])

    def test_toggle_public_status_form__when_empty_string__should_be_valid(self) -> None:
        form = TogglePublicStatusForm({"is_public": ""})
        self.assertTrue(form.is_valid())
        self.assertFalse(form.cleaned_data["is_public"])


class ProductTogglePublicStatusViewTest(AuthenticationTestCase):
    @pytest.fixture(autouse=True)
    def setup_test_data(self, sample_user, sample_product):
        self.user = sample_user
        self.product = sample_product
        self.team = sample_product.team

    def test_toggle_product__when_private_product__should_make_it_public(self) -> None:
        self.product.projects.all().update(is_public=True)

        self.product.is_public = False
        self.product.save()

        url = reverse("core:toggle_public_status", kwargs={"item_type": "product", "item_id": str(self.product.id)})
        response = self.client.post(url, {"is_public": True})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response["HX-Trigger"]), {"messages": [{"type": "success", "message": "Product is now public"}]})
        self.assertEqual(json.loads(response.content), {"is_public": True})

        self.product.refresh_from_db()
        self.assertTrue(self.product.is_public)

    def test_toggle_product__when_public_product__should_make_it_private(self) -> None:
        self.product.projects.all().update(is_public=False)

        self.team.billing_plan = "business"
        self.team.save()

        self.product.is_public = True
        self.product.save()

        url = reverse("core:toggle_public_status", kwargs={"item_type": "product", "item_id": str(self.product.id)})
        response = self.client.post(url, {"is_public": False})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response["HX-Trigger"]), {"messages": [{"type": "success", "message": "Product is now private"}]})
        self.assertEqual(json.loads(response.content), {"is_public": False})

        self.product.refresh_from_db()
        self.assertFalse(self.product.is_public)


class ProjectTogglePublicStatusViewTest(AuthenticationTestCase):
    @pytest.fixture(autouse=True)
    def setup_test_data(self, sample_user, sample_project):
        self.user = sample_user
        self.project = sample_project
        self.team = sample_project.team

    def test_toggle_project__when_private_project__should_make_it_public(self) -> None:
        from sbomify.apps.sboms.models import Component

        self.project.components.all().update(visibility=Component.Visibility.PUBLIC)

        self.project.is_public = False
        self.project.save()

        url = reverse("core:toggle_public_status", kwargs={"item_type": "project", "item_id": str(self.project.id)})
        response = self.client.post(url, {"is_public": True})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response["HX-Trigger"]), {"messages": [{"type": "success", "message": "Project is now public"}]})
        self.assertEqual(json.loads(response.content), {"is_public": True})

        self.project.refresh_from_db()
        self.assertTrue(self.project.is_public)

    def test_toggle_project__when_public_project__should_make_it_private(self) -> None:
        self.team.billing_plan = "business"
        self.team.save()

        self.project.is_public = True
        self.project.save()

        url = reverse("core:toggle_public_status", kwargs={"item_type": "project", "item_id": str(self.project.id)})
        response = self.client.post(url, {"is_public": False})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response["HX-Trigger"]), {"messages": [{"type": "success", "message": "Project is now private"}]})
        self.assertEqual(json.loads(response.content), {"is_public": False})

        self.project.refresh_from_db()
        self.assertFalse(self.project.is_public)


class ComponentTogglePublicStatusViewTest(AuthenticationTestCase):
    @pytest.fixture(autouse=True)
    def setup_test_data(self, sample_user, sample_component):
        self.user = sample_user
        self.component = sample_component
        self.team = sample_component.team

    def test_toggle_component__when_private_component__should_make_it_public(self) -> None:
        from sbomify.apps.sboms.models import Component

        self.component.visibility = Component.Visibility.PRIVATE
        self.component.save()

        url = reverse("core:toggle_public_status", kwargs={"item_type": "component", "item_id": str(self.component.id)})
        response = self.client.post(url, {"visibility": "public"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response["HX-Trigger"]), {"messages": [{"type": "success", "message": "Component is now public"}]})
        self.assertEqual(json.loads(response.content), {"visibility": "public"})

        self.component.refresh_from_db()
        self.assertEqual(self.component.visibility, Component.Visibility.PUBLIC)

    def test_toggle_component__when_public_component__should_make_it_private(self) -> None:
        from sbomify.apps.sboms.models import Component

        self.team.billing_plan = "business"
        self.team.save()

        self.component.visibility = Component.Visibility.PUBLIC
        self.component.save()

        url = reverse("core:toggle_public_status", kwargs={"item_type": "component", "item_id": str(self.component.id)})
        response = self.client.post(url, {"visibility": "private"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response["HX-Trigger"]), {"messages": [{"type": "success", "message": "Component is now private"}]})
        self.assertEqual(json.loads(response.content), {"visibility": "private"})

        self.component.refresh_from_db()
        self.assertEqual(self.component.visibility, Component.Visibility.PRIVATE)
