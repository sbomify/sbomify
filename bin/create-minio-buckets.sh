#!/bin/sh
set -e

# These variables are expected to be set in the environment by Docker Compose
# via the x-minio-env anchor.
MINIO_ENDPOINT_URL="${AWS_ENDPOINT_URL_S3}"
MEDIA_BUCKET_NAME="${AWS_MEDIA_STORAGE_BUCKET_NAME}"
SBOMS_BUCKET_NAME="${AWS_SBOMS_STORAGE_BUCKET_NAME}"

echo "Attempting to configure MinIO client..."
echo "MINIO_ROOT_USER is: '${MINIO_ROOT_USER}'"
echo "MINIO_ROOT_PASSWORD is: '${MINIO_ROOT_PASSWORD}' (not shown)"

# Configure mc alias. It will use MINIO_ROOT_USER and MINIO_ROOT_PASSWORD from the environment.
/usr/bin/mc alias set myminio "${MINIO_ENDPOINT_URL}" "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"

echo "Creating MinIO bucket: ${MEDIA_BUCKET_NAME}..."
/usr/bin/mc mb "myminio/${MEDIA_BUCKET_NAME}" --ignore-existing

echo "Creating MinIO bucket: ${SBOMS_BUCKET_NAME}..."
/usr/bin/mc mb "myminio/${SBOMS_BUCKET_NAME}" --ignore-existing

echo "Setting public access for ${MEDIA_BUCKET_NAME}..."
/usr/bin/mc anonymous set public "myminio/${MEDIA_BUCKET_NAME}"

echo "MinIO bucket creation and setup complete."