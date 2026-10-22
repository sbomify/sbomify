"""The Markdown filter that renders notes written in the app."""

from __future__ import annotations

from sbomify.apps.core.templatetags.markdown_tags import strict_markdown


def test_markdown_becomes_markup():
    html = strict_markdown("## Fixed\n\n- **Upgrade** to `1.4.3`\n- *Restart* the service")
    assert "<h2>Fixed</h2>" in html
    assert "<li><strong>Upgrade</strong> to <code>1.4.3</code></li>" in html
    assert "<li><em>Restart</em> the service</li>" in html


def test_raw_html_is_shown_as_text():
    html = strict_markdown('<img src=x onerror="alert(1)"> **ok**')
    assert "<img" not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "<strong>ok</strong>" in html


def test_a_link_keeps_its_query_string():
    html = strict_markdown("[Fix & notes](https://example.com/?a=1&b=2)")
    assert '<a href="https://example.com/?a=1&amp;b=2"' in html
    assert ">Fix &amp; notes</a>" in html


def test_unsafe_link_schemes_are_neutralised():
    html = strict_markdown("[x](javascript:alert)")
    assert 'href="#"' in html
    assert "javascript:" not in html


def test_a_missing_note_renders_nothing():
    assert strict_markdown(None) == ""
    assert strict_markdown("") == ""
