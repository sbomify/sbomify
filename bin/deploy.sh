#!/bin/bash
set -euo pipefail

SBOMIFY_IMAGE="${SBOMIFY_IMAGE:-sbomifyhub/sbomify}"
SBOMIFY_TAG="${SBOMIFY_TAG:-latest}"

echo "=== Deploying sbomify ==="
echo ""

# Pull image
echo "Pulling ${SBOMIFY_IMAGE}:${SBOMIFY_TAG}..."
docker pull -q "${SBOMIFY_IMAGE}:${SBOMIFY_TAG}" > /dev/null

# Get digest
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "${SBOMIFY_IMAGE}:${SBOMIFY_TAG}" | cut -d'@' -f2)

# Verify with cosign if available
if command -v cosign &> /dev/null; then
    # Check cosign version (need v2.0.0+)
    COSIGN_VERSION=$(cosign version 2>/dev/null | grep 'GitVersion' | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    MAJOR_VERSION=$(echo "$COSIGN_VERSION" | cut -d'v' -f2 | cut -d'.' -f1)

    if [ -n "$MAJOR_VERSION" ] && [ "$MAJOR_VERSION" -lt 2 ]; then
        echo "✗ cosign version $COSIGN_VERSION is too old (need v2.0.0+)"
        exit 1
    fi

    echo "Verifying image signature..."

    # Try attestation verification with timeout
    if timeout 30 cosign verify-attestation \
        --type https://slsa.dev/provenance/v1 \
        --certificate-identity-regexp "^https://github.com/sbomify/sbomify/.*" \
        --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
        "${SBOMIFY_IMAGE}@${DIGEST}" > /dev/null 2>&1; then
        echo "✓ Signature verified"
    else
        echo "✗ Signature verification failed"
        exit 1
    fi
    echo ""
fi

# Deploy - Rolling update strategy for zero-downtime deployments
echo "Deploying..."

# 1. Ensure infrastructure is running (don't recreate Redis/DB - they're stateful)
#    --no-recreate: Never kill Redis/DB even if their config changed
echo "  Ensuring infrastructure services..."
docker compose --env-file ./override.env up -d --no-recreate sbomify-db sbomify-redis

# 2. Run migrations (blocks until complete)
echo "  Running migrations..."
docker compose --env-file ./override.env up sbomify-migrations

# 3. Update app services (plain `up -d` auto-detects config changes including env vars)
#    With stop_grace_period set, Docker sends SIGTERM and waits before killing
#    --no-deps: Don't restart dependencies (Redis stays running)
echo "  Updating backend services..."
docker compose --env-file ./override.env up -d --no-deps sbomify-backend sbomify-worker

# 4. Update Caddy last (after backends are healthy)
echo "  Updating proxy..."
docker compose --env-file ./override.env up -d --no-deps sbomify-caddy

# 5. Remove orphans (containers from old configs)
docker compose --env-file ./override.env up -d --remove-orphans

# Cleanup
echo "Cleaning up..."
docker system prune -f

echo ""
echo "✓ Deployment complete"
