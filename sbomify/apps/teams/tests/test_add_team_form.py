"""The add-workspace dialog renders the form's own name widget."""

from __future__ import annotations

from django.template.loader import render_to_string

from sbomify.apps.teams.forms import AddTeamForm


def test_the_name_input_carries_the_legacy_input_class() -> None:
    html = str(AddTeamForm()["name"])

    assert 'class="tw-form-input"' in html
    assert 'name="name"' in html


def test_the_form_modal_renders_the_name_input_with_its_class() -> None:
    html = render_to_string(
        "components/modals/form_modal.html.j2",
        {
            "modal_id": "add-workspace-modal",
            "modal_title": "Add Workspace",
            "form": AddTeamForm(),
            "form_action": "/workspaces/",
            "submit_text": "Add Workspace",
        },
    )

    assert html.count('class="tw-form-input"') == 1
    assert 'id="add-workspace-modal-form"' in html
