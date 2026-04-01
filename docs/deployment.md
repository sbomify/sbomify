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
REDIS_HOST=redis.example.com:6379
# REDIS_URL=rediss://:password@redis.example.com:6379/0  # Full URL (takes precedence)
# REDIS_PASSWORD=password            # Only with REDIS_HOST
# REDIS_TLS=true                     # Only with REDIS_HOST
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

Option A — full URL (recommended for production):

```env
REDIS_URL=rediss://:yourpassword@redis.internal:6379/0
```

Option B — individual environment variables:

```env
REDIS_HOST=redis.internal:6379
REDIS_PASSWORD=yourpassword
REDIS_TLS=true
```

The `rediss://` scheme (note double `s`) enables TLS. The `redis-py` client uses Python's `ssl` module, which respects the `SSL_CERT_FILE` environment variable for CA certificate trust.

## Private PKI / Custom CA Certificates

If you run your own PKI — for example using [Smallstep](https://smallstep.com/docs/step-ca/) — to issue TLS certificates for internal services like PostgreSQL, Redis, or Keycloak, you need to configure each service to trust your private CA.

This has been tested with Smallstep's `step-ca` but applies to any private CA that issues X.509 certificates in PEM format.

### Prepare the CA Bundle

Create a combined PEM bundle containing your system's default CA certificates plus your private CA certificate. This is necessary because setting `SSL_CERT_FILE` **replaces** the default trust store rather than appending to it:

```bash
mkdir -p certs
cat /etc/ssl/certs/ca-certificates.crt /path/to/your-private-ca.crt > certs/ca-bundle.crt
```

### Configure Python Services (backend, worker, migrations)

Create a compose override file (e.g., `docker-compose.pki.yml`):

```yaml
x-ca-volume: &ca-volume ./certs/ca-bundle.crt:/etc/ssl/certs/ca-bundle.crt:ro

services:
  sbomify-backend:
    volumes:
      - *ca-volume
    environment:
      SSL_CERT_FILE: /etc/ssl/certs/ca-bundle.crt
      REQUESTS_CA_BUNDLE: /etc/ssl/certs/ca-bundle.crt
      PGSSLROOTCERT: /etc/ssl/certs/ca-bundle.crt
      DATABASE_SSLMODE: verify-full

  sbomify-worker:
    volumes:
      - *ca-volume
    environment:
      SSL_CERT_FILE: /etc/ssl/certs/ca-bundle.crt
      REQUESTS_CA_BUNDLE: /etc/ssl/certs/ca-bundle.crt
      PGSSLROOTCERT: /etc/ssl/certs/ca-bundle.crt

  sbomify-migrations:
    volumes:
      - *ca-volume
    environment:
      SSL_CERT_FILE: /etc/ssl/certs/ca-bundle.crt
      PGSSLROOTCERT: /etc/ssl/certs/ca-bundle.crt
```

No application code changes are required. These are standard environment variables respected by:

| Variable | Used by |
| --- | --- |
| `SSL_CERT_FILE` | Python `ssl` module, `urllib3`, `requests`, `httpx` |
| `REQUESTS_CA_BUNDLE` | `requests` library (fallback) |
| `PGSSLROOTCERT` | `psycopg2` / `libpq` for PostgreSQL connections |

### Configure Keycloak

The `ca-cert` init container copies your private CA certificate into a shared volume. Enable it and point Keycloak at the certificate:

```yaml
# In docker-compose.pki.yml or override.env
CA_CERT_REPLICAS=1
CA_CERT_PATH=./certs/your-private-ca.crt
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

See the [Keycloak truststore documentation](https://www.keycloak.org/server/keycloak-truststore) for details. Keycloak merges custom certificates with its default Java truststore, so you only need to provide your private CA certificate (not the combined bundle).

### Configure Redis TLS

To connect to Redis over TLS, use the `rediss://` scheme:

```env
REDIS_URL=rediss://:yourpassword@redis.internal:6379/0
```

The `redis-py` client picks up `SSL_CERT_FILE` automatically for certificate verification. For a Redis-specific CA certificate (e.g., when Redis uses a different CA than other services), set:

```env
REDIS_CA_CERTS=/etc/ssl/certs/ca-bundle.crt
```

This is passed to all Redis consumers (cache, channels, dramatiq).

### Deploy with PKI Override

```bash
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
