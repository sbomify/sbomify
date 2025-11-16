# Caddy Reverse Proxy and Custom Domain Setup

This document explains how sbomify uses Caddy as a reverse proxy with on-demand TLS for custom domains.

## Overview

All HTTP/HTTPS traffic to sbomify flows through Caddy, which acts as:

- **Reverse proxy** to the Django application
- **TLS termination** for HTTPS
- **On-demand TLS certificate issuer** for custom domains
- **Security layer** protecting internal endpoints

## Architecture

```text
Internet
   │
   ├─> https://app.sbomify.com ──────┐
   ├─> https://trust.customer1.com ──┤
   └─> https://trust.customer2.com ──┤
                                      │
                                   [Caddy]
                                      │
                         ┌────────────┴────────────┐
                         │                         │
                    Port 80/443              Port 2019
                   (Public HTTPS)          (Admin API)
                         │
                         ↓
                 [sbomify-backend:8000]
                  (NOT publicly exposed)
```

## Configuration Files

### `Caddyfile`

The main Caddy configuration file defines:

- Main application domain (from `APP_DOMAIN` env var)
- Custom domain wildcard pattern
- On-demand TLS configuration
- Security headers
- Internal endpoint protection

### Environment Variables

Set these in your `.env` file or deployment configuration:

| Variable          | Description                                             | Example             | Default             |
| ----------------- | ------------------------------------------------------- | ------------------- | ------------------- |
| `APP_BASE_URL`    | Your main application domain (domain only, no protocol) | `app.sbomify.com`   | `localhost`         |
| `ACME_EMAIL`      | Email for Let's Encrypt certificates                    | `admin@sbomify.com` | `admin@example.com` |
| `HTTP_PORT`       | HTTP port (host side)                                   | `80`                | `80`                |
| `HTTPS_PORT`      | HTTPS port (host side)                                  | `443`               | `443`               |
| `CADDY_LOG_LEVEL` | Logging level                                           | `INFO`, `DEBUG`     | `INFO`              |

**Important:** `APP_BASE_URL` should be **just the domain** (e.g., `app.sbomify.com`), not a full URL with protocol. Caddy handles the protocol automatically. This aligns with the same variable used by the Django application.

## Custom Domain Flow

### 1. Customer Setup

When a business/enterprise customer wants to use a custom domain:

1. Customer creates a custom domain via API:

   ```bash
   POST /api/v1/workspaces/{team_key}/custom-domain
   {
     "hostname": "trust.example.com"
   }
   ```

2. Customer is instructed to create a CNAME DNS record:

   ```text
   trust.example.com. CNAME app.sbomify.com.
   ```

3. Customer triggers verification:

   ```bash
   POST /api/v1/workspaces/{team_key}/custom-domain/verify
   ```

4. sbomify verifies the DNS configuration asynchronously

### 2. TLS Certificate Issuance

When a request comes to a custom domain for the first time:

1. Caddy receives HTTPS request for `trust.example.com`
2. Caddy checks if it has a valid certificate (not yet)
3. Caddy makes an **internal-only** request to:

   ```text
   GET http://sbomify-backend:8000/_tls/allow-host?domain=trust.example.com
   ```

4. Django checks:
   - Domain exists in `CustomDomain` table
   - Domain is verified (`is_verified=True`)
   - Domain is active (`is_active=True`)
   - Optional: Real-time DNS check still points to sbomify
5. If all checks pass → Django returns `200 OK`
6. Caddy requests certificate from Let's Encrypt
7. Certificate is issued and cached
8. Request is proxied to Django backend

### 3. Subsequent Requests

For subsequent requests to the same custom domain:

- Caddy uses the cached certificate
- No need to check with Django again
- Requests are directly proxied to backend

## Security

### Internal Endpoint Protection

The `/_tls/allow-host` endpoint is **critical for security**:

```caddyfile
# Block direct access to internal TLS verification endpoint
@tls_internal {
    path /_tls/*
}
handle @tls_internal {
    respond "Not Found" 404
}
```

**This ensures:**

- Public users cannot enumerate domains
- Attackers cannot probe for existence of custom domains
- Only Caddy (within Docker network) can access this endpoint

### Rate Limiting

The endpoint has built-in rate limiting:

- **Per-IP limit**: 100 requests/minute (configurable via `TLS_MAX_REQUESTS_PER_MINUTE`)
- **Per-domain limit**: 10 requests/minute (configurable via `TLS_MAX_REQUESTS_PER_DOMAIN`)

### TLS Security

Caddy automatically:

- Issues certificates from Let's Encrypt
- Renews certificates before expiration
- Implements OCSP stapling
- Uses modern TLS protocols (TLS 1.2+)
- Manages certificate storage in `/data` volume

## Docker Compose Integration

### Production (`docker-compose.yml`)

```yaml
services:
  sbomify-backend:
    # Backend is NOT directly accessible
    expose:
      - 8000 # Only accessible within Docker network

  sbomify-caddy:
    ports:
      - "80:80" # Public HTTP
      - "443:443" # Public HTTPS
      - "2019:2019" # Admin API (restrict in production!)
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data # Certificate storage
      - caddy_config:/config # Caddy configuration
```

### Development (`docker-compose.dev.yml`)

Development uses the same Caddy configuration but with:

- `localhost` as the default domain
- DEBUG logging enabled
- Self-signed certificates (Caddy's internal CA)

## Deployment Checklist

### First-Time Setup

- [ ] Set `APP_BASE_URL` to your main domain hostname only (e.g., `app.sbomify.com`, not `https://app.sbomify.com`)
- [ ] Set `ACME_EMAIL` to a valid email for Let's Encrypt
- [ ] Configure DNS A/AAAA records for your main domain pointing to your server IP
- [ ] Ensure ports 80 and 443 are open in firewall
- [ ] Start services: `docker-compose up -d`
- [ ] Check Caddy logs: `docker-compose logs -f sbomify-caddy`

### Production Hardening

- [ ] **Restrict Caddy admin API** (port 2019) - do not expose publicly
- [ ] Consider using Caddy's `admin off` in production
- [ ] Set up monitoring for certificate expiration
- [ ] Configure firewall rules to only allow Caddy → backend traffic
- [ ] Review and adjust rate limits based on traffic patterns
- [ ] Set `CADDY_LOG_LEVEL=INFO` or `WARN` in production

### Monitoring

Monitor these Caddy metrics:

- Certificate expiration dates
- Certificate issuance failures
- On-demand TLS request counts
- Backend health check failures
- Rate limit hits

Access Caddy metrics:

```bash
curl http://localhost:2019/metrics
```

## Troubleshooting

### Custom Domain Not Working

1. **Check DNS propagation:**

   ```bash
   dig trust.example.com
   nslookup trust.example.com
   ```

2. **Verify domain in database:**

   ```bash
   docker-compose exec sbomify-backend python manage.py shell
   >>> from sbomify.apps.teams.models import CustomDomain
   >>> CustomDomain.objects.filter(hostname="trust.example.com").first()
   ```

3. **Check Caddy logs:**

   ```bash
   docker-compose logs -f sbomify-caddy
   ```

4. **Test TLS endpoint manually (from within Docker network):**

   ```bash
   docker-compose exec sbomify-caddy wget -O- \
     "http://sbomify-backend:8000/_tls/allow-host?domain=trust.example.com"
   ```

### Certificate Issuance Failures

Common causes:

- DNS not properly configured
- Domain not verified in sbomify
- Rate limits hit (Let's Encrypt has limits)
- Firewall blocking Let's Encrypt's validation

Check:

```bash
# Caddy logs
docker-compose logs sbomify-caddy | grep -i "certificate\|acme\|error"

# Certificate storage
docker-compose exec sbomify-caddy ls -la /data/caddy/certificates/
```

### Backend Connection Issues

If Caddy cannot reach backend:

```bash
# Test backend health from Caddy container
docker-compose exec sbomify-caddy wget -O- http://sbomify-backend:8000/health

# Check Docker network
docker network inspect sbomify_default

# Verify backend is running
docker-compose ps sbomify-backend
```

## Development

### Local Testing with Self-Signed Certificates

Caddy automatically issues self-signed certificates for localhost:

```bash
# Start dev environment
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# Access via HTTPS
curl -k https://localhost/

# Trust Caddy's local CA (optional)
docker-compose exec sbomify-caddy cat /data/caddy/pki/authorities/local/root.crt > caddy-root.crt
# Install caddy-root.crt in your system's trust store
```

### Testing Custom Domain Locally

Add to `/etc/hosts`:

```text
127.0.0.1 trust.test.local
```

Access: `https://trust.test.local` (you'll need to accept self-signed certificate)

## References

- [Caddy Documentation](https://caddyserver.com/docs/)
- [Caddy On-Demand TLS](https://caddyserver.com/docs/automatic-https#on-demand-tls)
- [Let's Encrypt Rate Limits](https://letsencrypt.org/docs/rate-limits/)
