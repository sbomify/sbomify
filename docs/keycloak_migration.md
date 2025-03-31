# Keycloak Migration Guide

This document provides step-by-step instructions for migrating from Auth0 to Keycloak for authentication in Sbomify.

## 1. Setting up Keycloak

### 1.1 Running Keycloak

First, create a directory for persistent storage:

```bash
mkdir -p ~/keycloak-data
```

Run Keycloak using Docker or Podman with persistent storage:

```bash
# Using Podman
podman run -p 8080:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  -e KC_DB=dev-file \
  -v ~/keycloak-data:/opt/keycloak/data \
  quay.io/keycloak/keycloak:26.1.4 \
  start-dev

# Using Docker
docker run -p 8080:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  -e KC_DB=dev-file \
  -v ~/keycloak-data:/opt/keycloak/data \
  quay.io/keycloak/keycloak:26.1.4 \
  start-dev
```

For production environments, you should use a proper database like PostgreSQL instead of the file-based storage. Here's how to run Keycloak with PostgreSQL:

```bash
# First, create a network for Keycloak and PostgreSQL to communicate
podman network create keycloak-network

# Run PostgreSQL
podman run -d --name keycloak-db \
  --net keycloak-network \
  -e POSTGRES_DB=keycloak \
  -e POSTGRES_USER=keycloak \
  -e POSTGRES_PASSWORD=keycloak \
  -v ~/keycloak-postgres-data:/var/lib/postgresql/data \
  postgres:15

# Run Keycloak with PostgreSQL
podman run -p 8080:8080 \
  --name keycloak \
  --net keycloak-network \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  -e KC_DB=postgres \
  -e KC_DB_URL=jdbc:postgresql://keycloak-db:5432/keycloak \
  -e KC_DB_USERNAME=keycloak \
  -e KC_DB_PASSWORD=keycloak \
  quay.io/keycloak/keycloak:26.1.4 \
  start-dev
```

Access the Keycloak admin console at <http://localhost:8080/admin/> and log in with the admin credentials.

### 1.2 Create a Realm

1. Hover over the dropdown in the top-left corner (showing "master") and click "Create Realm"
2. Enter "sbomify" as the realm name
3. Click "Create"

### 1.3 Create a Client

1. Navigate to "Clients" in the left sidebar
2. Click "Create client"
3. Enter the following details:
   - Client type: OpenID Connect
   - Client ID: sbomify
4. Click "Next"
5. Enable "Client authentication"
6. Enable "Standard flow" and "Direct access grants"
7. Click "Next"
8. Add valid redirect URIs (adjust according to your environment):
   - <http://localhost:8000/>*
   - <http://127.0.0.1:8000/>*
9. Add valid web origins:
   - <http://localhost:8000>
   - <http://127.0.0.1:8000>
10. Click "Save"

The realm accont console is at: <http://localhost:8080/realms/sbomify-dev/account>

### 1.4 Get Client Secret

1. Navigate to the "Credentials" tab of your new client
2. Copy the client secret (you will need this for your Django settings)

## 2. Configuring Django for Keycloak

Update your `.env` file with the following settings:

```env
USE_KEYCLOAK=True
KEYCLOAK_SERVER_URL=http://localhost:8080/
KEYCLOAK_REALM=sbomify
KEYCLOAK_CLIENT_ID=sbomify
KEYCLOAK_CLIENT_SECRET=your-client-secret-from-previous-step
KEYCLOAK_ADMIN_USERNAME=admin
KEYCLOAK_ADMIN_PASSWORD=admin
```

## 3. Migrating Existing Users

Django comes with a management command to migrate existing users from Django to Keycloak:

```bash
# Dry run (does not create users in Keycloak, just shows what would happen)
python manage.py migrate_to_keycloak --dry-run

# Migrate all users
python manage.py migrate_to_keycloak

# Migrate all users and send password reset emails
python manage.py migrate_to_keycloak --send-reset-emails

# Migrate a specific user
python manage.py migrate_to_keycloak --user-email user@example.com
```

During migration:

1. Users are created in Keycloak with the same email, username, first name, and last name as in Django
2. A random temporary password is set for each user
3. Optionally, password reset emails can be sent to users

## 4. Testing the Integration

To test the integration:

1. Make sure Keycloak is running
2. Set `USE_KEYCLOAK=True` in your `.env` file
3. Start the Django server
4. Navigate to the login page
5. Click "Sign in with Keycloak"
6. You should be redirected to the Keycloak login page
7. After signing in, you should be redirected back to the Django application

## 5. Troubleshooting

### 5.1 Keycloak Integration Issues

- Check that Keycloak is running and accessible
- Verify your realm name and client ID are correct
- Ensure your client secret is correctly copied to your `.env` file
- Confirm that redirect URIs in Keycloak match your Django application URLs

### 5.2 User Migration Issues

- Check the logs for detailed error messages
- Verify that Keycloak admin credentials are correct
- Ensure that users have valid email addresses in the Django database

### 5.3 Login Issues

- Clear your browser cookies and try again
- Check that the Keycloak server is running and accessible
- Verify that the user exists in Keycloak (check the Users section in the Keycloak admin console)

## 6. Switching Back to Auth0 (if needed)

If you need to switch back to Auth0 temporarily:

1. Set `USE_KEYCLOAK=False` in your `.env` file
2. Restart the Django server
