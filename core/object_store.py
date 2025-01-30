"""
S3 Compatible Storage

Utilities for working with S3 compatible storage services.
"""

import hashlib
from typing import Literal

import boto3
from botocore.exceptions import ClientError
from django.conf import settings


class S3Client:
    def __init__(self, bucket_type: Literal["MEDIA", "SBOMS"]):
        self.bucket_type = bucket_type
        access_key = getattr(settings, f"AWS_{bucket_type}_ACCESS_KEY_ID")
        secret_key = getattr(settings, f"AWS_{bucket_type}_SECRET_ACCESS_KEY")
        self.s3 = boto3.resource(
            "s3",
            region_name=settings.AWS_REGION,
            endpoint_url=settings.AWS_ENDPOINT_URL_S3,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def upload_data_as_file(self, bucket_name, object_name, data):
        try:
            self.s3.Bucket(bucket_name).put_object(Key=object_name, Body=data)
        except ClientError as e:
            print(e)  # noqa F821
            raise

    def upload_media(self, object_name: str, data: bytes):
        if self.bucket_type != "MEDIA":
            raise ValueError("This method is only for MEDIA bucket")

        self.upload_data_as_file(settings.AWS_MEDIA_STORAGE_BUCKET_NAME, object_name, data)

    def upload_sbom(self, data: bytes) -> str:
        if self.bucket_type != "SBOMS":
            raise ValueError("This method is only for SBOMS bucket")

        object_name = hashlib.sha256(data).hexdigest() + ".json"
        self.upload_data_as_file(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, object_name, data)

        return object_name

    def get_sbom_data(self, object_name: str) -> bytes:
        if self.bucket_type != "SBOMS":
            raise ValueError("This method is only for SBOMS bucket")

        return self.get_file_data(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, object_name)

    def upload_file(self, bucket_name, file_path, object_name):
        try:
            self.s3.Bucket(bucket_name).upload_file(file_path, object_name)
        except ClientError as e:
            print(e)  # noqa F821
            raise

    def download_file(self, bucket_name, object_name, file_path):
        try:
            self.s3.Bucket(bucket_name).download_file(object_name, file_path)
        except ClientError as e:
            print(e)  # noqa F821
            raise

    def get_file_data(self, bucket_name, file_path):
        try:
            response = self.s3.Bucket(bucket_name).Object(file_path).get()
            if response["ResponseMetadata"]["HTTPStatusCode"] == 200:
                return response["Body"].read()
            else:
                return None
        except ClientError as e:
            print(e)  # noqa F821
            raise

    def delete_object(self, bucket_name, object_name):
        try:
            self.s3.Object(bucket_name, object_name).delete()
        except ClientError as e:
            print(e)  # noqa F821
            raise
