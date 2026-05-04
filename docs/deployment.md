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

# Generate secrets (run these commands and paste the output below):
# openssl rand -base64 32
# openssl rand -base64 32
SECRET_KEY=PASTE_GENERATED_SECRET_HERE
SIGNED_URL_SALT=PASTE_GENERATED_SALT_HERE

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
# Generate with: openssl rand -base64 32
SECRET_KEY=your-generated-secret-key
# Generate with: openssl rand -base64 32
SIGNED_URL_SALT=your-generated-salt

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
# DATABASE_SSLMODE=require          # or verify-ca, verify-full
# DATABASE_SSLROOTCERT=/path/to/ca.crt

# External Redis (default: uses included Redis)
REDIS_URL=redis://redis.example.com:6379
# REDIS_URL=rediss://:password@redis.example.com:6379  # With password + TLS
# REDIS_CA_CERTS=/path/to/ca.crt    # Custom CA for Redis TLS

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

## TLS and Authentication

### PostgreSQL TLS

When using individual `DATABASE_*` environment variables:

```env
DATABASE_SSLMODE=verify-full
DATABASE_SSLROOTCERT=/etc/ssl/certs/ca-bundle.crt
```

When using `DATABASE_URL`, append the SSL mode as a query parameter:

```env
DATABASE_URL=postgres://user:pass@host:5432/dbname?sslmode=verify-full
```

For `verify-full` with `DATABASE_URL`, set `PGSSLROOTCERT` as well (libpq reads it natively).

### Redis TLS and Password

Configure via `REDIS_URL`:

```env
# Plain
REDIS_URL=redis://redis.internal:6379

# With password
REDIS_URL=redis://:yourpassword@redis.internal:6379

# With password + TLS
REDIS_URL=rediss://:yourpassword@redis.internal:6379
```

> **Note:** Do not include a database number (e.g., `/0`) in `REDIS_URL`. The application appends database numbers automatically (0 for cache, 1 for workers, 2 for channels).

The `rediss://` scheme (note double `s`) enables TLS.

## Private PKI / Custom CA Certificates

If you run your own PKI — for example using [Smallstep](https://smallstep.com/docs/step-ca/) — to issue TLS certificates for internal services like PostgreSQL, Redis, or Keycloak, you need to configure each service to trust your private CA root certificate.

Each service has its own CA configuration that adds to (not replaces) its default trust store, so you only need to provide your private CA root certificate — no bundle required.

### Configure PostgreSQL

Set `DATABASE_SSLROOTCERT` (or `PGSSLROOTCERT` for the `DATABASE_URL` path) to your CA root certificate:

```env
DATABASE_SSLMODE=verify-full
DATABASE_SSLROOTCERT=/certs/root_ca.crt
```

`libpq` uses this certificate to verify the server — it does not affect the system trust store.

### Configure Redis

Set `REDIS_CA_CERTS` to your CA root certificate. This is passed to all Redis consumers (cache, channels, dramatiq) and adds to the default SSL trust store:

```env
REDIS_CA_CERTS=/certs/root_ca.crt
```

### Configure Keycloak

The `ca-cert` init container copies your private CA certificate into a shared volume. Enable it by setting:

```bash
CA_CERT_PATH=./certs/root_ca.crt docker compose --profile pki up ca-cert
```

Then configure Keycloak to mount the volume and trust the CA:

```yaml
services:
  keycloak:
    volumes:
      - ca_certs:/opt/keycloak/certs:ro
    environment:
      KC_TRUSTSTORE_PATHS: /opt/keycloak/certs/private-ca.crt
```

Keycloak merges custom certificates with its default Java truststore. See the [Keycloak truststore documentation](https://www.keycloak.org/server/keycloak-truststore) for details.

### Example compose override

Create a `docker-compose.pki.yml` to mount the CA cert into Python services:

```yaml
x-ca-volume: &ca-volume ./certs/root_ca.crt:/certs/root_ca.crt:ro

services:
  sbomify-backend:
    volumes:
      - *ca-volume
    environment:
      DATABASE_SSLROOTCERT: /certs/root_ca.crt
      REDIS_CA_CERTS: /certs/root_ca.crt

  sbomify-worker:
    volumes:
      - *ca-volume
    environment:
      REDIS_CA_CERTS: /certs/root_ca.crt

  sbomify-migrations:
    volumes:
      - *ca-volume
    environment:
      DATABASE_SSLROOTCERT: /certs/root_ca.crt
```

Deploy with:

```bash
# First, provision the CA cert into the shared volume
CA_CERT_PATH=./certs/root_ca.crt docker compose --profile pki up ca-cert

# Then start services with the PKI override
docker compose -f docker-compose.yml -f docker-compose.pki.yml --env-file override.env up -d
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
docker pull ghcr.io/sbomify/sbomify:latest
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/sbomify/sbomify:latest | cut -d'@' -f2)

# Verify (optional)
cosign verify-attestation \
  --type https://slsa.dev/provenance/v1 \
  --certificate-identity-regexp "^https://github.com/sbomify/sbomify/.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  "ghcr.io/sbomify/sbomify@${DIGEST}"

# Deploy
docker compose --env-file ./override.env up -d --force-recreate --remove-orphans
docker system prune -f
```
