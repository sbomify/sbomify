# Caddy Reverse Proxy and Custom Domains

## Overview

Caddy acts as reverse proxy for all HTTP/HTTPS traffic. The Django backend is not directly exposed.

```text
Internet → Caddy (80/443) → Django Backend (internal:8000)
```

## Configuration

### Environment Variables

| Variable          | Description                        | Production | Development |
| ----------------- | ---------------------------------- | ---------- | ----------- |
| `APP_BASE_URL`    | Main domain (no protocol)          | `localhost`| `localhost` |
| `ACME_EMAIL`      | Let's Encrypt email                | Required   | `dev@localhost` |
| `HTTP_PORT`       | HTTP port (host)                   | `80`       | `8000`      |
| `HTTPS_PORT`      | HTTPS port (host)                  | `443`      | `8443`      |
| `CADDY_LOG_LEVEL` | Logging level                      | `INFO`     | `DEBUG`     |
| `CADDY_ADMIN`     | Admin API endpoint                 | `off`      | `0.0.0.0:2019` |

**Note:** `APP_BASE_URL` should be just the domain (e.g., `app.sbomify.com`), not a full URL.

### Ports

**Production:** 80 (HTTP), 443 (HTTPS)
**Development:** 8000 (HTTP), 8443 (HTTPS), 2019 (Admin API)

Port 8000 is used in dev because Keycloak uses 8080.

## Custom Domain Flow

1. Customer creates custom domain via API
2. Customer adds CNAME: `trust.example.com CNAME app.sbomify.com`
3. Customer triggers verification: `POST /api/v1/workspaces/{key}/custom-domain/verify`
4. On first HTTPS request to custom domain:
   - Caddy queries internal endpoint: `GET http://sbomify-backend:8000/_tls/allow-host?domain=trust.example.com`
   - Django validates domain (exists, verified, active, DNS check)
   - If valid, Caddy issues Let's Encrypt certificate
   - Certificate cached for future requests

## Security

### Internal Endpoint Protection

The `/_tls/allow-host` endpoint is blocked from public access in Caddyfile:

```caddyfile
@tls_internal {
    path /_tls/*
}
handle @tls_internal {
    respond "Not Found" 404
}
```

Only Caddy (within Docker network) can access this endpoint.

### Cloudflare Tunnel Support

HTTP to HTTPS redirects respect `X-Forwarded-Proto` header to avoid redirect loops when behind Cloudflare Tunnel or similar proxies.

```caddyfile
@already_https {
    header X-Forwarded-Proto https
}
# If already HTTPS via proxy, serve normally (no redirect)
```

Caddy trusts proxy headers from Cloudflare's IP ranges via `trusted_proxies` directive.

## Deployment

### Standard Deployment

```bash
# Set environment
APP_BASE_URL=app.sbomify.com
ACME_EMAIL=admin@sbomify.com

# Deploy
docker-compose up -d

# Verify
docker-compose logs -f sbomify-caddy
```

### Cloudflare Tunnel

Configure `/etc/cloudflared/config.yml`:

```yaml
tunnel: <tunnel-id>
credentials-file: /root/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: app.sbomify.com
    service: http://localhost:80
  - hostname: "*.sbomify.com"
    service: http://localhost:80
  - service: http_status:404
```

No changes to sbomify configuration needed. Caddy automatically detects and handles Cloudflare Tunnel via `X-Forwarded-Proto` header.

## Development

```bash
# Start
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# Access
http://localhost:8000/
https://localhost:8443/
http://localhost:2019/  # Admin API
```

## Troubleshooting

**Custom domain not working:**

```bash
dig trust.example.com  # Check DNS
docker-compose logs sbomify-caddy  # Check Caddy logs
docker-compose exec sbomify-caddy wget -O- "http://sbomify-backend:8000/_tls/allow-host?domain=trust.example.com"
```

**Certificate issues:**

```bash
docker-compose logs sbomify-caddy | grep -i certificate
docker-compose exec sbomify-caddy ls -la /data/caddy/certificates/
```

**Backend connection:**

```bash
docker-compose exec sbomify-caddy wget -O- http://sbomify-backend:8000/health
```

## References

- [Caddy Documentation](https://caddyserver.com/docs/)
- [Caddy On-Demand TLS](https://caddyserver.com/docs/automatic-https#on-demand-tls)
- [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
