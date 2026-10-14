"""The controls models are listed on the admin site sbomify mounts."""

from __future__ import annotations

import pytest

from sbomify.apps.controls.models import Control, ControlCatalog, ControlStatus
from sbomify.apps.core.admin import admin_site


@pytest.mark.parametrize("model", [ControlCatalog, Control, ControlStatus])
def test_the_model_is_on_the_mounted_admin_site(model) -> None:
    """``sbomify/urls.py`` mounts only core's ``admin_site``; Django's default site is never served."""
    assert admin_site.is_registered(model)
