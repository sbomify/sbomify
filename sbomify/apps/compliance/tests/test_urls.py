"""Tests for CRA compliance URL resolution."""

from __future__ import annotations

import pytest
from django.urls import resolve, reverse

pytestmark = pytest.mark.django_db


class TestCRAURLResolution:
    def test_product_list_url(self):
        url = reverse("compliance:cra_product_list")
        assert url == "/compliance/cra/"
        resolved = resolve(url)
        assert resolved.view_name == "compliance:cra_product_list"

    def test_wizard_shell_url(self):
        url = reverse("compliance:cra_wizard_shell", kwargs={"assessment_id": "abc123"})
        assert url == "/compliance/cra/abc123/"
        resolved = resolve(url)
        assert resolved.view_name == "compliance:cra_wizard_shell"

    def test_step_url(self):
        url = reverse("compliance:cra_step", kwargs={"assessment_id": "abc123", "step": 3})
        assert url == "/compliance/cra/abc123/step/3/"
        resolved = resolve(url)
        assert resolved.view_name == "compliance:cra_step"
        assert resolved.kwargs["assessment_id"] == "abc123"
        assert resolved.kwargs["step"] == 3

    def test_start_assessment_url(self):
        url = reverse("compliance:cra_start_assessment", kwargs={"product_id": "prod123"})
        assert url == "/compliance/cra/start/prod123/"
        resolved = resolve(url)
        assert resolved.view_name == "compliance:cra_start_assessment"

    def test_all_five_steps_resolve(self):
        for step in range(1, 6):
            url = reverse("compliance:cra_step", kwargs={"assessment_id": "test", "step": step})
            resolved = resolve(url)
            assert resolved.view_name == "compliance:cra_step"
