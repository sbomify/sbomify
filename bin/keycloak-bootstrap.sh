#!/bin/sh
set -e

KC_URL="${KC_URL:-http://keycloak:8080}"
REALM="${KEYCLOAK_REALM:-sbomify}"
CLIENT_ID="${KEYCLOAK_CLIENT_ID:-sbomify}"
ADMIN_USER="${KEYCLOAK_ADMIN_USERNAME:-admin}"
ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET:-dev-client-secret}"

# Wait for Keycloak REST API to be ready
until /opt/keycloak/bin/kcadm.sh config credentials --server $KC_URL --realm master --user $ADMIN_USER --password $ADMIN_PASS; do
  echo "Waiting for Keycloak to be ready for admin CLI..."
  sleep 3
done

# Create realm if it doesn't exist
if ! /opt/keycloak/bin/kcadm.sh get realms/$REALM > /dev/null 2>&1; then
  /opt/keycloak/bin/kcadm.sh create realms \
    -s realm=$REALM \
    -s enabled=true
fi

# Create client if it doesn't exist
if ! /opt/keycloak/bin/kcadm.sh get clients -r $REALM -q clientId=$CLIENT_ID | grep -q '"id"'; then
  /opt/keycloak/bin/kcadm.sh create clients -r $REALM \
    -s clientId=$CLIENT_ID \
    -s enabled=true \
    -s protocol=openid-connect \
    -s publicClient=false \
    -s 'redirectUris=["http://localhost:8000/*","http://127.0.0.1:8000/*"]' \
    -s 'webOrigins=["http://localhost:8000","http://127.0.0.1:8000"]' \
    -s standardFlowEnabled=true \
    -s directAccessGrantsEnabled=true \
    -s serviceAccountsEnabled=true \
    -s secret=$CLIENT_SECRET
else
  CLIENT_UUID=$(/opt/keycloak/bin/kcadm.sh get clients -r $REALM -q clientId=$CLIENT_ID --fields id --format csv | tail -n1 | tr -d '"')
  /opt/keycloak/bin/kcadm.sh update clients/$CLIENT_UUID -r $REALM -s secret=$CLIENT_SECRET
fi

# Always enable user registration after all other steps
/opt/keycloak/bin/kcadm.sh update realms/$REALM -s registrationAllowed=true

echo "Keycloak client secret for $CLIENT_ID: $CLIENT_SECRET"
