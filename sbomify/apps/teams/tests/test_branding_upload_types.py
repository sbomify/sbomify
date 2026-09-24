"""Branding uploads store only images, typed from their bytes rather than from the client.

Icons and logos are served straight from the public media bucket. What lands
there, the extension on its key and the ContentType it is served with all follow
from what the file is: a PNG, JPEG or WebP, or an SVG with nothing in it for a
browser to run or fetch.
"""

import json
import tracemalloc
from unittest.mock import call

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Team

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24
WEBP = b"RIFF\x1c\x00\x00\x00WEBPVP8 " + b"\x00" * 16
HTML = b"<html><body><script>alert(1)</script></body></html>"


def svg(body: str = "<rect width='10' height='10'/>", attributes: str = "") -> bytes:
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'"
        f" viewBox='0 0 10 10'{attributes}>{body}</svg>"
    ).encode()


@pytest.fixture
def s3(mocker):
    """The boto3 resource behind every StorageClient: what S3 itself would have been sent."""
    return mocker.patch("boto3.resource").return_value


@pytest.fixture
def owner(client, sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    team.branding_info = {"icon": "old_icon.png", "logo": "old_logo.png"}
    team.save()
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)
    return client, team


def upload(client, team, name: str, data: bytes, content_type: str):
    return client.post(
        f"/api/v1/workspaces/{team.key}/branding/upload/logo",
        {"file": SimpleUploadedFile(name, data, content_type=content_type)},
    )


def assert_nothing_stored(s3, team):
    s3.Bucket.return_value.put_object.assert_not_called()
    s3.Object.return_value.delete.assert_not_called()
    team.refresh_from_db()
    assert (team.branding_info["icon"], team.branding_info["logo"]) == ("old_icon.png", "old_logo.png")


@pytest.mark.django_db
class TestBrandingUploadEndpoint:
    @pytest.mark.parametrize(
        "name,data,extension,content_type",
        [
            pytest.param("logo.png", PNG, ".png", "image/png", id="png"),
            pytest.param("logo.jpg", JPEG, ".jpg", "image/jpeg", id="jpeg"),
            pytest.param("logo.webp", WEBP, ".webp", "image/webp", id="webp"),
            pytest.param("logo.svg", svg(), ".svg", "image/svg+xml", id="svg"),
            pytest.param("logo.html", PNG, ".png", "image/png", id="png-named-html"),
        ],
    )
    def test_an_image_is_stored_under_the_type_its_bytes_show(self, owner, s3, name, data, extension, content_type):
        client, team = owner

        response = upload(client, team, name, data, "text/html")

        assert response.status_code == 200
        stored = response.json()["logo"]
        assert stored.startswith(f"team_{team.key}_logo_")
        assert stored.endswith(extension)
        s3.Bucket.return_value.put_object.assert_called_once_with(Key=stored, Body=data, ContentType=content_type)

    @pytest.mark.parametrize(
        "name,data,content_type",
        [
            pytest.param("logo.html", HTML, "text/html", id="html"),
            pytest.param("logo.png", HTML, "image/png", id="html-named-png"),
            pytest.param("logo.gif", b"GIF89a" + b"\x00" * 16, "image/gif", id="gif"),
        ],
    )
    def test_anything_else_is_rejected_before_it_reaches_the_bucket(self, owner, s3, name, data, content_type):
        client, team = owner

        response = upload(client, team, name, data, content_type)

        assert response.status_code == 400
        assert response.json()["error_code"] == "VALIDATION_ERROR"
        assert_nothing_stored(s3, team)

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(svg("<script>alert(1)</script>"), id="script"),
            pytest.param(svg(attributes=" onload='alert(1)'"), id="event-handler"),
            pytest.param(svg("<a href='javascript:alert(1)'><rect width='10' height='10'/></a>"), id="javascript-link"),
            pytest.param(
                svg("<a xlink:href='java&#9;script:alert(1)'><rect width='10' height='10'/></a>"),
                id="javascript-link-split-by-a-tab",
            ),
            pytest.param(svg("<image href='https://example.com/logo.png'/>"), id="external-reference"),
            pytest.param(svg("<use href='data:image/svg+xml;base64,PHN2Zy8+#x'/>"), id="svg-data-url"),
            pytest.param(
                svg("<a href='#x' ping='https://example.com/beacon'><rect width='10' height='10'/></a>"), id="link-ping"
            ),
            pytest.param(
                svg("<a href='#x'><set attributeName='ping' to='https://example.com/beacon'/></a>"), id="animated-ping"
            ),
            pytest.param(
                svg("<a href='#x'><set attributeName='href' to='javascript:alert(1)'/></a>"), id="animated-href"
            ),
            pytest.param(svg("<set attributeName='onmouseover' to='alert(1)'/>"), id="animated-event-handler"),
            pytest.param(
                svg("<a href='#x'><set attributeName='xml:base' to='javascript:alert(1)//'/></a>"),
                id="animated-xml-base",
            ),
            pytest.param(
                svg("<foreignObject><p xmlns='http://www.w3.org/1999/xhtml'>hi</p></foreignObject>"),
                id="foreign-object",
            ),
            pytest.param(
                svg("<iframe xmlns='http://www.w3.org/1999/xhtml' src='https://example.com'/>"), id="html-element"
            ),
            pytest.param(svg("<math xmlns='http://www.w3.org/1998/Math/MathML'><mi>x</mi></math>"), id="mathml"),
            pytest.param(b"<?xml-stylesheet type='text/xsl' href='#x'?>" + svg(), id="stylesheet-instruction"),
            pytest.param(svg("<?xml-stylesheet type='text/xsl' href='#x'?>"), id="instruction-inside-svg"),
            pytest.param(b"<!DOCTYPE svg [<!ATTLIST svg onload CDATA 'alert(1)'>]>" + svg(), id="internal-dtd"),
            pytest.param(b"<!DOCTYPE svg SYSTEM 'https://example.com/svg.dtd'>" + svg(), id="external-dtd"),
            pytest.param(
                svg("<a xml:base='javascript:alert(1)//' href='#x'><rect width='10' height='10'/></a>"), id="xml-base"
            ),
            pytest.param(svg("<style>@import 'https://example.com/a.css';</style>"), id="css-import"),
            pytest.param(svg("<style>rect{fill:url(https://example.com/a.svg#g)}</style>"), id="css-external-url"),
            pytest.param(
                svg("<style>rect{fill:u\\72l(https://example.com/a.svg#g)}</style>"),
                id="css-url-written-with-an-escape",
            ),
            pytest.param(
                svg("<style>rect{fill:u\\72&#13;&#10;l(https://example.com/a.svg#g)}</style>"),
                id="css-escape-before-a-crlf",
            ),
            pytest.param(
                svg("<style>rect{fill:ur<!-- -->l(https://example.com/a.svg#g)}</style>"),
                id="css-url-split-by-an-xml-comment",
            ),
            pytest.param(
                svg("<style>a{content:'/*'}rect{fill:url(https://example.com/a.svg#g)}a{content:'*/'}</style>"),
                id="css-url-between-comment-marks-in-strings",
            ),
            pytest.param(svg("<style>ur<g/>l(https://example.com/a.svg#g)</style>"), id="element-inside-a-style-sheet"),
            pytest.param(
                svg("<style>rect{background:image-set('https://example.com/a.png' 1x)}</style>"), id="css-image-set"
            ),
            pytest.param(
                svg("<rect style='fill:url(https://example.com/a.svg#g)' width='10' height='10'/>"),
                id="style-attribute-external-url",
            ),
            pytest.param(
                svg(
                    "<rect width='10' height='10'><set attributeName='fill' to='url(https://example.com/a.svg#g)'/></rect>"
                ),
                id="animated-external-url",
            ),
            pytest.param(b"<?xml version='1.0' encoding='x-unknown'?>" + svg(), id="unknown-encoding"),
            pytest.param(svg("<g/>" * 300_000), id="over-the-size-cap"),
            pytest.param(svg()[:-1], id="malformed"),
            pytest.param(b"<note>hi</note>", id="not-svg"),
        ],
    )
    def test_an_svg_that_could_run_anything_is_rejected(self, owner, s3, data):
        client, team = owner

        response = upload(client, team, "logo.svg", data, "image/svg+xml")

        assert response.status_code == 400
        assert_nothing_stored(s3, team)

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(
                b"<?xml version='1.0' encoding='UTF-8'?><!-- exported -->" + svg(), id="declaration-and-comment"
            ),
            pytest.param(
                svg(
                    "<defs><linearGradient id='g'/></defs>"
                    "<rect fill='url(#g)' width='10' height='10'/><use xlink:href='#g'/>"
                ),
                id="internal-references",
            ),
            pytest.param(svg("<image href='data:image/png;base64,iVBORw0KGgo='/>"), id="embedded-png"),
            pytest.param(svg("<image href='data:image/jpg;base64,/9j/4AAQ'/>"), id="embedded-jpg"),
            pytest.param(svg("<style>.a{fill:#fff}</style><rect class='a' width='10' height='10'/>"), id="style"),
            pytest.param(
                svg("<style><![CDATA[.a{fill:url(#g)}]]></style><linearGradient id='g'/><rect class='a' width='10'/>"),
                id="css-internal-reference",
            ),
            pytest.param(
                svg("<rect style='fill:url(\"#g\");stroke:url( #g )' width='10' height='10'/>"),
                id="style-attribute-internal-reference",
            ),
            pytest.param(
                svg(
                    "<g inkscape:label='Layer 1'><rect width='10' height='10'/></g>",
                    " xmlns:inkscape='http://www.inkscape.org/namespaces/inkscape' inkscape:version='1.3'",
                ),
                id="editor-metadata",
            ),
            pytest.param(
                svg("<rect width='10' height='10'><animate attributeName='opacity' from='0' to='1' dur='1s'/></rect>"),
                id="animated-opacity",
            ),
        ],
    )
    def test_an_svg_with_nothing_to_run_is_accepted(self, owner, s3, data):
        client, team = owner

        response = upload(client, team, "logo.svg", data, "image/svg+xml")

        assert response.status_code == 200
        stored = response.json()["logo"]
        s3.Bucket.return_value.put_object.assert_called_once_with(Key=stored, Body=data, ContentType="image/svg+xml")


@pytest.mark.django_db
class TestBrandingSettingsForm:
    def post(self, client, team, files):
        return client.post(reverse("teams:team_branding", kwargs={"team_key": team.key}), files)

    def test_a_new_icon_is_stored_under_the_type_its_bytes_show(self, owner, s3):
        client, team = owner

        response = self.post(client, team, {"icon": SimpleUploadedFile("icon.gif", JPEG, content_type="image/gif")})

        assert json.loads(response["HX-Trigger"])["messages"][0]["type"] == "success"
        team.refresh_from_db()
        stored = team.branding_info["icon"]
        assert stored.endswith(".jpg")
        s3.Bucket.return_value.put_object.assert_called_once_with(Key=stored, Body=JPEG, ContentType="image/jpeg")

    def test_a_raster_past_the_svg_cap_is_stored_whole(self, owner, s3):
        client, team = owner
        large_png = PNG + bytes(3 * 1024 * 1024)
        icon = SimpleUploadedFile("icon.png", large_png, content_type="image/png")

        response = self.post(client, team, {"icon": icon})

        assert json.loads(response["HX-Trigger"])["messages"][0]["type"] == "success"
        team.refresh_from_db()
        s3.Bucket.return_value.put_object.assert_called_once_with(
            Key=team.branding_info["icon"], Body=large_png, ContentType="image/png"
        )

    def test_an_icon_and_a_logo_are_each_stored_from_their_own_bytes(self, owner, s3):
        client, team = owner

        response = self.post(
            client,
            team,
            {
                "icon": SimpleUploadedFile("icon.png", PNG, content_type="image/png"),
                "logo": SimpleUploadedFile("logo.jpg", JPEG, content_type="image/jpeg"),
            },
        )

        assert json.loads(response["HX-Trigger"])["messages"][0]["type"] == "success"
        team.refresh_from_db()
        assert s3.Bucket.return_value.put_object.call_args_list == [
            call(Key=team.branding_info["icon"], Body=PNG, ContentType="image/png"),
            call(Key=team.branding_info["logo"], Body=JPEG, ContentType="image/jpeg"),
        ]
        assert s3.Object.call_args_list == [
            call(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, "old_icon.png"),
            call(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, "old_logo.png"),
        ]

    def test_a_failed_upload_removes_this_save_s_uploads_and_keeps_the_old_files(self, owner, s3):
        client, team = owner
        s3.Bucket.return_value.put_object.side_effect = [None, ConnectionError("S3 unavailable")]

        with pytest.raises(ConnectionError):
            self.post(
                client,
                team,
                {
                    "icon": SimpleUploadedFile("icon.png", PNG, content_type="image/png"),
                    "logo": SimpleUploadedFile("logo.jpg", JPEG, content_type="image/jpeg"),
                },
            )

        # The failed key goes too: S3 can store an object and still answer with an error.
        new_icon, new_logo = (upload.kwargs["Key"] for upload in s3.Bucket.return_value.put_object.call_args_list)
        assert s3.Object.call_args_list == [
            call(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, new_icon),
            call(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, new_logo),
        ]
        team.refresh_from_db()
        assert (team.branding_info["icon"], team.branding_info["logo"]) == ("old_icon.png", "old_logo.png")

    def test_a_failed_save_removes_the_new_file_and_keeps_the_old_one(self, owner, s3, mocker):
        client, team = owner
        mocker.patch.object(Team, "save", side_effect=DatabaseError("save failed"))

        with pytest.raises(DatabaseError):
            self.post(client, team, {"icon": SimpleUploadedFile("icon.png", PNG, content_type="image/png")})

        new_icon = s3.Bucket.return_value.put_object.call_args.kwargs["Key"]
        assert s3.Object.call_args_list == [call(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, new_icon)]

    def test_one_rejected_file_stores_nothing(self, owner, s3):
        """A valid icon must not be half-applied, with its old file deleted, when the logo beside it fails."""
        client, team = owner

        response = self.post(
            client,
            team,
            {
                "icon": SimpleUploadedFile("icon.png", PNG, content_type="image/png"),
                "logo": SimpleUploadedFile("logo.svg", svg("<script>alert(1)</script>"), content_type="image/svg+xml"),
            },
        )

        assert json.loads(response["HX-Trigger"])["messages"][0] == {
            "type": "error",
            "message": "Upload a PNG, JPEG or WebP image, or a plain SVG under 1 MB.",
        }
        assert_nothing_stored(s3, team)

    def test_a_file_sent_with_its_removal_is_ignored(self, owner, s3):
        """Removal wins over a new file, so the file is neither checked nor stored."""
        client, team = owner

        response = self.post(
            client,
            team,
            {"logo_pending_deletion": "true", "logo": SimpleUploadedFile("logo.html", HTML, content_type="text/html")},
        )

        assert json.loads(response["HX-Trigger"])["messages"][0]["type"] == "success"
        s3.Bucket.return_value.put_object.assert_not_called()
        s3.Object.assert_called_once_with(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, "old_logo.png")
        team.refresh_from_db()
        assert team.branding_info["logo"] == ""


def test_an_svg_at_the_size_cap_is_checked_without_keeping_its_elements():
    """An element tree of this file would take over 50 MB. The check reads each element and keeps none."""
    from sbomify.apps.teams.apis import _MAX_SVG_BYTES, _branding_image_type

    data = svg("<g/>" * 250_000)
    assert len(data) <= _MAX_SVG_BYTES

    tracemalloc.start()
    try:
        assert _branding_image_type(data) == (".svg", "image/svg+xml")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < 8 * 1024 * 1024
