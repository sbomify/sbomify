# Deployment

Deploy sbomify using Docker Compose with cryptographic image verification.

## Prerequisites

**Tools:**

- Docker & Docker Compose
- cosign v2.0.0+ ([install guide](https://docs.sigstore.dev/cosign/installation/))

**External Services:**

- **Keycloak** (required) - Authentication provider, must be configured before deploying
- **S3 Storage** (required) - AWS S3, MinIO, or compatible service with 2 buckets

**Included Services:**

- PostgreSQL 17 - Production-ready database
- Redis 8 - Cache and message broker

> Use external database/Redis only if you need HA or managed services.

## Quick Start

```bash
# 1. Download files
curl -O https://raw.githubusercontent.com/sbomify/sbomify/master/docker-compose.yml
curl -O https://raw.githubusercontent.com/sbomify/sbomify/master/bin/deploy.sh
curl -O https://raw.githubusercontent.com/sbomify/sbomify/master/Caddyfile
chmod +x deploy.sh

# 2. Configure
cat > override.env << 'EOF'
SBOMIFY_TAG=latest
APP_BASE_URL=https://your-domain.com
SECRET_KEY=$(openssl rand -base64 32)
SIGNED_URL_SALT=$(openssl rand -base64 32)

# Keycloak (setup externally first)
KEYCLOAK_SERVER_URL=https://keycloak.example.com/
KEYCLOAK_CLIENT_ID=sbomify
KEYCLOAK_CLIENT_SECRET=your-secret
KEYCLOAK_REALM=sbomify
KC_HOSTNAME_URL=https://keycloak.example.com/

# S3 Storage
AWS_ENDPOINT_URL_S3=https://s3.example.com
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=key
AWS_SECRET_ACCESS_KEY=secret
AWS_MEDIA_ACCESS_KEY_ID=media-key
AWS_MEDIA_SECRET_ACCESS_KEY=media-secret
AWS_SBOMS_ACCESS_KEY_ID=sboms-key
AWS_SBOMS_SECRET_ACCESS_KEY=sboms-secret
AWS_MEDIA_STORAGE_BUCKET_NAME=sbomify-media
AWS_MEDIA_STORAGE_BUCKET_URL=https://s3.example.com/sbomify-media
AWS_SBOMS_STORAGE_BUCKET_NAME=sbomify-sboms
AWS_SBOMS_STORAGE_BUCKET_URL=https://s3.example.com/sbomify-sboms
EOF

# 3. Deploy
./deploy.sh

# 4. Verify
docker compose ps
```

The deploy script:

1. Pulls and verifies the image signature
2. Deploys all services
3. Cleans up unused resources

> **Production:** Use a reverse proxy (nginx/Caddy) for SSL termination. App runs on port 8000.

## Reverse Proxy (Caddy)

The included `Caddyfile` provides automatic HTTPS with Let's Encrypt:

**Features:**

- Automatic TLS certificate provisioning and renewal
- HTTP/2 and HTTP/3 support
- Security headers (HSTS, XSS protection, etc.)
- Health checks and failover
- Cloudflare proxy support
- On-demand TLS for custom domains

**Configuration:**

Add to your `override.env`:

```env
# Caddy Configuration
APP_DOMAIN=sbomify.example.com
ACME_EMAIL=admin@example.com
ACME_CA=https://acme-v02.api.letsencrypt.org/directory  # Production
# ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory  # Staging/testing
LOG_LEVEL=INFO
```

The Caddyfile will:

- Serve your app on port 80/443
- Automatically obtain and renew SSL certificates
- Redirect HTTP to HTTPS
- Proxy requests to the Django backend
- Block external access to internal API endpoints

> **Note:** Ensure ports 80 and 443 are open in your firewall for ACME challenges.

## Environment Variables

### Required

```env
# Application
APP_BASE_URL=https://your-domain.com
SECRET_KEY=$(openssl rand -base64 32)
SIGNED_URL_SALT=$(openssl rand -base64 32)

# Keycloak
KEYCLOAK_SERVER_URL=https://keycloak.example.com/
KEYCLOAK_CLIENT_ID=sbomify
KEYCLOAK_CLIENT_SECRET=secret
KEYCLOAK_REALM=sbomify
KC_HOSTNAME_URL=https://keycloak.example.com/

# S3
AWS_ENDPOINT_URL_S3=https://s3.example.com
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=key
AWS_SECRET_ACCESS_KEY=secret
AWS_MEDIA_ACCESS_KEY_ID=key
AWS_MEDIA_SECRET_ACCESS_KEY=secret
AWS_SBOMS_ACCESS_KEY_ID=key
AWS_SBOMS_SECRET_ACCESS_KEY=secret
AWS_MEDIA_STORAGE_BUCKET_NAME=bucket
AWS_MEDIA_STORAGE_BUCKET_URL=https://s3.example.com/bucket
AWS_SBOMS_STORAGE_BUCKET_NAME=bucket
AWS_SBOMS_STORAGE_BUCKET_URL=https://s3.example.com/bucket
```

### Optional

```env
# Version
SBOMIFY_TAG=latest  # or v1.2.3

# External database (default: uses included PostgreSQL)
DATABASE_HOST=postgres.example.com
DATABASE_NAME=sbomify
DATABASE_USER=sbomify
DATABASE_PASSWORD=password

# External Redis (default: uses included Redis)
REDIS_HOST=redis.example.com:6379

# Features
BILLING=False
```

## Common Tasks

### Update Version

```bash
DOCKER_TAG=v1.3.0 ./deploy.sh
```

### Rollback

```bash
DOCKER_TAG=v1.2.0 ./deploy.sh
```

### View Logs

```bash
docker compose logs -f
docker compose logs -f sbomify-backend
```

### Scale Services

```bash
docker compose up -d --scale sbomify-backend=3 --scale sbomify-worker=2
```

### Database Operations

```bash
docker compose exec sbomify-backend python manage.py migrate
docker compose exec sbomify-backend python manage.py createsuperuser
```

### Backup Database

```bash
docker compose exec sbomify-db pg_dump -U sbomify sbomify > backup.sql
```

## Troubleshooting

### Signature Verification Fails

```bash
# Check cosign version (need v2.0.0+)
cosign version

# Test network access
curl -I https://rekor.sigstore.dev
```

Common causes: outdated cosign, network issues, unsigned image (only master/tags are signed).

### Container Won't Start

```bash
docker compose logs sbomify-backend
docker compose config  # Check env vars
```

### Keycloak Issues

```bash
docker compose exec sbomify-backend env | grep KEYCLOAK
docker compose exec sbomify-backend curl -f $KEYCLOAK_SERVER_URL/realms/$KEYCLOAK_REALM
```

### S3 Issues

```bash
docker compose exec sbomify-backend env | grep AWS
```

## Keycloak Setup

Configure before deploying sbomify:

1. **Create Realm**: Name `sbomify`
2. **Create Client**:
   - Client ID: `sbomify`
   - Client type: OpenID Connect
   - Client authentication: Enabled
   - Valid redirect URIs: `https://your-domain.com/*`
   - Valid web origins: `https://your-domain.com`
3. **Get Client Secret**: From admin console → Clients → sbomify → Credentials

## S3 Storage Setup

Create two buckets before deploying:

1. **Media bucket** (`sbomify-media`): Public read access
2. **SBOM bucket** (`sbomify-sboms`): Private access

Example bucket policy for media:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::sbomify-media/*"
  }]
}
```

## Manual Deployment

If you prefer not to use the deploy script:

```bash
docker pull sbomifyhub/sbomify:latest
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' sbomifyhub/sbomify:latest | cut -d'@' -f2)

# Verify (optional)
cosign verify-attestation \
  --type https://slsa.dev/provenance/v1 \
  --certificate-identity-regexp "^https://github.com/sbomify/sbomify/.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  "sbomifyhub/sbomify@${DIGEST}"

# Deploy
docker compose --env-file ./override.env up -d --force-recreate --remove-orphans
docker system prune -f
```
