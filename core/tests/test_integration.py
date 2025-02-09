import pytest
from pytest_mock.plugin import MockerFixture

from core.object_store import S3Client


def test_object_store(mocker: MockerFixture):
    mocker.patch("boto3.resource")
    s3 = S3Client("MEDIA")
    patched_upload = mocker.patch("core.object_store.S3Client.upload_data_as_file")
    with pytest.raises(ValueError) as e:
        s3.upload_sbom(b"test")
    assert patched_upload.assert_not_called
    assert str(e.value) == "This method is only for SBOMS bucket"