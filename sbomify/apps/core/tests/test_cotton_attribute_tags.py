"""Cotton component tags never carry a bare template tag between attributes.

Cotton parses a component's opening tag itself and does not understand a
`{% if %}` sitting between its attributes: it splits the tag into junk
attributes (`{%=""`, `if=""`, ...) and whatever the condition guarded is lost.
The delete confirmation's `@click` vanished this way and its button did
nothing. Template tags inside a quoted attribute value are fine; only the bare
ones break.
"""

import re
from pathlib import Path

import pytest
from django.template.loader import render_to_string

SBOMIFY_ROOT = Path(__file__).resolve().parents[3]


def _template_files() -> list[Path]:
    files = [*SBOMIFY_ROOT.glob("apps/*/templates/**/*.j2"), *SBOMIFY_ROOT.glob("templates/**/*.html")]
    return sorted(files)


def _bare_tags_in_component_tags(source: str) -> list[tuple[int, str]]:
    """Each `<c-...>` opening tag with a `{% %}` outside its quoted values."""
    found = []
    for match in re.finditer(r"<c-[\w.\-]+", source):
        index, quote, bare = match.end(), None, False
        while index < len(source):
            if source.startswith(("{%", "{{"), index):
                closer = "%}" if source[index + 1] == "%" else "}}"
                bare = bare or (quote is None and closer == "%}")
                index = source.find(closer, index) + 2
                continue
            char = source[index]
            if quote:
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char == ">":
                break
            index += 1
        if bare:
            found.append((source.count("\n", 0, match.start()) + 1, match.group(0)))
    return found


@pytest.mark.parametrize("path", _template_files(), ids=lambda p: str(p.relative_to(SBOMIFY_ROOT)))
def test_no_bare_template_tag_inside_a_component_tag(path: Path) -> None:
    offenders = _bare_tags_in_component_tags(path.read_text())
    assert not offenders, f"{path}: template tag between cotton attributes at {offenders}"


def test_scanner_flags_a_conditional_attribute() -> None:
    assert _bare_tags_in_component_tags('<c-buttons.danger {% if x %}@click="go()"{% endif %}>')
    assert not _bare_tags_in_component_tags('<c-buttons.danger class="{% if x %}a{% endif %}" @click="go()">')


def test_delete_confirmation_binds_its_callback() -> None:
    rendered = render_to_string(
        "components/delete_confirmation_modal.html.j2",
        {"modal_id": "showDeleteModal", "confirm_callback": "confirmDeleteRelease()", "confirm_text": "Delete release"},
    )
    button = rendered[rendered.index('x-ref="deleteButton"') :]
    button = button[: button.index(">")]
    assert '@click="confirmDeleteRelease()"' in button
    assert "{%" not in button
