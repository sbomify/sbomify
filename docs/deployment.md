# Deployment Process

This document outlines how to deploy sbomify using Docker Compose for production environments.

## Overview

The recommended deployment approach is to use Docker Compose with an external configuration file. This method provides:

- **Simplicity**: Single command deployment
- **Flexibility**: Environment-specific configuration via override files
- **Scalability**: External services (Keycloak, S3) for production reliability
- **Version Control**: Easy tag-based deployments

## Quick Deployment

To deploy sbomify in production:

1. **Download the compose file**:

   ```bash
   curl -O https://raw.githubusercontent.com/sbomify/sbomify/master/docker-compose.yml
   ```

2. **Create your environment override file** (`override.env`):

   ```env
   # Application Configuration
   SBOMIFY_TAG=v1.2.3
   APP_BASE_URL=https://your-domain.com
   SECRET_KEY=your-super-secret-key-here
   SIGNED_URL_SALT=your-signed-url-salt-here

   # Database Configuration
   DATABASE_HOST=your-postgres-host
   DATABASE_NAME=sbomify_prod
   DATABASE_USER=sbomify_user
   DATABASE_PASSWORD=secure-db-password

   # Redis Configuration
   REDIS_URL=redis://your-redis-host:6379/0

   # External Keycloak Configuration
   KEYCLOAK_SERVER_URL=https://your-keycloak.com/
   KEYCLOAK_CLIENT_ID=sbomify
   KEYCLOAK_CLIENT_SECRET=your-keycloak-client-secret
   KEYCLOAK_REALM=sbomify
   KC_HOSTNAME_URL=https://your-keycloak.com/

   # External S3 Configuration
   AWS_ENDPOINT_URL_S3=https://your-s3-endpoint.com
   AWS_REGION=us-east-1
   AWS_ACCESS_KEY_ID=your-access-key
   AWS_SECRET_ACCESS_KEY=your-secret-key
   AWS_MEDIA_ACCESS_KEY_ID=your-media-access-key
   AWS_MEDIA_SECRET_ACCESS_KEY=your-media-secret-key
   AWS_SBOMS_ACCESS_KEY_ID=your-sboms-access-key
   AWS_SBOMS_SECRET_ACCESS_KEY=your-sboms-secret-key
   AWS_MEDIA_STORAGE_BUCKET_NAME=sbomify-prod-media
   AWS_MEDIA_STORAGE_BUCKET_URL=https://your-s3-endpoint.com/sbomify-prod-media
   AWS_SBOMS_STORAGE_BUCKET_NAME=sbomify-prod-sboms
   AWS_SBOMS_STORAGE_BUCKET_URL=https://your-s3-endpoint.com/sbomify-prod-sboms

   # Optional: Custom ports and binding
   HTTP_PORT=8000
   HTTPS_PORT=8443
   # For production, use 0.0.0.0 to accept connections from any interface.
   # Use 127.0.0.1 to restrict access to localhost (e.g., for local development).
   BIND_IP=0.0.0.0
   ```

3. **Deploy**:

   ```bash
   docker compose --env-file ./override.env up -d
   ```

That's it! sbomify will be running with your specified configuration.

> **⚠️ Important**: For production deployments, you should place a load balancer (such as nginx) in front of sbomify to handle HTTP/HTTPS traffic, SSL termination, and provide additional security features. The sbomify application runs on port 8000 by default and should not be directly exposed to the internet.

## Environment Configuration

### Available Environment Variables

The Docker Compose configuration supports extensive customization through environment variables:

#### Application Settings

- `SBOMIFY_IMAGE` - Container registry and image name (default: `sbomifyhub/sbomify`)
- `SBOMIFY_TAG` - Image tag/version (default: `latest`)
- `SBOMIFY_PULL_POLICY` - Pull policy (default: `always`)
- `SBOMIFY_RESTART_POLICY` - Restart policy (default: `always`)
- `HTTP_PORT` - Caddy HTTP port (default: `8000`)
- `HTTPS_PORT` - Caddy HTTPS port (default: `8443`)
- `BIND_IP` - IP address to bind Caddy ports to (default: `127.0.0.1`)
- `APP_BASE_URL` - Application base URL
- `SECRET_KEY` - Django secret key
- `SIGNED_URL_SALT` - Salt for signed URLs
- `BILLING` - Enable billing features (default: `False`)

#### Database Settings

- `POSTGRES_IMAGE` - PostgreSQL image (default: `postgres:17-alpine`)
- `POSTGRES_RESTART_POLICY` - PostgreSQL restart policy (default: `always`)
- `POSTGRES_PORT` - External PostgreSQL port (default: `5432`)
- `DATABASE_HOST` - Database host (default: `localhost`)
- `DATABASE_NAME` - Database name (default: `sbomify`)
- `DATABASE_USER` - Database user (default: `sbomify`)
- `DATABASE_PASSWORD` - Database password (default: `sbomify`)
- `DATABASE_PORT` - Database port (default: `5432`)
- `DOCKER_DATABASE_HOST` - Internal database host (default: `sbomify-db`)

#### Redis Settings

- `REDIS_IMAGE` - Redis image (default: `redis:8-alpine`)
- `REDIS_RESTART_POLICY` - Redis restart policy (default: `always`)
- `REDIS_PORT` - External Redis port (default: `6379`)
- `REDIS_URL` - Redis connection URL

#### Authentication (Keycloak)

- `KEYCLOAK_SERVER_URL` - Keycloak server URL
- `KEYCLOAK_CLIENT_ID` - OAuth client ID (default: `sbomify`)
- `KEYCLOAK_CLIENT_SECRET` - OAuth client secret
- `KEYCLOAK_REALM` - Keycloak realm (default: `sbomify`)
- `KC_HOSTNAME_URL` - Keycloak hostname URL

#### Storage (S3-Compatible)

- `AWS_ENDPOINT_URL_S3` - S3 endpoint URL
- `AWS_REGION` - AWS region (default: `auto`)
- `AWS_ACCESS_KEY_ID` - Primary access key
- `AWS_SECRET_ACCESS_KEY` - Primary secret key
- `AWS_MEDIA_ACCESS_KEY_ID` - Media storage access key
- `AWS_MEDIA_SECRET_ACCESS_KEY` - Media storage secret key
- `AWS_SBOMS_ACCESS_KEY_ID` - SBOM storage access key
- `AWS_SBOMS_SECRET_ACCESS_KEY` - SBOM storage secret key
- `AWS_MEDIA_STORAGE_BUCKET_NAME` - Media files bucket
- `AWS_MEDIA_STORAGE_BUCKET_URL` - Media files bucket URL
- `AWS_SBOMS_STORAGE_BUCKET_NAME` - SBOM files bucket
- `AWS_SBOMS_STORAGE_BUCKET_URL` - SBOM files bucket URL

## Deployment Scenarios

### Production Deployment

```bash
# Create production environment file
cat > production.env << EOF
SBOMIFY_TAG=v1.2.3
APP_BASE_URL=https://sbomify.example.com
SECRET_KEY=$(openssl rand -base64 32)
DATABASE_HOST=prod-db.example.com
KEYCLOAK_SERVER_URL=https://auth.example.com/
AWS_ENDPOINT_URL_S3=https://s3.example.com
EOF

# Deploy
docker compose --env-file ./production.env up -d
```

### Staging Deployment

```bash
# Create staging environment file
cat > staging.env << EOF
SBOMIFY_TAG=staging
APP_BASE_URL=https://staging.sbomify.example.com
DATABASE_HOST=staging-db.example.com
KEYCLOAK_SERVER_URL=https://staging-auth.example.com/
EOF

# Deploy
docker compose --env-file ./staging.env up -d
```

### Development with External Services

```bash
# For development with external Keycloak/S3 but local database
cat > dev-external.env << EOF
SBOMIFY_TAG=dev
APP_BASE_URL=http://localhost:8000
DATABASE_HOST=localhost
KEYCLOAK_SERVER_URL=https://dev-auth.example.com/
AWS_ENDPOINT_URL_S3=https://dev-s3.example.com
EOF

# Deploy (will use local PostgreSQL and Redis from compose)
docker compose --env-file ./dev-external.env up -d
```

## Management Commands

### Updating to a New Version

```bash
# Update to specific version
echo "SBOMIFY_TAG=v1.3.0" >> override.env
docker compose --env-file ./override.env pull
docker compose --env-file ./override.env up -d
```

### Scaling Services

```bash
# Scale backend instances
docker compose --env-file ./override.env up -d --scale sbomify-backend=3

# Scale worker instances
docker compose --env-file ./override.env up -d --scale sbomify-worker=2
```

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f sbomify-backend

# Recent logs
docker compose logs --tail=100 -f
```

### Database Operations

```bash
# Run migrations
docker compose exec sbomify-backend python manage.py migrate

# Create superuser
docker compose exec sbomify-backend python manage.py createsuperuser

# Database shell
docker compose exec sbomify-backend python manage.py dbshell
```

## Troubleshooting

### Common Issues

#### Container Won't Start

```bash
# Check container logs
docker compose logs sbomify-backend

# Check if environment variables are loaded correctly
docker compose config

# Verify image exists and is accessible
docker compose pull
```

#### Database Connection Issues

```bash
# Test database connectivity
docker compose exec sbomify-backend python manage.py dbshell

# Check database host resolution
docker compose exec sbomify-backend nslookup $DATABASE_HOST

# Verify database credentials
docker compose exec sbomify-backend env | grep DATABASE
```

#### Authentication Problems

```bash
# Verify Keycloak configuration
docker compose exec sbomify-backend env | grep KEYCLOAK

# Test Keycloak connectivity
docker compose exec sbomify-backend curl -f $KEYCLOAK_SERVER_URL/realms/$KEYCLOAK_REALM
```

#### Storage Issues

```bash
# Check S3 configuration
docker compose exec sbomify-backend env | grep AWS

# Test S3 connectivity
docker compose exec sbomify-backend python manage.py shell -c "
from django.core.files.storage import default_storage
print(default_storage.bucket_name)
"
```

### Performance Tuning

#### Resource Limits

Add resource limits to your override file:

```env
# Limit memory usage
COMPOSE_MEMORY_LIMIT=1g

# Set CPU limits
COMPOSE_CPU_LIMIT=1.0
```

#### Database Optimization

```bash
# Monitor database connections
docker compose exec sbomify-backend python manage.py shell -c "
from django.db import connection
print(f'Database connections: {len(connection.queries)}')
"
```

## Rollback Procedure

### Quick Rollback

```bash
# Rollback to previous version
SBOMIFY_TAG=v1.2.2 docker compose --env-file ./override.env up -d
```

### Full Rollback with Database

```bash
# Stop services
docker compose down

# Restore database backup (if needed)
# ... your database restore process ...

# Start with previous version
SBOMIFY_TAG=v1.2.2 docker compose --env-file ./override.env up -d
```

## Monitoring and Maintenance

### Health Checks

```bash
# Check service health
docker compose ps

# Application health endpoint
curl http://localhost:8000/health/

# Database health
docker compose exec sbomify-backend python manage.py check --database
```

### Backups

```bash
# Database backup
docker compose exec sbomify-db pg_dump -U $DATABASE_USER $DATABASE_NAME > backup_$(date +%Y%m%d).sql

# Volume backup
docker run --rm -v sbomify_postgres_data:/data -v $(pwd):/backup alpine tar czf /backup/postgres_backup_$(date +%Y%m%d).tar.gz /data
```

### Log Management

```bash
# Rotate logs
docker compose logs --no-log-prefix > app_logs_$(date +%Y%m%d).log
docker system prune -f

# Monitor disk usage
docker system df
```

## External Service Requirements

When deploying sbomify with external services, ensure the following are properly configured:

### External Keycloak Setup

Your external Keycloak instance should have:

1. **Realm Configuration**:
   - Realm name: `sbomify` (or set via `KEYCLOAK_REALM`)
   - Realm enabled and configured

2. **Client Configuration**:
   - Client ID: `sbomify` (or set via `KEYCLOAK_CLIENT_ID`)
   - Client type: OpenID Connect
   - Client authentication: Enabled
   - Standard flow: Enabled
   - Direct access grants: Enabled
   - Valid redirect URIs: `https://your-domain.com/*`
   - Valid web origins: `https://your-domain.com`

3. **Client Secret**:
   - Copy from Keycloak admin console → Clients → sbomify → Credentials tab
   - Set as `KEYCLOAK_CLIENT_SECRET` in your override.env

### External S3-Compatible Storage

Your S3-compatible storage should have:

1. **Buckets Created**:
   - Media bucket: `sbomify-[env]-media` (public read access)
   - SBOM bucket: `sbomify-[env]-sboms` (private access)

2. **Access Credentials**:
   - Media storage: `AWS_MEDIA_ACCESS_KEY_ID` and `AWS_MEDIA_SECRET_ACCESS_KEY`
   - SBOM storage: `AWS_SBOMS_ACCESS_KEY_ID` and `AWS_SBOMS_SECRET_ACCESS_KEY`
   - General access: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`

3. **Bucket Policies**:

   ```json
   // Media bucket policy (public read)
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": "*",
         "Action": "s3:GetObject",
         "Resource": "arn:aws:s3:::sbomify-prod-media/*"
       }
     ]
   }
   ```

### External Database

Your PostgreSQL database should:

1. **Be accessible** from your deployment environment
2. **Have the database created**: `CREATE DATABASE sbomify_prod;`
3. **Have a dedicated user** with appropriate permissions:

   ```sql
   CREATE USER sbomify_user WITH PASSWORD 'secure-password';
   GRANT ALL PRIVILEGES ON DATABASE sbomify_prod TO sbomify_user;
   ```

### External Redis

Your Redis instance should:

1. **Be accessible** from your deployment environment
2. **Have appropriate memory** for session storage and caching
3. **Be configured** with proper persistence if needed
