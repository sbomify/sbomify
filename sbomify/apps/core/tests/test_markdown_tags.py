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


def test_wrapped_lines_join_into_one_paragraph():
    html = strict_markdown("uv's bundled CA store trusts an\nemSign root.\n\nNext paragraph.")
    assert "<p>uv&#x27;s bundled CA store trusts an emSign root.</p>" in html
    assert "<p>Next paragraph.</p>" in html


def test_a_fenced_code_block_keeps_its_text_verbatim():
    html = strict_markdown("```python\nprint('<hi>')  # *not italic*\n    indented\n```")
    assert "<pre><code>print(&#x27;&lt;hi&gt;&#x27;)  # *not italic*\n    indented</code></pre>" in html
    assert "<em>" not in html


def test_an_unclosed_fence_still_renders_as_code():
    assert strict_markdown("```\nx = 1") == "<pre><code>x = 1</code></pre>"


def test_numbered_lists_keep_their_start():
    html = strict_markdown("3. third\n4. fourth")
    assert '<ol start="3">\n<li>third</li>\n<li>fourth</li>\n</ol>' in html


def test_indented_items_nest_inside_their_parent():
    html = strict_markdown("- parent\n  - child\n- sibling")
    assert html == "<ul>\n<li>parent\n<ul>\n<li>child</li>\n</ul></li>\n<li>sibling</li>\n</ul>"


def test_a_blank_line_between_items_keeps_one_list():
    assert strict_markdown("- a\n\n- b").count("<ul>") == 1


def test_a_quote_renders_as_a_blockquote():
    html = strict_markdown("> one\n> two\n\nafter")
    assert "<blockquote><p>one two</p></blockquote>" in html
    assert "<p>after</p>" in html


def test_a_bare_url_becomes_a_link_without_its_trailing_punctuation():
    html = strict_markdown("Fixed in https://github.com/org/repo/pull/461. See (https://example.com/a?b=1&c=2).")
    assert (
        '<a href="https://github.com/org/repo/pull/461" rel="nofollow ugc noopener noreferrer"'
        ' class="text-primary hover:underline">https://github.com/org/repo/pull/461</a>.'
    ) in html
    assert '(<a href="https://example.com/a?b=1&amp;c=2"' in html
    assert "c=2</a>)." in html


def test_a_url_with_its_own_parentheses_keeps_them():
    html = strict_markdown("See https://en.wikipedia.org/wiki/Foo_(bar), then stop.")
    assert 'href="https://en.wikipedia.org/wiki/Foo_(bar)"' in html


def test_a_bare_url_inside_link_text_does_not_nest_anchors():
    html = strict_markdown("[see https://a.example](https://b.example)")
    assert html.count("<a ") == 1
    assert '<a href="https://b.example"' in html
    assert ">see https://a.example</a>" in html


def test_every_link_is_marked_as_user_content():
    html = strict_markdown("[notes](https://example.com)")
    assert 'rel="nofollow ugc noopener noreferrer"' in html


def test_a_url_the_parser_rejects_does_not_fail_the_page():
    html = strict_markdown("[x](http://[broken)")
    assert 'href="#"' in html


def test_already_escaped_text_is_escaped_exactly_once():
    from django.utils.html import escape

    assert strict_markdown(escape("Fix & <b>notes</b>")) == strict_markdown("Fix & <b>notes</b>")
    assert "Fix &amp; &lt;b&gt;notes&lt;/b&gt;" in strict_markdown(escape("Fix & <b>notes</b>"))


def test_flat_renders_headings_as_bold_paragraphs():
    from sbomify.apps.core.templatetags.markdown_tags import strict_markdown_flat

    html = strict_markdown_flat("# Title\n\n## Summary **now**\n\nBody")
    assert "<p><strong>Title</strong></p>" in html
    assert "<p><strong>Summary <strong>now</strong></strong></p>" in html
    assert "<h1>" not in html and "<h2>" not in html
    assert "<p>Body</p>" in html
