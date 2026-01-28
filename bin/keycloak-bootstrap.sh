#!/bin/sh
set -e

KC_URL="${KEYCLOAK_SERVER_URL}"
REALM="${KEYCLOAK_REALM}"
CLIENT_ID="${KEYCLOAK_CLIENT_ID}"
ADMIN_USER="${KC_BOOTSTRAP_ADMIN_USERNAME}"
ADMIN_PASS="${KC_BOOTSTRAP_ADMIN_PASSWORD}"
CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET}"
APP_BASE_URL="${APP_BASE_URL:-http://127.0.0.1:8000}"

# Wait for Keycloak REST API to be ready
until /opt/keycloak/bin/kcadm.sh config credentials --server "$KC_URL" --realm master --user "$ADMIN_USER" --password "$ADMIN_PASS"; do
  echo "Waiting for Keycloak to be ready for admin CLI..."
  sleep 3
done

# Create realm if it doesn't exist
if ! /opt/keycloak/bin/kcadm.sh get "realms/$REALM" > /dev/null 2>&1; then
  /opt/keycloak/bin/kcadm.sh create realms \
    -s "realm=$REALM" \
    -s enabled=true
fi

# Disable SSL requirement for development (only in dev mode)
if [ "$KEYCLOAK_DEV_MODE" = "true" ]; then
  /opt/keycloak/bin/kcadm.sh update "realms/$REALM" -s sslRequired=NONE
  echo "SSL requirement disabled for development"
fi

# Ensure the realm uses the bundled sbomify login theme for branding.
/opt/keycloak/bin/kcadm.sh update "realms/$REALM" -s "loginTheme=sbomify"

# Create client if it doesn't exist
if ! /opt/keycloak/bin/kcadm.sh get clients -r "$REALM" -q "clientId=$CLIENT_ID" | grep -q '"id"'; then
  # In dev mode, allow all redirect URIs and web origins for flexibility
  if [ "$KEYCLOAK_DEV_MODE" = "true" ]; then
    /opt/keycloak/bin/kcadm.sh create clients -r "$REALM" \
      -s "clientId=$CLIENT_ID" \
      -s enabled=true \
      -s protocol=openid-connect \
      -s publicClient=false \
      -s 'redirectUris=["*"]' \
      -s 'webOrigins=["*"]' \
      -s standardFlowEnabled=true \
      -s directAccessGrantsEnabled=true \
      -s serviceAccountsEnabled=true \
      -s "baseUrl=$APP_BASE_URL" \
      -s "rootUrl=$APP_BASE_URL" \
      -s "secret=$CLIENT_SECRET"
  else
    /opt/keycloak/bin/kcadm.sh create clients -r "$REALM" \
      -s "clientId=$CLIENT_ID" \
      -s enabled=true \
      -s protocol=openid-connect \
      -s publicClient=false \
      -s 'redirectUris=["http://localhost:8000/*","http://127.0.0.1:8000/*"]' \
      -s 'webOrigins=["http://localhost:8000","http://127.0.0.1:8000"]' \
      -s standardFlowEnabled=true \
      -s directAccessGrantsEnabled=true \
      -s serviceAccountsEnabled=true \
      -s "baseUrl=$APP_BASE_URL" \
      -s "rootUrl=$APP_BASE_URL" \
      -s "secret=$CLIENT_SECRET"
  fi
else
  CLIENT_UUID=$(/opt/keycloak/bin/kcadm.sh get clients -r "$REALM" -q clientId="$CLIENT_ID" --fields id --format csv | tail -n1 | tr -d '"')
  /opt/keycloak/bin/kcadm.sh update "clients/$CLIENT_UUID" -r "$REALM" -s secret="$CLIENT_SECRET"

  # In dev mode, also update redirect URIs to allow all
  if [ "$KEYCLOAK_DEV_MODE" = "true" ]; then
    /opt/keycloak/bin/kcadm.sh update "clients/$CLIENT_UUID" -r "$REALM" \
      -s 'redirectUris=["*"]' \
      -s 'webOrigins=["*"]'
  fi
fi

# Always enable user registration after all other steps
/opt/keycloak/bin/kcadm.sh update "realms/$REALM" -s registrationAllowed=true

# Create test users for development (only in dev mode)
if [ "$KEYCLOAK_DEV_MODE" = "true" ]; then
  # Create test user if it doesn't exist
  if ! /opt/keycloak/bin/kcadm.sh get users -r "$REALM" -q username=jdoe | grep -q '"id"'; then
    /opt/keycloak/bin/kcadm.sh create users -r "$REALM" \
      -s username=jdoe \
      -s firstName=John \
      -s lastName=Doe \
      -s email=jdoe@example.com \
      -s enabled=true
    echo "Created test user: jdoe"
  fi

  # Set password for test user
  /opt/keycloak/bin/kcadm.sh set-password -r "$REALM" --username jdoe --new-password foobar123

  # Create second test user if it doesn't exist
  if ! /opt/keycloak/bin/kcadm.sh get users -r "$REALM" -q username=ssmith | grep -q '"id"'; then
    /opt/keycloak/bin/kcadm.sh create users -r "$REALM" \
      -s username=ssmith \
      -s firstName=Steve \
      -s lastName=Smith \
      -s email=ssmith@example.com \
      -s enabled=true
    echo "Created test user: ssmith"
  fi

  # Set password for second test user
  /opt/keycloak/bin/kcadm.sh set-password -r "$REALM" --username ssmith --new-password foobar123
fi

echo "Keycloak client secret for $CLIENT_ID: $CLIENT_SECRET"

if [ "$KEYCLOAK_DEV_MODE" = "true" ]; then
  echo "Development test users created:"
  echo "  - jdoe / foobar123 (John Doe)"
  echo "  - ssmith / foobar123 (Steve Smith)"
fi
